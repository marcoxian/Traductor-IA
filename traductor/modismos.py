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

# "Fuck" de sexo frente a "fuck" de palabrota. Ante la duda se toma por sexo (no se avisa): solo se busca
# "follar" en frases donde el inglés maldice sin hablar de sexo ("I was fucking right", "the fucking car").
_SEXO_VOCAB = (r"\b(?:sex\w*|cocks?|dicks?|puss(?:y|ies)|cunts?|cum\w*|horny|naked|nude|tits|titties|boobs?|"
               r"nipples?|orgasm\w*|moan\w*|clit\w*|condoms?|penis|vagina|bang(?:s|ed|ing)?|rail(?:s|ed|ing)|"
               r"blowjobs?|handjobs?|bj|creampie|anal|threesome|sluts?|whores?|naughty|kinky|lewd|"
               r"inside\s+(?:me|you|her|him)|ride\s+(?:me|you|him|her|it)|in\s+(?:my|your|her|his)\s+(?:ass|mouth))\b")
_FUCK = r"fu+ck(?:s|ed|ing|in['’])?"
_FUCK_SEXO = (
    # con objeto: "fuck me", "fucking her", "fucked Ana", "fuck the first woman", "fuck [mc]"
    rf"\b{_FUCK}(?:\s|…|\.\.\.)+(?:me|you|ya|him|her|them|us|each\s+other|someone|somebody|anyone|anybody|everyone|"
    rf"every\w*|my|your|his|their|our|a|an|the|some|girls?|women|guys?|men)\b|"
    r"\b(?:is|was|were|are|am|be|been|['’]s|['’]re)\s+fucking\s+(?:that|this|those|these)\b|"
    r"\b(?:is|was|were|are|am|be|been|['’]s|['’]re)\s+fucking\s+(?=(?:in|on|at|for|all|like|again|while|when|every)\b)|"
    r"\b(?:who|that|women|girls|guys|men|people)\s+(?:\w+\s+){0,3}fucked\b(?!\s+(?:up|off|around))|"
    rf"\b{_FUCK}\s+(?:\[\w+\]|(?-i:[A-Z][a-z]))|"
    # sin objeto: "want to fuck", "let's fuck", "we fucked", "get fucked", "fucked like mad"
    r"\b(?:to|wanna|gonna|let['’]?s|lets|will|would|could|can|should|must|might|did|never|we|they|you|i|he|she)"
    r"\s+(?:\w+\s+)?fuck(?:ed)?\b(?!\s+(?:around|up|off|with|over|it|that|this|yourself|yourselves|himself|herself|"
    r"themselves))|"
    r"\b(?:get|gets|got|getting|be|been|being)\s+fucked\b(?!\s+up)|"
    rf"\b{_FUCK}\s+(?:like|hard|harder|deeper|rough|senseless|silly|all\s+night)\b|"
    # sustantivo: "a good fuck", "fuck buddy", "hate-fucked", "much fucking", "start fucking!"
    r"\b(?:good|great|quick|amazing|luxurious)\s+fuck\b|\bfuck[\s-]*(?:buddy|buddies|toy|doll|boy|girl|fest)\w*|"
    r"\bhate[\s-]fuck\w*|\b(?:much|more|less|some|any|good|great|love|enjoy|about|without)\s+fucking\b|"
    r"\b(?:start|stop|keep|go|be|been|was|were|are|is|am)\s+fucking\b(?=\s*(?:[,.!?…\[{]|$))")
