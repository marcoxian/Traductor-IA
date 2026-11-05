"""Inyector de traducciones para Ren'Py: rellena los archivos ``game/tl/<idioma>/**/*.rpy``.

Ren'Py traduce con archivos ``tl`` que genera su SDK (launcher -> "Generate Translations", o
``renpy.exe <sdk> <juego> translate spanish``). Cada diálogo es un bloque::

    # game/script.rpy:59
    translate spanish start_17b89e7e:

        # m "Aah! Idiot! Knock!"
        m "Aah! Idiot! Knock!"           <- sin traducir: el SDK copia el original

y los textos de interfaz y menús van en ``translate spanish strings:`` como pares ``old`` / ``new``.

Este motor traduce lo que sigue igual que el original (o vacío) y deja intacto lo ya traducido, así
que se puede relanzar las veces que haga falta. Pasa quién habla como código ``renpy:<variable>``,
el mismo que guarda la ficha de personajes (``define m = Character("Mia")`` -> Mia; ``mc`` -> protagonista).
No genera los ``tl``: sus identificadores los calcula el propio Ren'Py.
"""
from __future__ import annotations

import codecs
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..ollama import OllamaTranslator
from ..personajes import InfoLinea
from ..texto import reinsertar_saltos, tiene_texto_visible
from .rpgmaker import traductor_acepta_info

log = logging.getLogger(__name__)

_CADENA = r'"(?P<texto>(?:[^"\\]|\\.)*)"'
_BLOQUE = re.compile(r"^\s*translate\s+(?P<idioma>\w+)\s+(?P<id>[\w.]+)\s*:\s*$")
# Comentario con el original: '# m "Hola"', '#"Hola"', '# m happy "Hola"'
_ORIGINAL = re.compile(r"^\s*#\s*(?:(?P<quien>[A-Za-z_][\w.]*)\s+(?:[\w-]+\s+)*?)?" + _CADENA + r"(?P<resto>.*)$")
# Línea de diálogo: 'm "Hola"', '"Hola"', 'm happy "Hola" with dissolve'
_DIALOGO = re.compile(r"^(?P<pre>\s*(?:(?P<quien>[A-Za-z_][\w.]*)\s+(?:[\w-]+\s+)*?)?)" + _CADENA + r"(?P<resto>.*)$")
# Hablante como cadena: '"Eileen" "Hola"' (el primero es el nombre, el segundo el diálogo)
_NOMBRE = r'"(?P<nombre>(?:[^"\\]|\\.)*)"\s+'
_ORIGINAL_CON_NOMBRE = re.compile(r"^\s*#\s*" + _NOMBRE + _CADENA + r"(?P<resto>.*)$")
_DIALOGO_CON_NOMBRE = re.compile(r"^(?P<pre>\s*" + _NOMBRE + r")" + _CADENA + r"(?P<resto>.*)$")
_OLD = re.compile(r"^\s*old\s+" + _CADENA + r"\s*$")
_NEW = re.compile(r"^(?P<pre>\s*new\s+)" + _CADENA + r"(?P<resto>\s*)$")
# Sentencias que llevan una cadena pero NO son diálogo
_NO_DIALOGO = {"voice", "play", "queue", "stop", "show", "hide", "scene", "with", "window", "nvl", "pause",
               "call", "jump", "return", "renpy", "define", "default", "image", "transform", "screen",
               "label", "menu", "if", "elif", "else", "while", "python", "init", "old", "new", "translate"}
_NARRADOR = {None, "narrator", "n", "nar", "narr", "centered", "extend"}
_SALTO = re.compile(r"\\n")


def desescapar(texto: str) -> str:
    """Cadena de un .rpy -> texto para traducir (solo las comillas; '\\n' se trata aparte)."""
    return texto.replace('\\"', '"')


def escapar(texto: str) -> str:
    """Texto traducido -> cadena válida dentro de "..." en un .rpy."""
    return re.sub(r'(?<!\\)"', r'\\"', texto)


@dataclass
class Pendiente:
    """Una cadena sin traducir de un archivo ``tl``."""

    linea: int           # índice de la línea física en el archivo
    pre: str             # lo que va antes de la cadena ('    m "', '    new "')
    original: str        # texto original (tal cual en el .rpy)
    resto: str           # lo que va después de la cadena (' with dissolve', '')
    quien: str | None    # variable del hablante ('m', 'mc') o None
    es_cadena: bool      # True = old/new (interfaz, menús)
    nombre: str | None = None  # hablante escrito como cadena ('"Eileen" "Hola"')

    def info(self) -> InfoLinea | None:
        if self.es_cadena:
            return None
        if self.nombre:
            return InfoLinea(hablante=self.nombre)
        if self.quien in _NARRADOR:
            return None
        return InfoLinea(codigo=f"renpy:{self.quien}")


def _sin_traducir(original: str, actual: str) -> bool:
    return not actual.strip() or actual == original


