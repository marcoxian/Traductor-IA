"""Fallos de gramática del español que se ven sin entender la frase (funciones puras).

- ``arreglar_determinantes``: determinante masculino delante de un sustantivo que siempre es femenino
  ("muchos actualizaciones", "un Navidad", "al recepción") -> femenino. Solo con las terminaciones que no
  fallan (-ción, -sión, -dad, -tad, -tud, -umbre): se corrige sin preguntar.
- ``imperativo_negativo_mal``: "Don't pretend" traducido "No finge" (indicativo) o "No finja" (usted). Con
  "tú" el verbo acaba en -s ("No finjas") y con "vosotros" en -éis/-áis/-ís. Solo se detecta: el arreglo
  necesita conjugar, así que se reintenta con una nota.
- ``tartamudeo_como_yo``: "I-It threw her" es un tartamudeo de "It", no "yo"; el modelo pone "Yo... La
  lanzó". Solo se detecta.

No dependen del resto del paquete (las usa ``texto.evaluar_traduccion`` y se pueden probar solas).
"""
from __future__ import annotations

import re

__all__ = ["arreglar_determinantes", "imperativo_negativo_mal", "tartamudeo_como_yo"]

_I = re.IGNORECASE
_L = r"[^\W\d_]"

# --------------------------------------------------------------------------- Determinante + sustantivo
# Terminaciones de sustantivos que son SIEMPRE femeninos (las palabras cortas "dad", "tad" son inglés).
_FEM_SING = r"(?:" + _L + r"{2,}(?:ción|sión|dad|tad|tud)|" + _L + r"+umbre)"
_FEM_PLUR = r"(?:" + _L + r"{2,}(?:ciones|siones|dades|tades|tudes)|" + _L + r"+umbres)"

_A_FEMENINO = {
    # singular
    "el": "la", "un": "una", "este": "esta", "ese": "esa", "aquel": "aquella", "ningún": "ninguna",
    "algún": "alguna", "otro": "otra", "mucho": "mucha", "poco": "poca", "nuestro": "nuestra",
    "vuestro": "vuestra", "demasiado": "demasiada", "primer": "primera",
    "tercer": "tercera", "buen": "buena", "del": "de la", "al": "a la", "todo el": "toda la",
    "cualquier otro": "cualquier otra", "tanto": "tanta", "cuánto": "cuánta",
    "el primer": "la primera", "el tercer": "la tercera", "un primer": "una primera", "un buen": "una buena",
    "un gran": "una gran", "el gran": "la gran", "este gran": "esta gran", "su primer": "su primera",
    "mi primer": "mi primera", "tu primer": "tu primera", "nuestro primer": "nuestra primera",
    "el otro": "la otra", "el mismo": "la misma", "el último": "la última", "el nuevo": "la nueva",
    "un nuevo": "una nueva", "el propio": "la propia", "su propio": "su propia",
    "los otros": "las otras", "los mismos": "las mismas", "los últimos": "las últimas", "los nuevos": "las nuevas",
    "unos nuevos": "unas nuevas", "sus propios": "sus propias",
    # plural
    "los": "las", "unos": "unas", "muchos": "muchas", "pocos": "pocas", "estos": "estas", "esos": "esas",
    "aquellos": "aquellas", "todos los": "todas las", "varios": "varias", "algunos": "algunas",
    "otros": "otras", "nuestros": "nuestras", "vuestros": "vuestras", "tantos": "tantas",
    "demasiados": "demasiadas", "cuántos": "cuántas",
}
_DET_SING = "|".join(sorted((d for d in _A_FEMENINO if d not in ("los", "todos los") and not d.endswith("os")),
                            key=len, reverse=True))
_DET_PLUR = "|".join(sorted((d for d in _A_FEMENINO if d.endswith("os")), key=len, reverse=True))
_ESPACIOS = r"\s+"
_RE_DET_SING = re.compile(rf"(?<!{_L})({_DET_SING.replace(' ', _ESPACIOS)})(\s+)({_FEM_SING})(?!{_L})", _I)
_RE_DET_PLUR = re.compile(rf"(?<!{_L})({_DET_PLUR.replace(' ', _ESPACIOS)})(\s+)({_FEM_PLUR})(?!{_L})", _I)


def _igual_mayusculas(modelo: str, nueva: str) -> str:
    if modelo.isupper() and len(modelo) > 1:
        return nueva.upper()
    if modelo[:1].isupper():
        return nueva[:1].upper() + nueva[1:]
    return nueva


def _a_femenino(m: re.Match) -> str:
    det = m.group(1)
    nueva = _A_FEMENINO.get(re.sub(r"\s+", " ", det.lower()))
    if nueva is None:
        return m.group(0)
    return f"{_igual_mayusculas(det, nueva)}{m.group(2)}{m.group(3)}"


