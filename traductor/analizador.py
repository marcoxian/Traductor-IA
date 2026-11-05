"""Paso 0: analiza los archivos de un juego para crear su ficha de personajes (``personajes.json``).

Qué hace:
  1. Lee los textos ORIGINALES en inglés según el motor:
       - RPG Maker MV/MZ: ``*.json.bak`` si existen (originales) o ``*.json``; quién habla sale de las
         cajas de nombre (``\\N<Ana>``), del nombre de hablante de MZ, de los códigos de hablante
         ("HeFrOp.") y de las caras de los mensajes (``face:Actor1#0``). En los juegos que usan esos
         códigos, el evento común "MESSAGE" contiene el mapa EXACTO código -> personaje ("VOICE Laura").
       - Ren'Py: ``define x = Character("Nombre")`` y los diálogos (``game/tl/<idioma>`` si existe).
       - CSV de localización (DKTools/Godot): columna inglesa y caja ``\\N<Nombre>``.
       - Unity + XUnity: claves inglesas de ``Translation/<idioma>/Text/*.txt`` (sin hablantes).
  2. Detecta personajes (actores, hablantes, códigos, nombres de pila frecuentes) y al protagonista.
  3. Deduce el género con EVIDENCIA y sin adivinar: pronombres que siguen al nombre ("Ana... she"),
     tratamientos ("Miss Ana", "Father Brian"), predicados ("Ana is my girlfriend"), cómo
     llaman al protagonista ("young man", "miss"), un léxico de nombres de pila (pista débil) y,
     opcionalmente, la IA local. Si la evidencia no es clara, el género queda ``desconocido``.

Uso: ``analizar_juego(ruta)`` devuelve un ``InformeAnalisis``; ``analizar_y_guardar(juego, ruta)``
además fusiona el resultado con ``workspace/<juego>/personajes.json`` sin pisar lo que el usuario
haya confirmado. CLI: ``python 0_analizar_juego.py --ruta "J:\\Juegos\\MiJuego"``.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .genero import DESCONOCIDO, HOMBRE, MUJER, normalizar_genero
from .personajes import (ARCHIVO_PERSONAJES, MARCADORES_PROTAGONISTA, FichaPersonajes, InfoLinea,
                         Personaje, limpiar_nombre)

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- Léxicos
_AMBIGUOS = set("""kim sam alex jaime robin jordan taylor charlie jesse max casey riley harley dana
jackie sora hikaru nova sky jean sasha nikki toni billie frankie jamie lee morgan quinn reese rory
sage skylar ash avery cameron drew elliot kai pat chris andy terry tracy val mel jo ali""".split())

_NOMBRES_F = set("""abby abigail ada adele adriana agatha agnes aiko aileen akane alana alexa
alexandra alexis alia alice alicia alina alison allison alyssa amanda amber amelia amy ana anastasia
andrea angela angelica angelina anita ann anna anne annie april ariana arianna ariel ashley astrid
audrey aurora ava barbara beatrice becky bella belle beth bethany betty bianca bonnie brenda brianna
bridget brittany brooke caitlin camila camille candace cara carla carmen carol caroline carolyn
cassandra cassie catherine cecilia celeste celia charlotte chelsea cheryl chloe christina christine
cindy claire clara clare claudia colette cora courtney crystal cynthia daisy daniela daphne darla
dawn debbie deborah delia denise diana diane dolores donna dora dorothy eleanor elena elisa eliza
elizabeth ella ellen ellie eloise elsa emily emma erica erika erin esther eva eve evelyn evie faith
fiona flora frances gabriela gabrielle gina ginger gloria grace gwen hailey haley hana hannah
harriet hazel heather heidi helen helena hilda holly hope ida ines irene iris isabel isabella
isabelle ivy jacqueline jade jane janet janice jasmine jenna jennifer jenny jess jessica jill joan
joanna jocelyn josephine joy joyce judith judy julia julie juliet june kaley karen kate katherine
kathleen kathy katie katrina kayla kelly kimberly kira klaudia kristen kristin lacey laura lauren
layla leah lena leona lexi lila lilith lillian lily linda lindsay lisa liz lola lorna lorraine
louise lucia lucy luna lydia lynn madalyn madeline madison maggie maria marie marina marissa martha
mary maya megan mei melanie melissa mia michelle mila mildred mina miranda miya molly monica nadia
nancy naomi natalie natasha nellie nicole nina nora olga olivia paige pamela patricia paula
pauline peggy penelope penny phoebe piper polly priscilla rachel raven rebecca regina rena rhea
rita roberta rosa rosalie rose rosie ruby ruth sabrina sakura sally samantha sara sarah scarlett
selena serena sharon sheila shelly sierra sofia sonia sophia sophie stella stephanie sue summer
susan suzy sylvia tamara tanya tara tasha tess tessa theresa tiffany tina trish ursula valentina
valerie vanessa vera veronica vicky victoria violet virginia vivian wanda wendy whitney yuki yumi
yvonne zara zoe zoey iori himari ichika yuna miku hinata akari ayaka misaki natsuki haruka morrigan
lilly vili kaya ayame emi rika yui naomi katherine judy""".split()) - _AMBIGUOS

_NOMBRES_M = set("""aaron adam adrian alan albert alexander alfred andrew anthony arnold arthur
austin barry ben benjamin bernard bill billy bob bobby brad bradley brandon brian bruce bryan caleb
calvin carl carlos chad charles christian christopher clark colin connor craig dale damian dan
daniel danny darren dave david dean dennis derek diego dominic don donald doug douglas duke duncan
dustin dylan earl ed eddie edgar edward eli elijah eric ernest ethan eugene evan felix fernando
frank franklin fred frederick gabriel gary george gerald gilbert glen gordon graham greg gregory
gus harold harry harvey hector henry herbert howard hugo ian isaac ivan jack jacob jake james
jared jason jasper jeff jeffrey jeremy jerry jim jimmy joe joel john johnny jon jonathan jose
joseph josh joshua juan julian justin karl keith kenneth kevin kyle lance larry lawrence leo leon
leonard liam logan louis lucas luke malcolm marcus mario mark martin marvin mason matt matthew
maurice michael mike miles mitchell nathan neil nick nicholas noah norman oliver oscar owen
patrick paul pedro peter phil philip ralph randy ray raymond richard rick ricky rob robert roger
roland ron ronald ross roy russell ryan samuel scott sean sebastian seth shane simon solomon
spencer stan stanley stefan stephen steve steven stuart ted theo thomas tim timothy todd tom tommy
tony travis trevor tristan troy tyler victor vincent wade walter warren wayne will william wyatt
xavier zach zachary zeke hiro takeshi kenji kenta ryu haruto yuto daiki shota william albert
brian bradley""".split()) - _AMBIGUOS

# Nombres que también son palabras: el LLM tiende a traducirlos ("Amber" -> "Ámbar").
NOMBRES_PALABRA: dict[str, str] = {
    "Hope": "Esperanza", "Rose": "Rosa", "Amber": "Ámbar", "Lily": "Lirio",
    "Ruby": "Rubí", "Violet": "Violeta", "Daisy": "Margarita", "Summer": "Verano", "Autumn": "Otoño",
    "Dawn": "Amanecer", "Faith": "Fe", "Grace": "Gracia", "Joy": "Alegría", "Crystal": "Cristal",
    "Pearl": "Perla", "Ivy": "Hiedra", "Holly": "Acebo", "Sky": "Cielo", "Storm": "Tormenta",
    "Hunter": "Cazador", "Angel": "Ángel", "Star": "Estrella", "Cherry": "Cereza", "Honey": "Miel",
    "Candy": "Caramelo", "Ginger": "Jengibre", "Raven": "Cuervo", "Bunny": "Conejita",
    "Destiny": "Destino", "Melody": "Melodía", "Harmony": "Armonía", "Will": "Voluntad",
    "Mark": "Marca", "Rob": "Robar", "Bill": "Factura", "Frank": "Franco", "Rusty": "Oxidado",
    "Chance": "Oportunidad", "Ace": "As", "Wolf": "Lobo", "Fox": "Zorro", "Bird": "Pájaro",
    "Bear": "Oso", "Duke": "Duque", "King": "Rey", "Prince": "Príncipe", "Sunny": "Soleado",
    "Misty": "Brumosa", "Cookie": "Galleta", "Kitty": "Gatita", "Heaven": "Cielo",
    "Serenity": "Serenidad", "Trinity": "Trinidad", "Charity": "Caridad", "Patience": "Paciencia",
    "Willow": "Sauce", "Hazel": "Avellana", "Olive": "Aceituna", "Poppy": "Amapola",
    "Jasmine": "Jazmín", "Lavender": "Lavanda", "Sandy": "Arenosa", "Nova": "Nova",
}

# Palabras con mayúscula que NO son personajes aunque aparezcan mucho.
_NO_NOMBRES = set("""i i'm i'll i've i'd ok okay oh ah eh hey hi hello yes no yeah god lord jesus
christ mr mrs ms miss sir madam the a an and but or so if what why how when where who which
monday tuesday wednesday thursday friday saturday sunday january february march april may june
july august september october november december christmas halloween easter english spanish
american japanese chinese earth heaven hell new game save load options exit continue quit
please thanks thank sorry well wait look come let go stop help damn fuck shit wow hmm huh
uh um ugh mom dad mommy daddy sis bro honey baby babe darling sweetie dear doctor nurse officer
captain boss master mistress father mother brother sister uncle aunt grandma grandpa level hp mp
item items skill skills gold coins day night morning evening chapter quest you he she they we it
this that there here my your his her our their its yes""".split())

_PRON_M = {"he": 1.0, "himself": 1.0, "his": 0.8, "him": 0.5, "he's": 1.0, "he'd": 1.0, "he'll": 1.0}
_PRON_F = {"she": 1.0, "herself": 1.0, "hers": 0.8, "her": 0.5, "she's": 1.0, "she'd": 1.0, "she'll": 1.0}

_TITULOS_M = ("mr", "mister", "sir", "lord", "king", "prince", "father", "brother", "uncle",
              "grandpa", "grandfather", "dad", "master", "monsieur", "señor", "don", "duke", "baron", "count")
_TITULOS_F = ("mrs", "ms", "miss", "madam", "madame", "lady", "queen", "princess", "mother", "mom",
              "sister", "aunt", "auntie", "grandma", "grandmother", "mistress", "nurse", "nun", "señora",
              "señorita", "doña", "duchess", "baroness", "countess", "mademoiselle")
# El punto solo vale en abreviaturas ("Mr. Smith"); "Thanks, Sister. Brad..." NO es "Sister Brad".
# Los tratamientos van con mayúscula ("Lady Valerie"); "that lady Brad" no es un tratamiento.
def _variantes_titulo(t: str) -> str:
    return f"{re.escape(t.capitalize())}|{re.escape(t.upper())}"


_PATRON_TITULO = re.compile(
    r"(?<![\w'])(?:(?P<abr>Mr|Mrs|Ms|MR|MRS|MS)\.?|(?P<t>"
    + "|".join(_variantes_titulo(t) for t in sorted((t for t in _TITULOS_M + _TITULOS_F if t not in ("mr", "mrs", "ms")),
                                                     key=len, reverse=True))
    + r"))\s+$")

_SUST_F = ("girl", "woman", "lady", "wife", "girlfriend", "daughter", "sister", "mother", "mom", "aunt",
           "grandma", "queen", "princess", "nun", "bride", "widow", "actress", "waitress", "hostess",
           "witch", "goddess", "heroine", "mistress", "maid", "babe", "gal", "chick", "succubus",
           "housewife", "milf", "stepmom", "stepsister", "niece", "fiancee", "fiancée", "ex-wife", "ex-girlfriend")
_SUST_M = ("guy", "man", "boy", "husband", "boyfriend", "son", "brother", "father", "dad", "uncle",
           "grandpa", "king", "prince", "priest", "monk", "groom", "widower", "actor", "waiter", "wizard",
           "god", "hero", "gentleman", "dude", "lad", "stepdad", "stepbrother", "nephew", "fiance",
           "fiancé", "ex-husband", "ex-boyfriend", "incubus")
_PATRON_PREDICADO = re.compile(
    r"^\s*(?:is|was|'s)\s+(?P<neg>not\s+|n't\s+)?(?:a|an|my|your|his|her|our|their|the|such\s+a|just\s+a|"
    r"really\s+a)\s+(?:[a-z-]+\s+){0,2}?(?P<s>" + "|".join(sorted(_SUST_F + _SUST_M, key=len, reverse=True))
    + r")\b", re.IGNORECASE)
_PATRON_AUTODESCRIPCION = re.compile(
    r"\bI(?:'m|\s+am)\s+(?:a|an|just\s+a|only\s+a|your|his|her)\s+(?:[a-z-]+\s+){0,2}?(?P<s>"
    + "|".join(sorted(_SUST_F + _SUST_M, key=len, reverse=True)) + r")\b", re.IGNORECASE)
# Aposición justo delante del nombre: "my tech guy, Lio", "her sister Carla", "Carla's mom, Sofia".
_DETERMINANTE = r"(?:\b(?:my|your|his|her|our|their|the|this|that)|\b[A-Z][\w]*'s)"
_APOSICION_GENERO = re.compile(
    _DETERMINANTE + r"\s+(?:[a-z-]+\s+){0,2}?(?P<s>" + "|".join(sorted(_SUST_F + _SUST_M, key=len, reverse=True))
    + r")\s*,?\s*$", re.IGNORECASE)
# "my friend, Cypher." NO es un vocativo (se habla DE Cypher): el pronombre siguiente sí es suyo.
_APOSICION = re.compile(_DETERMINANTE + r"\s+(?:[a-z-]+\s+){0,2}[a-z-]+\s*,\s*$")
_SEGUNDA_PERSONA_EN = re.compile(r"\byou(?:'re|'ve|'ll|'d)?\b|\byour(?:self)?\b", re.IGNORECASE)


def _aposicion_valida(antes: str, despues: str, m: re.Match) -> bool:
    """Una aposición CON coma ("my tech guy, Lio.") se confunde con un vocativo ("Don't count on your
    mother, Marta." / "Have you told this guy, Marta?"). Sin coma ("her sister Carla") siempre vale."""
    if "," not in m.group(0):
        return True
    if re.match(r"\s*[?!]", despues) or m.group(0).lower().startswith("your"):
        return False
    cortes = list(_FIN_ORACION.finditer(antes))
    oracion = antes[cortes[-1].end():] if cortes else antes
    return not _SEGUNDA_PERSONA_EN.search(oracion)

# Cómo llaman otros al protagonista (solo en posición de vocativo: ", sir." / "Thanks, miss!").
# Pista débil: los NPC también hablan entre ellos. Se excluyen interjecciones ("Oh, man!") y
# apelativos genéricos ("girl", "boy", "dude") que se dicen a cualquiera.
_VOCATIVOS_M = ("young man", "sir", "mister", "son", "good boy", "handsome", "big boy", "lad", "stud",
                "mr", "big guy")
_VOCATIVOS_F = ("young lady", "ma'am", "maam", "miss", "good girl", "madam", "missy", "sweet girl")
_PATRON_VOC_TRATO = re.compile(
    r"(?:,\s*|^(?:hey|hi|hello|oh|well|thanks|thank you|sorry|okay|ok|yes|no|look|listen)?\s*,?\s*)"
    r"(?P<v>" + "|".join(sorted(_VOCATIVOS_M + _VOCATIVOS_F, key=len, reverse=True)) + r")\s*[.!?…,~]",
    re.IGNORECASE)

_INTERJECCIONES = (r"(?:hey|hi|hello|oh|ah|thanks|thank\s+you|sorry|ok|okay|well|yes|yeah|no|look|"
                   r"listen|come\s+on|wait|good\s+morning|good\s+night|morning|bye|goodbye|dear|my\s+dear|"
                   r"so|please|excuse\s+me|welcome|welcome\s+back|hmm|um|uh)")
_INICIO_VOC = re.compile(rf"^\W*(?:{_INTERJECCIONES}\s*,?\s*)?$", re.IGNORECASE)

_CODIGOS = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}<>|.!^$]|<[^>]*>|\{[^{}]*\}|\[[a-z/][^\]]*\]")
_FIN_ORACION = re.compile(r"[.!?…]+[\"')\]]*\s+")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z'-]*")

