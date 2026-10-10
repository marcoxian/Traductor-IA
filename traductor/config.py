"""Configuración central: rutas del proyecto, ajustes de Ollama y perfiles de juego.

Todas las rutas se calculan a partir de la ubicación de este archivo, así los scripts
funcionan igual se lancen desde la carpeta del proyecto, desde un .bat o desde VS Code.

Perfiles de juego
-----------------
Lo universal vive en ``glosarios/``. Lo específico de cada juego vive en
``workspace/<juego>/`` y se SUMA a lo universal (si una clave se repite, gana la del juego):

    workspace/<juego>/glosario.json            términos obligatorios {"inglés": "español"}
    workspace/<juego>/contexto.txt             sinopsis, géneros, tono... (las líneas con # se ignoran)
    workspace/<juego>/nombres_protegidos.json  {"Nombre": "regex de la traducción incorrecta"}
    workspace/<juego>/nombres_propios.txt      un nombre por línea (lo usa el paso 5)
    workspace/<juego>/nombres_hablantes.csv    tabla 'ingles;correccion' de quien habla (paso 5)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- Rutas
RAIZ = Path(__file__).resolve().parent.parent
DIR_GLOSARIOS = RAIZ / "glosarios"
DIR_WORKSPACE = RAIZ / "workspace"
DIR_DATASETS = RAIZ / "datasets"
DIR_MODELOS = RAIZ / "modelos"

GLOSARIO_GLOBAL = DIR_GLOSARIOS / "glosario_activo.json"
CONTEXTO_GLOBAL = DIR_GLOSARIOS / "contexto.txt"
NOMBRES_GLOBAL = DIR_GLOSARIOS / "nombres_protegidos.json"
DICCIONARIO_INTERFAZ = DIR_GLOSARIOS / "glosario_interfaz_rpgmaker.csv"

# --------------------------------------------------------------------------- Ollama
# Se pueden sobrescribir con variables de entorno sin tocar el código.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODELO_POR_DEFECTO = os.environ.get("TRADUCTOR_MODELO", "IA_Traductora")

# Máximo de términos de glosario que se inyectan en un prompt (más solo añade ruido).
MAX_TERMINOS_PROMPT = 25


# --------------------------------------------------------------------------- Utilidades
def slug(nombre: str) -> str:
    """'The Adventures of HILLS' -> 'the_adventures_of_hills'."""
    return re.sub(r"[^a-z0-9]+", "_", nombre.lower()).strip("_")


def cargar_json(ruta: Path, por_defecto):
    """Lee un JSON. Si no existe devuelve ``por_defecto``; si está roto lo avisa (antes fallaba en silencio)."""
    if not ruta.exists():
        return por_defecto
    try:
        return json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("No se pudo leer %s (%s). Se ignora.", ruta, e)
        return por_defecto


def leer_contexto(ruta: Path) -> str:
    """Lee un contexto.txt descartando comentarios (#) y líneas vacías."""
    if not ruta.exists():
        return ""
    lineas = [l.strip() for l in ruta.read_text(encoding="utf-8-sig").splitlines()]
    return " ".join(l for l in lineas if l and not l.startswith("#"))


def resolver_juego(juego: str | None = None, ruta_juego: str | Path | None = None) -> str | None:
    """Determina el nombre del perfil de juego.

    1. Si se pasa ``--juego`` se usa tal cual.
    2. Si no, se deduce del nombre de la carpeta del juego: se busca en ``workspace/`` una
       carpeta con ese nombre o cuyo nombre sea una de sus palabras
       ('The Adventures of HILLS' encuentra 'workspace/hills').
    """
    if juego:
        return juego
    if not ruta_juego:
        return None
    s = slug(Path(ruta_juego).name)
    if not s:
        return None
    if (DIR_WORKSPACE / s).is_dir():
        return s
    palabras = set(s.split("_"))
    if DIR_WORKSPACE.is_dir():
        for carpeta in sorted(DIR_WORKSPACE.iterdir()):
            if carpeta.is_dir() and carpeta.name in palabras:
                return carpeta.name
    return s


def carpeta_juego(juego: str | None, crear: bool = False) -> Path:
    """Carpeta de trabajo de un juego (``workspace/_comun`` si no hay perfil)."""
    carpeta = DIR_WORKSPACE / (juego or "_comun")
    if crear:
        carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


# --------------------------------------------------------------------------- Perfil
@dataclass
class Perfil:
    """Glosario, contexto y nombres protegidos que se aplican a una traducción."""

    juego: str | None = None
    glosario: dict[str, str] = field(default_factory=dict)
    contexto: str = ""
    nombres_protegidos: dict[str, str] = field(default_factory=dict)
    _patrones_glosario: list = field(init=False, repr=False, default_factory=list)
    _patrones_nombres: list = field(init=False, repr=False, default_factory=list)

    def __post_init__(self):
        # Coincidencia por palabra completa (+ plural simple). Antes era una subcadena:
        # 'fence' saltaba con 'defence' y 'Save' con 'saved', llenando el prompt de ruido.
        terminos = sorted(self.glosario.items(), key=lambda kv: -len(kv[0]))
        self._patrones_glosario = [
            (re.compile(rf"(?<!\w){re.escape(en)}(?:e?s)?(?!\w)", re.IGNORECASE), en, es)
            for en, es in terminos if en.strip()
        ]
        self._patrones_nombres = []
        for nombre, patron in self.nombres_protegidos.items():
            try:
                self._patrones_nombres.append((nombre, re.compile(patron)))
            except re.error as e:
                log.warning("Regex inválida para el nombre protegido '%s': %s", nombre, e)

    # ----------------------------------------------------------------- Consultas
    def terminos_para(self, texto: str) -> list[tuple[str, str]]:
        """Términos del glosario que aparecen en ``texto`` (los más largos primero)."""
        encontrados = [(en, es) for patron, en, es in self._patrones_glosario if patron.search(texto)]
        return encontrados[:MAX_TERMINOS_PROMPT]

    def restaurar_nombres(self, origen: str, traducido: str) -> str:
        """Si el original contiene un nombre protegido y la traducción lo ha perdido, lo restaura."""
        for nombre, patron in self._patrones_nombres:
            if nombre in origen and nombre not in traducido:
                traducido = patron.sub(nombre, traducido)
        return traducido

    def huella(self) -> str:
        """Hash corto del contexto: si cambias el contexto, la caché ya no se reutiliza."""
        return hashlib.sha1(self.contexto.encode("utf-8")).hexdigest()[:10]

    def resumen(self) -> str:
        return (f"perfil '{self.juego or 'global'}': {len(self.glosario)} términos, "
                f"{len(self.nombres_protegidos)} nombres protegidos, "
                f"contexto de {len(self.contexto)} caracteres")


def cargar_perfil(juego: str | None = None) -> Perfil:
    """Combina lo universal (``glosarios/``) con lo del juego (``workspace/<juego>/``)."""
    glosario = dict(cargar_json(GLOSARIO_GLOBAL, {}))
    nombres = dict(cargar_json(NOMBRES_GLOBAL, {}))
    contextos = [leer_contexto(CONTEXTO_GLOBAL)]

    if juego:
        carpeta = carpeta_juego(juego)
        if carpeta.is_dir():
            glosario.update(cargar_json(carpeta / "glosario.json", {}))
            nombres.update(cargar_json(carpeta / "nombres_protegidos.json", {}))
            contextos.append(leer_contexto(carpeta / "contexto.txt"))
        else:
            log.info("No existe %s: se usa solo el perfil global. "
                     "Crea esa carpeta para añadir glosario/contexto propios del juego.", carpeta)

    return Perfil(
        juego=juego,
        glosario=glosario,
        contexto=" ".join(c for c in contextos if c),
        nombres_protegidos=nombres,
    )
