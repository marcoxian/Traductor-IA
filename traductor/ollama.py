"""Cliente de Ollama: traducción frase a frase o por lotes, caché persistente y autocorrección.

Mejoras respecto a la versión anterior:
  - Una sola implementación para el modo seguro y el turbo (solo cambia ``tam_lote``).
  - ``requests.Session`` (reutiliza la conexión) y reintentos con espera progresiva.
  - Nunca devuelve ``None``: si Ollama falla, devuelve el texto original y NO lo cachea.
  - Si Ollama deja de responder varias veces seguidas se detiene (antes "traducía"
    el juego entero dejándolo en inglés sin avisar).
  - Caché en disco por juego y modelo: si se corta, al relanzar continúa donde iba.
    La clave incluye el contexto y los términos de glosario aplicados, así que si cambias
    el glosario esas frases se vuelven a traducir.
  - Lotes que se desincronizan se parten por la mitad antes de caer a frase a frase.
  - La autocorrección usa su propio prompt y no contamina el historial de contexto.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter, deque
from pathlib import Path
from typing import Iterable

import requests

from . import config, prompts
from .config import Perfil
from .registro import AZUL, RESET, VERDE
from .texto import (comparar_etiquetas, describir_fallo, extraer_etiquetas, forzar_etiquetas,
                    limpiar_respuesta)

log = logging.getLogger(__name__)

MAX_FALLOS_SEGUIDOS = 5


class OllamaNoDisponible(RuntimeError):
    """Ollama no responde o el modelo no existe."""


# --------------------------------------------------------------------------- Caché
class CacheTraducciones:
    """Diccionario clave -> traducción que se guarda en disco de forma atómica."""

    def __init__(self, ruta: Path | None, guardar_cada: int = 50):
        self.ruta = ruta
        self.guardar_cada = guardar_cada
        self._datos: dict[str, str] = {}
        self._pendientes = 0
        if ruta and ruta.exists():
            try:
                self._datos = json.loads(ruta.read_text(encoding="utf-8"))
                log.info("Caché cargada: %d traducciones previas (%s)", len(self._datos), ruta.name)
            except (OSError, json.JSONDecodeError) as e:
                log.warning("Caché ilegible (%s); se empieza de cero.", e)

    def __len__(self) -> int:
        return len(self._datos)

    def get(self, clave: str) -> str | None:
        return self._datos.get(clave)

    def set(self, clave: str, valor: str) -> None:
        if self._datos.get(clave) == valor:
            return
        self._datos[clave] = valor
        self._pendientes += 1
        if self._pendientes >= self.guardar_cada:
            self.guardar()

    def guardar(self) -> None:
        if not self.ruta or not self._pendientes:
            return
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_name(self.ruta.name + ".tmp")
        tmp.write_text(json.dumps(self._datos, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.ruta)
        self._pendientes = 0


def ruta_cache_por_defecto(juego: str | None, modelo: str) -> Path:
    nombre = re.sub(r"[^A-Za-z0-9._-]+", "_", modelo)
    return config.carpeta_juego(juego) / "cache" / f"cache_{nombre}.json"


# --------------------------------------------------------------------------- Lotes
_LINEA_NUMERADA = re.compile(r"^(\d+)\s*[.)]\s*(.*)$")


def parsear_lote(respuesta: str, n: int) -> list[str] | None:
    """Convierte '1. a\\n2. b' en ['a', 'b']. Las líneas sin número se pegan a la anterior.
    Devuelve None si no aparecen exactamente los números 1..n."""
    items: dict[int, str] = {}
    actual = None
    for linea in respuesta.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        m = _LINEA_NUMERADA.match(linea)
        if m and 1 <= int(m.group(1)) <= n and int(m.group(1)) not in items:
            actual = int(m.group(1))
            items[actual] = m.group(2).strip()
        elif actual is not None:
            items[actual] = f"{items[actual]} {linea}".strip()
    if sorted(items) != list(range(1, n + 1)):
        return None
    return [items[i] for i in range(1, n + 1)]


# --------------------------------------------------------------------------- Traductor
class OllamaTranslator:
    """Traduce textos con un modelo local de Ollama."""

    def __init__(self,
                 model_name: str = config.MODELO_POR_DEFECTO,
                 endpoint: str = config.OLLAMA_URL,
                 perfil: Perfil | None = None,
                 usar_historial: bool = False,
                 tam_lote: int = 1,
                 ruta_cache: Path | None = None,
                 reintentos: int = 3,
                 timeout: int = 120):
        self.model_name = model_name
        self.endpoint = endpoint  # antes se ignoraba este parámetro
        self.perfil = perfil if perfil is not None else config.cargar_perfil(None)
        self.usar_historial = usar_historial
        self.historial: deque[str] = deque(maxlen=3)
        self.tam_lote = max(1, tam_lote)
        self.cache = CacheTraducciones(ruta_cache)
        self.reintentos = reintentos
        self.timeout = timeout
        self.session = requests.Session()
        self.estadisticas: Counter = Counter()
        self._fallos_seguidos = 0
        # Opcional: traductor.progreso.EstadoProgreso (lo asigna 1_traducir_juego.py)
        self.progreso = None

    def _avisar_nueva(self, texto: str) -> None:
        if self.progreso is not None:
            self.progreso.frase_nueva(texto)

    def _avisar_avance(self, hechas: int) -> None:
        if self.progreso is not None:
            self.progreso.avance_archivo(hechas)

    # ----------------------------------------------------------------- Ciclo de vida
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    def cerrar(self) -> None:
        self.cache.guardar()
        self.session.close()

    def comprobar_conexion(self) -> None:
        """Falla pronto y con un mensaje claro si Ollama no está o el modelo no existe."""
        base = self.endpoint.split("/api/")[0]
        try:
            r = self.session.get(f"{base}/api/tags", timeout=5)
            r.raise_for_status()
            modelos = [m.get("name", "") for m in r.json().get("models", [])]
        except (requests.RequestException, ValueError) as e:
            raise OllamaNoDisponible(f"No se puede conectar con Ollama en {base} ({e}). "
                                     "¿Está abierto? Prueba: ollama serve") from e
        if self.model_name not in modelos and f"{self.model_name}:latest" not in modelos:
            raise OllamaNoDisponible(f"El modelo '{self.model_name}' no existe en Ollama. "
                                     f"Disponibles: {', '.join(modelos) or '(ninguno)'}")

    # ----------------------------------------------------------------- Bajo nivel
    def _generar(self, prompt: str, num_predict: int) -> str | None:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": num_predict},
        }
        for intento in range(1, self.reintentos + 1):
            try:
                r = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
                r.raise_for_status()
                respuesta = r.json().get("response", "")
                self._fallos_seguidos = 0
                return respuesta
            except (requests.RequestException, ValueError) as e:
                log.warning("Error con Ollama (intento %d/%d): %s", intento, self.reintentos, e)
                if intento < self.reintentos:
                    time.sleep(2 ** (intento - 1))
        self._fallos_seguidos += 1
        self.estadisticas["errores"] += 1
        if self._fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
            raise OllamaNoDisponible(f"Ollama ha fallado {self._fallos_seguidos} veces seguidas. "
                                     "Se detiene para no dejar el juego a medio traducir en inglés.")
        return None

    def _clave(self, texto: str, terminos: Iterable[tuple[str, str]]) -> str:
        firma = "|".join(f"{en}={es}" for en, es in terminos)
        bruto = f"{self.model_name}\x00{self.perfil.huella()}\x00{firma}\x00{texto}"
        return hashlib.sha1(bruto.encode("utf-8")).hexdigest()

    def _clave_de(self, texto: str) -> str:
        return self._clave(texto, self.perfil.terminos_para(texto))

    def _recordar(self, original: str, traducido: str) -> None:
        # Las frases cortas (menús) no aportan contexto
        if self.usar_historial and len(original) > 8:
            self.historial.append(f"[{original} = {traducido}]")

    @staticmethod
    def _tokens_para(texto: str, minimo: int) -> int:
        return max(minimo, int(len(texto) * 0.8))

    # ----------------------------------------------------------------- Traducción
    def translate(self, text: str) -> str:
        """Traduce una frase (con caché). Si Ollama falla devuelve el original."""
        if not text.strip():
            return text
        terminos = self.perfil.terminos_para(text)
        clave = self._clave(text, terminos)
        cacheado = self.cache.get(clave)
        if cacheado is not None:
            self.estadisticas["cache"] += 1
            return cacheado

        historial = list(self.historial) if self.usar_historial else []
        instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, self.perfil.contexto,
                                                    terminos, historial)
        respuesta = self._generar(prompts.formatear(instruccion, text), self._tokens_para(text, 250))
        if respuesta is None:
            return text
        final = limpiar_respuesta(respuesta, text) or text
        self.cache.set(clave, final)
        self.estadisticas["traducidas"] += 1
        self._recordar(text, final)
        self._avisar_nueva(final)
        return final

    def batch_translate(self, texts: list[str]) -> list[str]:
        """Traduce una lista. Con ``tam_lote`` > 1 agrupa en lotes numerados (modo turbo)."""
        resultados: list[str | None] = [None] * len(texts)
        pendientes: dict[str, list[int]] = {}  # texto -> posiciones (sin duplicados)
        for i, t in enumerate(texts):
            if not t.strip():
                resultados[i] = t
                continue
            cacheado = self.cache.get(self._clave_de(t))
            if cacheado is not None:
                self.estadisticas["cache"] += 1
                resultados[i] = cacheado
            else:
                pendientes.setdefault(t, []).append(i)

        resueltas = sum(r is not None for r in resultados)
        self._avisar_avance(resueltas)
        unicos = list(pendientes)
        for inicio in range(0, len(unicos), self.tam_lote):
            bloque = unicos[inicio:inicio + self.tam_lote]
            for original, traducido in zip(bloque, self._traducir_bloque(bloque)):
                for i in pendientes[original]:
                    resultados[i] = traducido
                resueltas += len(pendientes[original])
            self._avisar_avance(resueltas)
            if len(unicos) > self.tam_lote:
                log.info("  Progreso: %d/%d frases nuevas", min(inicio + self.tam_lote, len(unicos)), len(unicos))
        return [r if r is not None else t for r, t in zip(resultados, texts)]

    def _traducir_bloque(self, textos: list[str]) -> list[str]:
        if len(textos) == 1:
            return [self.translate(textos[0])]
        for _ in range(2):
            resultado = self._pedir_lote(textos)
            if resultado is not None:
                return resultado
            log.warning("Lote de %d desincronizado; reintentando...", len(textos))
        mitad = len(textos) // 2
        log.warning("Se parte el lote en dos (%d + %d).", mitad, len(textos) - mitad)
        return self._traducir_bloque(textos[:mitad]) + self._traducir_bloque(textos[mitad:])

    def _pedir_lote(self, textos: list[str]) -> list[str] | None:
        entrada = "\n".join(f"{i}. {t.replace(chr(10), ' ')}" for i, t in enumerate(textos, 1))
        terminos = list(dict.fromkeys(tm for t in textos for tm in self.perfil.terminos_para(t)))
        instruccion = prompts.construir_instruccion(prompts.INSTRUCCION_LOTE, self.perfil.contexto,
                                                    terminos[:config.MAX_TERMINOS_PROMPT])
        respuesta = self._generar(prompts.formatear(instruccion, entrada), self._tokens_para(entrada, 1000))
        if respuesta is None:
            return None
        partes = parsear_lote(respuesta, len(textos))
        if partes is None:
            return None
        finales = []
        for original, parte in zip(textos, partes):
            final = limpiar_respuesta(parte, original) or original
            self.cache.set(self._clave_de(original), final)
            self.estadisticas["traducidas"] += 1
            self._avisar_nueva(final)
            finales.append(final)
        return finales

    # ----------------------------------------------------------------- Validación
    def autocorrect(self, original: str, bad_translation: str, reason: str | None = None,
                    max_attempts: int = 2) -> str:
        """Pide al modelo que corrija una traducción con etiquetas rotas.
        Si no lo consigue, pega las etiquetas que falten al inicio (último recurso)."""
        ok, faltan, sobran = comparar_etiquetas(original, bad_translation)
        if ok:
            return bad_translation
        etiquetas = extraer_etiquetas(original)
        actual = bad_translation
        for intento in range(1, max_attempts + 1):
            instruccion = prompts.instruccion_correccion(etiquetas, reason or describir_fallo(faltan, sobran))
            entrada = prompts.entrada_correccion(original, actual)
            respuesta = self._generar(prompts.formatear(instruccion, entrada), self._tokens_para(original, 250))
            if respuesta is None:
                break
            corregido = limpiar_respuesta(respuesta, original)
            ok, faltan, sobran = comparar_etiquetas(original, corregido)
            if ok and corregido:
                log.info("%s  ✔ Autocorregido (intento %d): %s%s", AZUL, intento, corregido[:50], RESET)
                self.estadisticas["autocorregidas"] += 1
                return corregido
            actual = corregido or actual
            reason = None
        self.estadisticas["forzadas"] += 1
        forzado = forzar_etiquetas(original, bad_translation)
        log.warning("  ✖ Etiquetas irrecuperables; se pegan al inicio: %s", forzado[:60])
        return forzado

    def traducir_textos(self, textos: list[str]) -> list[str]:
        """Traduce + valida etiquetas + autocorrige. Es lo que usan los motores."""
        if self.tam_lote == 1:
            brutos = []
            for t in textos:  # en orden, para el historial
                brutos.append(self.translate(t))
                self._avisar_avance(len(brutos))
        else:
            brutos = self.batch_translate(textos)
        finales = []
        for original, traducido in zip(textos, brutos):
            ok, faltan, sobran = comparar_etiquetas(original, traducido)
            if not ok:
                log.warning("  ⚠ Etiquetas rotas (%s) en: %s", describir_fallo(faltan, sobran), traducido[:50])
                traducido = self.autocorrect(original, traducido)
                self.cache.set(self._clave_de(original), traducido)  # no repetir la corrección
            elif traducido != original:
                log.info("%s  ✔ %s%s", VERDE, traducido[:70], RESET)
            finales.append(traducido)
        return finales

    def traducir_validado(self, texto: str) -> str:
        return self.traducir_textos([texto])[0]

    # ----------------------------------------------------------------- Compatibilidad
    def extract_format_tags(self, text: str) -> list[str]:
        return extraer_etiquetas(text)

    def validate_format_tags(self, original: str, translated: str):
        return (comparar_etiquetas(original, translated)[0],
                sorted(extraer_etiquetas(original)), sorted(extraer_etiquetas(translated)))
