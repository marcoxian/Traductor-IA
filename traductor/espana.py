"""Vocabulario de Latinoamérica -> español de España (funciones puras, sin dependencias del paquete).

El modelo aprendió parte del vocabulario de traducciones de Latinoamérica. Aquí solo se cambia lo que se
puede cambiar sin entender la frase:

- "enojar" -> "enfadar" en todas sus formas ("no te enojes" -> "no te enfades"). "Enojoso" (molesto) se
  usa también en España: no se toca.
- "lindo/linda" -> "bonito/bonita" ("¡Qué lindo!", "¡Hola, linda!"). Si el original tiene a alguien que se
  llama Linda o Lindo, no se toca.
- "apúrate" -> "date prisa" y las demás formas de "apurarse" con el sentido de ir deprisa, solo si el
  inglés dice "hurry", "rush" o "quick". "Apurado" se queda (en España es "en un apuro").
- "extrañar" -> "echar de menos" solo si el inglés dice "miss" y la forma es claramente un verbo ("te
  extraño", "extraño a mis padres", "voy a extrañarte"). "Extraño" adjetivo (raro) no se toca.

"Ustedes" no se cambia aquí: hace falta cambiar también los verbos ("ustedes son" -> "vosotros sois") y a
veces es respeto. Lo detecta ``texto.evaluar_traduccion`` (problema leve "ustedes", con reintento).
"""
from __future__ import annotations

import re

__all__ = ["a_espanol_de_espana"]

_L = r"[^\W\d_]"


def _igual_mayusculas(modelo: str, nueva: str) -> str:
    if modelo.isupper() and len(modelo) > 1:
        return nueva.upper()
    if modelo[:1].isupper():
        return nueva[:1].upper() + nueva[1:]
    return nueva


# --------------------------------------------------------------------------- enojar -> enfadar
# "enójate" -> "enfádate": la tilde cae en otra sílaba, pero en la misma posición de la raíz.
_ENOJAR = re.compile(rf"(?<!{_L})(en[oó]j)(?!os[oa]s?(?!{_L})|osamente)(?={_L})", re.IGNORECASE)


def _enfadar(m: re.Match) -> str:
    raiz = m.group(1)
    nueva = "enfád" if raiz[2].lower() == "ó" else "enfad"
    return _igual_mayusculas(raiz, nueva)


# --------------------------------------------------------------------------- lindo -> bonito
_LINDO = re.compile(rf"(?<!{_L})lind(o|a|os|as|ísimo|ísima|ísimos|ísimas)(?!{_L})", re.IGNORECASE)
_NOMBRE_LINDA = re.compile(r"\bLind[ao]\b")


def _bonito(m: re.Match) -> str:
    return _igual_mayusculas(m.group(0), "bonit" + m.group(1).lower())


# --------------------------------------------------------------------------- apurarse -> darse prisa
_PRISA_EN = re.compile(r"\b(?:hurr\w*|rush\w*|quick\w*|hasten\w*)\b", re.IGNORECASE)
_APURAR_FORMAS = {
    # imperativos
    "apúrate": "date prisa", "apúrese": "dese prisa", "apúrense": "daos prisa", "apurémonos": "démonos prisa",
    "apuraos": "daos prisa", "apúrale": "date prisa", "apúrenle": "daos prisa",
    # infinitivo y gerundio con pronombre
    "apurarme": "darme prisa", "apurarte": "darte prisa", "apurarse": "darse prisa", "apurarnos": "darnos prisa",
    "apuraros": "daros prisa", "apurándome": "dándome prisa", "apurándote": "dándote prisa",
    "apurándose": "dándose prisa", "apurándonos": "dándonos prisa",
}
_APURAR_SUELTO = re.compile(rf"(?<!{_L})({'|'.join(sorted(_APURAR_FORMAS, key=len, reverse=True))})(?!{_L})",
                            re.IGNORECASE)
# Con el pronombre delante: "te apuras" -> "te das prisa", "si no se apura" -> "si no se da prisa".
_DAR = {"o": "doy", "as": "das", "a": "da", "amos": "damos", "áis": "dais", "an": "dan",
        "é": "di", "aste": "diste", "ó": "dio", "asteis": "disteis", "aron": "dieron",
        "aré": "daré", "arás": "darás", "ará": "dará", "aremos": "daremos", "aréis": "daréis", "arán": "darán",
        "aría": "daría", "arías": "darías", "aríamos": "daríamos", "arían": "darían",
        "e": "dé", "es": "des", "emos": "demos", "éis": "deis", "en": "den"}
_FINALES_APURAR = "|".join(sorted(_DAR, key=len, reverse=True))
_APURAR_CON_PRONOMBRE = re.compile(
    rf"(?<!{_L})(?P<pron>me|te|se|nos|os)\s+apur(?P<fin>{_FINALES_APURAR})(?!{_L})", re.IGNORECASE)