_IGNORAR_JSON = {"Animations.json", "Tilesets.json", "MapInfos.json", "System.json", "Actors.json"}
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _visible(texto: str) -> str:
    t = (texto or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = _CODIGOS.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- Estructuras
@dataclass
class LineaCorpus:
    """Una línea en inglés del juego con lo que se sepa de quién la dice."""

    texto: str
    hablante: str | None = None
    codigo: str | None = None
    es_opcion: bool = False
    origen: str = ""


@dataclass
class _DatosJuego:
    ruta: Path
    motor: str = ""
    titulo: str = ""
    lineas: list[LineaCorpus] = field(default_factory=list)
    actores: list[dict] = field(default_factory=list)          # {id, nombre, apodo, perfil, cara}
    codigos_hablante: dict[str, str] = field(default_factory=dict)  # 'He' -> 'Laura', 'Mc' -> 'MC'
    renpy: dict[str, str] = field(default_factory=dict)        # variable -> nombre visible
    avisos: list[str] = field(default_factory=list)


@dataclass
class _Candidato:
    nombre: str
    fuentes: set[str] = field(default_factory=set)
    alias: set[str] = field(default_factory=set)
    codigos: set[str] = field(default_factory=set)
    descripcion: str = ""
    lineas: int = 0
    menciones: int = 0
    vocativos: int = 0
    m: float = 0.0
    f: float = 0.0
    evidencia: Counter = field(default_factory=Counter)
    muestras: list[str] = field(default_factory=list)
    protagonista: bool = False

    def votar(self, genero: str, peso: float, motivo: str) -> None:
        if genero == HOMBRE:
            self.m += peso
        elif genero == MUJER:
            self.f += peso
        self.evidencia[motivo] += 1


@dataclass
class InformeAnalisis:
    """Resultado del análisis de un juego."""

    ficha: FichaPersonajes
    motor: str = ""
    titulo: str = ""
    lineas_analizadas: int = 0
    avisos: list[str] = field(default_factory=list)
    nombres_palabra_comun: dict[str, str] = field(default_factory=dict)
    duracion: float = 0.0

    def texto_informe(self) -> str:
        """Tabla legible del análisis (para la consola y el Centro de Control)."""
        f = self.ficha
        lineas = [
            "=" * 96,
            f"🔎 ANÁLISIS DE PERSONAJES — {self.titulo or 'juego sin título'} (motor: {self.motor or '?'})",
            f"   {self.lineas_analizadas} líneas analizadas en {self.duracion:.1f} s | {f.resumen()}",
            "=" * 96,
            f"{'ROL':<13}{'NOMBRE':<22}{'GÉNERO':<13}{'CONF.':>6}{'LÍNEAS':>8}{'MENC.':>7}  CÓDIGOS / EVIDENCIA",
            "-" * 96,
        ]
        for p in f.personajes:
            if p.rol == "extra":
                continue
            marca = "✔" if p.confirmado else ("⚠" if p.genero == DESCONOCIDO or p.confianza < 0.6 else " ")
            extra = ", ".join(p.codigos[:4])
            if p.evidencia:
                extra = (extra + " | " if extra else "") + "; ".join(p.evidencia[:3])
            lineas.append(f"{p.rol:<13}{p.nombre[:21]:<22}{marca} {p.genero:<11}{round(p.confianza * 100):>5}%"
                          f"{p.apariciones:>8}{p.menciones:>7}  {extra[:60]}")
        extras = sum(1 for p in f.personajes if p.rol == "extra")
        if extras:
            lineas.append(f"(+{extras} personajes extra con pocas apariciones, guardados en la ficha)")
        if self.nombres_palabra_comun:
            lineas.append("Nombres que son palabras (se protegen para que no se traduzcan): "
                          + ", ".join(f"{k}→{v}" for k, v in self.nombres_palabra_comun.items()))
        for aviso in self.avisos:
            lineas.append(f"⚠ {aviso}")
        pendientes = f.pendientes_de_revisar()
        if pendientes:
            lineas.append("👉 Revisa sobre todo: " + ", ".join(p.etiqueta() for p in pendientes[:10]))
        lineas.append("=" * 96)
        return "\n".join(lineas)


# --------------------------------------------------------------------------- Detección de motor
_MARCAS_DATOS_RPG = ("System.json", "Actors.json", "System.json.bak", "Actors.json.bak")


def _es_carpeta_datos_rpg(carpeta: Path) -> bool:
    if any((carpeta / n).exists() for n in _MARCAS_DATOS_RPG):
        return True
    # Algunos juegos (o parches) solo traen parte de los datos: basta con mapas o eventos comunes.
    return carpeta.is_dir() and (next(carpeta.glob("Map[0-9]*.json*"), None) is not None
                                 or (carpeta / "CommonEvents.json").exists()
                                 or (carpeta / "CommonEvents.json.bak").exists())


def detectar_motor_analisis(ruta: Path) -> str:
    """RPGMaker, RenPy, Unity, CSV o Desconocido (sin escribir nada)."""
    if _es_carpeta_datos_rpg(ruta):
        return "RPGMaker"  # carpeta de datos suelta (p. ej. una copia de la carpeta data)
    if (ruta / "www" / "data").is_dir() or _es_carpeta_datos_rpg(ruta / "data"):
        return "RPGMaker"
    juego = ruta / "game"
    if (ruta / "renpy").is_dir() or (juego.is_dir() and any(
            next(juego.rglob(p), None) is not None for p in ("*.rpy", "*.rpyc", "*.rpa"))):
        return "RenPy"
    if (ruta / "UnityPlayer.dll").exists() or any(ruta.glob("*_Data")) or (ruta / "BepInEx").is_dir():
        return "Unity"
    if next(ruta.rglob("*.csv"), None) is not None:
        return "CSV"
    return "Desconocido"


# --------------------------------------------------------------------------- Escáner RPG Maker
def _carpeta_datos_rpg(ruta: Path) -> Path | None:
    for c in (ruta, ruta / "www" / "data", ruta / "data"):
        if _es_carpeta_datos_rpg(c):
            return c
    return None


def _archivos_json_rpg(carpeta: Path) -> list[Path]:
    """Archivos de datos (X.json), aunque solo exista su copia original X.json.bak."""
    nombres = {p.name for p in carpeta.glob("*.json")}
    nombres |= {p.name[:-len(".bak")] for p in carpeta.glob("*.json.bak")}
    return [carpeta / n for n in sorted(nombres)]


def _leer_json_original(ruta: Path):
    bak = ruta.with_suffix(".json.bak")
    origen = bak if bak.exists() else ruta
    try:
        return json.loads(origen.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        log.debug("No se pudo leer %s: %s", origen, e)
        return None


def _mapa_codigos(eventos_comunes: list) -> dict[str, str]:
    """Códigos de hablante -> nombre del personaje, leídos del evento común que identifica al hablante.

    Busca ``if ($gameVariables.value(V).includes("He")) {`` + ``setValue(ID, 13)`` y las ramas
    ``111 [1, ID, 0, 13, 0]`` que llaman (code 117) a eventos comunes "VOICE Laura"/"DISPLAY Laura".
    """
    nombres_ce = {ev["id"]: ev.get("name") or "" for ev in eventos_comunes if isinstance(ev, dict)}
    codigo_a_valor: dict[str, tuple[int, int]] = {}
    valor_a_nombre: dict[tuple[int, int], str] = {}
    pat_inc = re.compile(r"""includes\(\s*["']([A-Za-z0-9]{2,3})["']\s*\)""")
    pat_set = re.compile(r"setValue\(\s*(\d+)\s*,\s*(\d+)\s*\)")
    pat_ce = re.compile(r"^\s*(?:VOICE|DISPLAY)\s+(.+?)\s*$", re.IGNORECASE)
    for ev in eventos_comunes:
        if not isinstance(ev, dict):
            continue
        lista = ev.get("list") or []
        for i, cmd in enumerate(lista):
            if not isinstance(cmd, dict):
                continue
            c, p = cmd.get("code"), cmd.get("parameters") or []
            if c in (355, 655) and p and isinstance(p[0], str):
                m = pat_inc.search(p[0])
                if m:
                    for sig in lista[i:i + 3]:
                        sp = (sig.get("parameters") or [""]) if isinstance(sig, dict) else [""]
                        ms = pat_set.search(sp[0]) if sp and isinstance(sp[0], str) else None
                        if ms:
                            codigo_a_valor.setdefault(m.group(1), (int(ms.group(1)), int(ms.group(2))))
                            break
            elif c == 111 and len(p) >= 4 and p[0] == 1 and p[2] == 0 and isinstance(p[3], int):
                indent = cmd.get("indent", 0)
                for sig in lista[i + 1:i + 12]:
                    if not isinstance(sig, dict) or sig.get("indent", 0) <= indent:
                        break
                    if sig.get("code") == 117:
                        nombre = nombres_ce.get((sig.get("parameters") or [None])[0], "")
                        mn = pat_ce.match(nombre)
                        if mn:
                            valor_a_nombre.setdefault((p[1], p[3]), mn.group(1).strip())
                            break
    # La variable "de personaje" es la que usan casi todos los códigos (27 en un juego real); las demás son
    # banderas de voz/emoción ('Vo' -> 49, 'No1' -> 80) y no identifican a nadie.
    variables = Counter(var for var, _ in codigo_a_valor.values())
    if not variables:
        return {}
    var_personaje = variables.most_common(1)[0][0]
    return {cod: valor_a_nombre[v] for cod, v in codigo_a_valor.items()
            if v[0] == var_personaje and v in valor_a_nombre}


def _escanear_rpgmaker(datos: _DatosJuego) -> None:
    from .motores.rpgmaker import InyectorRPGMaker  # import perezoso (evita ciclos)

    carpeta = _carpeta_datos_rpg(datos.ruta)
    if carpeta is None:
        datos.avisos.append("No se encontró la carpeta de datos de RPG Maker (www/data o data).")
        return
    sistema = _leer_json_original(carpeta / "System.json")
    if isinstance(sistema, dict) and sistema.get("gameTitle"):
        datos.titulo = str(sistema["gameTitle"]).strip()
    actores = _leer_json_original(carpeta / "Actors.json")
    if isinstance(actores, list):
        for a in actores:
            if not isinstance(a, dict):
                continue
            nombre = limpiar_nombre(str(a.get("name") or ""))
            if not _nombre_valido(nombre):
                continue
            cara = f"face:{a['faceName']}#{a.get('faceIndex', 0)}" if a.get("faceName") else ""
            datos.actores.append({"id": a.get("id"), "nombre": nombre, "apodo": str(a.get("nickname") or ""),
                                  "perfil": str(a.get("profile") or ""), "cara": cara})
    eventos = _leer_json_original(carpeta / "CommonEvents.json")
    if isinstance(eventos, list):
        datos.codigos_hablante = _mapa_codigos(eventos)

    inyector = InyectorRPGMaker(datos.ruta, translator=None)  # solo se usa la extracción
    for ruta in _archivos_json_rpg(carpeta):
        if ruta.name in _IGNORAR_JSON:
            continue
        contenido = _leer_json_original(ruta)
        if contenido is None:
            continue
        cola: list[str] = []
        infos: list[InfoLinea | None] = []
        try:
            inyector._extraer(contenido, cola, infos)  # el objeto es desechable: no hace falta copiarlo
        except Exception as e:  # un archivo raro no debe tumbar el análisis
            log.debug("Extracción fallida en %s: %s", ruta.name, e)
            continue
        for texto, info in zip(cola, infos):
            datos.lineas.append(LineaCorpus(
                texto=texto, hablante=info.hablante if info else None, codigo=info.codigo if info else None,
                es_opcion=bool(info and info.es_opcion), origen=ruta.name))


# --------------------------------------------------------------------------- Escáner Ren'Py
_RE_DEFINE = re.compile(
    r"""^\s*define\s+([A-Za-z_]\w*)\s*=\s*(?:Dynamic)?Character\(\s*(?:_\(\s*)?(?:"([^"]*)"|'([^']*)'|(None))""")
_RE_DIALOGO = re.compile(r'^\s*([A-Za-z_]\w*)\s+(?:@\s*[\w ]+\s+)?"((?:[^"\\]|\\.)*)"\s*(?:with\s+\w+)?\s*$')
_RE_DIALOGO_TL = re.compile(r'^\s*#\s*([A-Za-z_]\w*)\s+(?:@\s*[\w ]+\s+)?"((?:[^"\\]|\\.)*)"')
_RE_NARRADOR = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*$')
_RE_NARRADOR_TL = re.compile(r'^\s*#\s*"((?:[^"\\]|\\.)*)"\s*$')
_RE_OPCION = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*(?:if\s+.+)?:\s*$')
_PALABRAS_RENPY = {"show", "scene", "play", "jump", "call", "define", "default", "image", "label", "menu",
                   "if", "elif", "else", "return", "with", "python", "init", "voice", "queue", "stop",
                   "pause", "window", "nvl", "hide", "transform", "screen", "style", "translate", "old",
                   "new", "text", "add", "action", "textbutton", "imagebutton", "renpy", "extend", "at"}
_VARIABLES_PROTA = {"mc", "pc", "player", "hero", "me", "you", "protagonist", "main", "p", "y"}


def _escanear_renpy(datos: _DatosJuego) -> None:
    juego = datos.ruta / "game" if (datos.ruta / "game").is_dir() else datos.ruta
    scripts = [p for p in juego.rglob("*.rpy") if "tl" not in p.relative_to(juego).parts[:1]]
    traducciones = [p for p in juego.rglob("*.rpy") if p.relative_to(juego).parts[:1] == ("tl",)]
    if not scripts and not traducciones:
        datos.avisos.append("Juego Ren'Py sin scripts .rpy (solo .rpyc/.rpa): genera las traducciones "
                            "(carpeta game/tl) o descompila con unrpyc/UnRen para analizarlo mejor.")
    for p in scripts:
        for linea in _leer_texto(p).splitlines():
            m = _RE_DEFINE.match(linea)
            if m:
                datos.renpy[m.group(1)] = (m.group(2) if m.group(2) is not None else (m.group(3) or "")).strip()
    # Si hay carpeta tl/, sus comentarios '# x "texto"' son el corpus (no se cuenta dos veces).
    fuente = traducciones[: 400] if traducciones else scripts
    if traducciones:
        idiomas = sorted({p.relative_to(juego).parts[1] for p in traducciones if len(p.relative_to(juego).parts) > 2})
        if idiomas:
            fuente = [p for p in traducciones if p.relative_to(juego).parts[1] == idiomas[0]]
    for p in fuente:
        es_tl = p in traducciones
        for linea in _leer_texto(p).splitlines():
            m = (_RE_DIALOGO_TL if es_tl else _RE_DIALOGO).match(linea)
            if m and m.group(1) not in _PALABRAS_RENPY:
                var = m.group(1)
                nombre = datos.renpy.get(var)
                datos.lineas.append(LineaCorpus(texto=_texto_renpy(m.group(2)), hablante=nombre or None,
                                                codigo=f"renpy:{var}", origen=p.name))
                continue
            if not es_tl and _RE_OPCION.match(linea):
                datos.lineas.append(LineaCorpus(texto=_texto_renpy(_RE_OPCION.match(linea).group(1)),
                                                es_opcion=True, origen=p.name))
                continue
            m = (_RE_NARRADOR_TL if es_tl else _RE_NARRADOR).match(linea)
            if m:
                datos.lineas.append(LineaCorpus(texto=_texto_renpy(m.group(1)), origen=p.name))
    if not datos.titulo:
        datos.titulo = datos.ruta.name


def _texto_renpy(texto: str) -> str:
    return re.sub(r"\{[^{}]*\}", "", texto.replace('\\"', '"').replace("\\n", " ")).strip()


def _leer_texto(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


# --------------------------------------------------------------------------- Escáner CSV y XUnity
def _escanear_csv(datos: _DatosJuego, max_archivos: int = 60) -> None:
    from .csv_locales import analizar_cabecera, leer_lineas, partir
    from .texto import PATRON_NOMBRE_HABLANTE, PATRON_PREFIJO

    # Los originales (*.csv.original, a veces en carpetas de copia) tienen el inglés intacto;
    # el *.csv del juego puede estar ya traducido.
    originales: dict[str, Path] = {}
    for p in sorted(datos.ruta.rglob("*.csv.original")):
        originales.setdefault(p.name, p)
    archivos = list(originales.values()) or sorted(
        p for p in datos.ruta.rglob("*.csv") if "backup" not in str(p.parent).lower())
    vistos = 0
    for ruta in archivos:
        if vistos >= max_archivos:
            break
        original = ruta.with_name(ruta.name + ".original")
        try:
            _, lineas = leer_lineas(original if original.exists() else ruta)
        except (OSError, UnicodeDecodeError):
            continue
        if not lineas:
            continue
        delim, _, col = analizar_cabecera(lineas)
        if col is None:
            continue
        vistos += 1
        for linea in lineas[1:]:
            partes, _ = partir(linea, delim)
            if len(partes) <= col:
                continue
            texto = partes[col].strip().strip('"')
            m = PATRON_NOMBRE_HABLANTE.match(texto)
            hablante = limpiar_nombre(m.group(2)) if m else None
            pref = PATRON_PREFIJO.match(texto)
            cuerpo = texto[pref.end():] if pref else texto
            if cuerpo.strip():
                datos.lineas.append(LineaCorpus(texto=cuerpo.replace("\\n", " "), hablante=hablante,
                                                origen=ruta.name))


def _escanear_xunity(datos: _DatosJuego) -> None:
    from .xunity import leer_traducciones

    archivos: list[Path] = []
    for base in (datos.ruta / "BepInEx" / "Translation", datos.ruta / "Translation", datos.ruta / "AutoTranslator"):
        if base.is_dir():
            archivos.extend(sorted(base.glob("*/Text/*.txt")))
    if not archivos:
        datos.avisos.append("Juego Unity sin textos de XUnity.AutoTranslator todavía: juega un rato con el proxy "
                            "activo (o rellena personajes.json a mano) y vuelve a analizar.")
        return
    vistos: set[str] = set()
    for ruta in archivos:
        try:
            pares = leer_traducciones(ruta)
        except Exception as e:
            log.debug("No se pudo leer %s: %s", ruta, e)
            continue
        for original in pares:
            if original not in vistos:
                vistos.add(original)
                datos.lineas.append(LineaCorpus(texto=original, origen=ruta.name))
    if not datos.titulo:
        datos.titulo = datos.ruta.name


# --------------------------------------------------------------------------- Candidatos
def _nombre_valido(nombre: str) -> bool:
    if not nombre or len(nombre) < 2 or len(nombre) > 30 or not any(c.isalpha() for c in nombre):
        return False
    if nombre.isdigit() or re.fullmatch(r"[\W\d_]+", nombre):
        return False
    if nombre.isupper() and " " in nombre:  # 'HERO STANDIN', 'DUMMY ACTOR'...
        return False
    return nombre.casefold() not in _NO_NOMBRES


class _Registro:
    """Candidatos por nombre (sin distinguir mayúsculas) + índices de códigos."""

    def __init__(self) -> None:
        self.por_clave: dict[str, _Candidato] = {}
        self.por_codigo: dict[str, _Candidato] = {}

    def obtener(self, nombre: str, fuente: str) -> _Candidato | None:
        nombre = limpiar_nombre(nombre)
        if not _nombre_valido(nombre) and nombre not in MARCADORES_PROTAGONISTA:
            return None
        clave = nombre.casefold()
        c = self.por_clave.get(clave)
        if c is None:
            c = _Candidato(nombre=nombre)
            self.por_clave[clave] = c
        c.fuentes.add(fuente)
        return c

    def alias(self, candidato: _Candidato, nombre: str) -> None:
        nombre = limpiar_nombre(nombre)
        if nombre and nombre.casefold() != candidato.nombre.casefold():
            candidato.alias.add(nombre)
            self.por_clave.setdefault(nombre.casefold(), candidato)

    def codigo(self, candidato: _Candidato, codigo: str) -> None:
        candidato.codigos.add(codigo)
        self.por_codigo.setdefault(codigo, candidato)

    def todos(self) -> list[_Candidato]:
        unicos: dict[int, _Candidato] = {}
        for c in self.por_clave.values():
            unicos[id(c)] = c
        return list(unicos.values())


def _marcador_protagonista(datos: _DatosJuego) -> str | None:
    """Marcador que el juego usa en el texto para el nombre del protagonista ('1Hero', '[mcname]'...)."""
    cuenta = Counter()
    muestra = datos.lineas if len(datos.lineas) < 60000 else datos.lineas[::3]
    for ln in muestra:
        for marcador in MARCADORES_PROTAGONISTA:
            if marcador in ln.texto:
                cuenta[marcador] += 1
    for linea in datos.renpy.values():
        if linea.startswith("[") and linea.endswith("]"):
            cuenta[linea] += 50
    if not cuenta:
        return None
    marcador, veces = cuenta.most_common(1)[0]
    return marcador if veces >= 3 else None


def _construir_candidatos(datos: _DatosJuego, reg: _Registro) -> _Candidato | None:
    """Crea los candidatos a partir de actores, códigos y hablantes. Devuelve el protagonista si se sabe."""
    prota: _Candidato | None = None
    marcador = _marcador_protagonista(datos)

    def _prota(nombre_base: str, fuente: str) -> _Candidato | None:
        nonlocal prota
        nombre = marcador if marcador and marcador not in ("\\N[1]", "\\n[1]") else nombre_base
        c = reg.obtener(nombre, fuente)
        if c is None:
            return None
        if nombre != nombre_base:
            reg.alias(c, nombre_base)
        c.protagonista = True
        prota = c
        return c

    # 1. Códigos de hablante: el mapa del evento "MESSAGE" es la fuente más fiable (incluye al protagonista 'MC').
    for codigo, nombre in sorted(datos.codigos_hablante.items()):
        if nombre.strip().upper() in ("MC", "PLAYER", "HERO", "PROTAGONIST"):
            actor1 = datos.actores[0]["nombre"] if datos.actores and datos.actores[0].get("id") == 1 else ""
            c = prota or _prota(actor1 or "1Hero", "codigos")
        else:
            c = reg.obtener(nombre, "codigos")
            if c is not None:
                c.evidencia[f"MESSAGE: VOICE/DISPLAY {nombre}"] += 1
        if c is not None:
            reg.codigo(c, codigo)

    # 2. Actores de RPG Maker (el 1 es el protagonista si no lo dio el evento MESSAGE)
    for a in datos.actores:
        es_uno = a.get("id") == 1
        base = a["nombre"].split()[0] if " " in a["nombre"] and reg.por_clave.get(a["nombre"].split()[0].casefold()) else None
        if base:  # 'Ana Bikini' -> alias de 'Ana'
            c = reg.por_clave[base.casefold()]
            reg.alias(c, a["nombre"])
        elif es_uno and prota is None:
            c = _prota(a["nombre"], "actor")
        elif es_uno and prota is not None:
            c = prota
            reg.alias(c, a["nombre"])
        else:
            c = reg.obtener(a["nombre"], "actor")
        if c is None:
            continue
        if a.get("cara"):
            reg.codigo(c, a["cara"])
        if not c.descripcion:
            c.descripcion = (a.get("perfil") or a.get("apodo") or "").replace("\n", " ").strip()[:160]
    if prota is not None:
        reg.alias(prota, "\\N[1]")

    # 3. Ren'Py: variables de Character()
    for var, nombre in datos.renpy.items():
        if var in _VARIABLES_PROTA or (nombre.startswith("[") and nombre.endswith("]")):
            c = prota or _prota(nombre if nombre else (marcador or "Protagonista"), "renpy")
        elif nombre:
            c = reg.obtener(nombre, "renpy")
        else:
            continue
        if c is not None:
            reg.codigo(c, f"renpy:{var}")

    # 4. Hablantes que aparecen en las líneas (cajas de nombre, MZ, Ren'Py sin define)
    for ln in datos.lineas:
        if ln.hablante:
            if re.fullmatch(r"\\[Nn]\[1\]", ln.hablante):
                if prota is None:
                    _prota(marcador or "Protagonista", "caja")
                continue
            reg.obtener(ln.hablante, "hablante")
        elif ln.codigo and ln.codigo.startswith("renpy:") and ln.codigo not in reg.por_codigo:
            var = ln.codigo.split(":", 1)[1]
            if var in _VARIABLES_PROTA:
                c = prota or _prota(marcador or "Protagonista", "renpy")
            elif len(var) >= 3 and var.isalpha():
                c = reg.obtener(var.capitalize(), "renpy")
            else:
                c = None
            if c is not None:
                reg.codigo(c, ln.codigo)

    # 5. Marcador de protagonista sin ninguna otra pista ({ProtagonistName}, [mcname]...)
    if prota is None and marcador:
        _prota(marcador, "marcador")
    return prota


_MAYUSCULA_EN_MITAD = re.compile(r"(?<=[a-z,;:] )([A-Z][a-z]{2,14})\b")
_VOCATIVO_INICIAL = re.compile(r"(?:^|[.!?] )([A-Z][a-z]{2,14})(?=,)")


def _candidatos_por_frecuencia(datos: _DatosJuego, reg: _Registro, minimo: int = 6) -> Counter:
    """Nombres de pila conocidos que aparecen a menudo en mitad de frase (juegos sin hablantes).
    Devuelve el recuento de palabras en mayúscula en mitad de frase (lo usa ``_candidatos_sin_lexico``)."""
    cuenta: Counter = Counter()
    for ln in datos.lineas:
        texto = _visible(ln.texto)
        for m in _MAYUSCULA_EN_MITAD.finditer(texto):
            cuenta[m.group(1)] += 1
        for m in _VOCATIVO_INICIAL.finditer(texto):
            cuenta[m.group(1)] += 1  # vocativo al inicio: "Noelia, ..."
    for nombre, veces in cuenta.items():
        cf = nombre.casefold()
        if veces >= minimo and (cf in _NOMBRES_F or cf in _NOMBRES_M or cf in _AMBIGUOS) and cf not in _NO_NOMBRES:
            reg.obtener(nombre, "frecuencia")
    return cuenta


# Palabras en mayúscula que pueden ir delante de un nombre sin formar parte de él ("Hey Lio", "Miss Nova").
_ANTES_DE_NOMBRE = (r"Hey|Hi|Hello|Thanks|Thank|Oh|Ah|Yes|No|Okay|Ok|Well|Sorry|Dear|Poor|Little|Big|Old|"
                    r"Young|Miss|Mr|Mrs|Ms|Sir|Lady|Lord|Madam|Dr|Doctor|Uncle|Aunt|Sister|Brother|Bye|Goodbye|"
                    r"Wait|Look|Listen|Please|Come|Damn|Fuck|Shit|Wow|Uh|Um|Hmm|So|But|And|Then|Now|What")


def _candidatos_sin_lexico(datos: _DatosJuego, reg: _Registro, prota: _Candidato | None,
                           cuenta: Counter, minimo: int) -> list[str]:
    """Nombres que NO están en el léxico ("Lio", "Cal", "Cypher") pero que el texto trata claramente
    como personas: "my tech guy, Lio. He'll know...". Sobre todo para juegos sin hablantes (XUnity).

    Para no confundirlos con lugares o marcas se descartan las palabras que suelen ir tras "the"
    ("the Cartel") o pegadas a otra mayúscula ("Glowing Hole", "Nail Salon"), y la evidencia se
    recoge en una pasada aparte sobre una COPIA del registro: así no le roban votos de pronombres a
    los personajes ya conocidos. Solo se añaden si los pronombres/tratamientos deciden su género.
    Devuelve los nombres añadidos.
    """
    conocidas = _NOMBRES_F | _NOMBRES_M | _AMBIGUOS | _NO_NOMBRES | _ROL_F_PAL | _ROL_M_PAL
    conocidas |= set(_TITULOS_M) | set(_TITULOS_F)
    posibles = [n for n, veces in cuenta.items()
                if veces >= minimo and n.casefold() not in conocidas and n.casefold() not in reg.por_clave]
    if not posibles:
        return []
    alternativas = "|".join(re.escape(n) for n in sorted(posibles, key=len, reverse=True))
    patron = re.compile(rf"(?P<the>\b[Tt]he\s+)?(?P<ant>\b(?!(?:{_ANTES_DE_NOMBRE})\b)[A-Z][a-z]+\s+)?"
                        rf"\b(?P<n>{alternativas})\b(?P<sig>\s+[A-Z][a-z])?")
    total: Counter = Counter()
    pegadas: Counter = Counter()
    for ln in datos.lineas:
        for m in patron.finditer(_visible(ln.texto)):
            n = m.group("n")
            total[n] += 1
            if m.group("the") or m.group("ant") or m.group("sig"):
                pegadas[n] += 1
    provisionales = [n for n in posibles if total[n] >= minimo and pegadas[n] <= 0.3 * total[n]]
    if not provisionales:
        return []

    copia, prota_copia = copy.deepcopy((reg, prota))
    nuevos = {n: copia.obtener(n, "frecuencia") for n in provisionales}
    _recoger_evidencia(datos, copia, prota_copia)
    anadidos = []
    for nombre, c in nuevos.items():
        if c is None:
            continue
        genero, _ = _decidir_genero(c)
        decisiva = any(k.startswith(("pronombres", "tratamiento", "es '", "aposición")) for k in c.evidencia)
        if genero not in (HOMBRE, MUJER) or not decisiva:
            continue
        real = reg.obtener(nombre, "pronombres")
        if real is None:
            continue
        real.m, real.f = c.m, c.f
        real.evidencia = Counter(c.evidencia)
        real.menciones, real.vocativos = c.menciones, c.vocativos
        real.muestras = list(c.muestras)
        anadidos.append(nombre)
    return anadidos


# --------------------------------------------------------------------------- Evidencia de género
def _patron_nombres(candidatos: list[_Candidato]) -> tuple[re.Pattern | None, dict[str, _Candidato]]:
    formas: dict[str, _Candidato] = {}
    for c in candidatos:
        for n in [c.nombre, *c.alias]:
            n = limpiar_nombre(n)
            if len(n) >= 2 and (n[0].isalnum() or n in MARCADORES_PROTAGONISTA):
                formas.setdefault(n, c)
                if n[:1].isalpha():
                    formas.setdefault(n.upper(), c)
    if not formas:
        return None, {}
    alternativas = "|".join(re.escape(n) for n in sorted(formas, key=len, reverse=True))
    return re.compile(rf"(?<![\w\\])(?:{alternativas})(?![\w])"), formas


def _resolver_hablante(ln: LineaCorpus, reg: _Registro, prota: _Candidato | None) -> _Candidato | None:
    if ln.es_opcion:
        return prota
    if ln.hablante:
        if re.fullmatch(r"\\[Nn]\[1\]", ln.hablante):
            return prota
        c = reg.por_clave.get(limpiar_nombre(ln.hablante).casefold())
        if c is not None:
            return c
    if ln.codigo:
        c = reg.por_codigo.get(ln.codigo)
        if c is None and not ln.codigo.startswith(("face:", "renpy:")):
            c = reg.por_codigo.get(ln.codigo[:2])
        return c
    return None


def _recoger_evidencia(datos: _DatosJuego, reg: _Registro, prota: _Candidato | None) -> None:
    candidatos = reg.todos()
    patron, formas = _patron_nombres(candidatos)
    hay_hablantes = any(ln.hablante or ln.codigo for ln in datos.lineas)
    for ln in datos.lineas:
        texto = _visible(ln.texto)
        if not texto:
            continue
        hablante = _resolver_hablante(ln, reg, prota)
        if hablante is not None:
            hablante.lineas += 1
            if len(hablante.muestras) < 8 and len(texto) > 12:
                hablante.muestras.append(f"[{hablante.nombre}] {texto[:160]}")
            m = _PATRON_AUTODESCRIPCION.search(texto)
            if m and not re.search(r"\bnot\b", texto[max(0, m.start() - 8):m.end()], re.IGNORECASE):
                s = m.group("s").lower()
                hablante.votar(MUJER if s in _SUST_F else HOMBRE, 2.0, f"se describe como '{s}'")
        # Cómo llaman al protagonista quienes hablan con él (solo si se sabe que habla otro)
        if prota is not None and hablante is not None and hablante is not prota and hay_hablantes:
            for mv in _PATRON_VOC_TRATO.finditer(texto):
                v = mv.group("v").lower()
                prota.votar(MUJER if v in _VOCATIVOS_F else HOMBRE, 0.3, f"le llaman '{v}'")
        if patron is None:
            continue
        for m in patron.finditer(texto):
            c = formas.get(m.group(0))
            if c is None:
                continue
            if c is not hablante:
                c.menciones += 1
                if len(c.muestras) < 14 and len(texto) > 12:
                    c.muestras.append(texto[:160])
            antes, despues = texto[:m.start()], texto[m.end():]
            mt = _PATRON_TITULO.search(antes[-20:])
            if mt:
                t = (mt.group("abr") or mt.group("t")).lower()
                c.votar(HOMBRE if t in _TITULOS_M else MUJER, 3.0, f"tratamiento '{t.capitalize()}'")
            mp = _PATRON_PREDICADO.match(despues)
            if mp and not mp.group("neg"):
                s = mp.group("s").lower()
                c.votar(MUJER if s in _SUST_F else HOMBRE, 2.0, f"es '{s}'")
            cola = antes[-60:]
            ma = _APOSICION_GENERO.search(cola)
            if ma and not _aposicion_valida(antes, despues, ma):
                ma = None
            if ma:
                s = ma.group("s").lower()
                c.votar(MUJER if s in _SUST_F else HOMBRE, 2.0, f"aposición '{s}'")
            mn = ma or _APOSICION.search(cola)
            aposicion = bool(mn) and _aposicion_valida(antes, despues, mn)
            # Vocativo ("Chloe, ...", "..., Chloe?"): se habla CON el personaje, así que el
            # pronombre que venga después ("Thanks, Chloe. She said...") es de otra persona.
            if _INICIO_VOC.match(antes) and re.match(r"\s*[,!?…]", despues):
                c.vocativos += 1
            elif re.search(r",\s*$", antes) and not aposicion and re.match(r"\s*[.!?…~]*(?:\s|$)", despues):
                c.vocativos += 1
            elif re.match(r"\s*[.!?…~]", despues) and not aposicion and _palabras_en_la_oracion(antes):
                # "Do it 1Hero. Taste her ass." -> vocativo sin coma (o complemento): el pronombre
                # de la oración siguiente es de otra persona. Sí cuenta "Carla? I haven't seen her."
                c.vocativos += 1
            else:
                _votar_pronombre(c, despues, formas)


# Pronombres objeto/ambiguos: en la MISMA oración casi siempre son de otra persona
# ("1Hero kissed her", "Carla hugged him"); en la oración siguiente sí suelen referirse al nombrado
# ("Carla? I haven't seen her.").
_PRON_OBJETO = {"him", "her", "hers"}
# "1Hero's mom... she" -> el pronombre es de la madre, no de 1Hero.
_POSESIVO = re.compile(
    r"^'s\s+(?!(?:been|not|a|an|the|so|very|really|just|here|there|going|gonna|coming|got|gotten|always|"
    r"never|still|already|done|gone|right|okay|ok|fine|back|out|in|at|on|over|with|my|your|our|too|also|"
    r"actually|probably|definitely|such|kind|sort|that|this|what|how|like|more|less|all|about|only|even|"
    r"nice|good|bad|cute|hot|great|busy|home|away|late|sick|tired|alone|safe|dead|gay|mine|yours|"
    # "Lio's stuck", "Sarah's worried": contracción de "is", no posesivo
    r"stuck|drunk|lost|hurt|caught|left|taken|broken|asleep|awake|upset|mad|angry|wrong|pregnant|crazy|"
    r"sorry|ready|married|single|worried|scared|happy|sad|excited|nervous|afraid|alive|hungry|missing|"
    r"coming|trying|waiting|looking|working|sleeping|talking|staying|leaving|playing|getting|doing|"
    r"making|taking|having|being|saying|thinking|acting|hiding|running|helping)\b)[a-z]")


_INTERJ_SUELTAS = re.compile(rf"^\W*(?:{_INTERJECCIONES}\W*)*$", re.IGNORECASE)


def _palabras_en_la_oracion(antes: str) -> bool:
    """True si en la misma oración, antes del nombre, hay palabras que no son solo interjecciones."""
    cortes = list(_FIN_ORACION.finditer(antes))
    inicio = cortes[-1].end() if cortes else 0
    resto = antes[inicio:]
    return bool(_TOKEN.search(resto)) and not _INTERJ_SUELTAS.match(resto)


def _votar_pronombre(c: _Candidato, despues: str, formas: dict[str, _Candidato]) -> None:
    """Primer pronombre de 3.ª persona tras el nombre (misma oración o la siguiente)."""
    if _POSESIVO.match(despues):
        return
    trozo = despues[:220]
    cortes = list(_FIN_ORACION.finditer(trozo))
    if len(cortes) >= 2:
        trozo = trozo[:cortes[1].start()]
    fin_oracion = cortes[0].start() if cortes else len(trozo)
    for tok in _TOKEN.finditer(trozo):
        palabra = tok.group(0)
        if palabra in formas and formas[palabra] is not c:
            return  # aparece otro personaje antes: el pronombre podría ser suyo
        baja = palabra.lower()
        misma_oracion = tok.start() < fin_oracion
        if baja in _PRON_OBJETO and misma_oracion:
            continue
        peso = 0.6 if baja in _PRON_OBJETO else None
        if baja in _PRON_M:
            c.votar(HOMBRE, peso or _PRON_M[baja], "pronombres he/him")
            return
        if baja in _PRON_F:
            c.votar(MUJER, peso or _PRON_F[baja], "pronombres she/her")
            return


# Roles como palabra completa ("Woman", "Head Maid", "Old Man", "Mujer") o como final de una palabra
# compuesta de 6+ letras ("henchwoman", "policeman", "landlady"). "Wilson" o "Allison" NO son "son".
_ROL_F_PAL = {"woman", "women", "girl", "lady", "wife", "mother", "mom", "sister", "queen", "princess", "nun",
              "maid", "witch", "waitress", "goddess", "mistress", "succubus", "daughter", "aunt", "grandma",
              "bride", "madam", "mujer", "chica", "señora", "senora", "señorita", "senorita", "niña", "nina",
              "madre", "hermana", "reina", "princesa", "monja", "criada", "bruja", "camarera", "diosa", "abuela"}
_ROL_M_PAL = {"man", "men", "boy", "guy", "husband", "father", "dad", "brother", "king", "prince", "priest",
              "monk", "waiter", "wizard", "incubus", "son", "uncle", "grandpa", "groom", "lord", "sir",
              "hombre", "chico", "señor", "senor", "niño", "nino", "padre", "hermano", "rey", "príncipe",
              "principe", "sacerdote", "monje", "camarero", "brujo", "mago", "abuelo"}
_ROL_F_SUF = ("woman", "women", "lady", "girl", "maid", "wife", "mother", "sister", "queen", "witch")
_ROL_M_SUF = ("man", "men", "boy", "guy", "husband", "father", "brother", "king")


def _votar_lexico(c: _Candidato) -> None:
    """Pista débil por el nombre de pila ('Laura') o por el rol ('Henchwoman', 'Old Man').
    Se mira el nombre y, si no dice nada, sus alias (p. ej. '1Hero' -> actor 1 'William')."""
    for nombre in [c.nombre, *sorted(c.alias)]:
        if _votar_lexico_nombre(c, nombre):
            return


def _votar_lexico_nombre(c: _Candidato, nombre: str) -> bool:
    palabras = [_sin_tildes(w).casefold() for w in re.findall(r"[A-Za-zÀ-ÿ]+", nombre)]
    for w in palabras:
        if w in _NOMBRES_F:
            c.votar(MUJER, 2.0, "léxico de nombres: mujer")
            return True
        if w in _NOMBRES_M:
            c.votar(HOMBRE, 2.0, "léxico de nombres: hombre")
            return True
    for w in palabras:
        if w in _AMBIGUOS:
            return True  # nombre ambiguo: no se mira nada más (tampoco los alias)
        compuesta = len(w) >= 6
        if w in _ROL_F_PAL or (compuesta and w.endswith(_ROL_F_SUF)):  # 'henchwoman' antes que 'man'
            c.votar(MUJER, 2.0, f"rol: {w}")
            return True
        if (w in _ROL_M_PAL or (compuesta and w.endswith(_ROL_M_SUF))) and not w.endswith(
                ("human", "woman", "women", "german", "roman", "shaman")):
            c.votar(HOMBRE, 2.0, f"rol: {w}")
            return True
    return False


def _decidir_genero(c: _Candidato) -> tuple[str, float]:
    total = c.m + c.f
    if total <= 0:
        return DESCONOCIDO, 0.0
    dif = abs(c.m - c.f)
    confianza = min(0.99, dif / (total + 1.0))
    if max(c.m, c.f) >= 2.0 and confianza >= 0.4:
        return (HOMBRE if c.m > c.f else MUJER), confianza
    return DESCONOCIDO, confianza


def _mapear_codigos_por_iniciales(datos: _DatosJuego, reg: _Registro, candidatos: list[_Candidato]) -> None:
    """Códigos de hablante sin mapa ('Am', 'Va' en juegos antiguos) -> personaje por sus iniciales.

    Solo se asigna si todos los personajes con esas iniciales tienen el MISMO género (o hay uno solo):
    así, aunque se elija mal entre 'Amber' y 'Amanda', la concordancia de género sigue siendo correcta.
    """
    libres = Counter(ln.codigo for ln in datos.lineas
                     if ln.codigo and not ln.codigo.startswith(("face:", "renpy:"))
                     and ln.codigo not in reg.por_codigo)
    asignados: list[str] = []
    dudosos: list[str] = []
    for cod, veces in libres.most_common():
        if veces < 5 or len(cod) < 2:
            continue
        opciones = [c for c in candidatos if c.nombre[:2].casefold() == cod[:2].casefold()]
        if not opciones:
            continue
        generos = {_decidir_genero(c)[0] for c in opciones}
        if len(opciones) == 1 or (len(generos) == 1 and DESCONOCIDO not in generos):
            elegido = max(opciones, key=lambda c: (c.menciones, c.lineas))
            reg.codigo(elegido, cod)
            elegido.lineas += veces
            elegido.evidencia[f"código '{cod}' asignado por iniciales"] += 1
            asignados.append(f"{cod}→{elegido.nombre}")
        else:
            dudosos.append(f"{cod} ({'/'.join(c.nombre for c in opciones[:3])})")
    if asignados:
        datos.avisos.append("Códigos de hablante asignados por iniciales (revísalos): " + ", ".join(asignados[:20]))
    if dudosos:
        datos.avisos.append("Códigos de hablante sin asignar por ambigüedad de género (asígnalos en el editor): "
                            + ", ".join(dudosos[:15]))


def _texto_evidencia(c: _Candidato) -> list[str]:
    return [f"{motivo} x{veces}" if veces > 1 else motivo for motivo, veces in c.evidencia.most_common(6)]


# --------------------------------------------------------------------------- IA (opcional)
_PROHIBIDOS_IA = ("ia_traductora",)


def _modelo_ia_por_defecto(endpoint: str) -> str | None:
    import requests

    base = endpoint.split("/api/")[0]
    try:
        r = requests.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
        modelos = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as e:
        log.warning("No se pudo consultar Ollama para el análisis con IA (%s).", e)
        return None
    for preferido in ("llama3.1", "qwen2.5", "mistral", "gemma", "llama3"):
        for m in modelos:
            if m.lower().startswith(preferido) and not m.lower().startswith(_PROHIBIDOS_IA):
                return m
    for m in modelos:
        if not m.lower().startswith(_PROHIBIDOS_IA):
            return m
    return None


def _preguntar_ia(c: _Candidato, titulo: str, modelo: str, endpoint: str) -> str:
    import requests

    muestras = "\n".join(f"- {s}" for s in c.muestras[:12])
    rol = "the protagonist (the player character)" if c.protagonista else "a character"
    prompt = (f"Game: {titulo or 'unknown'}. Decide the gender of {rol} named \"{c.nombre}\" using ONLY "
              f"these lines from the game (lines starting with [{c.nombre}] are said by them):\n{muestras}\n\n"
              "Answer with JSON: {\"genero\": \"hombre\" | \"mujer\" | \"desconocido\", \"motivo\": \"...\"}. "
              "Use \"desconocido\" if the lines do not make it clear.")
    try:
        r = requests.post(endpoint, json={"model": modelo, "prompt": prompt, "stream": False, "format": "json",
                                          "options": {"temperature": 0, "num_predict": 120}}, timeout=60)
        r.raise_for_status()
        datos = json.loads(r.json().get("response") or "{}")
        return normalizar_genero(datos.get("genero"))
    except Exception as e:
        log.debug("La IA no pudo clasificar a %s: %s", c.nombre, e)
        return DESCONOCIDO


# --------------------------------------------------------------------------- Análisis completo
def analizar_juego(ruta_juego: str | Path, motor: str | None = None, *, usar_ia: bool = False,
                   modelo_ia: str | None = None, endpoint: str | None = None,
                   juego: str | None = None) -> InformeAnalisis:
    """Analiza el juego (solo lectura) y devuelve su ficha de personajes con la evidencia."""
    t0 = time.time()
    ruta = Path(ruta_juego)
    datos = _DatosJuego(ruta=ruta)
    if not ruta.exists():
        datos.avisos.append(f"No existe la carpeta del juego: {ruta}")
        return InformeAnalisis(ficha=FichaPersonajes(), avisos=datos.avisos)
    datos.motor = motor or detectar_motor_analisis(ruta)
    if datos.motor == "RPGMaker":
        _escanear_rpgmaker(datos)
        hay_csv = next(ruta.rglob("*.csv*"), None) is not None
        no_ingles = sum(1 for ln in datos.lineas if _CJK.search(ln.texto))
        if datos.lineas and no_ingles > 0.3 * len(datos.lineas):
            # Juego original en chino/japonés/coreano (hay juegos así): el inglés está en los CSV.
            datos.lineas = []
            datos.actores = [a for a in datos.actores if not _CJK.search(a["nombre"])]
            datos.codigos_hablante = {}
            datos.avisos.append("Los datos del juego no están en inglés: se analizan los CSV de localización."
                                if hay_csv else "Los textos del juego no están en inglés: el análisis no es fiable.")
            if hay_csv:
                _escanear_csv(datos)
        elif not any(ln.hablante or ln.codigo for ln in datos.lineas) and hay_csv:
            _escanear_csv(datos)  # RPG Maker con textos en CSV (DKTools_Localization)
    elif datos.motor == "RenPy":
        _escanear_renpy(datos)
    elif datos.motor in ("CSV", "Godot"):
        _escanear_csv(datos)
    elif datos.motor == "Unity":
        _escanear_xunity(datos)
    else:
        datos.avisos.append("Motor no reconocido: rellena personajes.json a mano (o con el editor).")
    if not datos.titulo:
        datos.titulo = ruta.name

    reg = _Registro()
    prota = _construir_candidatos(datos, reg)
    minimo = 6 if any(ln.hablante or ln.codigo for ln in datos.lineas) else 4
    cuenta = _candidatos_por_frecuencia(datos, reg, minimo=minimo)
    _recoger_evidencia(datos, reg, prota)
    anadidos = _candidatos_sin_lexico(datos, reg, prota, cuenta, minimo)
    if anadidos:
        log.debug("Personajes fuera del léxico detectados por pronombres: %s", ", ".join(anadidos))
    candidatos = reg.todos()

    # Narración en 2.ª persona ("You run upstairs..."): el protagonista es "tú", sin nombre, y el
    # personaje más nombrado suele ser la chica/chico principal, NO el protagonista.
    sin_hablante = [ln for ln in datos.lineas if not (ln.hablante or ln.codigo or ln.es_opcion)]
    narracion_tu = sum(1 for ln in sin_hablante
                       if re.match(r"^\W*You\s+(?!know|see|guys|two|bastard|idiot|pervert)[a-z]+", _visible(ln.texto))
                       and not _visible(ln.texto).rstrip().endswith("?"))
    segunda_persona = bool(sin_hablante) and narracion_tu >= max(20, 0.03 * len(sin_hablante))
    if segunda_persona and prota is None:
        datos.avisos.append(f"El juego narra en 2.ª persona ({narracion_tu} líneas tipo 'You walk...'): el "
                            "protagonista es «tú» sin nombre. Indica su nombre y género en el editor.")
    # Sin protagonista claro (o si el actor 1 es un marcador que el texto nunca usa, como "Main"
    # en algunos juegos), el protagonista suele ser a quien más se llama por su nombre.
    if candidatos and not segunda_persona and (prota is None or prota.menciones < 5):
        orden = sorted((c for c in candidatos if c is not prota), key=lambda c: -c.vocativos)
        if orden and orden[0].vocativos >= 5 and (
                len(orden) == 1 or orden[0].vocativos >= 1.5 * max(1, orden[1].vocativos)):
            nuevo = orden[0]
            if prota is not None:  # el actor 1 pasa a ser alias del protagonista real
                prota.protagonista = False
                reg.alias(nuevo, prota.nombre)
                for a in prota.alias:
                    reg.alias(nuevo, a)
                for cod in prota.codigos:
                    nuevo.codigos.add(cod)
                    reg.por_codigo[cod] = nuevo
                nuevo.lineas += prota.lineas
                candidatos = [c for c in candidatos if c is not prota]
                reg.por_clave = {k: (nuevo if v is prota else v) for k, v in reg.por_clave.items()}
            prota = nuevo
            prota.protagonista = True
            prota.evidencia["protagonista: el más llamado por su nombre"] += 1
            datos.avisos.append(f"Protagonista deducido ({prota.nombre}) por ser el personaje al que más se "
                                "llama por su nombre: confírmalo.")
    if prota is None:
        datos.avisos.append("No se pudo determinar el protagonista: indícalo en el editor de personajes "
                            "o con configurar_perfil_juego.py --protagonista NOMBRE --genero hombre|mujer.")

    for c in candidatos:
        _votar_lexico(c)
    _mapear_codigos_por_iniciales(datos, reg, candidatos)

    relevantes = sorted(candidatos, key=lambda c: -(c.lineas + 0.5 * c.menciones))
    relevantes = [c for c in relevantes if c.protagonista or c.lineas >= 1 or c.menciones >= 3]

    if usar_ia:
        endpoint = endpoint or config.OLLAMA_URL
        modelo = modelo_ia or _modelo_ia_por_defecto(endpoint)
        if modelo is None:
            datos.avisos.append("Análisis con IA no disponible (Ollama sin modelos generales).")
        else:
            for c in [c for c in relevantes[:15] if c.protagonista or c.lineas or c.menciones >= 10]:
                genero, conf = _decidir_genero(c)
                if genero == DESCONOCIDO or conf < 0.6:
                    g = _preguntar_ia(c, datos.titulo, modelo, endpoint)
                    if g in (HOMBRE, MUJER):
                        c.votar(g, 2.5, f"IA ({modelo}): {g}")

    personajes: list[Personaje] = []
    for i, c in enumerate(relevantes[:80]):
        genero, conf = _decidir_genero(c)
        if c.protagonista:
            rol = "protagonista"
        elif i < 14 and (c.lineas + c.menciones) >= 15:
            rol = "principal"
        elif (c.lineas + c.menciones) >= 3 or c.codigos:
            rol = "secundario"
        else:
            rol = "extra"
        personajes.append(Personaje(
            nombre=c.nombre, genero=genero, rol=rol, alias=sorted(c.alias), codigos=sorted(c.codigos),
            descripcion=c.descripcion, apariciones=c.lineas, menciones=c.menciones,
            confianza=conf, evidencia=_texto_evidencia(c)))
    ficha = FichaPersonajes(personajes=personajes, titulo=datos.titulo, motor=datos.motor)
    palabras = {p.nombre: NOMBRES_PALABRA[p.nombre] for p in personajes
                if p.nombre in NOMBRES_PALABRA and p.rol != "extra"}
    return InformeAnalisis(ficha=ficha, motor=datos.motor, titulo=datos.titulo,
                           lineas_analizadas=len(datos.lineas), avisos=datos.avisos,
                           nombres_palabra_comun=palabras, duracion=time.time() - t0)


# --------------------------------------------------------------------------- Guardado
def _regex_literal(literal: str) -> str:
    """'Ámbar' -> '\\b[ÁáAa]mbar\\b' (formato de nombres_protegidos.json)."""
    primera = literal[0]
    variantes = {primera.upper(), primera.lower(), _sin_tildes(primera).upper(), _sin_tildes(primera).lower()}
    clase = "".join(sorted(variantes, key=lambda x: (x.lower() != x, x)))
    return rf"\b[{clase}]{re.escape(literal[1:])}\b"


def analizar_y_guardar(juego: str, ruta_juego: str | Path, *, usar_ia: bool = False,
                       modelo_ia: str | None = None, simular: bool = False,
                       motor: str | None = None) -> tuple[Path | None, InformeAnalisis]:
    """Analiza el juego y fusiona el resultado con ``workspace/<juego>/personajes.json``.

    Lo que el usuario haya marcado como ``confirmado`` no se toca. También añade los nombres a
    ``nombres_propios.txt`` y protege los nombres que son palabras en ``nombres_protegidos.json``.
    Con ``simular=True`` no escribe nada y devuelve ``(None, informe)``.
    """
    informe = analizar_juego(ruta_juego, motor, usar_ia=usar_ia, modelo_ia=modelo_ia, juego=juego)
    if simular:
        return None, informe
    if not informe.ficha.personajes:
        informe.avisos.append("No se detectó ningún personaje: no se ha creado personajes.json.")
        return None, informe
    carpeta = config.carpeta_juego(juego, crear=True)
    ruta = carpeta / ARCHIVO_PERSONAJES
    existente = FichaPersonajes.cargar(ruta)
    ficha = existente.fusionar(informe.ficha) if existente is not None else informe.ficha
    ficha.guardar(ruta)
    informe.ficha = ficha

    # nombres_propios.txt (lo usa el Paso 5): añadir sin duplicar
    p_propios = carpeta / "nombres_propios.txt"
    actuales = set()
    if p_propios.exists():
        actuales = {l.strip() for l in p_propios.read_text(encoding="utf-8-sig").splitlines() if l.strip()}
    nuevos = [p.nombre for p in ficha.personajes
              if p.rol != "extra" and p.nombre not in actuales and p.nombre[:1].isalpha()]
    if nuevos:
        previo = p_propios.read_text(encoding="utf-8-sig") if p_propios.exists() else ""
        if previo and not previo.endswith("\n"):
            previo += "\n"
        p_propios.write_text(previo + "\n".join(nuevos) + "\n", encoding="utf-8", newline="\n")

    # nombres_protegidos.json: nombres que son palabras ("Amber" -> no traducir como "Ámbar")
    if informe.nombres_palabra_comun:
        p_prot = carpeta / "nombres_protegidos.json"
        protegidos = config.cargar_json(p_prot, {})
        if isinstance(protegidos, dict):
            cambiado = False
            for nombre, literal in informe.nombres_palabra_comun.items():
                if nombre not in protegidos and literal.casefold() != nombre.casefold():
                    protegidos[nombre] = _regex_literal(literal)
                    cambiado = True
            if cambiado:
                p_prot.write_text(json.dumps(protegidos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                  newline="\n")
    log.info("👥 Ficha de personajes guardada en %s (%s)", ruta, ficha.resumen())
    return ruta, informe
