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
    workspace/<juego>/personajes.json          protagonista, personajes y su género (Paso 0)
    workspace/<juego>/glosario_bd.json         nombres de objetos, habilidades... (lo crea el traductor
                                               de RPG Maker; se puede corregir a mano)

Con ``personajes.json`` el contexto empieza por la regla del protagonista de la ficha y se
omiten las líneas ``@sin_ficha:`` del contexto global (p. ej. "el protagonista habla SIEMPRE en
masculino"). Sin ficha todo funciona como siempre (mismo contexto, misma huella, misma caché).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# personajes.py solo importa genero.py: no hay ciclo. El analizador (que sí importa config)
# se importa SIEMPRE dentro de las funciones.
from . import ambiguas, modismos  # solo usan la biblioteca estándar: no hay ciclo
from .genero import DESCONOCIDO
from .personajes import ARCHIVO_PERSONAJES, FichaPersonajes, Personaje

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
# Modelo de las herramientas que no traducen un juego concreto (evaluaciones, reparar etiquetas...).
MODELO_POR_DEFECTO = os.environ.get("TRADUCTOR_MODELO", "IA_Traductora_v4")
# Elección automática por juego (``modelo_para_juego``): la de por defecto en el Paso 1, el proxy y el
# Centro de Control. Lo que el usuario elija a mano para un juego (ajustes.json) se respeta.
MODELO_AUTOMATICO = "auto"
ETIQUETA_AUTOMATICO = "Automático (recomendado)"
_NOMBRES_AUTOMATICO = {"auto", "automatico", "automático", ETIQUETA_AUTOMATICO.casefold()}
MODELO_CON_FICHA = os.environ.get("TRADUCTOR_MODELO_CON_FICHA", "IA_Traductora_v4")
MODELO_SIN_FICHA = os.environ.get("TRADUCTOR_MODELO_SIN_FICHA", "IA_Traductora")
NUM_CTX_POR_DEFECTO = int(os.environ.get("TRADUCTOR_NUM_CTX", "4096"))
KEEP_ALIVE_POR_DEFECTO = os.environ.get("TRADUCTOR_KEEP_ALIVE", "30m")
REINTENTOS_CALIDAD = int(os.environ.get("TRADUCTOR_REINTENTOS_CALIDAD", "3"))

# Máximo de términos de glosario que se inyectan en un prompt (más solo añade ruido).
MAX_TERMINOS_PROMPT = 25

# Glosario de la base de datos (RPG Maker): nombres de objetos, armas, habilidades, estados...
# traducidos UNA vez para que el inventario, la ventana de "Has conseguido..." y los diálogos digan
# lo mismo. Lo crea ``InyectorRPGMaker`` en workspace/<juego>/ y el usuario puede corregirlo.
ARCHIVO_GLOSARIO_BD = "glosario_bd.json"
# Sección con los nombres que también se piden dentro de las frases (el juego siempre los escribe con
# mayúscula) y sección con los que solo se usan cuando el texto ES el nombre ("Stick", "Chest": en
# los diálogos son palabras corrientes, "Stick with me", "my chest").
SECCION_BD_FRASES = "en_dialogos"
SECCION_BD_EXACTOS = "solo_texto_entero"
_NOTA_GLOSARIO_BD = (
    "Nombres de la base de datos del juego (objetos, armas, habilidades, estados...) traducidos una sola "
    "vez para que el inventario, las ventanas de 'Has conseguido...' y los diálogos digan lo mismo. "
    f"'{SECCION_BD_FRASES}': también se piden dentro de las frases. '{SECCION_BD_EXACTOS}': solo cuando "
    "el texto es exactamente el nombre (son palabras corrientes en los diálogos). Puedes corregir "
    "cualquier traducción o pasar un nombre de una sección a la otra: se respeta en la próxima pasada."
)

# Códigos de RPG Maker y etiquetas que pueden rodear un nombre ("\\c[23]Album\\c[0]", "<b>Llave</b>").
_BORDE = r"(?:\\[A-Za-z]+\[[^\]]*\]|\\[{}|.!^$<>]|</?[A-Za-z][^<>]*>|\s)"
_PATRON_BORDES = re.compile(rf"^({_BORDE}*)(.*?)({_BORDE}*)$", re.DOTALL)


def separar_bordes(texto: str) -> tuple[str, str, str]:
    """'\\c[23]Album\\c[0]' -> ('\\c[23]', 'Album', '\\c[0]'): códigos y espacios del principio y del final."""
    m = _PATRON_BORDES.match(texto or "")
    return (m.group(1), m.group(2), m.group(3)) if m else ("", texto or "", "")


def leer_glosario_bd(ruta: Path | None) -> tuple[dict[str, str], set[str]]:
    """Lee ``glosario_bd.json``: ({nombre inglés: traducción}, nombres que también van en frases)."""
    datos = cargar_json(ruta, {}) if ruta is not None else {}
    if not isinstance(datos, dict):
        return {}, set()
    nombres: dict[str, str] = {}
    frases: set[str] = set()
    for seccion in (SECCION_BD_FRASES, SECCION_BD_EXACTOS):
        bloque = datos.get(seccion)
        if not isinstance(bloque, dict):
            continue
        for en, es in bloque.items():
            if isinstance(en, str) and isinstance(es, str) and en.strip() and es.strip():
                nombres[en.strip()] = es.strip()
                if seccion == SECCION_BD_FRASES:
                    frases.add(en.strip())
    return nombres, frases


def guardar_glosario_bd(ruta: Path, nombres: dict[str, str], frases) -> Path:
    """Guarda ``glosario_bd.json`` (escritura atómica, por orden alfabético)."""
    frases = set(frases)
    datos = {
        "_info": _NOTA_GLOSARIO_BD,
        SECCION_BD_FRASES: {en: nombres[en] for en in sorted(nombres, key=str.casefold) if en in frases},
        SECCION_BD_EXACTOS: {en: nombres[en] for en in sorted(nombres, key=str.casefold) if en not in frases},
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, ruta)
    return ruta


# --------------------------------------------------------------------------- Utilidades
def slug(nombre: str) -> str:
    """'The Adventures of Mi Juego' -> 'the_adventures_of_mi_juego'."""
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


# Prefijo de las líneas de contexto.txt que solo valen para juegos SIN personajes.json.
PREFIJO_SIN_FICHA = "@sin_ficha:"


def leer_contexto(ruta: Path, con_ficha: bool = False) -> str:
    """Lee un contexto.txt descartando comentarios (#) y líneas vacías.

    Las líneas que empiezan por ``@sin_ficha:`` (p. ej. la regla del protagonista masculino por
    defecto) solo valen para juegos sin ficha de personajes: con ``con_ficha=False`` se incluyen
    SIN el prefijo (el texto es el de siempre y la caché sigue valiendo); con ``con_ficha=True``
    se omiten, porque la ficha ya dice quién es el protagonista y su género.
    """
    if not ruta.exists():
        return ""
    lineas: list[str] = []
    for l in ruta.read_text(encoding="utf-8-sig").splitlines():
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        if l.startswith(PREFIJO_SIN_FICHA):
            if con_ficha:
                continue
            l = l[len(PREFIJO_SIN_FICHA):].strip()
            if not l:
                continue
        lineas.append(l)
    return " ".join(lineas)


def huella_contexto(contexto: str) -> str:
    """Hash corto de un contexto (forma parte de la clave de la caché de traducciones)."""
    return hashlib.sha1(contexto.encode("utf-8")).hexdigest()[:10]


_SUFIJOS_EDICION = re.compile(r"(?:_(?:demo|steam|final|full|edition|remastered|goty|v\d+))+$")


def _clave_carpeta(nombre: str) -> str:
    return str(nombre).strip().casefold().replace(" ", "_")


def _perfil_por_carpeta(nombre: str) -> str | None:
    """Perfil cuyo ``ajustes.json`` dice que su juego está en una carpeta llamada ``nombre`` (lo guarda el
    inyector de Unity). Sirve para carpetas cuyo nombre no da un perfil (en chino, japonés...)."""
    if not DIR_WORKSPACE.is_dir():
        return None
    clave = _clave_carpeta(nombre)
    for carpeta in sorted(DIR_WORKSPACE.iterdir()):
        ajustes = carpeta / "ajustes.json"
        if carpeta.name.startswith("_") or not ajustes.is_file():
            continue
        datos = cargar_json(ajustes, {})
        if isinstance(datos, dict) and datos.get("carpeta_juego") and _clave_carpeta(datos["carpeta_juego"]) == clave:
            return carpeta.name
    return None


def resolver_perfil_existente(nombre: str | None) -> str | None:
    """Busca en ``workspace/`` el perfil que mejor corresponde a ``nombre``.

    Si la carpeta exacta no existe (p. ej. el ejecutable del juego se llama
    ``Mi Juego Demo`` -> ``mi_juego_demo``),
    prueba quitando sufijos de edición (``_demo``, ``_steam``...) y buscando la carpeta
    de ``workspace/`` cuyas palabras estén todas incluidas en el nombre.
    """
    if not nombre:
        return None
    s = slug(nombre)
    if s and (DIR_WORKSPACE / s).is_dir():
        return s
    por_carpeta = _perfil_por_carpeta(nombre)
    if por_carpeta:
        return por_carpeta
    if not s:
        return nombre
    recortado = _SUFIJOS_EDICION.sub("", s)
    if recortado and (DIR_WORKSPACE / recortado).is_dir():
        return recortado
    palabras = set(s.split("_"))
    if DIR_WORKSPACE.is_dir():
        candidatos: list[tuple[int, str]] = []
        for carpeta in DIR_WORKSPACE.iterdir():
            if not carpeta.is_dir() or carpeta.name.startswith("_") or carpeta.name.endswith("_data"):
                continue
            partes_c = [p for p in carpeta.name.split("_") if p]
            if partes_c and all(p in palabras for p in partes_c):
                candidatos.append((len(partes_c), carpeta.name))
        if candidatos:
            candidatos.sort(key=lambda x: (-x[0], x[1]))
            return candidatos[0][1]
    return s


def resolver_juego(juego: str | None = None, ruta_juego: str | Path | None = None) -> str | None:
    """Determina el nombre del perfil de juego.

    1. Si se pasa ``--juego`` lo resuelve contra ``workspace/`` (tolerando sufijos como ``_demo``).
    2. Si no, lo deduce del nombre de la carpeta del juego.
    """
    if juego:
        return resolver_perfil_existente(juego)
    if not ruta_juego:
        return None
    return resolver_perfil_existente(Path(ruta_juego).name)


def carpeta_juego(juego: str | None, crear: bool = False) -> Path:
    """Carpeta de trabajo de un juego (``workspace/_comun`` si no hay perfil)."""
    resuelto = resolver_perfil_existente(juego) if juego else None
    carpeta = DIR_WORKSPACE / (resuelto or "_comun")
    if crear:
        carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def ruta_personajes(juego: str | None) -> Path:
    """Ruta de la ficha de personajes de un juego (``workspace/<juego>/personajes.json``)."""
    return carpeta_juego(juego) / ARCHIVO_PERSONAJES


def ajustes_juego(juego: str | None) -> dict:
    """Lee ``workspace/<juego>/ajustes.json`` si existe (ej. ``{"modelo": "IA_Traductora_v2"}``)."""
    if not juego:
        return {}
    carpeta = carpeta_juego(juego)
    datos = cargar_json(carpeta / "ajustes.json", {})
    return datos if isinstance(datos, dict) else {}


def guardar_ajustes_juego(juego: str | None, **cambios) -> Path | None:
    """Actualiza ``workspace/<juego>/ajustes.json`` conservando lo demás. Solo si la carpeta del juego
    ya existe (no crea perfiles). Devuelve la ruta o None si no se ha guardado."""
    if not juego:
        return None
    carpeta = carpeta_juego(juego)
    if not carpeta.is_dir() or carpeta.name == "_comun":
        return None
    datos = ajustes_juego(juego)
    datos.update({k: v for k, v in cambios.items() if v is not None})
    ruta = carpeta / "ajustes.json"
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, ruta)
    return ruta