def _darse_prisa(m: re.Match) -> str:
    return f"{m.group('pron')} {_igual_mayusculas(m.group(0)[len(m.group('pron')) + 1:], _DAR[m.group('fin').lower()])} prisa"


# --------------------------------------------------------------------------- extrañar -> echar de menos
# "miss" verbo; no "Miss Ana" (señorita) ni "miss the bus".
_MISS_EN = re.compile(r"\b[Mm]iss(?:es|ed|ing)?\b(?!\s+[A-Z])(?!\s+(?:the\s+)?(?:bus|train|shot|chance|"
                      r"target|mark|point|deadline|flight|opportunity)\b)")
_ECHAR = {"o": "echo", "as": "echas", "a": "echa", "amos": "echamos", "áis": "echáis", "an": "echan",
          "é": "eché", "aste": "echaste", "ó": "echó", "asteis": "echasteis", "aron": "echaron",
          "aba": "echaba", "abas": "echabas", "ábamos": "echábamos", "aban": "echaban",
          "aré": "echaré", "arás": "echarás", "ará": "echará", "aremos": "echaremos", "arán": "echarán",
          "aría": "echaría", "arías": "echarías", "aríamos": "echaríamos", "arían": "echarían",
          "e": "eche", "es": "eches", "emos": "echemos", "en": "echen", "ado": "echado", "ando": "echando"}
_FINALES_EXTRANAR = "|".join(sorted(_ECHAR, key=len, reverse=True))
_CLITICO = r"(?:me|te|lo|la|los|las|le|les|nos|os)"
_INTENSIDAD = r"(?:mucho|muchísimo|tanto|un\s+montón|horrores|demasiado|bastante)"
# "te extraño (mucho)", "lo he extrañado", "extraño a mis padres", "extraño mucho a..."
_EXTRANAR_VERBO = re.compile(
    rf"(?<!{_L})(?P<ante>{_CLITICO}\s+(?:(?:he|has|ha|hemos|habéis|han|había|habías|habíamos|habían)\s+)?)?"
    rf"(?P<verbo>extrañ(?P<fin>{_FINALES_EXTRANAR}))(?!{_L})(?P<int>\s+{_INTENSIDAD}(?!{_L}))?"
    rf"(?P<a>(?=\s+a(?:l)?\s))?",
    re.IGNORECASE)
# "voy a extrañarte", "extrañándola": el pronombre va pegado.
_EXTRANAR_PEGADO = re.compile(rf"(?<!{_L})extrañ(?P<fin>ar|ando|ándo)(?P<pron>me|te|lo|la|los|las|le|les|nos|os)"
                              rf"(?!{_L})(?P<int>\s+{_INTENSIDAD}(?!{_L}))?", re.IGNORECASE)


# "la/lo/los/las" también son artículos ("la extraña esfera"): con ellos delante solo es verbo si detrás no
# viene otra palabra (o viene una de estas).
_ARTICULO = re.compile(r"^(?:la|las|lo|los)\s+$", re.IGNORECASE)
_TRAS_VERBO = re.compile(r"\s*(?:[.,;:!?…)\"»”'~]|$|\s+(?:y|e|o|pero|cuando|desde|ya|también|cada|todos|todas|"
                         r"aquí|ahí|ahora|tanto)\b)", re.IGNORECASE)
# "me extraña" / "nos extraña" suele ser "me sorprende" (o el modelo ya lo ha traducido al revés: "I miss it"
# -> "me extraña"), y "extrañarse de" es sorprenderse: no se tocan.
_SORPRESA = re.compile(r"^(?:me|nos)\s", re.IGNORECASE)
_DE = re.compile(r"\s+de\b", re.IGNORECASE)


def _echar_de_menos(m: re.Match) -> str:
    ante, intensidad = m.group("ante"), m.group("int")
    if not (ante or m.start("a") >= 0):
        return m.group(0)  # "una extraña sensación", "Extraño..." suelto: es el adjetivo
    if (ante and _SORPRESA.match(ante)) or _DE.match(m.string, m.end()):
        return m.group(0)
    if ante and _ARTICULO.match(ante) and not (intensidad or m.start("a") >= 0) \
            and not _TRAS_VERBO.match(m.string, m.end("verbo")):
        return m.group(0)
    forma = _igual_mayusculas(m.group("verbo"), _ECHAR[m.group("fin").lower()])
    intensidad = f" {intensidad.strip()}" if intensidad else ""
    return f"{ante or ''}{forma}{intensidad} de menos"


def _echar_de_menos_pegado(m: re.Match) -> str:
    base = "echar" if m.group("fin").lower() == "ar" else "echándo"  # "extrañandote" sin tilde también
    forma = _igual_mayusculas(m.group(0), base + m.group("pron").lower())
    intensidad = f" {m.group('int').strip()}" if m.group("int") else ""
    return f"{forma}{intensidad} de menos"