_LIO = r"\b(?:mess|chaos|fuss|ruckus|commotion|racket|shitshow|clusterfuck)\b"


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
    Modismo("fuck! (exclamación)", _re(r"^(?:\{[^}]*\}|[^\w{])*(?:(?:oh|ah|aw|ugh),?\s+)?(?:fu+cking\s+)?fu+ck"
                                       r"(?:ing\s+hell|ing\s+fuck)?(?:\{[^}]*\}|[^\w{])*$"),
            "¡Joder! (exclamación, no es una orden)",
            mal=_re(r"\bf[oó]ll\w*|\bc[oó]g\w*|\bc[oó]j(?!ones)\w*|\bmamad\w*"),
            # "FUUUCK!" -> "¡FUEEERROOOO!": sin ninguna palabrota de España también es un fallo
            bien=_re(r"\bjod\w*|\bmierd\w*|\bhostia\w*|\bco[ñn]o+\b|\bme\s+cago\b|\bmaldit[oa]\b|\bmaldici[oó]n\b|"
                     r"\bputa\b|\bostra+s\b"),
            pista=True),
    Modismo("holy fuck", _re(r"\bholy\s+(?:fu+ck\w*|shit+|crap)\b"), "¡Hostia!, ¡Joder!, ¡La hostia!",
            mal=_re(r"\bsant[oa]s?\s+(?:puta|mierda|joder)\w*|\bsagrad[oa]\s+mierda\b"), pista=False),
    Modismo("fuck yes", _re(r"\bfu+ck(?:ing)?[\s,!.]+(?:yes+|yeah+|yea|yep)\b"), "¡Joder, sí!, ¡Sí, joder!, ¡Y tanto!",
            mal=_re(r"\bf[oó]ll\w*[\s,!¡.]*s[ií]+\b"), pista=True),
    Modismo("go fuck yourself", _re(r"\b(?:go\s+)?fuck\s+(?:yourself|yourselves|himself|herself|themselves|off)\b"),
            "vete a la mierda, que te jodan, que le den",
            mal=_re(r"\bc[oó]g\w*|\bcoj\w*|\bf[oó]ll\w*|\ba\s+s[ií]\s+mism[oa]\b"),
            pista=True),
    # "fucked this whole thing up"; no "shut the fuck up" ni "fucking me close up"
    Modismo("fuck up", _re(rf"(?<!\bthe\s)\b{_FUCK}\s+(?:(?:it|this|that|these|those|things?|everything|me|you|him|her|"
                           r"us|them|my|your|his|our|their|the|a|an|whole|entire|stuff|plan|job|life)\s+){0,3}up\b|"
                           r"(?<!\bthe\s)\bfuck[\s-]?ups?\b"),
            "cagarla, joderla, joder algo ('fucked up' = jodido, hecho polvo; no es sexo)",
            mal=_re(r"\bf[oó]ll\w*"), pista=True),
    Modismo("eye-fucking", _re(r"\beye[\s-]?fuck\w*|\bfuck\w*\s+(?:\w+\s+){0,3}with\s+(?:her|his|their|your|my)\s+eyes\b"),
            "comerse con los ojos (a alguien)", mal=_re(r"\bf[oó]ll\w*"), pista=True),
    Modismo("fuck around", _re(rf"\b{_FUCK}\s+around\b"),
            "hacer el tonto, perder el tiempo, tontear (si habla de sexo: acostarse con cualquiera)", pista=True),
    # "Fuck" de palabrota (sin sexo en la frase) traducido "follar" o "follón": "I was fucking right" ->
    # "Yo estaba follando", "the fucking desert" -> "el follón del desierto", "Fucking do it!" -> "¡Fóllalo!".
    Modismo("fuck (palabrota, no sexo)",
            re.compile(rf"^(?!.*{_SEXO_VOCAB})(?!.*(?:{_FUCK_SEXO}))(?!.*{_LIO})(?=.*\bfu+ck)", re.I | re.S),
            "aquí 'fuck/fucking' es una palabrota, no sexo: 'joder', 'puto/a' (delante del nombre), 'de los "
            "cojones' o nada; nunca 'follar' ni 'follón'",
            mal=_re(r"\bf[oó]ll\w*")),
    Modismo("fucking + verbo", _re(r"\b(?:fucking|fuckin['’]?)\s+(?:kill|hate|murder|destroy|end|hurt|smash|punch|"
                                   r"beat|break|ruin|strangle)\w*"),
            "intensificador ('lo mato, te lo juro', 'lo odio, joder'); 'de puta madre' es 'genial'",
            mal=_re(r"\bde\s+puta\s+madre\b")),
    Modismo("asshole", re.compile(r"^(?!.*\b(?:son\s+of\s+a|sonofa|motherfuck\w*|bastards?)\b)(?=.*\bassholes?\b)",
                                  re.I | re.S),
            "gilipollas, capullo, cabrón (no 'hijo de puta' ni 'puta')",
            mal=_re(r"\bhij[oa]s?\s+de\s+puta\b|\bputa\b|\bputas\b"), pista=True),
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
    # "It's not like that" (niega lo que el otro insinúa): el modelo puso "No es así de fácil" en 7 de 40
    # frases de un juego, aunque el inglés no habla de nada fácil.
    Modismo("it's not like that",
            re.compile(r"^(?!.*\b(?:easy|easier|simple|simpler)\b).*\bnot\s+like\s+that\b", _I),
            "no es eso, no es lo que piensas, no es lo que parece",
            mal=_re(r"\bas[ií]\s+de\s+f[aá]cil\b|\bno\s+es\s+como\s+eso\b")),
    # "rack" del cuerpo ("nice rack", "her rack") son las tetas, no la cadera ni la barriga.
    Modismo("rack (tetas)",
            _re(rf"\b(?:nice|good|great|best|better|glorious|amazing|huge|big|perfect|that|an?|{_POS}|"
                r"[A-Z]\w+['’]s)\s+rack\b(?!\s+of\b)"),
            "tetas, delantera (parte del cuerpo)",
            mal=_re(r"\bcaderas?\b|\bpanzas?\b|\bbarrigas?\b")),
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
# "FUCK!" / "{b}FUUUCK!" como frase entera (sin "oh", "fucking hell"...): la única palabra es la palabrota
_EXCLAMACION = next(m for m in MODISMOS if m.clave == "fuck! (exclamación)")
_FUCK_SOLO = _re(r"^(?:\{[^}]*\}|[^\w{])*(fu+ck)((?:\{[^}]*\}|[^\w{])*)$")
_ETIQUETA = re.compile(r"\{[^}]*\}")
# "It's not like that" -> "No es así de fácil" / "no es como eso": el reintento no lo arregla (el modelo lo repite)
_NO_ES_ASI = next(m for m in MODISMOS if m.clave == "it's not like that")
_ASI_DE_FACIL = re.compile(r"\b([Nn])o\s+es\s+(?:as[ií]\s+de\s+f[aá]cil|como\s+eso)\b")