def es_automatico(modelo: str | None) -> bool:
    """¿Pide la elección automática? (nada, "auto" o la etiqueta del Centro de Control)."""
    return not modelo or str(modelo).strip().casefold() in _NOMBRES_AUTOMATICO


def modelo_automatico(juego: str | None) -> tuple[str, str]:
    """(modelo, motivo) de la elección automática (fase 4, V1-V2): con ficha de personajes, v4 (muy
    superior con el género cuando se sabe quién habla y empate en Unity); sin ficha, v1 (se equivoca
    menos cuando nadie le dice quién habla). La calidad general es la misma (chrF, O6)."""
    if juego and ruta_personajes(juego).is_file():
        return MODELO_CON_FICHA, "el juego tiene ficha de personajes"
    return MODELO_SIN_FICHA, "el juego no tiene ficha de personajes (Paso 0)"


def modelo_para_juego(juego: str | None, modelo: str | None = None) -> str:
    """Modelo con el que se traduce un juego: el que se pide expresamente (``--modelo``; "auto" pide el
    automático aunque el juego tenga otro guardado); si no se pide nada, el de su ``ajustes.json``; si
    no hay ninguno guardado (o es "auto"), el automático."""
    if modelo and not es_automatico(modelo):
        return str(modelo)
    if not modelo:
        guardado = ajustes_juego(juego).get("modelo")
        if not es_automatico(guardado):
            return str(guardado)
    return modelo_automatico(juego)[0]


