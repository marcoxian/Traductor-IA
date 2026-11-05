"""Cliente de Ollama: traducción frase a frase o por lotes, caché persistente y puerta de calidad.

Mejoras de fiabilidad (oct-2026):
  - ``CacheTraducciones`` thread-safe (``threading.RLock``) y escritura atómica desde instantánea.
  - ``requests.Session`` por hilo (``threading.local``) para uso seguro en proxy y ejecutores paralelos.
  - ``num_ctx`` dinámico y ``keep_alive`` explícito en cada llamada a Ollama para evitar que Ollama
    recorte el inicio del prompt o descargue el modelo de VRAM en mitad de la partida.
  - Separación de envoltorio (``<i>...</i> [pic=N]``) antes de traducir y preservación de saltos
    de línea reales (``\\n``) en documentos y registros multilínea.
  - Puerta de calidad (``evaluar_traduccion``) con reintentos automáticos y temperatura progresiva:
    nunca guarda en caché traducciones vacías, sin traducir, mutiladas o con bucles.
  - En los lotes (modo turbo), cada frase pasa la puerta de calidad; solo se reintentan
    individualmente las frases del lote que hayan fallado.

Ficha de personajes (nov-2026), solo si el juego tiene ``workspace/<juego>/personajes.json``:
  - Cada línea se resuelve con ``personajes.resolver_linea`` (quién habla, a quién, a quién se
    menciona) usando lo que sepa el motor (``info: InfoLinea``) y el propio texto.
  - El prompt lleva ``PERSONAJES: ...`` y la clave de caché la firma de la línea (sin firma, la
    clave es la de siempre); tras traducir se aplica ``aplicar_concordancia`` antes de la puerta de
    calidad y de la caché.
  - La caché anterior (sin ficha) se reaprovecha si no contradice los géneros conocidos.
  Sin ficha no se hace ningún trabajo extra: prompts, claves y resultados son los de siempre.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from . import ambiguas, config, prompts
from .config import Perfil
from .genero import HOMBRE, MUJER, marcas_genero
from .personajes import ContextoLinea, InfoLinea, aplicar_concordancia, resolver_linea
from .registro import AZUL, RESET, VERDE
from .texto import (
    comparar_etiquetas,
    describir_fallo,
    evaluar_traduccion,
    extraer_etiquetas,
    forzar_etiquetas,
    gravedad,
    limpiar_respuesta,
    nombres_perdidos,
    nota_reintento,
    postprocesar_traduccion,
    quitar_cola_pegada,
    quitar_etiquetas_inventadas,
    reinsertar_saltos,
    sanitizar,
    separar_envoltorio,
    tiene_fallo_grave,
    tiene_texto_visible,
)

log = logging.getLogger(__name__)

MAX_FALLOS_SEGUIDOS = 5
# workspace/<juego>/casos_dificiles.jsonl: frases arregladas en un reintento (ver activar_casos_dificiles)
ARCHIVO_CASOS_DIFICILES = "casos_dificiles.jsonl"
_HASH_SHA1 = re.compile(r"^[0-9a-f]{40}$")


class OllamaNoDisponible(RuntimeError):
    """Ollama no responde o el modelo no existe."""


class TraduccionFallida(RuntimeError):
    """No se pudo obtener una traducción válida tras los reintentos."""


# --------------------------------------------------------------------------- Caché
class CacheTraducciones:
    """Diccionario clave -> traducción thread-safe que se guarda en disco de forma atómica."""

    def __init__(self, ruta: Path | None, guardar_cada: int = 50):
        self.ruta = ruta
        self.guardar_cada = guardar_cada
        self._lock = threading.RLock()
        self._datos: dict[str, str] = {}
        self._pendientes = 0
        if ruta and ruta.exists():
            try:
                cargado = json.loads(ruta.read_text(encoding="utf-8"))
                if isinstance(cargado, dict):
                    self._datos = cargado
                    log.info("Caché cargada: %d traducciones previas (%s)", len(self._datos), ruta.name)
            except (OSError, json.JSONDecodeError) as e:
                log.warning("Caché ilegible (%s); se empieza de cero.", e)

    def __len__(self) -> int:
        with self._lock:
            return len(self._datos)

    def get(self, clave: str) -> str | None:
        with self._lock:
            return self._datos.get(clave)

    def pop(self, clave: str) -> str | None:
        with self._lock:
            if clave in self._datos:
                self._pendientes += 1
                return self._datos.pop(clave)
            return None

    def claves_no_hash(self) -> list[str]:
        """Devuelve claves antiguas en texto plano (no SHA1) para poder migrarlas."""
        with self._lock:
            return [k for k in self._datos if not _HASH_SHA1.match(k)]

    def set(self, clave: str, valor: str) -> None:
        guardar_ahora = False
        with self._lock:
            if self._datos.get(clave) == valor:
                return
            self._datos[clave] = valor
            self._pendientes += 1
            if self._pendientes >= self.guardar_cada:
                guardar_ahora = True
        if guardar_ahora:
            self.guardar()

    def guardar(self) -> None:
        if not self.ruta:
            return
        with self._lock:
            if not self._pendientes:
                return
            instantanea = dict(self._datos)
            self._pendientes = 0
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_name(f"{self.ruta.name}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(instantanea, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.ruta)


def ruta_cache_por_defecto(juego: str | None, modelo: str) -> Path:
    nombre = re.sub(r"[^A-Za-z0-9._-]+", "_", modelo)
    return config.carpeta_juego(juego) / "cache" / f"cache_{nombre}.json"


# --------------------------------------------------------------------------- Personajes
def _choca_genero(marcas: set[str], persona: str, genero: str) -> bool:
    """True si las ``marcas`` (ver ``genero.marcas_genero``) contradicen ``genero`` en la ``persona``
    ('1' = quien habla, '2' = a quien se habla). Con 'neutro' cualquier marca de género choca."""
    if genero == HOMBRE:
        return f"{persona}f" in marcas
    if genero == MUJER:
        return f"{persona}m" in marcas
    return f"{persona}m" in marcas or f"{persona}f" in marcas


# --------------------------------------------------------------------------- Lotes
_LINEA_NUMERADA = re.compile(r"^\s*(?:\*\*|\[)?(\d+)(?:\*\*|\])?\s*[.):\-]\s*(.*)$")


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
                 timeout: int = 120,
                 num_ctx: int = config.NUM_CTX_POR_DEFECTO,
                 keep_alive: str = config.KEEP_ALIVE_POR_DEFECTO,
                 reintentos_calidad: int = config.REINTENTOS_CALIDAD):
        self.model_name = model_name
        self.endpoint = endpoint
        self.perfil = perfil if perfil is not None else config.cargar_perfil(None)
        self.usar_historial = usar_historial
        self.historial: deque[str] = deque(maxlen=6)
        self.tam_lote = max(1, tam_lote)
        self.cache = CacheTraducciones(ruta_cache)
        self.reintentos = reintentos
        self.timeout = timeout
        self.num_ctx = max(2048, num_ctx)
        self.keep_alive = keep_alive
        self.reintentos_calidad = max(1, reintentos_calidad)
        self._local = threading.local()
        self._session_override = None
        self._sesiones_creadas: list = []
        self._lock = threading.RLock()
        self.estadisticas: Counter = Counter()
        self._fallos_seguidos = 0
        # Opcional: traductor.progreso.EstadoProgreso (lo asigna 1_traducir_juego.py)
        self.progreso = None
        # Caché de otro modelo que se reaprovecha al cambiar de modelo (ver reaprovechar_cache_de)
        self._respaldo: tuple[str, CacheTraducciones] | None = None
        # Opcional (activar_casos_dificiles): JSONL donde se guardan las frases que el modelo falló al
        # primer intento y arregló en un reintento, para reentrenar. None = no se guarda nada.
        self.ruta_casos_dificiles: Path | None = None
        # Migrar en memoria cualquier clave en texto plano que hubiera en la caché
        self._migrar_claves_planas()

    @property
    def session(self):
        if self._session_override is not None:
            return self._session_override
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            self._local.session = s
            with self._lock:
                self._sesiones_creadas.append(s)
        return s

    @session.setter
    def session(self, valor) -> None:
        self._session_override = valor

    def _avisar_nueva(self, texto: str) -> None:
        if self.progreso is not None:
            self.progreso.frase_nueva(texto)

    def _avisar_avance(self, hechas: int) -> None:
        if self.progreso is not None:
            self.progreso.avance_archivo(hechas)

    def _exacta_bd(self, texto: str) -> str | None:
        """Si ``texto`` es exactamente un nombre de la base de datos del juego (objeto, habilidad...),
        su traducción fijada en glosario_bd.json: se copia tal cual, sin preguntar al modelo, para que
        el inventario y la ventana de "Has conseguido..." digan siempre lo mismo."""
        buscar = getattr(self.perfil, "traduccion_exacta", None)
        exacta = buscar(texto) if buscar is not None else None
        if exacta is not None:
            with self._lock:
                self.estadisticas["glosario_bd"] += 1
        return exacta

    def _comprobar_pausa(self) -> None:
        """Verifica si el usuario ha solicitado pausar la traducción."""
        archivo_pausa = config.DIR_WORKSPACE / ".pausa"
        if archivo_pausa.exists():
            if self.progreso is not None:
                self.progreso.estado = "pausado"
                self.progreso.mensaje = "Traducción pausada por el usuario"
                self.progreso.guardar(forzar=True)
            self.cache.guardar()
            log.info("⏸️ [PAUSA] Traducción pausada. Esperando reanudación...")
            while archivo_pausa.exists():
                time.sleep(0.5)
            log.info("▶️ [REANUDAR] Traducción reanudada.")
            if self.progreso is not None:
                self.progreso.estado = "traduciendo"
                self.progreso.mensaje = ""
                self.progreso.guardar(forzar=True)

    # ----------------------------------------------------------------- Ciclo de vida
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    def cerrar(self) -> None:
        self.cache.guardar()
        with self._lock:
            for s in self._sesiones_creadas:
                try:
                    s.close()
                except Exception:
                    pass
            self._sesiones_creadas.clear()
        if self._session_override is not None:
            try:
                self._session_override.close()
            except Exception:
                pass

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

    def precalentar(self) -> bool:
        """Carga el modelo en VRAM con una generación mínima para evitar timeouts en la 1ª frase."""
        try:
            payload = {
                "model": self.model_name,
                "prompt": "Hola",
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": {"num_predict": 1, "num_ctx": self.num_ctx},
            }
            r = self.session.post(self.endpoint, json=payload, timeout=45)
            r.raise_for_status()
            return True
        except Exception as e:
            log.debug("No se pudo precalentar el modelo %s: %s", self.model_name, e)
            return False

    # ----------------------------------------------------------------- Bajo nivel
    def _generar(self, prompt: str, num_predict: int, temperature: float = 0.1) -> str | None:
        ctx_necesario = max(self.num_ctx, int(len(prompt) * 0.6) + num_predict + 256)
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "repeat_penalty": 1.15,
                "num_predict": num_predict,
                "num_ctx": min(ctx_necesario, 16384),
                "stop": [
                    "### Instruction",
                    "### Input",
                    "### Response",
                    "<|im_start|>",
                    "<|im_end|>",
                    "<|eot_id|>",
                    "<|end_of_text|>",
                ],
            },
        }
        for intento in range(1, self.reintentos + 1):
            try:
                r = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
                if getattr(r, "status_code", 200) == 404:
                    raise OllamaNoDisponible(f"El modelo '{self.model_name}' no existe en Ollama (404).")
                r.raise_for_status()
                datos = r.json()
                if datos.get("done_reason") == "length":
                    log.debug("Respuesta de Ollama truncada por num_predict (%d).", num_predict)
                respuesta = datos.get("response", "")
                with self._lock:
                    self._fallos_seguidos = 0
                return respuesta
            except OllamaNoDisponible:
                raise
            except (requests.RequestException, ValueError) as e:
                log.warning("Error con Ollama (intento %d/%d): %s", intento, self.reintentos, e)
                if intento < self.reintentos:
                    time.sleep(2 ** (intento - 1))
        with self._lock:
            self._fallos_seguidos += 1
            self.estadisticas["errores"] += 1
            fallos = self._fallos_seguidos
        if fallos >= MAX_FALLOS_SEGUIDOS:
            raise OllamaNoDisponible(f"Ollama ha fallado {fallos} veces seguidas. "
                                     "Se detiene para no dejar el juego a medio traducir en inglés.")
        return None

    def _clave(self, texto: str, terminos: Iterable[tuple[str, str]], firma: str = "",
               huella: str | None = None, modelo: str | None = None) -> str:
        """Clave SHA1 de la caché. Con ``firma`` vacía y ``huella`` None es exactamente la de siempre.

        ``firma`` es ``ContextoLinea.firma()`` (quién habla/escucha y su género) y ``huella`` permite
        calcular la clave de otro contexto (p. ej. ``perfil.huella_legacy``, el de antes de la ficha).
        ``modelo`` calcula la clave que usó otro modelo (ver ``reaprovechar_cache_de``).
        """
        glosario = "|".join(f"{en}={es}" for en, es in terminos)
        huella_ctx = self.perfil.huella() if huella is None else huella
        bruto = f"{self.model_name if modelo is None else modelo}\x00{huella_ctx}\x00{glosario}\x00{texto}"
        if firma:
            bruto = f"{bruto}\x00{firma}"
        return hashlib.sha1(bruto.encode("utf-8")).hexdigest()

    def _clave_de(self, texto: str, info: InfoLinea | None = None) -> str:
        """Clave con la que ``translate(texto, info=info)`` busca y guarda su traducción."""
        ctx = self._contexto_linea(texto, info)
        return self._clave(texto, self.perfil.terminos_para(texto), ctx.firma() if ctx is not None else "")

    def _recordar(self, original: str, traducido: str, ctx: ContextoLinea | None = None) -> None:
        if not self.usar_historial or not original.strip():
            return
        t_clean = original.strip()
        # Solo recordar frases de diálogo (≥ 3 palabras) para no contaminar el historial con menús
        if len(t_clean.split()) >= 3 and re.search(r"[A-Za-z]", t_clean) and not t_clean.startswith("http"):
            etiqueta = ctx.etiqueta_historial() if ctx is not None else ""  # 'Ana: ' = quién lo dijo
            with self._lock:
                self.historial.append(f"[{etiqueta}{t_clean} -> {traducido.strip()}]")

    # ----------------------------------------------------------------- Personajes
    def _contexto_linea(self, texto: str, info: InfoLinea | None = None) -> ContextoLinea | None:
        """Quién habla, a quién y a quién se menciona en ``texto`` (ver ``personajes.resolver_linea``).

        Devuelve None si el juego no tiene ficha de personajes: así los juegos sin ``personajes.json``
        (y el proxy de Unity) no hacen ningún trabajo extra y todo funciona como siempre.
        """
        ficha = getattr(self.perfil, "personajes", None)
        if ficha is None:
            return None
        return resolver_linea(ficha, texto, info)

    @staticmethod
    def _infos_alineadas(textos: Sequence[str], info: Sequence[InfoLinea | None] | None) -> list[InfoLinea | None]:
        """Lista de ``InfoLinea`` en paralelo a ``textos`` (None si el motor no sabe nada)."""
        if info is None:
            return [None] * len(textos)
        infos = list(info)
        if len(infos) != len(textos):
            # Mejor no atribuir frases a quien no las dice: se ignora toda la información.
            log.warning("Información de hablantes desalineada (%d textos, %d infos): se ignora.",
                        len(textos), len(infos))
            return [None] * len(textos)
        return infos

    def _compatible_con_ficha(self, traduccion: str, ctx: ContextoLinea) -> bool:
        """¿Sirve para esta línea una traducción hecha SIN ficha de personajes (caché antigua)?

        No sirve si contradice el género conocido de quien habla (1.ª persona) o de a quién se habla
        (2.ª persona), ni si marca masculino en 1.ª/2.ª persona cuando esa persona puede ser un
        protagonista que NO es hombre: el contexto antiguo forzaba siempre el masculino.
        """
        marcas = marcas_genero(traduccion)
        if not marcas:
            return True
        ficha = getattr(self.perfil, "personajes", None)
        prota = ficha.protagonista() if ficha is not None else None
        prota_hombre = prota is not None and prota.genero == HOMBRE
        h = ctx.hablante
        d = ctx.destinatario if ctx.destinatario is not h else None
        habla_prota = h is not None and h.es_protagonista
        if h is not None and h.genero_conocido:
            if _choca_genero(marcas, "1", h.genero):
                return False
        elif (h is None or habla_prota) and not prota_hombre and "1m" in marcas:
            return False
        if d is not None and d.genero_conocido:
            if _choca_genero(marcas, "2", d.genero):
                return False
        elif not habla_prota and not prota_hombre and "2m" in marcas:
            return False
        return True

    def _buscar_en_cache(self, texto: str, terminos: list[tuple[str, str]], clave: str,
                         ctx: ContextoLinea | None) -> str | None:
        """Traducción válida en caché para la clave nueva o, si hay ficha, para la clave antigua.

        La clave antigua es la de antes de tener ficha (``perfil.huella_legacy`` y sin firma). Su
        traducción se reutiliza (con la concordancia ya aplicada) solo si no contradice los géneros
        conocidos, y se guarda con la clave nueva. Si no hay nada, se mira la caché de otro modelo
        (``reaprovechar_cache_de``).
        """
        cacheado = self._obtener_cacheado_valido(texto, clave)
        if cacheado is not None:
            return cacheado
        if ctx is not None:
            cacheado = self._buscar_sin_ficha(texto, terminos, clave, ctx)
            if cacheado is not None:
                return cacheado
        return self._buscar_en_otro_modelo(texto, terminos, clave, ctx)

    def _buscar_sin_ficha(self, texto: str, terminos: list[tuple[str, str]], clave: str,
                          ctx: ContextoLinea) -> str | None:
        """Caché de este modelo con la clave de antes de tener ficha (ver ``_buscar_en_cache``)."""
        huella_antigua = getattr(self.perfil, "huella_legacy", "")
        if not huella_antigua:
            return None
        clave_antigua = self._clave(texto, terminos, "", huella_antigua)
        if clave_antigua == clave:
            return None
        antiguo = self._obtener_cacheado_valido(texto, clave_antigua)
        if antiguo is None:
            return None
        corregido = aplicar_concordancia(antiguo, texto, ctx)
        if not self._compatible_con_ficha(corregido, ctx):
            with self._lock:
                self.estadisticas["cache_antigua_descartada"] += 1
            log.debug("Caché antigua descartada por género (%s): %s", ctx.firma() or "sin hablante", antiguo[:60])
            return None
        self.cache.set(clave, corregido)
        with self._lock:
            self.estadisticas["cache_antigua"] += 1
        return corregido

    # ----------------------------------------------------------------- Caché de otro modelo
    def sembrar_traduccion(self, original: str, traduccion: str, info: InfoLinea | None = None) -> bool:
        """Guarda en la caché (con la clave de ahora) una traducción que ya existe, p. ej. la que tiene el
        juego, para no volver a pedirla al modelo (``--solo-genero``). No se guarda si sigue en inglés, si
        no pasa la puerta de calidad, si tiene marcas de género en 1.ª/2.ª persona (esas las retraduce el
        modelo) o si este modelo ya tiene su propia traducción. Devuelve True si se ha guardado."""
        exacta = getattr(self.perfil, "traduccion_exacta", None)
        if not original or not traduccion or traduccion.strip() == original.strip() \
                or not tiene_texto_visible(original) or (exacta is not None and exacta(original) is not None):
            return False  # los nombres de la base de datos ya salen de glosario_bd.json
        if tiene_fallo_grave(evaluar_traduccion(original, traduccion)):
            return False
        ctx = self._contexto_linea(original, info)
        if ctx is not None:
            traduccion = aplicar_concordancia(traduccion, original, ctx)
        if marcas_genero(traduccion):
            return False
        if self._sentido_mal(original, traduccion):  # "te apuñale en el cofre": que la traduzca el modelo
            with self._lock:
                self.estadisticas["reaprovechadas_sentido_descartadas"] += 1
            return False
        clave = self._clave(original, self.perfil.terminos_para(original), ctx.firma() if ctx is not None else "")
        if self.cache.get(clave) is not None:
            return False
        self.cache.set(clave, traduccion)
        with self._lock:
            self.estadisticas["reaprovechadas_juego"] += 1
        return True

    def reaprovechar_cache_de(self, modelo: str | None = None, ruta: Path | None = None) -> str | None:
        """Al cambiar de modelo, reaprovecha la caché del anterior para no retraducir el juego entero.

        Solo se reutilizan las traducciones SIN marcas de género en 1.ª o 2.ª persona ("Abre la puerta"
        sí; "Estoy cansado" no): esas son las que el modelo nuevo puede mejorar y se vuelven a traducir,
        igual que las que no estaban. Sin ``modelo`` se usa la caché más completa de otro modelo en
        ``workspace/<juego>/cache/``. Nunca se escribe en esa caché. Devuelve el modelo usado o None.
        """
        if ruta is None:
            if modelo:
                actual = getattr(self.cache, "ruta", None)
                ruta = (Path(actual).with_name(ruta_cache_por_defecto(None, modelo).name) if actual is not None
                        else ruta_cache_por_defecto(getattr(self.perfil, "juego", None), modelo))
            else:
                ruta, modelo = self._cache_de_otro_modelo()
        if not modelo or modelo == self.model_name or ruta is None or not ruta.exists():
            return None
        otra = CacheTraducciones(ruta, guardar_cada=10**9)  # solo lectura
        if not len(otra):
            return None
        self._respaldo = (modelo, otra)
        log.info("♻ Se reaprovechan las traducciones de %s (%d) que no tienen marcas de género; las que sí "
                 "las tienen se traducen con %s.", modelo, len(otra), self.model_name)
        return modelo

    def _cache_de_otro_modelo(self) -> tuple[Path | None, str | None]:
        """La caché más grande de otro modelo en la carpeta de cachés de este juego."""
        actual = getattr(self.cache, "ruta", None)
        juego = getattr(self.perfil, "juego", None)
        if actual is not None:
            carpeta = Path(actual).parent
        elif juego:
            carpeta = config.carpeta_juego(juego) / "cache"
        else:
            return None, None
        if not carpeta.is_dir():
            return None, None
        otras = [p for p in carpeta.glob("cache_*.json")
                 if actual is None or p.resolve() != Path(actual).resolve()]
        if not otras:
            return None, None
        mayor = max(otras, key=lambda p: p.stat().st_size)
        return mayor, mayor.stem[len("cache_"):]

    def _buscar_en_otro_modelo(self, texto: str, terminos: list[tuple[str, str]], clave: str,
                               ctx: ContextoLinea | None) -> str | None:
        respaldo = getattr(self, "_respaldo", None)
        if respaldo is None:
            return None
        modelo, otra = respaldo
        claves = [self._clave(texto, terminos, ctx.firma() if ctx is not None else "", modelo=modelo)]
        huella_antigua = getattr(self.perfil, "huella_legacy", "")
        if ctx is not None and huella_antigua:  # la otra caché puede ser de antes de tener ficha
            claves.append(self._clave(texto, terminos, "", huella_antigua, modelo=modelo))
        for k in dict.fromkeys(claves):
            previa = otra.get(k)
            if not previa or tiene_fallo_grave(evaluar_traduccion(texto, previa)):
                continue
            if ctx is not None:
                previa = aplicar_concordancia(previa, texto, ctx)
            if marcas_genero(previa):
                with self._lock:
                    self.estadisticas["otro_modelo_con_genero"] += 1
                return None  # que la traduzca el modelo nuevo
            if self._sentido_mal(texto, previa):
                return None
            self.cache.set(clave, previa)
            with self._lock:
                self.estadisticas["cache_otro_modelo"] += 1
            return previa
        return None

    # ----------------------------------------------------------------- Casos difíciles
    def activar_casos_dificiles(self, ruta: Path | None = None) -> Path | None:
        """Guarda en ``workspace/<juego>/casos_dificiles.jsonl`` (o en ``ruta``) cada frase que la
        puerta de calidad rechazó al primer intento y un reintento arregló: el par (original, versión
        aceptada) con la instrucción normal es un buen ejemplo para ``entrenar_v2.py --casos-dificiles``.
        Solo se activa a propósito (1_traducir_juego.py, el proxy) para que las pruebas no escriban en
        ``workspace/``. Devuelve la ruta usada (None si el juego no tiene carpeta de perfil)."""
        if ruta is None:
            juego = getattr(self.perfil, "juego", None)
            carpeta = config.carpeta_juego(juego) if juego else None
            if carpeta is None or carpeta.name == "_comun" or not carpeta.is_dir():
                return None
            ruta = carpeta / ARCHIVO_CASOS_DIFICILES
        self.ruta_casos_dificiles = ruta
        return ruta

    def _guardar_caso_dificil(self, texto: str, aceptada: str, terminos: list[tuple[str, str]],
                              ficha_linea: str, rechazada: str | None, problemas: list[str]) -> None:
        if self.ruta_casos_dificiles is None:
            return
        instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, self.perfil.contexto, terminos,
                                                    personajes=ficha_linea)
        registro = {"input": texto, "output": aceptada, "instruccion_completa": instruccion,
                    "contexto": "caso_dificil", "rechazada": rechazada, "problemas": problemas,
                    "modelo": self.model_name}
        try:
            with self._lock:
                with open(self.ruta_casos_dificiles, "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(registro, ensure_ascii=False) + "\n")
                self.estadisticas["casos_dificiles"] += 1
        except OSError as e:
            log.debug("No se pudo guardar el caso difícil: %s", e)

    @staticmethod
    def _tokens_para(texto: str, minimo: int) -> int:
        return max(minimo, int(len(texto) * 1.2) + 40)

    def _afinar_salida(self, original: str, traducido: str) -> str:
        """Restaura nombres protegidos, aplica posprocesado, limpia etiquetas inventadas, quita colas en
        inglés pegadas ("ARAÑAConstellation name (optional)") y arregla los artículos de "cofre"/"pecho"
        ("la cofre" -> "el cofre")."""
        limpio = self.perfil.restaurar_nombres(original, traducido)
        limpio = postprocesar_traduccion(limpio, original) or original
        limpio = quitar_etiquetas_inventadas(original, limpio)
        limpio = quitar_cola_pegada(original, limpio)
        return ambiguas.arreglar_articulos(limpio)

    def _sentido_mal(self, original: str, traduccion: str) -> list[ambiguas.Decision]:
        """Palabras de dos sentidos ("chest", "safe") que la traducción entiende al revés (vacío = bien)."""
        if not getattr(self.perfil, "palabras_ambiguas", True):
            return []
        return ambiguas.sentido_equivocado(original, traduccion)

    # ----------------------------------------------------------------- Migración de caché
    def _migrar_claves_planas(self) -> None:
        """Si la caché contiene claves antiguas en texto plano, las valida y las convierte a SHA1."""
        claves_planas = self.cache.claves_no_hash()
        if not claves_planas:
            return
        pares = {k: self.cache.pop(k) or "" for k in claves_planas}
        aceptadas, rechazadas = self.importar_pares_externos(pares, guardar=False)
        log.info("Caché migrada a formato hash: %d válidas conservadas, %d con fallos descartadas para retraducir.",
                 aceptadas, rechazadas)

    def importar_pares_externos(self, pares: Mapping[str, str], guardar: bool = True) -> tuple[int, int]:
        """Valida pares ``{original: traduccion}`` con la puerta de calidad e importa los válidos.

        Con ficha de personajes se aplica la concordancia de género y se descartan (igual que la
        caché antigua) los que contradigan el género conocido de quien habla o escucha."""
        aceptadas = 0
        rechazadas = 0
        for original, traduccion in pares.items():
            if not original or not tiene_texto_visible(original):
                continue
            # No importar resúmenes/corrupción multilínea si el original tenía ≥ 2 saltos y se perdieron todos
            if original.count("\n") >= 2 and "\n" not in (traduccion or ""):
                rechazadas += 1
                continue
            afinado = self._afinar_salida(original, limpiar_respuesta(traduccion or "", original))
            ok_tags, faltan, _ = comparar_etiquetas(original, afinado)
            if not ok_tags and faltan:
                afinado = forzar_etiquetas(original, afinado)
            probs = evaluar_traduccion(original, afinado)
            if tiene_fallo_grave(probs) or self._sentido_mal(original, afinado):
                rechazadas += 1
                continue
            ctx = self._contexto_linea(original)
            if ctx is not None:
                afinado = aplicar_concordancia(afinado, original, ctx)
                if not self._compatible_con_ficha(afinado, ctx):
                    rechazadas += 1
                    continue
            firma = ctx.firma() if ctx is not None else ""
            self.cache.set(self._clave(original, self.perfil.terminos_para(original), firma), afinado)
            aceptadas += 1
        if guardar:
            self.cache.guardar()
        return aceptadas, rechazadas

    # ----------------------------------------------------------------- Traducción
    def _obtener_cacheado_valido(self, texto: str, clave: str) -> str | None:
        cacheado = self.cache.get(clave)
        if cacheado is None:
            return None
        if texto.count("\n") >= 2 and "\n" not in cacheado:
            return None
        afinado = self._afinar_salida(texto, cacheado)
        if tiene_fallo_grave(evaluar_traduccion(texto, afinado)):
            return None
        if self._sentido_mal(texto, afinado):  # p. ej. "apuñale en el cofre" de antes de este arreglo
            with self._lock:
                self.estadisticas["cache_sentido_descartada"] += 1
            return None
        if afinado != cacheado:
            self.cache.set(clave, afinado)
        return afinado

    def _traducir_unidad(self, texto: str, *, lanzar_error: bool = False, info: InfoLinea | None = None,
                         ctx: ContextoLinea | None = None, buscar_cache: bool = True) -> str:
        """Traduce una unidad de una sola línea aplicando envoltorio y puerta de calidad con reintentos.

        ``ctx`` (contexto de personajes ya resuelto, p. ej. heredado de un documento multilínea)
        tiene prioridad sobre ``info``; si no se pasa ninguno se deduce del propio texto.
        ``buscar_cache=False`` cuando quien llama ya ha consultado la caché para este mismo texto.
        """
        if not texto.strip() or not tiene_texto_visible(texto):
            return texto
        exacta = self._exacta_bd(texto)
        if exacta is not None:
            return exacta
        self._comprobar_pausa()
        if ctx is None:
            ctx = self._contexto_linea(texto, info)
        firma = ctx.firma() if ctx is not None else ""
        ficha_linea = ctx.ficha() if ctx is not None else ""
        terminos = self.perfil.terminos_para(texto)
        clave = self._clave(texto, terminos, firma)
        cacheado = self._buscar_en_cache(texto, terminos, clave, ctx) if buscar_cache else None
        if cacheado is not None:
            with self._lock:
                self.estadisticas["cache"] += 1
            return cacheado

        prefijo_env, nucleo, sufijo_env = separar_envoltorio(texto)
        mejor_candidato: str | None = None
        mejor_gravedad = 10_000
        ultimos_problemas: list[str] = []
        ultimos_perdidos: list[str] = []
        ultimos_equivocados: list[ambiguas.Decision] = []
        primer_candidato: str | None = None
        primeros_problemas: list[str] = []
        # Personajes que nombra el original: si la traducción los pierde ("SCN - Habitación de Marisa"
        # -> "Sala de la Escuela...") se reintenta pidiendo que los conserve.
        ficha = getattr(self.perfil, "personajes", None)
        nombres_originales = ficha.nombres_en(texto) if ficha is not None else []

        for intento in range(1, self.reintentos_calidad + 1):
            with self._lock:
                historial = list(self.historial) if (self.usar_historial and intento == 1) else []
            instruccion = prompts.construir_instruccion(
                prompts.INSTRUCCION, self.perfil.contexto, terminos, historial, personajes=ficha_linea
            )
            if intento >= 2 and ultimos_problemas:
                nota = nota_reintento(ultimos_problemas)
                if "nombre_perdido" in ultimos_problemas and ultimos_perdidos:
                    nota = f"{nota} Nombres que deben aparecer: {', '.join(ultimos_perdidos)}.".strip()
                if "sentido_equivocado" in ultimos_problemas and ultimos_equivocados:
                    nota = f"{nota} {ambiguas.nota_reintento(ultimos_equivocados)}".strip()
                if nota:
                    instruccion = f"{instruccion} IMPORTANTE: {nota}"
            temp = 0.1 if intento == 1 else min(0.45, 0.15 + 0.15 * (intento - 1))
            respuesta = self._generar(prompts.formatear(instruccion, nucleo), self._tokens_para(nucleo, 180), temperature=temp)
            if respuesta is None:
                break

            limpio_nucleo = limpiar_respuesta(respuesta, nucleo) or nucleo
            candidato = f"{prefijo_env}{limpio_nucleo}{sufijo_env}" if (prefijo_env or sufijo_env) else limpio_nucleo
            candidato = self._afinar_salida(texto, candidato)
            if ctx is not None:
                candidato = aplicar_concordancia(candidato, texto, ctx)

            problemas = evaluar_traduccion(texto, candidato)
            perdidos = nombres_perdidos(candidato, nombres_originales, terminos)
            if perdidos:
                problemas.append("nombre_perdido")
            equivocados = self._sentido_mal(texto, candidato)
            if equivocados:
                problemas.append("sentido_equivocado")
            if intento == 1:
                primer_candidato, primeros_problemas = candidato, list(problemas)
            g = gravedad(problemas)
            if g < mejor_gravedad:
                mejor_candidato = candidato
                mejor_gravedad = g
                ultimos_problemas = problemas
                ultimos_perdidos = perdidos
                ultimos_equivocados = equivocados

            # "nombre_perdido" y "sentido_equivocado" no son graves: se reintenta mientras queden intentos
            # y, si no se arregla, se acepta la mejor versión (con el cambio seguro cofre -> pecho).
            leve_pendiente = bool(perdidos or equivocados) and intento < self.reintentos_calidad
            if not tiene_fallo_grave(problemas) and not leve_pendiente:
                if equivocados:
                    candidato = ambiguas.forzar_sentido(texto, candidato)
                self.cache.set(clave, candidato)
                with self._lock:
                    self.estadisticas["traducidas"] += 1
                    if intento > 1:
                        self.estadisticas["reintentadas_calidad"] += 1
                    if "sentido_equivocado" in primeros_problemas:
                        self.estadisticas["sentido_corregido"] += 1
                if intento > 1 and not perdidos and not equivocados:
                    self._guardar_caso_dificil(texto, candidato, terminos, ficha_linea,
                                               primer_candidato, primeros_problemas)
                self._recordar(texto, candidato, ctx)
                self._avisar_nueva(candidato)
                return candidato

            log.debug("Reintento de calidad %d/%d para '%s' por %s -> '%s'",
                      intento, self.reintentos_calidad, texto[:50], problemas, candidato[:50])

        if mejor_candidato is not None and "sentido_equivocado" in ultimos_problemas:
            mejor_candidato = ambiguas.forzar_sentido(texto, mejor_candidato)
        if mejor_candidato is not None and not tiene_fallo_grave(ultimos_problemas):
            # Solo quedaron problemas leves que los reintentos no arreglaron (un nombre que el modelo se
            # empeña en cambiar) y el último intento salió peor: se acepta la mejor versión.
            self.cache.set(clave, mejor_candidato)
            with self._lock:
                self.estadisticas["traducidas"] += 1
            self._recordar(texto, mejor_candidato, ctx)
            self._avisar_nueva(mejor_candidato)
            return mejor_candidato

        with self._lock:
            self.estadisticas["rechazadas_calidad"] += 1
        if lanzar_error:
            raise TraduccionFallida(f"No se pudo traducir con calidad aceptable ({ultimos_problemas}): {texto[:60]}")
        # No se guarda en caché para que pueda reintentarse en otra ejecución
        if mejor_candidato is not None and "sin_traducir" not in ultimos_problemas and "vacia" not in ultimos_problemas:
            return mejor_candidato
        return texto

    def translate(self, text: str, *, lanzar_error: bool = False, info: InfoLinea | None = None) -> str:
        """Traduce una frase o bloque multilínea (con caché y puerta de calidad).

        ``info`` (opcional) es lo que el motor sabe de la línea (hablante, código, opción...; ver
        ``personajes.InfoLinea``). Solo se usa si el juego tiene ficha de personajes.
        """
        if not text.strip() or not tiene_texto_visible(text):
            return text
        return self._traducir_texto(text, self._contexto_linea(text, info), lanzar_error=lanzar_error)

    def _traducir_texto(self, text: str, ctx: ContextoLinea | None, *, lanzar_error: bool = False) -> str:
        """``translate`` con el contexto de personajes ya resuelto (None = deducirlo del texto).
        Las líneas de un documento multilínea heredan el contexto del texto completo."""
        if not text.strip() or not tiene_texto_visible(text):
            return text
        exacta = self._exacta_bd(text)
        if exacta is not None:
            return exacta
        self._comprobar_pausa()
        if ctx is None:
            ctx = self._contexto_linea(text)
        terminos = self.perfil.terminos_para(text)
        clave = self._clave(text, terminos, ctx.firma() if ctx is not None else "")
        cacheado = self._buscar_en_cache(text, terminos, clave, ctx)
        if cacheado is not None:
            with self._lock:
                self.estadisticas["cache"] += 1
            return cacheado

        prefijo_env, nucleo, sufijo_env = separar_envoltorio(text)
        if "\n" not in nucleo:
            # La caché (nueva y antigua) de este mismo texto ya se ha consultado arriba.
            return self._traducir_unidad(text, lanzar_error=lanzar_error, ctx=ctx, buscar_cache=False)

        # Texto con saltos de línea reales en el núcleo
        sep_salto = "\r\n" if "\r\n" in nucleo else "\n"
        partes_nl = nucleo.splitlines()
        primera = partes_nl[0].rstrip() if partes_nl else ""
        # Si solo hay 1 salto en mitad de una frase (sin puntuación final), se traduce unida y se recoloca el salto
        if len(partes_nl) == 2 and primera and primera[-1] not in ".?!:;…\"')>}]":
            unido = sanitizar(nucleo)
            trad_unida = self._traducir_unidad(unido, lanzar_error=lanzar_error, ctx=ctx)
            con_salto = reinsertar_saltos(trad_unida, partes_nl).replace("\\n", sep_salto)
            final = f"{prefijo_env}{con_salto}{sufijo_env}"
        else:
            # Documento, carta o registro multilínea: traducir línea a línea preservando estructura
            lineas_trad = [
                self._traducir_unidad(linea, lanzar_error=lanzar_error, ctx=ctx) if tiene_texto_visible(linea) else linea
                for linea in partes_nl
            ]
            final = f"{prefijo_env}{sep_salto.join(lineas_trad)}{sufijo_env}"

        final = self._afinar_salida(text, final)
        if not tiene_fallo_grave(evaluar_traduccion(text, final)):
            self.cache.set(clave, final)
        return final

    def batch_translate(self, texts: list[str], info: Sequence[InfoLinea | None] | None = None) -> list[str]:
        """Traduce una lista. Con ``tam_lote`` > 1 agrupa en lotes numerados (modo turbo).

        ``info`` (opcional, en paralelo a ``texts``) indica lo que el motor sabe de cada línea.
        """
        infos = self._infos_alineadas(texts, info)
        resultados: list[str | None] = [None] * len(texts)
        # (texto, firma) -> posiciones (sin duplicados). La misma frase dicha por personajes de
        # distinto género tiene distinta firma y se traduce aparte.
        pendientes: dict[tuple[str, str], list[int]] = {}
        contextos: dict[tuple[str, str], ContextoLinea | None] = {}
        for i, (t, inf) in enumerate(zip(texts, infos)):
            if not t.strip() or not tiene_texto_visible(t):
                resultados[i] = t
                continue
            exacta = self._exacta_bd(t)
            if exacta is not None:
                resultados[i] = exacta
                continue
            ctx = self._contexto_linea(t, inf)
            firma = ctx.firma() if ctx is not None else ""
            terminos = self.perfil.terminos_para(t)
            cacheado = self._buscar_en_cache(t, terminos, self._clave(t, terminos, firma), ctx)
            if cacheado is not None:
                with self._lock:
                    self.estadisticas["cache"] += 1
                resultados[i] = cacheado
            else:
                pendientes.setdefault((t, firma), []).append(i)
                contextos.setdefault((t, firma), ctx)

        resueltas = sum(r is not None for r in resultados)
        self._avisar_avance(resueltas)

        # Los bloques multilínea se traducen preservando sus saltos de línea
        unicos_simples: list[tuple[str, str]] = []
        for k in list(pendientes):
            _, nucleo, _ = separar_envoltorio(k[0])
            if "\n" in nucleo:
                trad = self._traducir_texto(k[0], contextos[k])
                for i in pendientes.pop(k):
                    resultados[i] = trad
                    resueltas += 1
                self._avisar_avance(resueltas)
            else:
                unicos_simples.append(k)

        for inicio in range(0, len(unicos_simples), self.tam_lote):
            self._comprobar_pausa()
            bloque = unicos_simples[inicio:inicio + self.tam_lote]
            traducidos = self._traducir_bloque([k[0] for k in bloque], [contextos[k] for k in bloque])
            for k, traducido in zip(bloque, traducidos):
                for i in pendientes[k]:
                    resultados[i] = traducido
                resueltas += len(pendientes[k])
            self._avisar_avance(resueltas)
            if len(unicos_simples) > self.tam_lote:
                log.info("  Progreso: %d/%d frases nuevas",
                         min(inicio + self.tam_lote, len(unicos_simples)), len(unicos_simples))
        return [r if r is not None else t for r, t in zip(resultados, texts)]

    def _traducir_bloque(self, textos: list[str],
                         ctxs: Sequence[ContextoLinea | None] | None = None) -> list[str]:
        ctxs = list(ctxs) if ctxs is not None else [None] * len(textos)
        if len(textos) == 1:
            return [self._traducir_texto(textos[0], ctxs[0])]
        # Si el bloque es demasiado largo en caracteres, partirlo antes de llamar a Ollama
        if sum(len(t) for t in textos) > 2800 and len(textos) >= 2:
            mitad = len(textos) // 2
            return (self._traducir_bloque(textos[:mitad], ctxs[:mitad])
                    + self._traducir_bloque(textos[mitad:], ctxs[mitad:]))

        resultado = self._pedir_lote(textos, ctxs)
        if resultado is not None:
            return resultado

        mitad = len(textos) // 2
        log.warning("Lote de %d desincronizado; se parte en dos (%d + %d).",
                    len(textos), mitad, len(textos) - mitad)
        return (self._traducir_bloque(textos[:mitad], ctxs[:mitad])
                + self._traducir_bloque(textos[mitad:], ctxs[mitad:]))

    def _pedir_lote(self, textos: list[str],
                    ctxs: Sequence[ContextoLinea | None] | None = None) -> list[str] | None:
        ctxs = list(ctxs) if ctxs is not None else [self._contexto_linea(t) for t in textos]
        envoltorios = [separar_envoltorio(t) for t in textos]
        nucleos = [nuc.replace("\n", " ").strip() for _, nuc, _ in envoltorios]
        entrada = "\n".join(f"{i}. {n}" for i, n in enumerate(nucleos, 1))
        # Sin el sentido de "chest"/"safe": vale para una frase, no para todas las del lote. Si una frase sale
        # con el sentido equivocado se retraduce sola (abajo), ya con su término.
        terminos = list(dict.fromkeys(tm for t in textos for tm in self.perfil.terminos_para(t, con_ambiguas=False)))
        # Ficha de personajes de cada frase, por número: "PERSONAJES POR FRASE: 1) ...; 3) ..."
        fichas = [(i, c.ficha()) for i, c in enumerate(ctxs, 1) if c is not None]
        instruccion = prompts.construir_instruccion(prompts.INSTRUCCION_LOTE, self.perfil.contexto,
                                                    terminos[:config.MAX_TERMINOS_PROMPT],
                                                    personajes_lote=fichas)
        respuesta = self._generar(prompts.formatear(instruccion, entrada), self._tokens_para(entrada, 1000))
        if respuesta is None:
            return None
        partes = parsear_lote(respuesta, len(textos))
        if partes is None:
            return None
        finales = []
        ficha = getattr(self.perfil, "personajes", None)
        for original, ctx, (pref, nuc, suf), parte in zip(textos, ctxs, envoltorios, partes):
            limpio_nuc = limpiar_respuesta(parte, nuc) or nuc
            candidato = f"{pref}{limpio_nuc}{suf}" if (pref or suf) else limpio_nuc
            final = self._afinar_salida(original, candidato)
            if ctx is not None:
                final = aplicar_concordancia(final, original, ctx)
            # Puerta de calidad por elemento del lote: si uno falla (o pierde un personaje que el
            # original nombra), se retraduce individualmente, con sus reintentos.
            perdio_nombre = ficha is not None and bool(
                nombres_perdidos(final, ficha.nombres_en(original), self.perfil.terminos_para(original)))
            if tiene_fallo_grave(evaluar_traduccion(original, final)) or perdio_nombre \
                    or self._sentido_mal(original, final):
                log.debug("Frase de lote con fallo de calidad; retraduciendo individualmente: %s", original[:50])
                final = self._traducir_unidad(original, ctx=ctx)
            else:
                firma = ctx.firma() if ctx is not None else ""
                self.cache.set(self._clave(original, self.perfil.terminos_para(original), firma), final)
                with self._lock:
                    self.estadisticas["traducidas"] += 1
                self._avisar_nueva(final)
            finales.append(final)
        return finales

    # ----------------------------------------------------------------- Validación
    def autocorrect(self, original: str, bad_translation: str, reason: str | None = None,
                    max_attempts: int = 2) -> str:
        """Pide al modelo que corrija una traducción con etiquetas rotas.
        Si no lo consigue, coloca las etiquetas que falten en su posición (último recurso)."""
        bad_translation = quitar_etiquetas_inventadas(original, bad_translation)
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
            corregido = quitar_etiquetas_inventadas(original, limpiar_respuesta(respuesta, original))
            ok, faltan, sobran = comparar_etiquetas(original, corregido)
            if ok and corregido and not tiene_fallo_grave(evaluar_traduccion(original, corregido)):
                log.info("%s  ✔ Autocorregido (intento %d): %s%s", AZUL, intento, corregido[:50], RESET)
                with self._lock:
                    self.estadisticas["autocorregidas"] += 1
                return corregido
            actual = corregido or actual
            reason = None
        with self._lock:
            self.estadisticas["forzadas"] += 1
        forzado = forzar_etiquetas(original, bad_translation)
        log.warning("  ✖ Etiquetas irrecuperables; se restauran determinísticamente: %s", forzado[:60])
        return forzado

    def traducir_textos(self, textos: list[str], info: Sequence[InfoLinea | None] | None = None) -> list[str]:
        """Traduce + valida etiquetas + autocorrige. Es lo que usan los motores.

        ``info`` (opcional, en paralelo a ``textos``): lo que el motor sabe de cada línea (quién
        habla, si es una opción...). Solo se usa si el juego tiene ficha de personajes.
        """
        infos = self._infos_alineadas(textos, info)
        if self.tam_lote == 1:
            brutos = []
            for t, inf in zip(textos, infos):  # en orden, para el historial
                brutos.append(self.translate(t, info=inf))
                self._avisar_avance(len(brutos))
        else:
            brutos = self.batch_translate(textos, infos)
        finales = []
        for original, inf, traducido in zip(textos, infos, brutos):
            traducido = quitar_etiquetas_inventadas(original, traducido)
            ok, faltan, sobran = comparar_etiquetas(original, traducido)
            if not ok:
                log.warning("  ⚠ Etiquetas rotas (%s) en: %s", describir_fallo(faltan, sobran), traducido[:50])
                traducido = self.autocorrect(original, traducido)
                ctx = self._contexto_linea(original, inf)
                if ctx is not None:  # la autocorrección puede deshacer la concordancia de género
                    traducido = aplicar_concordancia(traducido, original, ctx)
                if not tiene_fallo_grave(evaluar_traduccion(original, traducido)):
                    firma = ctx.firma() if ctx is not None else ""
                    self.cache.set(self._clave(original, self.perfil.terminos_para(original), firma), traducido)
            elif traducido != original:
                log.info("%s  ✔ %s%s", VERDE, traducido[:70], RESET)
            finales.append(traducido)
        return finales

    def traducir_validado(self, texto: str, info: InfoLinea | None = None) -> str:
        return self.traducir_textos([texto], None if info is None else [info])[0]

    # ----------------------------------------------------------------- Compatibilidad
    def extract_format_tags(self, text: str) -> list[str]:
        return extraer_etiquetas(text)

    def validate_format_tags(self, original: str, translated: str):
        return (comparar_etiquetas(original, translated)[0],
                sorted(extraer_etiquetas(original)), sorted(extraer_etiquetas(translated)))
