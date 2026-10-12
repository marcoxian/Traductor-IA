"""Manejador y traductor nativo para RPG Maker (MV y MZ).

Traduce archivos JSON de datos (eventos, diálogos, opciones, scripts y base de datos)
manteniendo la estructura interna, códigos de control y ajuste de línea en ventana.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterator

from ..ollama import OllamaTranslator
from ..texto import (PATRON_PREFIJO_V21, ajustar_lineas, corregir_puntuacion_pegada,
                    sanitizar, tiene_texto_visible)

log = logging.getLogger(__name__)

# Campos de texto comunes en objetos de base de datos
CAMPOS_TEXTO_BD = (
    "name", "description", "message1", "message2", "message3", "nickname", "gameTitle"
)

# Listas de términos y tipos en System.json
CATEGORIAS_TERMINOS_LISTA = ("commands", "basic", "params")
CATEGORIAS_TIPOS_EQUIPO = ("equipTypes", "weaponTypes", "armorTypes", "elements", "skillTypes")

# Regex para comandos de script como:
# $gameVariables.setValue(21, "Br,fr,op.Smells like Val. Only stronger.");
# setValue(21, "Text here");
PATRON_SET_VALUE_21 = re.compile(
    r'((?:(?:\$gameVariables\.)?setValue\(\s*21\s*,\s*["\']))(.*?)(["\']\s*\))'
)


def es_traducible(texto: Any) -> bool:
    """Verifica que sea un string con contenido útil (letras fuera de etiquetas)."""
    return isinstance(texto, str) and bool(texto.strip()) and tiene_texto_visible(texto)


class InyectorRPGMaker:
    """Extrae textos de la estructura JSON de RPG Maker, los traduce y los reinyecta."""

    def __init__(self, ruta_juego: Path, translator: OllamaTranslator, archivo_objetivo: str | None = None):
        self.ruta_juego = ruta_juego
        self.translator = translator
        self.archivo_objetivo = archivo_objetivo

    def obtener_carpeta_datos(self) -> Path | None:
        """Localiza la carpeta de datos www/data (MV) o data (MZ)."""
        data_dir = self.ruta_juego / "www" / "data"
        if not data_dir.exists():
            data_dir = self.ruta_juego / "data"
        if not data_dir.exists():
            log.error("No se encontró la carpeta 'data' de RPG Maker en %s.", self.ruta_juego)
            return None
        return data_dir

    def obtener_archivos_json(self) -> list[Path]:
        carpeta = self.obtener_carpeta_datos()
        if not carpeta:
            return []
        archivos = sorted(carpeta.glob("*.json"))
        if self.archivo_objetivo:
            nombre = self.archivo_objetivo.lower()
            archivos = [f for f in archivos if f.name.lower() == nombre]
            if not archivos:
                log.error("No se encontró el archivo especificado: %s en %s", self.archivo_objetivo, carpeta)
        return archivos

    # ----------------------------------------------------------------- Extracción
    def _extraer(self, obj: Any, cola: list[str]) -> None:
        if isinstance(obj, dict):
            # No traducir nombres de audios/efectos (tienen name, volume y pitch)
            es_audio = ("name" in obj and "volume" in obj and "pitch" in obj)
            if not es_audio:
                for k in CAMPOS_TEXTO_BD:
                    if k in obj and es_traducible(obj[k]):
                        cola.append(sanitizar(obj[k]))

            if "terms" in obj and isinstance(obj["terms"], dict):
                terms = obj["terms"]
                for cat in CATEGORIAS_TERMINOS_LISTA:
                    if cat in terms and isinstance(terms[cat], list):
                        for item in terms[cat]:
                            if es_traducible(item):
                                cola.append(sanitizar(item))
                if "messages" in terms and isinstance(terms["messages"], dict):
                    for msg in terms["messages"].values():
                        if es_traducible(msg):
                            cola.append(sanitizar(msg))

            for ak in CATEGORIAS_TIPOS_EQUIPO:
                if ak in obj and isinstance(obj[ak], list):
                    for item in obj[ak]:
                        if es_traducible(item):
                            cola.append(sanitizar(item))

            # Code 402: etiqueta de bifurcación condicional de opciones
            if obj.get("code") == 402 and len(obj.get("parameters", [])) > 1:
                param = obj["parameters"][1]
                if es_traducible(param):
                    cola.append(sanitizar(param))

            for v in obj.values():
                self._extraer(v, cola)

        elif isinstance(obj, list):
            i = 0
            while i < len(obj):
                item = obj[i]
                # Code 401: Diálogos en pantalla (agrupar consecutivos)
                if (isinstance(item, dict) and item.get("code") == 401 and
                        item.get("parameters") and isinstance(item["parameters"][0], str)):
                    fragmentos = []
                    while (i < len(obj) and isinstance(obj[i], dict) and
                           obj[i].get("code") == 401 and obj[i].get("parameters") and
                           isinstance(obj[i]["parameters"][0], str)):
                        fragmentos.append(obj[i]["parameters"][0])
                        i += 1
                    texto_completo = " ".join(fragmentos)
                    if es_traducible(texto_completo):
                        cola.append(sanitizar(texto_completo))

                # Code 102: Opciones de diálogo presentadas al jugador
                elif (isinstance(item, dict) and item.get("code") == 102 and
                      item.get("parameters") and isinstance(item["parameters"][0], list)):
                    for opt in item["parameters"][0]:
                        if es_traducible(opt):
                            cola.append(sanitizar(opt))
                    i += 1

                # Code 355: Diálogos inyectados mediante script
                elif (isinstance(item, dict) and item.get("code") == 355 and
                      item.get("parameters") and isinstance(item["parameters"][0], str) and
                      "setValue(21" in item["parameters"][0]):
                    script = item["parameters"][0]
                    m = PATRON_SET_VALUE_21.search(script)
                    if m:
                        contenido = m.group(2)
                        m_pref = PATRON_PREFIJO_V21.match(contenido)
                        texto = m_pref.group(2) if m_pref else contenido
                        if es_traducible(texto):
                            cola.append(sanitizar(texto))
                    i += 1

                else:
                    self._extraer(item, cola)
                    i += 1

    # ----------------------------------------------------------------- Inyección
    def _inyectar(self, obj: Any, iterador: Iterator[str]) -> Any:
        if isinstance(obj, dict):
            es_audio = ("name" in obj and "volume" in obj and "pitch" in obj)
            if not es_audio:
                for k in CAMPOS_TEXTO_BD:
                    if k in obj and es_traducible(obj[k]):
                        orig = obj[k]
                        trad = next(iterador)
                        trad = self.translator.perfil.restaurar_nombres(orig, trad)
                        if k == "description":
                            trad = "\n".join(ajustar_lineas(trad, ancho=48))
                        obj[k] = trad

            if "terms" in obj and isinstance(obj["terms"], dict):
                terms = obj["terms"]
                for cat in CATEGORIAS_TERMINOS_LISTA:
                    if cat in terms and isinstance(terms[cat], list):
                        for idx, item in enumerate(terms[cat]):
                            if es_traducible(item):
                                trad = next(iterador)
                                terms[cat][idx] = self.translator.perfil.restaurar_nombres(item, trad)
                if "messages" in terms and isinstance(terms["messages"], dict):
                    for mk, msg in terms["messages"].items():
                        if es_traducible(msg):
                            trad = next(iterador)
                            terms["messages"][mk] = self.translator.perfil.restaurar_nombres(msg, trad)

            for ak in CATEGORIAS_TIPOS_EQUIPO:
                if ak in obj and isinstance(obj[ak], list):
                    for idx, item in enumerate(obj[ak]):
                        if es_traducible(item):
                            trad = next(iterador)
                            obj[ak][idx] = self.translator.perfil.restaurar_nombres(item, trad)

            if obj.get("code") == 402 and len(obj.get("parameters", [])) > 1:
                param = obj["parameters"][1]
                if es_traducible(param):
                    trad = next(iterador)
                    obj["parameters"][1] = self.translator.perfil.restaurar_nombres(param, trad)

            for k in list(obj.keys()):
                self._inyectar(obj[k], iterador)

        elif isinstance(obj, list):
            i = 0
            while i < len(obj):
                item = obj[i]
                if (isinstance(item, dict) and item.get("code") == 401 and
                        item.get("parameters") and isinstance(item["parameters"][0], str)):
                    inicio_grupo = i
                    fragmentos = []
                    while (i < len(obj) and isinstance(obj[i], dict) and
                           obj[i].get("code") == 401 and obj[i].get("parameters") and
                           isinstance(obj[i]["parameters"][0], str)):
                        fragmentos.append(obj[i]["parameters"][0])
                        i += 1
                    texto_completo = " ".join(fragmentos)
                    if es_traducible(texto_completo):
                        trad = next(iterador)
                        trad = self.translator.perfil.restaurar_nombres(texto_completo, trad)
                        trad = corregir_puntuacion_pegada(trad)
                        lineas = ajustar_lineas(trad, ancho=45)
                        nuevos_cmds = []
                        for linea in lineas:
                            cmd = copy.deepcopy(obj[inicio_grupo])
                            cmd["parameters"][0] = linea
                            nuevos_cmds.append(cmd)
                        obj[inicio_grupo:i] = nuevos_cmds
                        i = inicio_grupo + len(nuevos_cmds)

                elif (isinstance(item, dict) and item.get("code") == 102 and
                      item.get("parameters") and isinstance(item["parameters"][0], list)):
                    opciones = item["parameters"][0]
                    for idx in range(len(opciones)):
                        if es_traducible(opciones[idx]):
                            orig = opciones[idx]
                            trad = next(iterador)
                            trad = self.translator.perfil.restaurar_nombres(orig, trad)
                            opciones[idx] = corregir_puntuacion_pegada(trad)
                    i += 1

                elif (isinstance(item, dict) and item.get("code") == 355 and
                      item.get("parameters") and isinstance(item["parameters"][0], str) and
                      "setValue(21" in item["parameters"][0]):
                    script = item["parameters"][0]
                    m = PATRON_SET_VALUE_21.search(script)
                    if m:
                        contenido = m.group(2)
                        m_pref = PATRON_PREFIJO_V21.match(contenido)
                        if m_pref:
                            prefijo_int = m_pref.group(1) + "."
                            texto = m_pref.group(2)
                        else:
                            prefijo_int = ""
                            texto = contenido
                        if es_traducible(texto):
                            trad = next(iterador)
                            trad = self.translator.perfil.restaurar_nombres(texto, trad)
                            trad = corregir_puntuacion_pegada(trad)
                            # Limpiar comillas para no romper el string dentro del script JS
                            trad_seguro = trad.replace('"', "'").replace('\\', '')
                            nuevo_script = (
                                script[:m.start()] +
                                m.group(1) + prefijo_int + trad_seguro + m.group(3) +
                                script[m.end():]
                            )
                            item["parameters"][0] = nuevo_script
                    i += 1

                else:
                    self._inyectar(item, iterador)
                    i += 1
        return obj

    # ----------------------------------------------------------------- Ejecución
    def _leer_origen(self, json_path: Path) -> Any:
        backup_path = json_path.with_suffix(".json.bak")
        origen = backup_path if backup_path.exists() else json_path
        with open(origen, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def _contar_frases(self, archivos: list[Path]) -> dict[Path, int]:
        """Pre-escaneo rápido (solo lectura) para conocer el total real de frases."""
        conteo: dict[Path, int] = {}
        for json_path in archivos:
            try:
                cola: list[str] = []
                self._extraer(self._leer_origen(json_path), cola)
                conteo[json_path] = len(cola)
            except Exception:
                conteo[json_path] = 0
        return conteo

    def procesar(self) -> None:
        archivos = self.obtener_archivos_json()
        if not archivos:
            log.warning("No hay archivos JSON para procesar.")
            return

        total_archivos = len(archivos)
        log.info("Iniciando procesamiento de %d archivo(s) JSON de RPG Maker...", total_archivos)

        progreso = getattr(self.translator, "progreso", None)
        conteo: dict[Path, int] = {}
        if progreso is not None:
            conteo = self._contar_frases(archivos)
            progreso.definir_totales(sum(conteo.values()), total_archivos)
            log.info("Total estimado: %d frases en %d archivos.", sum(conteo.values()), total_archivos)

        for idx, json_path in enumerate(archivos, 1):
            log.info("[%d/%d] Analizando: %s...", idx, total_archivos, json_path.name)
            if progreso is not None:
                progreso.inicio_archivo(json_path.name, idx, conteo.get(json_path, 0))

            backup_path = json_path.with_suffix(".json.bak")
            if not backup_path.exists():
                shutil.copy2(json_path, backup_path)
                log.debug("Copia de seguridad creada: %s", backup_path.name)

            try:
                datos = self._leer_origen(json_path)
            except Exception as e:
                log.error("Error al leer %s: %s", json_path.name, e)
                if progreso is not None:
                    progreso.fin_archivo()
                continue

            cola: list[str] = []
            self._extraer(datos, cola)

            if not cola:
                log.info("  No se encontraron textos para traducir en %s.", json_path.name)
                if progreso is not None:
                    progreso.fin_archivo()
                continue

            log.info("  Traduciendo %d cadena(s) en %s...", len(cola), json_path.name)
            traducciones = self.translator.traducir_textos(cola)

            iterador = iter(traducciones)
            self._inyectar(datos, iterador)

            # Guardado atómico
            tmp_path = json_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False)
            os.replace(tmp_path, json_path)

            log.info("  ✔ Guardado con éxito: %s", json_path.name)
            if progreso is not None:
                progreso.fin_archivo()
