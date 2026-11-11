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

__all__ = ["Modismo", "MODISMOS", "terminos", "calcos", "nota_reintento"]

_I = re.IGNORECASE
_POS = r"(?:my|your|his|her|our|their|yer|ur)"
_ELOGIO = (r"(?:hot|perfect|beautiful|gorgeous|amazing|awesome|incredible|great|good|sexy|tight|nice|lovely|"
           r"delicious|best|brilliant|cute|pretty|fine)")


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
)


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