# --------------------------------------------------------------------------- Perfil
@dataclass
class Perfil:
    """Glosario, contexto, nombres protegidos y ficha de personajes que se aplican a una traducción."""

    juego: str | None = None
    glosario: dict[str, str] = field(default_factory=dict)
    contexto: str = ""
    nombres_protegidos: dict[str, str] = field(default_factory=dict)
    # Ficha de personajes (workspace/<juego>/personajes.json). None = modo antiguo, sin ficha.
    personajes: FichaPersonajes | None = None
    # Huella del contexto en modo antiguo (sin ficha): permite reaprovechar la caché anterior.
    # "" = desconocida (p. ej. perfiles construidos a mano).
    huella_legacy: str = ""
    # Contexto en modo antiguo (el que se usaría sin personajes.json). Lo usa 9_evaluar_genero.py
    # para medir cuánto ayuda la ficha frente al prompt de antes.
    contexto_legacy: str = ""
    # Nombres de la base de datos del juego (glosario_bd.json). Todos se copian tal cual cuando el
    # texto ES el nombre (inventario, "Has conseguido...", opciones) sin preguntar al modelo; los de
    # ``glosario_bd_frases`` además se piden dentro de las frases, con las mayúsculas del original.
    glosario_bd: dict[str, str] = field(default_factory=dict)
    glosario_bd_frases: frozenset = frozenset()
    # Palabras con dos sentidos ("chest": cofre / pecho; "safe": caja fuerte): si la frase deja claro el
    # sentido, se pide en su glosario y se comprueba la traducción (``traductor.ambiguas``).
    palabras_ambiguas: bool = True
    _patrones_glosario: list = field(init=False, repr=False, default_factory=list)
    _patrones_nombres: list = field(init=False, repr=False, default_factory=list)
    _patrones_bd: list = field(init=False, repr=False, default_factory=list)
    _largo_max_bd: int = field(init=False, repr=False, default=0)

    def __post_init__(self):
        # Coincidencia por palabra completa (+ plural simple). Antes era una subcadena:
        # 'fence' saltaba con 'defence' y 'Save' con 'saved', llenando el prompt de ruido.
        terminos = sorted(self.glosario.items(), key=lambda kv: -len(kv[0]))
        self._patrones_glosario = []
        for en, es in terminos:
            if not en.strip() or not isinstance(es, str):
                continue
            es_limpio = re.sub(
                r"\s*\([^)]*(?:contexto|traducir|comando|sexual|alternativ)[^)]*\)",
                "",
                es,
                flags=re.IGNORECASE,
            ).split(" / ")[0].strip()
            if es_limpio:
                self._patrones_glosario.append(
                    (re.compile(rf"(?<!\w){re.escape(en)}(?:e?s)?(?!\w)", re.IGNORECASE), en, es_limpio)
                )
        self._patrones_nombres = []
        for nombre, patron in self.nombres_protegidos.items():
            try:
                self._patrones_nombres.append((nombre, re.compile(patron)))
            except re.error as e:
                log.warning("Regex inválida para el nombre protegido '%s': %s", nombre, e)
        self._compilar_glosario_bd()

    def _compilar_glosario_bd(self) -> None:
        self.glosario_bd = {en.strip(): es.strip() for en, es in (self.glosario_bd or {}).items()
                            if isinstance(en, str) and isinstance(es, str) and en.strip() and es.strip()}
        self.glosario_bd_frases = frozenset(n.strip() for n in (self.glosario_bd_frases or ()) if n.strip())
        del_usuario = {en.strip().casefold() for en in self.glosario}
        self._largo_max_bd = max((len(en) for en in self.glosario_bd), default=0)
        self._patrones_bd = []
        for en in sorted(self.glosario_bd_frases, key=lambda t: -len(t)):
            es = self.glosario_bd.get(en)
            if es and en.casefold() not in del_usuario:  # si el usuario ya lo tiene en su glosario, manda el suyo
                # Con las mayúsculas del original: "Rough Diamond(s)" sí, "my chest" no.
                self._patrones_bd.append((re.compile(rf"(?<!\w){re.escape(en)}(?:e?s)?(?!\w)"), en, es))

    def fijar_glosario_bd(self, nombres: dict[str, str], en_frases=()) -> None:
        """Sustituye el glosario de la base de datos (lo llama el motor de RPG Maker antes de traducir)."""
        self.glosario_bd = dict(nombres)
        self.glosario_bd_frases = frozenset(en_frases)
        self._compilar_glosario_bd()

    # ----------------------------------------------------------------- Consultas
    def terminos_para(self, texto: str, con_ambiguas: bool = True) -> list[tuple[str, str]]:
        """Términos del glosario que aparecen en ``texto`` (los más largos primero).

        Sin nombres de la base de datos ni palabras de dos sentidos decididas en el texto, la lista es la
        de siempre (misma clave de caché). ``con_ambiguas=False`` omite el sentido decidido de "chest",
        "safe"... (los lotes no lo usan: vale para UNA frase, no para todas las del lote)."""
        encontrados = [(en, es) for patron, en, es in self._patrones_glosario if patron.search(texto)]
        if self._patrones_bd:
            ya = {en.casefold() for en, _ in encontrados}
            extra = [(en, es) for patron, en, es in self._patrones_bd
                     if en.casefold() not in ya and patron.search(texto)]
            if extra:
                encontrados = sorted(encontrados + extra, key=lambda t: -len(t[0]))
        encontrados = encontrados[:MAX_TERMINOS_PROMPT]
        if con_ambiguas and self.palabras_ambiguas:
            encontrados += ambiguas.terminos(texto, encontrados)
            # Frases hechas que el modelo traduce palabra por palabra ("busting my ass", "damn good")
            encontrados += modismos.terminos(texto, encontrados)
        return encontrados

    def valor_glosario(self, termino: str) -> str | None:
        """Traducción del glosario (global o del juego) para exactamente ``termino``, sin notas."""
        clave = (termino or "").strip().casefold()
        return next((es for _, en, es in self._patrones_glosario if en.strip().casefold() == clave), None)

    def traduccion_exacta(self, texto: str) -> str | None:
        """Si ``texto`` es exactamente un nombre de la base de datos (con o sin códigos de color alrededor:
        "\\c[23]Album\\c[0]"), su traducción fijada con esos mismos códigos; si no, None."""
        if not self.glosario_bd or not texto or len(texto) > self._largo_max_bd + 80:
            return None  # las frases largas no pueden ser un nombre: ni se miran
        prefijo, nucleo, sufijo = separar_bordes(texto)
        es = self.glosario_bd.get(nucleo)
        return None if es is None else f"{prefijo}{es}{sufijo}"

    def restaurar_nombres(self, origen: str, traducido: str) -> str:
        """Si el original contiene un nombre protegido y la traducción lo ha perdido, lo restaura.

        Nunca cambia una palabra que está tal cual en el original: si la regla de un nombre incluye el de otro
        personaje parecido ("Lucinda" con "Lucía"), "Lucía lo salvó" no se convierte en "Lucinda lo salvó"."""
        for nombre, patron in self._patrones_nombres:
            if (nombre in origen or patron.search(origen)) and nombre not in traducido:
                traducido = patron.sub(lambda m, n=nombre: m.group(0) if m.group(0) in origen else n, traducido)
        return traducido

    def huella(self) -> str:
        """Hash corto del contexto: si cambias el contexto, la caché ya no se reutiliza."""
        return huella_contexto(self.contexto)

    def resumen(self) -> str:
        texto = (f"perfil '{self.juego or 'global'}': {len(self.glosario)} términos, "
                 f"{len(self.nombres_protegidos)} nombres protegidos, "
                 f"contexto de {len(self.contexto)} caracteres")
        if self.glosario_bd:
            texto += f", {len(self.glosario_bd)} nombres de la base de datos"
        if self.personajes is not None:
            texto += f", ficha de personajes: {self.personajes.resumen()}"
        return texto


