"""Manejador y traductor nativo para RPG Maker (MV y MZ).

Traduce archivos JSON de datos (eventos, diálogos, opciones, scripts y base de datos)
manteniendo la estructura interna, códigos de control y ajuste de línea en ventana.

Además averigua QUIÉN dice cada línea (``InfoLinea``) para que el traductor concuerde el
género: caja de nombre (``\\N<Ana>``, Yanfly ``\\n<Ana>``), hablante de MZ, código de hablante
(``HeFrOp.``) o cara del mensaje (``face:Actor1#0``).
"""
from __future__ import annotations

import copy
import inspect
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Iterator

from .. import ambiguas, config
from ..ollama import OllamaTranslator
from ..personajes import (FichaPersonajes, InfoLinea, aplicar_concordancia, es_pensamiento,
                          limpiar_nombre, resolver_linea)
from ..texto import (PATRON_PREFIJO_V21, ajustar_lineas,
                    corregir_genero_hablante_v21, corregir_puntuacion_pegada,
                    es_palabra_comun, sanitizar, tiene_texto_visible)

log = logging.getLogger(__name__)

# Campos de texto comunes en objetos de base de datos
CAMPOS_TEXTO_BD = (
    "name", "description", "message1", "message2", "message3", "nickname", "gameTitle"
)


def nombre_interno(obj: dict) -> bool:
    """True si el ``name`` de este objeto solo existe en el editor y el jugador nunca lo ve: eventos de
    mapa ("Chica - DESPUÉS"), eventos comunes ("SCN - Habitación de Marisa"), tilesets, animaciones y
    tropas. Traducirlos era trabajo perdido (en un juego grande, más de 13.000 textos) y arriesgado:
    hay plugins que buscan los eventos por su nombre original. Los nombres de mapa (MapInfos) sí se
    traducen: algunos menús de guardado los muestran."""
    return (("pages" in obj and "x" in obj and "y" in obj)                  # evento de mapa
            or ("list" in obj and "trigger" in obj and "switchId" in obj)   # evento común
            or "tilesetNames" in obj                                        # tileset
            or ("frames" in obj and "timings" in obj)                       # animación
            or ("members" in obj and "pages" in obj))                       # tropa

def nombre_visible_mapa(obj: dict) -> bool:
    """True si ``obj`` es un mapa con nombre visible de verdad (``displayName``: se muestra al entrar).
    Los marcadores como "{map_name_0033}" (hay juegos que los rellenan desde su CSV de idiomas)
    no cuentan: ``es_traducible`` los descarta porque no tienen texto fuera de las llaves."""
    return "displayName" in obj and "events" in obj and es_traducible(obj["displayName"])


# Base de datos cuyos nombres se fijan ANTES de traducir el resto (ver _preparar_glosario_bd): así el
# inventario, la ventana de "Has conseguido..." y los diálogos nombran igual cada objeto. En la
# traducción de un juego real el 30 % de las menciones decía otra cosa ("Mancuerna" en el
# inventario y "Bandeja de pesas" al conseguirla; "Cenizas impías" y "Ceniza sagrada").
ARCHIVOS_BD = ("Items", "Weapons", "Armors", "Skills", "States", "Enemies", "Classes")
ETIQUETA_PASADA_BD = "Nombres de objetos y habilidades (base de datos)"

# Listas de términos y tipos en System.json
CATEGORIAS_TERMINOS_LISTA = ("commands", "basic", "params")
CATEGORIAS_TIPOS_EQUIPO = ("equipTypes", "weaponTypes", "armorTypes", "elements", "skillTypes")

# Regex para comandos de script como:
# $gameVariables.setValue(21, "Br,fr,op.Smells like Val. Only stronger.");
# $gameVariables.setValue(25, "Incoming call...");
# $gameVariables.setValue(107, "Oracle of the Seraph");
PATRON_SET_VALUE_VARS = re.compile(
    r'((?:(?:\$gameVariables\.)?setValue\(\s*(?:21|25|107)\s*,\s*["\']))(.*?)(["\']\s*\))'
)
PATRON_SET_VALUE_21 = PATRON_SET_VALUE_VARS  # Compatibilidad hacia atrás



_PATRON_COMANDO_VOZ_NLT = re.compile(r"^/[A-Za-z0-9_-]+$")


def es_traducible(texto: Any) -> bool:
    """Verifica que sea un string con contenido útil (letras fuera de etiquetas) y no un comando de voz (/worry)."""
    if not isinstance(texto, str):
        return False
    limpio = texto.strip()
    if not limpio or _PATRON_COMANDO_VOZ_NLT.match(limpio):
        return False
    return tiene_texto_visible(texto)


PATRON_PREFIJO_HTML_RPG = re.compile(
    r"^(?:<(?:center|br|wordwrap|/center|/br)\s*/?>\s*)+",
    re.IGNORECASE,
)
PATRON_SUFIJO_CONTROL_RPG = re.compile(
    r"((?:\\[wW]\[\d+\]|\\[.!^$|><{}]|\^\s*\\|\s*\^)+\s*)$"
)