def buscar_pendientes(lineas: list[str], idioma: str | None = None) -> list[Pendiente]:
    """Recorre las líneas de un ``tl`` y devuelve lo que falta por traducir."""
    pendientes: list[Pendiente] = []
    en_bloque = False
    original: tuple[str, str | None, str | None] | None = None   # (texto, quien, nombre) del último comentario
    old: str | None = None
    for i, linea in enumerate(lineas):
        cuerpo = linea.rstrip("\r\n")
        m = _BLOQUE.match(cuerpo)
        if m:
            en_bloque = idioma is None or m.group("idioma") == idioma
            original, old = None, None
            continue
        if not en_bloque or not cuerpo.strip():
            continue
        mo = _OLD.match(cuerpo)
        if mo:
            old = mo.group("texto")
            continue
        mn = _NEW.match(cuerpo)
        if mn:
            if old is not None and _sin_traducir(old, mn.group("texto")) and tiene_texto_visible(desescapar(old)):
                pendientes.append(Pendiente(i, mn.group("pre") + '"', old, '"' + mn.group("resto"), None, True))
            old = None
            continue
        if cuerpo.lstrip().startswith("#"):
            mc = _ORIGINAL_CON_NOMBRE.match(cuerpo)
            if mc:
                original = (mc.group("texto"), None, mc.group("nombre"))
                continue
            mc = _ORIGINAL.match(cuerpo)
            if mc and (mc.group("quien") or "") not in _NO_DIALOGO:
                original = (mc.group("texto"), mc.group("quien"), None)
            continue
        md = _DIALOGO_CON_NOMBRE.match(cuerpo)
        nombre = md.group("nombre") if md else None
        if md is None:
            md = _DIALOGO.match(cuerpo)
        if md and original is not None and (nombre or (md.group("quien") or "") not in _NO_DIALOGO):
            texto_original, quien_comentario, nombre_comentario = original
            quien = None if nombre else (md.group("quien") or quien_comentario)
            if _sin_traducir(texto_original, md.group("texto")) and tiene_texto_visible(desescapar(texto_original)):
                pendientes.append(Pendiente(i, md.group("pre") + '"', texto_original, '"' + md.group("resto"),
                                            quien, False, nombre or nombre_comentario))
            original = None
    return pendientes


def _leer(ruta: Path) -> tuple[bool, list[str]]:
    datos = ruta.read_bytes()
    bom = datos.startswith(codecs.BOM_UTF8)
    texto = datos[len(codecs.BOM_UTF8):].decode("utf-8") if bom else datos.decode("utf-8")
    return bom, texto.splitlines(keepends=True)


def _escribir(ruta: Path, bom: bool, lineas: list[str]) -> None:
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes((codecs.BOM_UTF8 if bom else b"") + "".join(lineas).encode("utf-8"))
    tmp.replace(ruta)


def _fin_de_linea(linea: str) -> str:
    return linea[len(linea.rstrip("\r\n")):]


class InyectorRenPy:
    """Traduce los ``tl`` de un juego Ren'Py en bloques, guardando el archivo tras cada bloque."""

    def __init__(self, ruta_juego: Path, translator: OllamaTranslator, archivo_objetivo: str | None = None,
                 idioma: str | None = None, tam_bloque: int = 30):
        self.ruta_juego = Path(ruta_juego)
        self.translator = translator
        self.archivo_objetivo = archivo_objetivo
        self.idioma = idioma
        self.tam_bloque = max(1, tam_bloque)

    def carpeta_tl(self) -> Path | None:
        base = self.ruta_juego / "game" / "tl"
        if not base.is_dir():
            return None
        if self.idioma:
            return base / self.idioma if (base / self.idioma).is_dir() else None
        for preferido in ("spanish", "espanol", "español", "es", "castellano"):
            if (base / preferido).is_dir():
                return base / preferido
        idiomas = [p for p in base.iterdir() if p.is_dir() and p.name.lower() != "none"]
        return idiomas[0] if len(idiomas) == 1 else None

    def procesar(self) -> int:
        """Traduce todo lo pendiente. Devuelve cuántas cadenas se han escrito."""
        carpeta = self.carpeta_tl()
        if carpeta is None:
            log.error("No hay carpeta game/tl/<idioma> en %s. Genera antes los archivos de traducción con "
                      "el SDK de Ren'Py (launcher -> 'Generate Translations', idioma 'spanish') y vuelve a "
                      "ejecutar: este motor rellena esos archivos.", self.ruta_juego)
            return 0
        archivos = sorted(carpeta.rglob("*.rpy"))
        if self.archivo_objetivo:
            archivos = [a for a in archivos if a.name == self.archivo_objetivo]
        log.info("Ren'Py: %d archivos de traducción en %s", len(archivos), carpeta)
        total = 0
        for archivo in archivos:
            total += self.procesar_archivo(archivo, carpeta.name)
        log.info("Ren'Py: %d cadenas traducidas.", total)
        return total

    def procesar_archivo(self, ruta: Path, idioma: str | None = None) -> int:
        bom, lineas = _leer(ruta)
        pendientes = buscar_pendientes(lineas, idioma)
        if not pendientes:
            return 0
        log.info("Procesando %s: %d cadenas sin traducir...", ruta.name, len(pendientes))
        copia = ruta.with_name(ruta.name + ".original")
        if not copia.exists():
            shutil.copy2(ruta, copia)
        acepta_info = traductor_acepta_info(self.translator)
        escritas = 0
        for inicio in range(0, len(pendientes), self.tam_bloque):
            bloque = pendientes[inicio:inicio + self.tam_bloque]
            segmentos = [_SALTO.split(desescapar(p.original)) for p in bloque]
            textos = [re.sub(r" {2,}", " ", " ".join(s.strip() for s in segs)).strip() for segs in segmentos]
            if acepta_info:
                traducciones = self.translator.traducir_textos(textos, info=[p.info() for p in bloque])
            else:
                traducciones = self.translator.traducir_textos(textos)
            for p, segs, texto, trad in zip(bloque, segmentos, textos, traducciones):
                trad = (trad or "").strip()
                if not trad or trad == texto:
                    continue
                if len(segs) > 1:
                    trad = reinsertar_saltos(trad, segs)
                lineas[p.linea] = f"{p.pre}{escapar(trad)}{p.resto}{_fin_de_linea(lineas[p.linea])}"
                escritas += 1
            _escribir(ruta, bom, lineas)
        return escritas