# --------------------------------------------------------------------------- coger -> follar
# En Latinoamérica "coger" es follar; en España es tomar. Solo se cambia si el inglés habla de sexo
# ("fuck", "bang", "screw") y no de tomar algo ("take", "grab", "catch", "pick up"): "¡Cógeme!" -> "¡Fóllame!".
_SEXO_EN = re.compile(r"\b(?:fuck(?:s|ed|ing|in['’]?)?|bang(?:s|ed|ing)?|screw(?:s|ed|ing)?|shag\w*|hump\w*)\b",
                      re.IGNORECASE)
_TOMAR_EN = re.compile(r"\b(?:take|takes|took|taken|taking|grab\w*|catch\w*|caught|pick\w*|hold\w*|seize\w*|"
                       r"snatch\w*|(?:get|gets|got)(?!\s+(?:\w+\s+)?(?:fucked|banged|screwed|laid)))\b",
                       re.IGNORECASE)
# terminación de "coger" -> la de "follar" (sin pronombres pegados). "coj-" es la raíz antes de a/o.
_FOLLAR = {
    "er": "ar", "erse": "arse", "iendo": "ando", "iéndo": "ándo", "ido": "ado", "ida": "ada", "idos": "ados",
    "idas": "adas", "e": "a", "es": "as", "en": "an", "emos": "amos", "éis": "áis", "í": "é", "iste": "aste",
    "ió": "ó", "imos": "amos", "isteis": "asteis", "ieron": "aron", "ía": "aba", "ías": "abas", "íamos": "ábamos",
    "íais": "abais", "ían": "aban", "eré": "aré", "erás": "arás", "erá": "ará", "eremos": "aremos",
    "eréis": "aréis", "erán": "arán", "ería": "aría", "erías": "arías", "eríamos": "aríamos", "erían": "arían",
    "iera": "ara", "ieras": "aras", "ieran": "aran", "ed": "ad", "o": "o", "a": "e", "as": "es", "an": "en",
    "amos": "emos", "áis": "éis",
}
_FINALES_COGER = "|".join(sorted(_FOLLAR, key=len, reverse=True))
_PRONOMBRES_PEGADOS = r"(?:me|te|se|lo|la|le|los|las|les|nos|os)*"
_COGER = re.compile(rf"(?<!{_L})(c)([oó])(g|j)(?P<fin>{_FINALES_COGER})(?P<pron>{_PRONOMBRES_PEGADOS})(?!{_L})",
                    re.IGNORECASE)


def _follar(m: re.Match) -> str:
    raiz, fin = m.group(3).lower(), m.group("fin").lower()
    # "coj-" solo va delante de a/o ("cojo", "coja"); "cog-" delante de e/i ("coge", "cogió")
    if (raiz == "j") != (fin[:1] in ("a", "o", "á")):
        return m.group(0)
    if raiz == "g" and fin == "o":
        return m.group(0)  # "cogo" no existe
    nuevo = "f" + m.group(2).lower() + "ll" + _FOLLAR[fin] + m.group("pron").lower()
    return _igual_mayusculas(m.group(0), nuevo)


def coger_a_follar(traduccion: str, original: str) -> str:
    """"coger" con sentido sexual -> "follar" en todas sus formas, si el inglés habla de sexo y no de tomar."""
    if not traduccion or not original or not _SEXO_EN.search(original) or _TOMAR_EN.search(original):
        return traduccion
    res = re.sub(r"\buna\s+buena\s+cogida\b", lambda m: _igual_mayusculas(m.group(0), "un buen polvo"),
                 traduccion, flags=re.IGNORECASE)
    return _COGER.sub(_follar, res)


# --------------------------------------------------------------------------- Todo junto
def a_espanol_de_espana(traduccion: str, original: str = "") -> str:
    """Cambia el vocabulario de Latinoamérica que se puede cambiar sin riesgo (ver el docstring del módulo).
    ``original`` es el inglés: decide "apurarse" (si dice "hurry") y "extrañar" (si dice "miss")."""
    if not traduccion:
        return traduccion
    res = _ENOJAR.sub(_enfadar, traduccion)
    if not _NOMBRE_LINDA.search(original or ""):
        res = _LINDO.sub(_bonito, res)
    if original and _PRISA_EN.search(original):
        res = _APURAR_SUELTO.sub(lambda m: _igual_mayusculas(m.group(0), _APURAR_FORMAS[m.group(0).lower()]), res)
        res = _APURAR_CON_PRONOMBRE.sub(_darse_prisa, res)
    if original and _MISS_EN.search(original):
        res = _EXTRANAR_VERBO.sub(_echar_de_menos, res)
        res = _EXTRANAR_PEGADO.sub(_echar_de_menos_pegado, res)
    if original:
        res = coger_a_follar(res, original)
    return res