def _separar_envoltorios_dialogo(texto: str) -> tuple[str, str, str, bool]:
    """Separa prefijos (<wordwrap>, <center>, <br>, V21, \\N<...>) y sufijos (\\w[x]\\^, \\^, etc.).
    Devuelve (prefijo, cuerpo_traducible, sufijo, envolver_automatico)."""
    prefijo = ""
    sufijo = ""
    resto = texto
    envolver = True

    m_ww = re.match(r"^(?:<wordwrap>\s*)+", resto, re.IGNORECASE)
    if m_ww:
        prefijo += "<wordwrap>"
        resto = resto[m_ww.end():]
        envolver = False

    m_html = PATRON_PREFIJO_HTML_RPG.match(resto)
    if m_html:
        prefijo += re.sub(r"\s+", "", m_html.group(0))
        resto = resto[m_html.end():]
        envolver = False

    m_v21 = PATRON_PREFIJO_V21.match(resto)
    if m_v21:
        prefijo += m_v21.group(1) + "."
        resto = m_v21.group(2)
        envolver = False
    else:
        m_spk = re.match(r"^(\\N<[^>]*>)\s*", resto)
        if m_spk:
            prefijo += m_spk.group(1)
            resto = resto[m_spk.end():]

    m_suf = PATRON_SUFIJO_CONTROL_RPG.search(resto)
    if m_suf:
        raw_suf = m_suf.group(1)
        sufijo = re.sub(r"\^\s*\\", r"\\^", raw_suf)
        sufijo = re.sub(r"(?<!\\)\^", r"\\^", sufijo)
        resto = resto[:m_suf.start()].rstrip()

    if "<center>" in prefijo.lower() or "<br>" in prefijo.lower():
        envolver = False

    return prefijo, resto, sufijo, envolver


def _separar_prefijo_dialogo(texto: str) -> tuple[str, str, bool]:
    p, c, _, env = _separar_envoltorios_dialogo(texto)
    return p, c, env


# --------------------------------------------------------------------------- Hablantes
# Caja de nombre dentro del mensaje: \N<Ana> y las de Yanfly \n<Ana>, \nl<..>, \nr<..>, \nc<..>
# (pueden llevar códigos de color dentro: \n<\C[9]\N[1]\C[0]>). '\fn<Arial>' (fuente) NO casa.
PATRON_CAJA_NOMBRE = re.compile(r"\\[Nn][LlRrCc]?<([^<>]*)>")
_NO_ES_NOMBRE = re.compile(r"^/?(?:br|center|left|right|wordwrap|b|i|u|s)$", re.IGNORECASE)
# Códigos de formato que pueden ir dentro del nombre (\fb, \OC[2]...) salvo \N[n] y \P[n],
# que nombran a un actor o miembro del grupo y sirven para identificarlo.
_CODIGOS_EN_NOMBRE = re.compile(r"\\(?![NnPp]\[)[A-Za-z]+(?:\[[^\]]*\])?")

INFO_OPCION = InfoLinea(es_opcion=True)  # opción de diálogo (code 102) y su etiqueta (code 402)


def _limpiar_hablante(nombre: str) -> str:
    """'\\C[2]Ana\\C[0]' -> 'Ana'; '\\n[1]' -> '\\N[1]' (protagonista); '' si no queda nada."""
    limpio = _CODIGOS_EN_NOMBRE.sub("", limpiar_nombre(nombre or ""))
    limpio = limpio.strip().strip(":：").strip()
    m = re.fullmatch(r"\\[Nn]\[(\d+)\]", limpio)
    return f"\\N[{m.group(1)}]" if m else limpio


def hablante_de_caja(texto: str, solo_al_inicio: bool = False) -> str | None:
    """Nombre de la caja de nombre de un mensaje ('\\n<\\C[2]Ana\\C[0]>Hola' -> 'Ana',
    '\\N<\\N[1]>...' -> '\\N[1]'). Con ``solo_al_inicio`` la caja no puede ir tras texto visible."""
    if not texto or "<" not in texto:
        return None
    for m in PATRON_CAJA_NOMBRE.finditer(texto):
        if solo_al_inicio and tiene_texto_visible(texto[:m.start()]):
            return None
        nombre = _limpiar_hablante(m.group(1))
        if nombre and not _NO_ES_NOMBRE.match(nombre):
            return nombre
    return None


def codigo_v21(prefijo: str | None) -> str | None:
    """Código de hablante de un prefijo de hablante: 'HeFrOp' -> 'He', 'D1FlOp#' -> 'D1',
    '@McVo>' -> 'Mc', 'Br,fr,op' -> 'Br'. 'NPC' (personaje genérico) -> None."""
    limpio = re.sub(r"^[^A-Za-z0-9]+", "", prefijo or "")
    if not limpio or limpio.startswith("NPC"):
        return None
    codigo = limpio[:2]
    if len(codigo) < 2 or not codigo[0].isalpha() or not codigo.isalnum():
        return None
    return codigo


def _info_codigo(prefijo: str | None) -> InfoLinea | None:
    codigo = codigo_v21(prefijo)
    return InfoLinea(codigo=codigo) if codigo else None


def _prefijo_v21_de(texto: str) -> str | None:
    """Prefijo de hablante de una línea de diálogo, saltando <wordwrap>/<center>/<br> (como al separarla)."""
    resto = re.sub(r"^(?:<wordwrap>\s*)+", "", texto, flags=re.IGNORECASE)
    m_html = PATRON_PREFIJO_HTML_RPG.match(resto)
    if m_html:
        resto = resto[m_html.end():]
    m = PATRON_PREFIJO_V21.match(resto)
    return m.group(1) if m else None


def _mensaje_de(comandos: list, inicio: int) -> tuple[dict | None, list[str]]:
    """Code 101 (Mostrar texto) del que dependen las líneas 401 que empiezan en ``inicio``
    y las líneas 401 anteriores del MISMO mensaje. (None, []) si no hay cabecera justo antes."""
    previas: list[str] = []
    j = inicio - 1
    while j >= 0:
        cmd = comandos[j]
        if not isinstance(cmd, dict):
            break
        if cmd.get("code") == 101:
            previas.reverse()
            return cmd, previas
        if cmd.get("code") != 401:
            break
        params = cmd.get("parameters") or []
        if params and isinstance(params[0], str):
            previas.append(params[0])
        j -= 1
    return None, []