def arreglar_determinantes(traduccion: str) -> str:
    """"muchos actualizaciones" -> "muchas actualizaciones", "un Navidad" -> "una Navidad",
    "al recepción" -> "a la recepción". Solo determinantes pegados al sustantivo."""
    if not traduccion:
        return traduccion
    res = _RE_DET_PLUR.sub(_a_femenino, traduccion)
    return _RE_DET_SING.sub(_a_femenino, res)


# --------------------------------------------------------------------------- Imperativo negativo
# "Don't + verbo" al empezar una frase (no "Don't you...?", que es pregunta). Algunos verbos suelen ser
# "I don't know" sin el "I" ("Don't know any Bruno, mate"): no se miran.
_EN_NO_IMPERATIVO = re.compile(
    r"(?:^|[.!?…]\s+|[\"“(¡¿*]\s*|,\s+(?:just|and|but|so|please)\s+)(?:just\s+|please\s+)?(?:don['’]t|do\s+not)\s+"
    r"(?!(?:you|we|they|I|he|she|it|know|think|care|mind|remember|need|want|have|like|see|get\s+it|"
    r"wanna|feel|believe|recall|understand|blame\s+me)\b)[a-z]+", _I)
_CLITICOS = r"(?:(?:me|te|se|lo|la|le|los|las|les|nos|os)\s+)*"
# "No" al empezar una frase de la traducción, con sus pronombres, y el verbo
_ES_NO_VERBO = re.compile(rf"(?:^|[.!?…:;]\s*|[\"“«(¡¿*]\s*)No\s+{_CLITICOS}({_L}+)", _I)
# Verbos con los que la traducción dice otra cosa válida ("No pasa nada" por "Don't worry about it")
_NO_VERBO_ES = {"hay", "pasa", "importa", "es", "está", "era", "más", "tan", "tanto", "mucho", "todo", "todos",
                "ahora", "aquí", "así", "nunca", "solo", "sólo", "otra", "otro", "vale", "sirve", "hace", "puede",
                "a", "al", "de", "del", "en", "con", "por", "para", "sin", "el", "la",
                "un", "una", "mal", "problema", "gracias", "pienso", "creo", "sé"}
# "Mr. X", "sir", "ma'am": el usted puede estar bien ("No intente engañarme, señor")
_FORMAL_EN = re.compile(r"\b(?:sir|sirs|ma['’]?am|madam|mr|mrs|ms|mister|your\s+(?:majesty|highness|honou?r|grace|"
                        r"excellency)|ladies|gentlemen|officer|customers?|guests?|clients?|passengers?)\b", _I)


def imperativo_negativo_mal(original: str, traduccion: str) -> str | None:
    """Verbo mal puesto en una prohibición ("Don't pretend" -> "No finge"/"No finja"/"No finjan"), o None.

    Con "tú" el verbo de un "No ..." acaba en -s ("No finjas", "No te preocupes"); con "vosotros", en -éis,
    -áis o -ís, que también acaban en -s. Se mira solo el primer "No" de la traducción. Si el inglés trata
    de usted ("sir", "Mr. Smith") no se avisa."""
    if not original or not traduccion or not _EN_NO_IMPERATIVO.search(original) or _FORMAL_EN.search(original):
        return None
    m = _ES_NO_VERBO.search(traduccion)
    if m is None:
        return None
    verbo = m.group(1)
    v = verbo.lower()
    # -s: tú o vosotros; -ar/-er/-ir: infinitivo de una opción de menú ("No mirar")
    if v in _NO_VERBO_ES or v.endswith(("s", "ar", "er", "ir")) or len(v) < 3:
        return None
    return verbo


# --------------------------------------------------------------------------- Tartamudeo "I-It"
# "I-It", "I-If", "I-Is": se repite la primera letra de una palabra que empieza por "I". No vale "I-I'm"
# (ahí sí es "yo").
_EN_TARTAMUDEO_I = re.compile(r"(?<![\w'’-])I-(?!I(?:['’]|\b))(I[a-z]+)\b")
_EN_YO = re.compile(r"(?<![\w-])I(?:['’](?:m|ll|ve|d)\b|\b)(?!-)")
_ES_YO = re.compile(r"(?<!\w)[Yy]o(?!\w)")


def tartamudeo_como_yo(original: str, traduccion: str) -> str | None:
    """"I-It threw her" traducido con "Yo..." (el tartamudeo de "It" leído como "I"). Devuelve la palabra
    tartamudeada ("It") o None. Si el inglés tiene además un "I" de verdad, no se avisa."""
    if not original or not traduccion:
        return None
    m = _EN_TARTAMUDEO_I.search(original)
    if m is None or not _ES_YO.search(traduccion):
        return None
    sin_tartamudeo = _EN_TARTAMUDEO_I.sub(r"\1", original)
    if _EN_YO.search(sin_tartamudeo):
        return None
    return m.group(1)