def _metadatos_juego(ruta_juego: str | Path | None, titulo: str) -> tuple[str, list[str]]:
    """Título (``System.json``) y nombres de los actores (``Actors.json``) de un juego RPG Maker."""
    personajes: list[str] = []
    if not ruta_juego:
        return titulo, personajes
    rj = Path(ruta_juego)
    posibles_system = [rj / "www" / "data" / "System.json", rj / "data" / "System.json"]
    posibles_actors = [rj / "www" / "data" / "Actors.json", rj / "data" / "Actors.json"]

    for ps in posibles_system:
        if ps.exists():
            try:
                s_data = json.loads(ps.read_text(encoding="utf-8-sig"))
                if s_data.get("gameTitle"):
                    titulo = s_data["gameTitle"]
            except Exception:
                pass
            break

    for pa in posibles_actors:
        if pa.exists():
            try:
                actores = json.loads(pa.read_text(encoding="utf-8-sig"))
                for act in actores:
                    if act and isinstance(act, dict) and act.get("name"):
                        personajes.append(act["name"])
            except Exception:
                pass
            break
    return titulo, personajes


def ficha_plantilla(titulo: str = "", protagonista: str = "", motor: str = "") -> FichaPersonajes:
    """Ficha mínima: solo el protagonista, con género DESCONOCIDO (nunca se adivina).

    ``protagonista`` suele ser el actor 1 de RPG Maker (el que muestra ``\\N[1]``); si no se
    sabe, se llama "Protagonista". El usuario debe revisar nombre y género.
    """
    evidencia = ["Actor 1 de Actors.json (sin confirmar)"] if protagonista else []
    prota = Personaje(nombre=protagonista or "Protagonista", genero=DESCONOCIDO, rol="protagonista",
                      descripcion="Plantilla: revisa el nombre y el género del protagonista.",
                      evidencia=evidencia)
    return FichaPersonajes(personajes=[prota], titulo=titulo, motor=motor)