def info_dialogo(comandos: list, inicio: int, texto: str) -> InfoLinea | None:
    """Quién dice el grupo de líneas 401 que empieza en ``comandos[inicio]`` (``texto`` = el grupo unido).

    Hablante (de más a menos fiable): caja de nombre del mensaje y nombre de hablante de MZ
    (``parameters[4]`` del code 101). Código: prefijo de hablante (Variable 21) ('HeFrOp.' -> 'He'; 'NPC.' -> ninguno)
    y, si no hay, la cara del mensaje (``face:{faceName}#{faceIndex}``). None si no se sabe nada.
    """
    cabecera, previas = _mensaje_de(comandos, inicio)
    params = cabecera.get("parameters") if cabecera is not None else None
    if not isinstance(params, list):
        params = []

    hablante = hablante_de_caja(texto)
    if hablante is None:
        # La caja de nombre se abre al principio del mensaje y vale para todas sus líneas
        for linea in reversed(previas):
            hablante = hablante_de_caja(linea)
            if hablante:
                break
    if hablante is None and len(params) > 4 and isinstance(params[4], str):
        hablante = _limpiar_hablante(params[4]) or None

    prefijo = _prefijo_v21_de(texto)
    codigo = codigo_v21(prefijo)
    if prefijo is None and params and isinstance(params[0], str) and params[0].strip():
        indice = params[1] if len(params) > 1 and isinstance(params[1], int) else 0
        codigo = f"face:{params[0]}#{indice}"

    # Con caja de nombre \n<..> dentro del texto, "(pensamiento)" ya no se detecta solo: se marca aquí
    pensamiento = None
    if PATRON_CAJA_NOMBRE.search(texto):
        _, cuerpo, _, _ = _separar_envoltorios_dialogo(texto)
        if es_pensamiento(PATRON_CAJA_NOMBRE.sub("", cuerpo)):
            pensamiento = True

    if hablante is None and codigo is None and pensamiento is None:
        return None
    return InfoLinea(hablante=hablante, codigo=codigo, es_pensamiento=pensamiento)


def _anotar(cola: list[str], infos: list[InfoLinea | None] | None, texto: str,
            info: InfoLinea | None = None) -> None:
    """Añade ``texto`` a la cola y, si se piden, su ``InfoLinea`` en la misma posición."""
    cola.append(texto)
    if infos is not None:
        if len(infos) < len(cola) - 1:  # mantener ambas listas alineadas pase lo que pase
            infos.extend([None] * (len(cola) - 1 - len(infos)))
        infos.append(info)


_FIRMAS: dict[tuple[Any, str], bool] = {}


def _acepta_parametro(funcion: Any, nombre: str) -> bool:
    """True si ``funcion`` declara el parámetro ``nombre`` (se mira una vez por función)."""
    clave: tuple[Any, str] | None = (getattr(funcion, "__func__", funcion), nombre)
    try:
        return _FIRMAS[clave]
    except KeyError:
        pass
    except TypeError:  # objeto no hashable: no se cachea
        clave = None
    try:
        acepta = nombre in inspect.signature(funcion).parameters
    except (TypeError, ValueError):
        acepta = False
    if clave is not None:
        _FIRMAS[clave] = acepta
    return acepta


def traductor_acepta_info(translator: Any) -> bool:
    """True si ``translator.traducir_textos`` admite ``info=`` (los traductores/mocks antiguos no)."""
    funcion = getattr(translator, "traducir_textos", None)
    return funcion is not None and _acepta_parametro(funcion, "info")