def _joder_como(original: str) -> str | None:
    """"FUUUCK!" -> "¡JODEEER!", "Fuck..." -> "Joder...", "fuck?!" -> "¡¿joder?!" (None si no es la exclamación
    sola). Tantas "e" como "u" tiene el inglés si la alarga, y en mayúsculas si el inglés va en mayúsculas."""
    m = _FUCK_SOLO.search(original)
    if not m:
        return None
    palabra, detras = m.group(1), _ETIQUETA.sub("", m.group(2))
    us = len(palabra) - 3
    joder = "jod" + ("e" * us if us > 1 else "e") + "r"
    if palabra.isupper():
        joder = joder.upper()
    elif palabra[0].isupper():
        joder = joder.capitalize()
    signos = re.sub(r"[^!?.…]", "", detras)
    abrir = "".join("¡" if c == "!" else "¿" for c in reversed(signos) if c in "!?")
    return abrir + joder + signos


def _arreglar_exclamacion(original: str, traduccion: str) -> str:
    """La exclamación sola mal traducida ("¡MAMADA!", "¡FUEEERROOOO!") pasa a "¡Joder!". Las etiquetas de la
    traducción ({b}, {/i}) se conservan: las de apertura delante y las de cierre detrás."""
    joder = _joder_como(original)
    if joder is None or not (_EXCLAMACION.mal.search(traduccion) or not _EXCLAMACION.bien.search(traduccion)):
        return traduccion
    m = re.match(r"^((?:\{[^}]*\}|[\s\"'‘’“”*])*)(.*?)((?:\{[^}]*\}|[\s\"'‘’“”*])*)$", traduccion, re.S)
    antes, medio, despues = m.group(1), m.group(2), m.group(3)
    etiquetas = _ETIQUETA.findall(medio)
    apertura = "".join(e for e in etiquetas if not e.startswith("{/"))
    cierre = "".join(e for e in etiquetas if e.startswith("{/"))
    return f"{antes}{apertura}{joder}{cierre}{despues}"


def arreglar(original: str, traduccion: str) -> str:
    """Arreglos seguros de dos frases hechas, por si los reintentos no bastan (si no aplica, no cambia nada):

    - "Later, Ana!" -> "¡Después, Ana!" pasa a "¡Hasta luego, Ana!". "Later." a secas pasa a "Luego.", que
      vale como despedida y como respuesta a "¿cuándo?". "Después de eso" no se toca.
    - "You're welcome" -> "Eres bienvenida" (al principio de una frase) pasa a "De nada". "Está bien" o
      "¡Bienvenido!" solo se cambian si el original no dice nada más ("Ha! You're welcome, Ana!").
    - "FUUUCK!" (la palabrota sola) -> "¡MAMADA!" o "¡FUEEERROOOO!" pasa a "¡JODEEER!".
    - "It's not like that" -> "No es así de fácil" / "no es como eso" pasa a "No es lo que piensas" (si el
      inglés no habla de algo fácil o simple).
    """
    if not original or not traduccion:
        return traduccion
    r = _arreglar_exclamacion(original, traduccion)
    if _NO_ES_ASI.patron.search(original):
        r = _ASI_DE_FACIL.sub(lambda m: f"{m.group(1)}o es lo que piensas", r)
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