def inicializar_perfil_nuevo(juego: str, ruta_juego: str | Path | None = None, *,
                             analizar: bool = True, usar_ia: bool = False) -> Path:
    """Crea automáticamente la carpeta en ``workspace/<juego>/`` con archivos base y plantilla de contexto.

    Inspecciona la carpeta del juego para autodetectar el título y los personajes si es posible.
    Si hay ``ruta_juego`` (y ``analizar``), crea ``personajes.json`` con el analizador del Paso 0
    (``traductor.analizador``); si no se puede, o si no hay ruta, deja una ficha plantilla con el
    protagonista de género DESCONOCIDO. Nunca se supone "hombre por defecto". En carpetas que ya
    existían sin ficha solo se crea si se pide un análisis (con ruta), para no cambiar el modo de
    traducción de un juego ya empezado.
    """
    nombre_seguro = slug(juego)
    if not nombre_seguro:
        nombre_seguro = "nuevo_juego"
    carpeta = DIR_WORKSPACE / nombre_seguro
    es_nueva = not carpeta.is_dir()
    carpeta.mkdir(parents=True, exist_ok=True)

    # 1. ajustes.json
    p_ajustes = carpeta / "ajustes.json"
    if not p_ajustes.exists():
        p_ajustes.write_text(json.dumps({"modelo": "IA_Traductora_v2"}, indent=2), encoding="utf-8")

    # 2. glosario.json
    p_glosario = carpeta / "glosario.json"
    if not p_glosario.exists():
        p_glosario.write_text("{}\n", encoding="utf-8")

    # 3. nombres_protegidos.json
    p_nombres = carpeta / "nombres_protegidos.json"
    if not p_nombres.exists():
        p_nombres.write_text("{}\n", encoding="utf-8")

    # 4. contexto.txt: autodetectar metadatos del juego si hay ruta
    p_contexto = carpeta / "contexto.txt"
    p_ficha = carpeta / ARCHIVO_PERSONAJES
    titulo, personajes = nombre_seguro.replace("_", " ").title(), []
    if not p_contexto.exists() or not p_ficha.exists():
        titulo, personajes = _metadatos_juego(ruta_juego, titulo)

    if not p_contexto.exists():
        lineas = [
            f"# Contexto específico de {titulo}",
            "# El protagonista y el género de cada personaje están en personajes.json (Paso 0:",
            "# 0_analizar_juego.py o el editor de personajes). No los repitas aquí para que no se contradigan.",
            f"- Título del juego: {titulo}",
        ]
        if personajes:
            lineas.append(f"- Personajes detectados: {', '.join(personajes[:20])}")
        lineas.extend([
            "- Tono y registro: Natural, fluido y coloquial en español de España (tuteo habitual).",
            "- Sinopsis y contexto: Novela visual / aventura / RPG.",
        ])
        p_contexto.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        log.info("✨ [NUEVO JUEGO DETECTADO] Plantilla de contexto autogenerada en: %s", p_contexto)

    # 5. personajes.json: protagonista, personajes principales y su género (Paso 0)
    if not p_ficha.exists() and ruta_juego and analizar:
        try:
            from .analizador import analizar_y_guardar  # import perezoso: el analizador importa config
            analizar_y_guardar(nombre_seguro, ruta_juego, usar_ia=usar_ia)
        except Exception as e:  # el análisis nunca debe impedir crear el perfil
            log.warning("No se pudieron analizar los personajes de %s (%s).", ruta_juego, e)
    if not p_ficha.exists() and es_nueva:
        ficha_plantilla(titulo, personajes[0] if personajes else "").guardar(p_ficha)
        log.warning("⚠ Ficha de personajes creada SIN género del protagonista: revisa %s "
                    "(o ejecuta el Paso 0: 0_analizar_juego.py).", p_ficha)

    return carpeta