class InyectorRPGMaker:
    """Extrae textos de la estructura JSON de RPG Maker, los traduce y los reinyecta."""

    def __init__(self, ruta_juego: Path, translator: OllamaTranslator, archivo_objetivo: str | None = None,
                 glosario_bd: bool = True, reaprovechar_traduccion: bool = False):
        self.ruta_juego = ruta_juego
        self.translator = translator
        self.archivo_objetivo = archivo_objetivo
        # Traducir primero los nombres de la base de datos y fijarlos (workspace/<juego>/glosario_bd.json)
        self.usar_glosario_bd = glosario_bd
        # Juego ya traducido: conservar su traducción salvo las frases con marcas de género (--solo-genero)
        self.reaprovechar_traduccion = reaprovechar_traduccion

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
    def _extraer(self, obj: Any, cola: list[str], infos: list[InfoLinea | None] | None = None) -> None:
        """Añade a ``cola`` los textos traducibles de ``obj`` en orden.

        Si se pasa ``infos``, se rellena EN PARALELO (misma longitud que ``cola``) con lo que se
        sabe de cada línea (``InfoLinea``: hablante, código, opción...) o None si no se sabe nada.
        """
        if isinstance(obj, dict):
            # No traducir nombres de audios/efectos (tienen name, volume y pitch)
            es_audio = ("name" in obj and "volume" in obj and "pitch" in obj)
            if not es_audio:
                interno = nombre_interno(obj)
                for k in CAMPOS_TEXTO_BD:
                    if k == "name" and interno:
                        continue
                    if k in obj and es_traducible(obj[k]):
                        _anotar(cola, infos, sanitizar(obj[k]))
                if nombre_visible_mapa(obj):
                    _anotar(cola, infos, sanitizar(obj["displayName"]))

            if "terms" in obj and isinstance(obj["terms"], dict):
                terms = obj["terms"]
                for cat in CATEGORIAS_TERMINOS_LISTA:
                    if cat in terms and isinstance(terms[cat], list):
                        for item in terms[cat]:
                            if es_traducible(item):
                                _anotar(cola, infos, sanitizar(item))
                if "messages" in terms and isinstance(terms["messages"], dict):
                    for msg in terms["messages"].values():
                        if es_traducible(msg):
                            _anotar(cola, infos, sanitizar(msg))

            for ak in CATEGORIAS_TIPOS_EQUIPO:
                if ak in obj and isinstance(obj[ak], list):
                    for item in obj[ak]:
                        if es_traducible(item):
                            _anotar(cola, infos, sanitizar(item))

            # Code 402: etiqueta de bifurcación condicional de opciones (repite la opción)
            if obj.get("code") == 402 and len(obj.get("parameters", [])) > 1:
                param = obj["parameters"][1]
                if es_traducible(param):
                    _anotar(cola, infos, sanitizar(param), INFO_OPCION)

            for v in obj.values():
                self._extraer(v, cola, infos)

        elif isinstance(obj, list):
            i = 0
            while i < len(obj):
                item = obj[i]
                # Code 401: Diálogos en pantalla (agrupar consecutivos)
                if (isinstance(item, dict) and item.get("code") == 401 and
                        item.get("parameters") and isinstance(item["parameters"][0], str)):
                    # Si es puramente código de control/espera sin texto visible (ej. \w[170]\^), NO agrupar
                    if not tiene_texto_visible(item["parameters"][0]):
                        i += 1
                        continue
                    inicio_grupo = i
                    fragmentos = []
                    while (i < len(obj) and isinstance(obj[i], dict) and
                           obj[i].get("code") == 401 and obj[i].get("parameters") and
                           isinstance(obj[i]["parameters"][0], str)):
                        linea_actual = obj[i]["parameters"][0]
                        if not tiene_texto_visible(linea_actual):
                            break
                        if fragmentos and PATRON_PREFIJO_V21.match(linea_actual):
                            break
                        fragmentos.append(linea_actual)
                        i += 1
                    texto_completo = " ".join(fragmentos)
                    _, cuerpo, _, _ = _separar_envoltorios_dialogo(texto_completo)
                    if es_traducible(cuerpo):
                        info = info_dialogo(obj, inicio_grupo, texto_completo) if infos is not None else None
                        _anotar(cola, infos, sanitizar(cuerpo), info)

                # Code 102: Opciones de diálogo presentadas al jugador
                elif (isinstance(item, dict) and item.get("code") == 102 and
                      item.get("parameters") and isinstance(item["parameters"][0], list)):
                    for opt in item["parameters"][0]:
                        if es_traducible(opt):
                            _anotar(cola, infos, sanitizar(opt), INFO_OPCION)
                    i += 1

                # Code 355 / 655: Diálogos y textos inyectados mediante script (V21, V25, V107)
                elif (isinstance(item, dict) and item.get("code") in (355, 655) and
                      item.get("parameters") and isinstance(item["parameters"][0], str) and
                      ".replace(/1Hero" in item["parameters"][0]):
                    item["parameters"][0] = (
                        "var res = $gameVariables.value(25).replace(/1Hero|1H[e\\u00e9]roe/gi, $gameActors.actor(1).name());"
                    )
                    i += 1

                elif (isinstance(item, dict) and item.get("code") in (355, 655) and
                      item.get("parameters") and isinstance(item["parameters"][0], str) and
                      any(v in item["parameters"][0] for v in ("setValue(21", "setValue(25", "setValue(107"))):
                    script = item["parameters"][0]
                    m = PATRON_SET_VALUE_VARS.search(script)
                    if m:
                        contenido = m.group(2)
                        m_pref = PATRON_PREFIJO_V21.match(contenido)
                        texto = m_pref.group(2) if m_pref else contenido
                        if es_traducible(texto):
                            info = _info_codigo(m_pref.group(1)) if (m_pref and infos is not None) else None
                            _anotar(cola, infos, sanitizar(texto), info)
                    i += 1

                else:
                    self._extraer(item, cola, infos)
                    i += 1

    def extraer_con_info(self, datos: Any) -> list[tuple[str, InfoLinea | None]]:
        """Textos traducibles (mismo orden que ``_extraer``) con lo que se sabe de cada línea.

        No modifica ``datos`` (se trabaja sobre una copia). Sirve para la auditoría de género,
        que empareja el JSON traducido con su ``.json.bak`` original.
        """
        cola: list[str] = []
        infos: list[InfoLinea | None] = []
        self._extraer(copy.deepcopy(datos), cola, infos)
        return list(zip(cola, infos))

    # ----------------------------------------------------------------- Inyección
    def _inyectar(self, obj: Any, iterador: Iterator[str]) -> Any:
        if isinstance(obj, dict):
            es_audio = ("name" in obj and "volume" in obj and "pitch" in obj)
            if not es_audio:
                interno = nombre_interno(obj)
                for k in CAMPOS_TEXTO_BD:
                    if k == "name" and interno:
                        continue  # mismo criterio que _extraer: el iterador va sincronizado
                    if k in obj and es_traducible(obj[k]):
                        orig = obj[k]
                        trad = next(iterador)
                        trad = self.translator.perfil.restaurar_nombres(orig, trad)
                        if k == "description":
                            trad = "\n".join(ajustar_lineas(trad, ancho=48))
                        obj[k] = trad
                if nombre_visible_mapa(obj):  # mismo orden que _extraer
                    trad = next(iterador)
                    obj["displayName"] = self.translator.perfil.restaurar_nombres(obj["displayName"], trad)

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
                    trad = self.translator.perfil.restaurar_nombres(param, trad)
                    obj["parameters"][1] = self._concordar(trad, sanitizar(param), INFO_OPCION)

            for k in list(obj.keys()):
                self._inyectar(obj[k], iterador)

        elif isinstance(obj, list):
            i = 0
            while i < len(obj):
                item = obj[i]
                if (isinstance(item, dict) and item.get("code") == 401 and
                        item.get("parameters") and isinstance(item["parameters"][0], str)):
                    # Si es puramente código de control/espera sin texto visible (ej. \w[170]\^), dejar intacto
                    if not tiene_texto_visible(item["parameters"][0]):
                        i += 1
                        continue
                    inicio_grupo = i
                    fragmentos = []
                    while (i < len(obj) and isinstance(obj[i], dict) and
                           obj[i].get("code") == 401 and obj[i].get("parameters") and
                           isinstance(obj[i]["parameters"][0], str)):
                        linea_actual = obj[i]["parameters"][0]
                        if not tiene_texto_visible(linea_actual):
                            break
                        if fragmentos and PATRON_PREFIJO_V21.match(linea_actual):
                            break
                        fragmentos.append(linea_actual)
                        i += 1
                    texto_completo = " ".join(fragmentos)
                    prefijo_dlg, cuerpo_dlg, sufijo_dlg, partir_en_lineas = _separar_envoltorios_dialogo(texto_completo)
                    if es_traducible(cuerpo_dlg):
                        trad = next(iterador)
                        trad = self.translator.perfil.restaurar_nombres(cuerpo_dlg, trad)
                        trad = re.sub(r"^(?:<wordwrap>\s*)+", "", trad, flags=re.IGNORECASE)
                        trad = corregir_puntuacion_pegada(trad)
                        if self._ficha() is not None:
                            trad = self._concordar(trad, sanitizar(cuerpo_dlg),
                                                   info_dialogo(obj, inicio_grupo, texto_completo))
                        if partir_en_lineas:
                            lineas = ajustar_lineas(trad, ancho=45)
                            if prefijo_dlg and lineas:
                                lineas[0] = f"{prefijo_dlg}{lineas[0]}"
                            if sufijo_dlg and lineas:
                                lineas[-1] = f"{lineas[-1]}{sufijo_dlg}"
                        else:
                            lineas = [f"{prefijo_dlg}{trad}{sufijo_dlg}"]
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
                            trad = corregir_puntuacion_pegada(trad)
                            opciones[idx] = self._concordar(trad, sanitizar(orig), INFO_OPCION)
                    i += 1

                elif (isinstance(item, dict) and item.get("code") in (355, 655) and
                      item.get("parameters") and isinstance(item["parameters"][0], str) and
                      ".replace(/1Hero" in item["parameters"][0]):
                    item["parameters"][0] = (
                        "var res = $gameVariables.value(25).replace(/1Hero|1H[e\\u00e9]roe/gi, $gameActors.actor(1).name());"
                    )
                    i += 1

                elif (isinstance(item, dict) and item.get("code") in (355, 655) and
                      item.get("parameters") and isinstance(item["parameters"][0], str) and
                      any(v in item["parameters"][0] for v in ("setValue(21", "setValue(25", "setValue(107"))):
                    script = item["parameters"][0]
                    m = PATRON_SET_VALUE_VARS.search(script)
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
                            if prefijo_int:
                                trad = self._corregir_genero_v21(trad, prefijo_int)
                            # Si el LLM devolvió accidentalmente el prefijo duplicado al inicio, quitarlo
                            if prefijo_int and trad.startswith(prefijo_int):
                                trad = trad[len(prefijo_int):].lstrip()
                            trad = self._concordar(trad, sanitizar(texto),
                                                   _info_codigo(m_pref.group(1)) if m_pref else None)
                            # Limpiar comillas según el delimitador JS usado para no romper el string
                            comilla = m.group(1)[-1]
                            if comilla == '"':
                                trad_seguro = trad.replace('\\"', "'").replace('"', "'")
                            else:
                                trad_seguro = trad.replace("\\'", '"').replace("'", '"')
                            trad_seguro = trad_seguro.rstrip("\\")
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

    # ----------------------------------------------------------------- Género (ficha de personajes)
    def _ficha(self) -> FichaPersonajes | None:
        """Ficha de personajes del perfil activo (None en el modo antiguo, sin personajes.json)."""
        ficha = getattr(getattr(self.translator, "perfil", None), "personajes", None)
        return ficha if isinstance(ficha, FichaPersonajes) else None

    def _corregir_genero_v21(self, trad: str, prefijo: str) -> str:
        """Corrección por código de hablante: con ficha, según sus personajes; sin ficha, como siempre."""
        ficha = self._ficha()
        if ficha is not None and _acepta_parametro(corregir_genero_hablante_v21, "ficha"):
            return corregir_genero_hablante_v21(trad, prefijo, ficha=ficha)
        return corregir_genero_hablante_v21(trad, prefijo)

    def _concordar(self, traducido: str, original: str, info: InfoLinea | None) -> str:
        """Concordancia de género determinista si se sabe quién habla y su género.

        Es la misma corrección que aplica el traductor (idempotente): aquí hace de red de
        seguridad para traductores sin ``info`` o traducciones antiguas de la caché.
        """
        ficha = self._ficha()
        if ficha is None or not ficha.personajes or not traducido:
            return traducido
        try:
            ctx = resolver_linea(ficha, original, info)
            if ctx.hablante is None or not ctx.hablante.genero_conocido:
                return traducido
            return aplicar_concordancia(traducido, original, ctx)
        except Exception as e:  # la inyección no debe romperse por una corrección auxiliar
            log.warning("  ⚠ No se pudo aplicar la concordancia de género a '%s': %s", original[:50], e)
            return traducido

    # ----------------------------------------------------------------- Glosario de la base de datos
    def _nombres_bd(self, carpeta: Path) -> list[str]:
        """Nombres en inglés (sin códigos alrededor ni repetidos) de objetos, armas, armaduras,
        habilidades, estados, enemigos y clases."""
        nombres: dict[str, None] = {}
        for base in ARCHIVOS_BD:
            ruta = carpeta / f"{base}.json"
            if not ruta.exists() and not ruta.with_suffix(".json.bak").exists():
                continue
            try:
                datos = self._leer_origen(ruta)
            except Exception as e:
                log.debug("No se pudo leer %s para el glosario de la base de datos: %s", ruta.name, e)
                continue
            for obj in datos if isinstance(datos, list) else []:
                nombre = obj.get("name") if isinstance(obj, dict) else None
                if not es_traducible(nombre):
                    continue
                _, nucleo, _ = config.separar_bordes(sanitizar(nombre))
                # Con códigos en medio ("\c[2]Red\c[0] Potion") se traduce como siempre, en su archivo.
                if len(nucleo) >= 2 and "\\" not in nucleo and re.search(r"[A-Za-z]", nucleo):
                    nombres.setdefault(nucleo, None)
        return list(nombres)

    def _nombres_bd_ya_traducidos(self, carpeta: Path) -> dict[str, str]:
        """{nombre inglés: nombre que ya tiene el juego traducido} (emparejados por posición con su .bak)."""
        actuales: dict[str, str] = {}
        for base in ARCHIVOS_BD:
            ruta = carpeta / f"{base}.json"
            if not (ruta.exists() and ruta.with_suffix(".json.bak").exists()):
                continue
            try:
                originales = self._leer_origen(ruta)
                traducidos = json.loads(ruta.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if not (isinstance(originales, list) and isinstance(traducidos, list)) or len(originales) != len(traducidos):
                continue
            for a, b in zip(originales, traducidos):
                en = a.get("name") if isinstance(a, dict) else None
                es = b.get("name") if isinstance(b, dict) else None
                if es_traducible(en) and isinstance(es, str):
                    nucleo_en = config.separar_bordes(sanitizar(en))[1]
                    nucleo_es = config.separar_bordes(sanitizar(es))[1].strip()
                    if nucleo_es and nucleo_es != nucleo_en and "\\" not in nucleo_es:
                        actuales.setdefault(nucleo_en, nucleo_es)
        return actuales

    def _usos_en_minuscula(self, carpeta: Path, nombres: Iterable[str]) -> set[str]:
        """Nombres que el juego TAMBIÉN escribe en minúscula en algún texto ("stick", "my chest"): son
        palabras corrientes y no se fuerzan dentro de las frases ("Stick with me" no habla de un palo)."""
        candidatos = {n.lower(): n for n in nombres if n != n.lower()}
        if not candidatos:
            return set()
        patron = re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in sorted(candidatos, key=len, reverse=True))
                            + r")(?:e?s)?(?!\w)")
        usados: set[str] = set()
        for ruta in sorted(carpeta.glob("*.json")):
            try:
                cola: list[str] = []
                self._extraer(self._leer_origen(ruta), cola)
            except Exception:
                continue
            for texto in cola:
                for m in patron.finditer(texto):
                    usados.add(candidatos[m.group(1)])
        return usados

    def _traducir_sin_progreso(self, textos: list[str]) -> list[str]:
        """Traduce sin mover la barra del archivo en curso (cada nombre se cuenta luego en su archivo)."""
        progreso = getattr(self.translator, "progreso", None)
        if progreso is None:
            return self.translator.traducir_textos(textos)
        progreso.archivo_actual = ETIQUETA_PASADA_BD
        progreso.guardar(forzar=True)
        self.translator.progreso = None
        try:
            return self.translator.traducir_textos(textos)
        finally:
            self.translator.progreso = progreso

    def _preparar_glosario_bd(self, carpeta: Path) -> None:
        """Traduce primero los nombres de la base de datos y los fija en workspace/<juego>/glosario_bd.json.

        - Un texto que ES un nombre (inventario, "Has conseguido...", opciones) copia esa traducción.
        - Dentro de las frases solo se piden los que el juego nunca escribe en minúscula: "Rough Diamond"
          sí; "Stick" o "Chest" no ("Stick with me", "my chest"), ni palabras corrientes como "Fire".
        - Lo que ya está en glosario_bd.json se respeta (el usuario puede corregirlo): solo se traducen
          los nombres nuevos. Los que están en el glosario del juego usan esa traducción. Los nombres de
          personajes no se tocan.
        """
        perfil = getattr(self.translator, "perfil", None)
        if not self.usar_glosario_bd or perfil is None or not hasattr(perfil, "fijar_glosario_bd"):
            return
        nombres = self._nombres_bd(carpeta)
        fijados = dict(perfil.glosario_bd)
        en_frases = set(perfil.glosario_bd_frases)
        ficha = self._ficha()
        personajes = {x.casefold() for p in (ficha.personajes if ficha is not None else []) for x in p.nombres()}
        protegidos = getattr(perfil, "nombres_protegidos", {}) or {}
        # Los objetos que se llaman como un personaje (p. ej. un objeto con el nombre de la protagonista) no se fijan.
        nuevos = [n for n in nombres if n not in fijados and n not in protegidos and n.casefold() not in personajes]
        if not nuevos:
            return
        del_glosario = {n: perfil.valor_glosario(n) for n in nuevos}
        if self.reaprovechar_traduccion:  # --solo-genero: el inventario se queda como ya estaba traducido
            actuales = self._nombres_bd_ya_traducidos(carpeta)
            for n in nuevos:
                # ...salvo los que entienden al revés una palabra de dos sentidos ("Safe Key" -> "Llave de
                # seguridad"): esos se vuelven a pedir, ya con el sentido en su glosario.
                if not del_glosario[n] and n in actuales and not ambiguas.sentido_equivocado(n, actuales[n]):
                    del_glosario[n] = actuales[n]
        pedir = [n for n in nuevos if not del_glosario[n]]
        log.info("📒 Fijando la traducción de %d nombre(s) de objetos, habilidades... (%d ya tenían traducción) "
                 "para que el inventario y los diálogos digan lo mismo.", len(nuevos), len(nuevos) - len(pedir))
        traducciones = self._traducir_sin_progreso(pedir) if pedir else []
        for n, t in zip(pedir, traducciones):
            _, limpio, _ = config.separar_bordes(t or "")
            limpio = limpio.strip()
            # Si vuelve el inglés (o nada) no se fija: se intentará otra vez en la próxima pasada.
            if limpio and limpio.casefold() != n.casefold() and "\n" not in limpio:
                fijados[n] = limpio
        for n, valor in del_glosario.items():
            if valor:
                fijados[n] = valor
        recien = [n for n in nuevos if n in fijados]
        if not recien:  # p. ej. marcas que se quedan igual ("Kamasutra"): nada nuevo que guardar
            return
        minusculas = self._usos_en_minuscula(carpeta, recien)
        for n in recien:
            if len(n) >= 3 and n != n.lower() and n not in minusculas and not es_palabra_comun(n):
                en_frases.add(n)
        perfil.fijar_glosario_bd(fijados, en_frases)
        carpeta_perfil = config.carpeta_juego(perfil.juego) if getattr(perfil, "juego", None) else None
        if carpeta_perfil is None or carpeta_perfil.name == "_comun" or not carpeta_perfil.is_dir():
            return  # sin carpeta de perfil se usa solo en esta pasada (no se crean perfiles a medias)
        ruta = carpeta_perfil / config.ARCHIVO_GLOSARIO_BD
        try:
            config.guardar_glosario_bd(ruta, fijados, en_frases)
        except OSError as e:
            log.warning("No se pudo guardar %s: %s", ruta, e)
            return
        log.info("📒 %d nombre(s) fijados (%d también dentro de los diálogos). Puedes corregirlos en %s",
                 len(recien), sum(1 for n in recien if n in en_frases), ruta)

    def _sembrar_traduccion_actual(self, json_path: Path, cola: list[str],
                                   infos: list[InfoLinea | None]) -> int:
        """--solo-genero: empareja frase a frase el JSON ya traducido con su original y guarda en la
        caché las traducciones SIN marcas de género en 1.ª/2.ª persona; el modelo solo recibe el resto
        (las de género y las que siguen en inglés). Devuelve cuántas se conservan."""
        sembrar = getattr(self.translator, "sembrar_traduccion", None)
        if sembrar is None or not json_path.with_suffix(".json.bak").exists():
            return 0
        try:
            actual = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            log.warning("  No se pudo leer la traducción actual de %s (%s): se traduce entero.", json_path.name, e)
            return 0
        cola_actual: list[str] = []
        self._extraer(actual, cola_actual)
        if len(cola_actual) != len(cola):
            log.info("  ↷ %s: la traducción actual no se puede emparejar frase a frase; se traduce entero.",
                     json_path.name)
            return 0
        conservadas = sum(1 for original, traduccion, info in zip(cola, cola_actual, infos)
                          if sembrar(original, traduccion, info))
        if conservadas:
            log.info("  ♻ %d de %d frases conservan la traducción que ya tenía el juego (sin marcas de género).",
                     conservadas, len(cola))
        return conservadas

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

        # Antes que nada, los nombres de objetos, habilidades... (los diálogos de los mapas los nombran)
        carpeta_bd = self.obtener_carpeta_datos()
        if carpeta_bd is not None:
            self._preparar_glosario_bd(carpeta_bd)

        for idx, json_path in enumerate(archivos, 1):
            getattr(self.translator, "_comprobar_pausa", lambda: None)()
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
            infos: list[InfoLinea | None] = []
            self._extraer(datos, cola, infos)

            if not cola:
                log.info("  No se encontraron textos para traducir en %s.", json_path.name)
                if progreso is not None:
                    progreso.fin_archivo()
                continue

            if self.reaprovechar_traduccion:
                self._sembrar_traduccion_actual(json_path, cola, infos)

            log.info("  Traduciendo %d cadena(s) en %s...", len(cola), json_path.name)
            if traductor_acepta_info(self.translator):
                con_pista = sum(1 for inf in infos if inf is not None and (inf.hablante or inf.codigo))
                if con_pista and self._ficha() is not None:
                    log.info("  👤 %d de %d línea(s) traen pista de hablante (caja de nombre, código de hablante o cara).",
                             con_pista, len(cola))
                traducciones = self.translator.traducir_textos(cola, info=infos)
            else:
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

        # Incrementar versionId en System.json para que RPG Maker recargue los mapas al cargar partida
        carpeta_datos = self.obtener_carpeta_datos()
        if carpeta_datos:
            sys_json = carpeta_datos / "System.json"
            if sys_json.exists():
                try:
                    sys_data = json.loads(sys_json.read_text(encoding="utf-8-sig"))
                    if isinstance(sys_data, dict) and isinstance(sys_data.get("versionId"), int):
                        sys_data["versionId"] += 1
                        sys_json.write_text(json.dumps(sys_data, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    log.debug("No se pudo incrementar versionId en System.json: %s", e)

        # Procesar configuraciones de plugins (plugins.js) y textos de interfaz (rpg_windows.js)
        self._procesar_plugins_js()

    def _procesar_plugins_js(self) -> None:
        """Traduce configuraciones y opciones de plugins en plugins.js y booleanos en rpg_windows.js."""
        # 1. Localizar plugins.js (MV: www/js/plugins.js, MZ: js/plugins.js)
        posibles_plugins = [
            self.ruta_juego / "www" / "js" / "plugins.js",
            self.ruta_juego / "js" / "plugins.js",
        ]
        plugins_js = next((p for p in posibles_plugins if p.exists()), None)
        if plugins_js:
            try:
                content = plugins_js.read_text(encoding="utf-8-sig")
                start = content.find("[")
                end = content.rfind("]") + 1
                if start != -1 and end > start:
                    plugins = json.loads(content[start:end])
                    modificado = False
                    glosario = {k.strip().lower(): v for k, v in self.translator.perfil.glosario.items()}

                    for p in plugins:
                        params = p.get("parameters", {})
                        if not isinstance(params, dict):
                            continue
                        for k, v in list(params.items()):
                            if not isinstance(v, str) or not v.strip():
                                continue
                            v_clean = v.strip()
                            v_low = v_clean.lower()
                            # Coincidencia con glosario activo
                            if v_low in glosario:
                                if params[k] != glosario[v_low]:
                                    params[k] = glosario[v_low]
                                    modificado = True
                                    log.info("  [Plugin %s] %s: '%s' -> '%s'", p.get("name"), k, v, params[k])
                            # Parámetros habituales de opciones de menú o textos visibles
                            elif any(term in k.lower() for term in ("option", "text", "command", "title", "speed", "name", "desc")):
                                if not v_clean.isdigit() and v_clean not in ("true", "false", "none", "auto") and tiene_texto_visible(v_clean):
                                    trad = self.translator.translate(v_clean)
                                    if trad and trad != v_clean:
                                        params[k] = trad
                                        modificado = True
                                        log.info("  [Plugin %s] %s: '%s' -> '%s'", p.get("name"), k, v, trad)

                    if modificado:
                        backup = plugins_js.with_suffix(".js.bak")
                        if not backup.exists():
                            shutil.copy2(plugins_js, backup)
                        nuevo_json = json.dumps(plugins, indent=2, ensure_ascii=False)
                        nuevo_content = content[:start] + nuevo_json + content[end:]
                        plugins_js.write_text(nuevo_content, encoding="utf-8")
                        log.info("✔ Opciones y textos de plugins.js traducidos y guardados con éxito.")
            except Exception as e:
                log.warning("No se pudo procesar plugins.js: %s", e)

        # 2. Localizar rpg_windows.js para ajustar 'ON' : 'OFF' a 'SÍ' : 'NO'
        posibles_windows = [
            self.ruta_juego / "www" / "js" / "rpg_windows.js",
            self.ruta_juego / "js" / "rpg_windows.js",
        ]
        windows_js = next((p for p in posibles_windows if p.exists()), None)
        if windows_js:
            try:
                w_content = windows_js.read_text(encoding="utf-8-sig")
                mod_w = False
                if "'ON' : 'OFF'" in w_content:
                    w_content = w_content.replace("'ON' : 'OFF'", "'SÍ' : 'NO'")
                    mod_w = True
                # Comodín del protagonista escrito en el texto ("1Hero" en lugar de su nombre): solo si la ficha
                # dice que el protagonista se llama así; el juego lo cambia por el nombre que elija el jugador.
                ficha = self._ficha()
                prota = ficha.protagonista() if ficha is not None else None
                comodin = prota.nombre if prota is not None and prota.nombre == "1Hero" else None
                target_esc = "    text = text.replace(/\\x1bG/gi, TextManager.currencyUnit);\n    return text;"
                patch_1hero = (
                    "    text = text.replace(/\\x1bG/gi, TextManager.currencyUnit);\n"
                    "    if ($gameActors && $gameActors.actor(1)) {\n"
                    "        text = text.replace(/1Hero|1H[e\\u00e9]roe/gi, $gameActors.actor(1).name());\n"
                    "    }\n"
                    "    return text;"
                )
                if comodin and comodin not in w_content and target_esc in w_content:
                    w_content = w_content.replace(target_esc, patch_1hero, 1)
                    mod_w = True
                if mod_w:
                    backup_w = windows_js.with_suffix(".js.bak")
                    if not backup_w.exists():
                        shutil.copy2(windows_js, backup_w)
                    windows_js.write_text(w_content, encoding="utf-8")
                    log.info("✔ rpg_windows.js actualizado ('ON'/'OFF' y comodín del protagonista).")
            except Exception as e:
                log.warning("No se pudo ajustar rpg_windows.js: %s", e)
