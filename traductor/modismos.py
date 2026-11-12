"""Frases hechas y palabrotas que el modelo traduce palabra por palabra (funciones puras).

"Busting my ass" no es "darme una patada en el culo" sino "matarme a trabajar"; "damn good" no es "maldita
buena" sino "buenísima"; "a hell of a race" no es "una carrera de mierda" sino "menuda carrera". Cada
modismo tiene:

- ``patron``: cuándo aparece en el inglés.
- ``sentido``: lo que significa en España. Si ``pista`` es True, entra en el GLOSARIO OBLIGATORIO de la
  frase (prevención: el modelo lo ve antes de traducir). Solo se ponen como pista los que el modelo falla
  casi siempre; los demás solo se comprueban (la clave de caché de esas frases no cambia).
- ``mal``: la traducción literal que delata el fallo. Si aparece, ``calcos`` lo avisa y el traductor
  reintenta con una nota (detección).
- ``bien``: (opcional) lo que TIENE que aparecer ("drop of blood" -> "gota").

Las frases de las pruebas son inventadas; los patrones salen de fallos vistos en juegos reales.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Modismo", "MODISMOS", "terminos", "calcos", "nota_reintento", "arreglar"]

_I = re.IGNORECASE
_POS = r"(?:my|your|his|her|our|their|yer|ur)"
_ELOGIO = (r"(?:hot|perfect|beautiful|gorgeous|amazing|awesome|incredible|great|good|sexy|tight|nice|lovely|"
           r"delicious|best|brilliant|cute|pretty|fine)")
# Lo que puede rodear una frase suelta sin cambiar su sentido: etiquetas ({i}, {w}), códigos (\C[2], \N[1]),
# comillas, asteriscos y puntos suspensivos al principio ("... Later, bro!").
_ANTES = r"(?:\{[^}]*\}|\\[A-Za-z]+(?:\[[^\]]*\]|<[^>]*>)?|[\s\"'‘’“”*(]|\.\.\.|…)*"
_DESPUES = r"(?:\{[^}]*\}|\\[A-Za-z]+(?:\[[^\]]*\]|<[^>]*>)?|[\s\"'’”*)])*"
# A quién se despide: [mc], \N[1], un nombre con mayúscula ("Later, Ana.") o un apelativo ("Later, bro.").
_VOCATIVO = (r"(?:\[\w+\]|\\[A-Za-z]+\[\d+\]|(?-i:[A-Z][\w'’-]*)(?:\s+(?-i:[A-Z][\w'’-]*))?|"
             r"bro|buddy|dude|man|guys|girls?|babe|kids?|sis|pal|mate|honey|sweetie|everyone|everybody|folks|"
             r"all|then)")


@dataclass(frozen=True)
class Modismo:
    clave: str                  # cómo aparece en el glosario ("busting my ass")
    patron: re.Pattern          # en el inglés
    sentido: str                # lo que significa en España
    mal: re.Pattern | None = None   # traducción literal que delata el fallo
    bien: re.Pattern | None = None  # lo que tiene que aparecer en la traducción
    pista: bool = False         # ¿se pone en el glosario de la frase antes de traducir?


def _re(patron: str) -> re.Pattern:
    return re.compile(patron, _I)


MODISMOS: tuple[Modismo, ...] = (
    Modismo("busting my ass", _re(rf"\bbust(?:s|ed|ing)?\s+{_POS}\s+(?:ass|butt|balls|hump)\b"),
            "matarse a trabajar, dejarse la piel (no es una patada)",
            mal=_re(r"\bpatadas?\b"), pista=True),
    Modismo("kick your ass", _re(rf"\bkick(?:s|ed|ing)?\s+{_POS}\s+(?:\w+\s+)?(?:ass|butt)\b"),
            "darle una paliza a alguien", mal=_re(r"\bpatadas?\s+en\s+(?:el|tu|su|mi)\s+culo\b")),
    Modismo("kick ass", _re(r"\bkick(?:s|ed|ing)?[\s-]+(?:some\s+)?ass\b"),
            "arrasar, ser la leche (en positivo)", mal=_re(r"\bpatadas?\s+(?:en\s+el\s+)?culo")),
    Modismo("damn good", _re(r"\b(?:damn(?:ed)?|fucking|bloody)\s+(?:good|well|fine|great)\b"),
            "buenísimo, de puta madre, jodidamente bueno",
            mal=_re(r"\bmaldit[oa]s?\s+(?:buen[oa]?s?|bien|gran(?:de)?s?|mejor(?:es)?)\b"), pista=True),
    Modismo("a hell of a", _re(r"\bhell\s+of\s+an?\b"),
            "menudo/menuda..., un ... de la leche (en positivo, no 'de mierda' ni 'demoníaco')",
            mal=_re(r"\bdemon[ií]ac[oa]s?\b|\bde\s+mierda\b|\bmaldit[oa]s?\s+buen"),
            pista=True),
    Modismo("fucking (en positivo)", _re(rf"\bfucking\s+{_ELOGIO}\b|\b{_ELOGIO}\s+fucking\b"),
            "puto/jodidamente en positivo ('su puto cuerpo perfecto'), nunca 'de mierda'",
            mal=_re(r"\bde\s+mierda\b"), pista=True),
    Modismo("fuck! (exclamación)", _re(r"^(?:\{[^}]*\}|[^\w{])*(?:(?:oh|ah|aw|ugh),?\s+)?fu+ck(?:ing\s+hell)?"
                                       r"(?:\{[^}]*\}|[^\w{])*$"),
            "¡Joder! (exclamación, no es una orden)", mal=_re(r"\bf[oó]ll\w*|\bc[oó]g\w*|\bc[oó]j(?!ones)\w*"),
            pista=True),
    Modismo("go fuck yourself", _re(r"\b(?:go\s+)?fuck\s+(?:yourself|yourselves|himself|herself|themselves|off)\b"),
            "vete a la mierda, que te jodan, que le den",
            mal=_re(r"\bc[oó]g\w*|\bcoj\w*|\bf[oó]llate\s+a\s+ti\b|\bfollarse\s+a\s+s[ií]\b|\ba\s+s[ií]\s+mism[oa]\b|"
                    r"\bvay\w*\s+a\s+follar(?:se|te)\b"),
            pista=True),
    Modismo("can't be fucked", _re(r"\bcan['’]?t\s+be\s+(?:fucked|bothered|arsed|assed)\b"),
            "no tener ganas de, pasar de ('paso de correr ahora')",
            mal=_re(r"\bc[oó]gid[oa]\b|\bfollad[oa]\b|\bmolestad[oa]\b"), pista=True),
    Modismo("shut it", _re(r"\bshut\s+it\b"), "cállate (ya), corta el rollo", mal=_re(r"\bc[aá]llalo\b")),
    Modismo("not at all", _re(r"\bnot\s+at\s+all\b"),
            "para nada, en absoluto (sin 'no' detrás)", mal=_re(r"\ben\s+absoluto,?\s+no\b|\bno\s+en\s+todo\b")),
    Modismo("every last drop", _re(r"\b(?:every|each|last|single)\s+(?:last\s+|single\s+)?drops?\s+of\b|\bdrops?\s+of\s+(?:my|your|his|her|their|our|blood|water|sweat|rain|cum)\b"),
            "gota (de sangre, de agua...)", bien=_re(r"\bgot(?:a|as|ita|itas)\b"), pista=True),
    Modismo("pain in the ass", _re(r"\bpain\s+in\s+(?:the|my|your|his|her)\s+(?:ass|butt|neck|arse)\b"),
            "un coñazo, un grano en el culo, un pesado",
            mal=_re(r"\bdolor\s+(?:en|de)\s+(?:el|mi|tu|su)\s+(?:culo|trasero|cuello)\b")),
    Modismo("my bad", _re(r"\bmy\s+bad\b"), "culpa mía, error mío", mal=_re(r"\bmi\s+mal[oa]?\b")),
    Modismo("break a leg", _re(r"\bbreak\s+a\s+leg\b"), "mucha suerte",
            mal=_re(r"\bromp\w*\s+(?:una|la)\s+pierna\b")),
    Modismo("screw it", _re(r"\bscrew\s+(?:it|that|this)\b"), "a la mierda, que le den",
            mal=_re(r"\batornill\w*|\btornillo")),
    Modismo("I'm screwed", _re(r"\b(?:I['’]m|we['’]re|you['’]re|he['’]s|she['’]s|they['’]re|so|totally|completely)\s+screwed\b"),
            "estar jodido", mal=_re(r"\batornillad\w*")),
    Modismo("out of my league", _re(rf"\bout\s+of\s+{_POS}\s+league\b"),
            "demasiado para mí/ti, no estar a su altura", mal=_re(r"\bligas?\b")),
    Modismo("are you kidding me", _re(r"\bkidding\s+me\b|\byou\s+kidding\b"),
            "¿me tomas el pelo?, ¿en serio?", mal=_re(r"\bniñ[oa]s?\b|\bbromeando\s+conmigo\b")),
    Modismo("pissed off", _re(r"\bpiss(?:ed|es|ing)?\s+(?:\w+\s+)?off\b|\bpissed\b(?!\s+(?:on|in|myself|himself|herself))"),
            "cabreado, mosqueado, cabrear ('piss off' a secas = lárgate)", mal=_re(r"\bmead[oa]\b|\borina\w*|\bmeó\b")),
    Modismo("blow my mind", _re(rf"\bblow\w*\s+{_POS}\s+mind\b|\bmind[\s-]+blowing\b"),
            "alucinar, flipar, dejar sin palabras", mal=_re(r"\bexplot\w*\s+(?:la|mi|tu|su)\s+mente\b|\bsopl\w*")),
    # Respuesta a "gracias": el modelo la tradujo mal 9 de cada 10 veces ("Eres bienvenida", "Está bien",
    # "¡Bienvenido!"). Solo cuenta si detrás viene un signo o el final ("You're welcome, Ana."): "You're
    # welcome to stay" y "You're always welcome here" sí son "bienvenido".
    Modismo("you're welcome", _re(r"\byou(?:['’]re|\s+are)\s+(?:so\s+|very\s+|most\s+|more\s+than\s+)?welcome\b"
                                  r"(?=\s*(?:$|[.!?,~…\"'’”*{\\\-—]))"),
            "de nada, no hay de qué (respuesta a 'gracias'; no es 'bienvenido')",
            bien=_re(r"\bde\s+nada\b|\bno\s+hay\s+(?:de|por)\s+qu[eé]\b|\bcuando\s+quieras\b|\bun\s+placer\b|"
                     r"\bcon\s+(?:mucho\s+)?gusto\b|\bfaltar[ií]a\s+m[aá]s\b|\bpara\s+(?:eso|servir\w*)\b|"
                     r"\bno\s+es\s+nada\b"),
            pista=True),
    # "Later." / "Later, bro!" como frase entera es una despedida; el modelo pone casi siempre "Después".
    # No cuenta "Later..." (salto de tiempo: "Más tarde..."), "Later?" ni "Later today".
    Modismo("later (despedida)",
            _re(rf"^{_ANTES}(?:(?:ok(?:ay)?|alright|all\s+right|right|yeah|yep|well|anyway|cool|bye)[,.!]*\s+)?"
                rf"later,?\s*(?:{_VOCATIVO}\s*)?(?:!+|\.(?!\.)|~)?{_DESPUES}$"),
            "Hasta luego, Nos vemos, Luego (no es 'Después')",
            mal=_re(r"\bdespu[eé]s\b|\bdesp[ií]d\w*"),
            bien=_re(r"\bluego\b|\bnos\s+vemos\b|\bm[aá]s\s+tarde\b|\badi[oó]s\b|\bchao\b|"
                     r"\bhasta\s+(?:pronto|la\s+vista|otra|ma[ñn]ana)\b"),
            pista=True),
)

# Para arreglar en código lo que los reintentos no arreglan (ver ``arreglar``).
_LATER = next(m for m in MODISMOS if m.clave == "later (despedida)")
_WELCOME = next(m for m in MODISMOS if m.clave == "you're welcome")
_LATER_SIN_NADA = _re(rf"^{_ANTES}later\.?{_DESPUES}$")       # "Later." a secas: despedida o "¿cuándo?"
_DESPUES_SUELTO = re.compile(r"\b([Dd])espu[eé]s\b(?!\s+de\b)")
_SOLO_WELCOME = _re(rf"^{_ANTES}(?:\w+[.!]+\s+)?you(?:['’]re|\s+are)\s+(?:so\s+|very\s+|most\s+)?welcome,?\s*"
                    rf"(?:{_VOCATIVO}\s*)?[.!]*{_DESPUES}$")
# Inicio de frase: principio, tras . ! ? … o tras ¡, comillas, etiquetas y códigos.
_INICIO = r"(?:^|(?<=[.!?…¡\"'“‘*}\]>])|(?<=[.!?…]\s))"
_ERES_BIENVENIDO = re.compile(
    _INICIO + r"(?:(?:t[uú]|usted)\s+)?(?:eres|es|est[aá]s|est[aá]n?|te\s+est[aá]s)\s+(?:muy\s+)?bienvenid[oa]s?\b",
    re.IGNORECASE)
_BIENVENIDO_SOLO = re.compile(_INICIO + r"(?:bienvenid[oa]s?|est[aá]\s+bien)\b(?=\s*[,.!…]|\s*$)", re.IGNORECASE)


def arreglar(original: str, traduccion: str) -> str:
    """Arreglos seguros de dos frases hechas, por si los reintentos no bastan (si no aplica, no cambia nada):

    - "Later, Ana!" -> "¡Después, Ana!" pasa a "¡Hasta luego, Ana!". "Later." a secas pasa a "Luego.", que
      vale como despedida y como respuesta a "¿cuándo?". "Después de eso" no se toca.
    - "You're welcome" -> "Eres bienvenida" (al principio de una frase) pasa a "De nada". "Está bien" o
      "¡Bienvenido!" solo se cambian si el original no dice nada más ("Ha! You're welcome, Ana!").
    """
    if not original or not traduccion:
        return traduccion
    r = traduccion
    if _LATER.patron.search(original):
        sustituto = "luego" if _LATER_SIN_NADA.search(original) else "hasta luego"
        r = _DESPUES_SUELTO.sub(lambda m: (sustituto[0].upper() if m.group(1) == "D" else sustituto[0])
                                + sustituto[1:], r)
    if _WELCOME.patron.search(original) and not _WELCOME.bien.search(r):
        r = _ERES_BIENVENIDO.sub("De nada", r)
        if _SOLO_WELCOME.search(original):
            r = _BIENVENIDO_SOLO.sub("De nada", r)
    return r


def terminos(texto: str, ya: list[tuple[str, str]] | tuple = ()) -> list[tuple[str, str]]:
    """Modismos de la frase que van al glosario obligatorio (solo los de ``pista``), sin repetir lo que ya
    está. Vacío si la frase no tiene ninguno: la clave de caché de esa frase no cambia."""
    if not texto:
        return []
    ya_claves = {en.casefold() for en, _ in ya}
    return [(m.clave, m.sentido) for m in MODISMOS
            if m.pista and m.clave.casefold() not in ya_claves and m.patron.search(texto)]


def calcos(original: str, traduccion: str) -> list[Modismo]:
    """Modismos del inglés traducidos palabra por palabra (vacío = bien o no hay ninguno)."""
    if not original or not traduccion:
        return []
    fallos = []
    for m in MODISMOS:
        if not m.patron.search(original):
            continue
        if (m.mal is not None and m.mal.search(traduccion)) or (m.bien is not None and not m.bien.search(traduccion)):
            fallos.append(m)
    return fallos


def nota_reintento(fallos: list[Modismo]) -> str:
    """Nota para el reintento: qué significa cada modismo que salió literal."""
    if not fallos:
        return ""
    partes = [f"'{m.clave}' significa: {m.sentido}" for m in fallos]
    return "Frases hechas que no se traducen palabra por palabra: " + "; ".join(partes) + "."