def cargar_perfil(juego: str | None = None, ruta_juego: str | Path | None = None, auto_crear: bool = True,
                  *, analizar: bool = True, usar_ia: bool = False) -> Perfil:
    """Combina lo universal (``glosarios/``) con lo del juego (``workspace/<juego>/``).

    - Sin ``personajes.json`` (modo antiguo): el contexto es byte a byte el de siempre, así que la
      huella y la caché de traducciones siguen valiendo.
    - Con ``personajes.json``: regla del protagonista de la ficha + contexto global SIN las líneas
      ``@sin_ficha:`` + contexto del juego. ``huella_legacy`` guarda la huella del modo antiguo
      para que el traductor pueda reaprovechar la caché anterior cuando no contradiga los géneros.

    ``analizar`` y ``usar_ia`` solo se usan si hay que crear un perfil nuevo (``auto_crear``).
    """
    glosario = dict(cargar_json(GLOSARIO_GLOBAL, {}))
    nombres = dict(cargar_json(NOMBRES_GLOBAL, {}))
    carpeta: Path | None = None

    if juego:
        juego_resuelto = resolver_perfil_existente(juego)
        carpeta = carpeta_juego(juego_resuelto)
        if not carpeta.is_dir() and auto_crear:
            inicializar_perfil_nuevo(juego, ruta_juego, analizar=analizar, usar_ia=usar_ia)
            juego_resuelto = resolver_perfil_existente(juego)
            carpeta = carpeta_juego(juego_resuelto)

        if carpeta.is_dir():
            glosario.update(cargar_json(carpeta / "glosario.json", {}))
            nombres.update(cargar_json(carpeta / "nombres_protegidos.json", {}))
        else:
            log.info("No existe %s: se usa solo el perfil global. "
                     "Crea esa carpeta para añadir glosario/contexto propios del juego.", carpeta)
            carpeta = None

    ctx_juego = carpeta / "contexto.txt" if carpeta is not None else None
    contexto_antiguo = " ".join(c for c in (
        leer_contexto(CONTEXTO_GLOBAL),
        leer_contexto(ctx_juego) if ctx_juego is not None else "",
    ) if c)

    ficha = FichaPersonajes.cargar(carpeta / ARCHIVO_PERSONAJES) if carpeta is not None else None
    glosario_bd, bd_frases = leer_glosario_bd(carpeta / ARCHIVO_GLOSARIO_BD if carpeta is not None else None)
    if ficha is None:
        contexto = contexto_antiguo
    else:
        regla = ficha.regla_protagonista()
        if not regla:
            log.warning("Revisa workspace/%s/%s: falta el género del protagonista (no se forzará masculino "
                        "ni femenino). Corrígelo con el editor de personajes o con "
                        "herramientas_extra/configurar_perfil_juego.py --genero hombre|mujer.",
                        carpeta.name, ARCHIVO_PERSONAJES)
        contexto = " ".join(c for c in (
            regla,
            leer_contexto(CONTEXTO_GLOBAL, con_ficha=True),
            leer_contexto(ctx_juego, con_ficha=True) if ctx_juego is not None else "",
        ) if c)

    return Perfil(
        juego=juego,
        glosario=glosario,
        contexto=contexto,
        nombres_protegidos=nombres,
        personajes=ficha,
        huella_legacy=huella_contexto(contexto_antiguo),
        contexto_legacy=contexto_antiguo,
        glosario_bd=glosario_bd,
        glosario_bd_frases=frozenset(bd_frases),
    )
