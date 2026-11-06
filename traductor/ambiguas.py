"""Palabras inglesas con dos sentidos que el modelo confunde.

"chest" puede ser un COFRE (caja del tesoro) o el PECHO (parte del cuerpo), y "safe" una CAJA FUERTE o
"a salvo". El modelo tiende a poner siempre "cofre": lo aprendió de datos de entrenamiento con ese fallo
("groping her chest" -> "tocándole el cofre"). Aquí se decide el sentido con las palabras de la propia
frase, con reglas sencillas y comprobables:

- Si está claro, ese sentido entra en el GLOSARIO OBLIGATORIO de la frase ('chest' = 'pecho') y, después,
  ``sentido_equivocado`` comprueba que la traducción lo respeta (si no, se reintenta avisando).
- Si no está claro, no se hace nada: el modelo decide como siempre (y la clave de caché no cambia).
- Las frases hechas ("get it off your chest", "close to the chest") no se fuerzan; solo se comprueba que
  no salga un cofre de verdad.

``arreglar_articulos`` corrige además los artículos de estos sustantivos masculinos ("la cofre" -> "el
cofre"), un fallo frecuente cuando el modelo cambia de palabra a mitad de frase.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = ["Decision", "decidir", "terminos", "sentido_equivocado", "nota_reintento", "forzar_sentido",
           "arreglar_articulos"]


@dataclass(frozen=True)
class Decision:
    """Sentido elegido para una palabra de la frase original."""

    palabra: str     # "chest", "safe", "chest of drawers"
    sentido: str     # "cofre", "pecho", "frase_hecha", "comoda", "caja_fuerte", "vulgar", "insulto", "dudoso"...
    termino: str     # traducción que se pide en el glosario ("" = ninguna: solo se comprueba)
    motivo: str      # pista que lo decidió (para depurar y para los tests)


_I = re.IGNORECASE
_RAPIDO = re.compile(r"\b(?:chest|safe|puss|cock|dick|tit|boob|cum|blow\s?job|hand\s?job|dildo|clit|nipple)", _I)

# --------------------------------------------------------------------------- "chest"
_POSESIVO = r"(?:my|your|his|her|their|our|its|ur|yer|thy)"
_GENITIVO = r"[A-Za-z][\w-]*(?:['’]s|s['’]|['’])"
_ADJ_COFRE = {"treasure", "storage", "wooden", "wood", "iron", "metal", "steel", "old", "antique", "ancient",
              "locked", "unlocked", "magic", "magical", "hidden", "secret", "heavy", "empty", "cursed",
              "gothic", "golden", "gold", "silver", "loot", "pirate", "rusty", "dusty", "mysterious",
              "sealed", "scary", "special", "chapel", "supply", "supplies", "weapon", "weapons"}
_ADJ_CUERPO = ("manly|hairy|bare|broad|flat|muscular|muscled|toned|ample|heaving|naked|exposed|chiseled|"
               "chiselled|sculpted|perky|busty|sweaty|pale|tanned|smooth")
_RE_CHEST = re.compile(r"\bchests?\b", _I)

_FRASE_HECHA = [
    (re.compile(rf"\boff\s+(?:{_POSESIVO}|one['’]?s)\s+chest\b", _I), "get it off one's chest"),
    (re.compile(r"\bclose\s+to\s+the\s+chest\b", _I), "close to the chest"),
    (re.compile(r"\bcards?\b[^.!?]{0,40}\bclose\s+to\s+\w+\s+chest\b", _I), "cards close to the chest"),
]
_COMODA = re.compile(r"\bchests?\s+of\s+drawers\b", _I)

# Pistas fuertes (2 puntos) del cuerpo
_CUERPO_FUERTE = [
    (re.compile(rf"\b{_ADJ_CUERPO}\s+chests?\b", _I), "adjetivo de cuerpo"),
    (re.compile(r"\bchests?\s+(?:hairs?|pains?|muscles?|size|area|bone|cavity|tattoo|wound|scar|hurts?|"
                r"aches?|tightness|pounding|heaving|rises?|rising|rose)\b", _I), "chest + parte del cuerpo"),
    (re.compile(r"\b(?:shot|shoot|shoots|stab|stabs|stabbed|stabbing|hit|hits|punch\w*|kick\w*|struck|strike|"
                r"pierc\w*|wound\w*|slash\w*|impal\w*|bullet|arrow|knife|dagger|sword|blade|spear|pain|ache|"
                r"hurt\w*|tight\w*|pressure|pound\w*|thump\w*|beat\w*)\b[^.!?]{0,40}"
                rf"\b(?:in|into|on|to|across|against)\s+(?:the|{_POSESIVO})\s+chest\b", _I), "golpe o dolor en el pecho"),
    (re.compile(r"\b(?:him|her|me|you|them|us)\s+(?:right\s+)?(?:in|on|across|against)\s+the\s+chest\b", _I),
     "a alguien en el pecho"),
]
# Pistas débiles (1 punto, como mucho 2 en total) del cuerpo: palabras de alrededor
_CUERPO_DEBIL = re.compile(
    r"\b(?:breasts?|boobs?|tits?|titties|nipples?|bra|bras|cleavage|cup\s+size|shirt|blouse|dress|outfit|"
    r"clothes|naked|topless|nude|grop\w*|fondl\w*|caress\w*|kiss\w*|lick\w*|rub\w*|massag\w*|strok\w*|"
    r"suck\w*|heart\w*|breath\w*|lungs?|reveal\w*|star(?:e|es|ed|ing)|ogl\w*|hug\w*|embrac\w*|cuddl\w*|"
    r"snuggl\w*|bur(?:y|ies|ied)\s+\w+\s+face|sweat\w*|abs|pecs|shoulders?|neck|belly|stomach|waist|"
    r"hips?|thighs?|body|bodies|chubby|tight)\b", _I)

# Pistas fuertes (2 puntos) del cofre
_VERBOS_COFRE = (r"(?:open|opens|opened|opening|unlock\w*|loot\w*|lockpick\w*|bring|brings|brought|bringing|"
                 r"carry|carries|carried|carrying|drag\w*|find|finds|found|finding|search\w*|inspect\w*|"
                 r"empt(?:y|ies|ied|ying)|steal\w*|stole|stolen|bury|buried|burying|hid|hidden|stor(?:e|es|ed|ing)|"
                 r"mov(?:e|es|ed|ing)|lift\w*|take|takes|took|taking|taken|fetch\w*|deliver\w*|cut\s+down)")
_DETERMINANTE = (r"(?:the|a|an|this|that|these|those|some|every|each|all|any|one|two|three|another|"
                 r"a\s+whole|the\s+whole)")
_COFRE_FUERTE = [
    (re.compile(r"\bchests?\s+(?:keys?|locks?|lids?)\b", _I), "chest key"),
    (re.compile(rf"\b{_VERBOS_COFRE}\s+{_DETERMINANTE}\s+(?:\w+\s+){{0,2}}chests?\b", _I), "verbo de cofre"),
    (re.compile(r"\bchests?\s+to\s+(?:open|unlock|loot|find)\b", _I), "chest to open"),
    (re.compile(r"\bchests?\s+(?:contain\w*|hold|holds)\b", _I), "chest contains"),
    (re.compile(r"\b(?:what|anything|something|nothing|everything)(?:['’]s|\s+is|\s+was|\s+could\s+be)?\s+"
                r"(?:in|inside)\s+(?:the|this|that)\s+chests?\b", _I), "what's in the chest"),
    (re.compile(rf"\b(?:inside|into)\s+{_DETERMINANTE}\s+(?:\w+\s+)?chests?\b", _I), "inside the chest"),
]
_COFRE_DEBIL = re.compile(
    r"\b(?:keys?|locks?|locked|lockpicks?|lock\s+picks?|unlock\w*|treasures?|loot\w*|gold|coins?|amulets?|"
    r"items?|inside|contents?|contain\w*|open\w*|chandelier|attic|basement|cave|caves|dungeon|map|craft\w*)\b",
    _I)
_PLURAL_SIN_DUENO = re.compile(r"\bchests\b", _I)


def _palabras_previas(texto: str, inicio: int, n: int = 3) -> list[str]:
    return re.findall(r"[\w'’-]+", texto[:inicio])[-n:]


def _puntos_chest(texto: str) -> tuple[int, int, str]:
    """(puntos de cuerpo, puntos de cofre, pista principal)."""
    cuerpo = cofre = 0
    pistas: list[str] = []
    for m in _RE_CHEST.finditer(texto):
        previas = [p.lower() for p in _palabras_previas(texto, m.start())]
        # posesivo o genitivo delante ("her chest", "Hilda's chest", "her big chest"), salvo que entre medias
        # haya un adjetivo de cofre ("your treasure chest")
        for i in range(len(previas) - 1, -1, -1):
            p = previas[i]
            if p in _ADJ_COFRE:
                break
            if re.fullmatch(_POSESIVO, p, _I) or re.fullmatch(_GENITIVO, p, _I):
                cuerpo += 2
                pistas.append("posesivo")
                break
            if p in ("the", "a", "an", "this", "that", "these", "those") or len(previas) - i > 2:
                break
        if previas and previas[-1] in _ADJ_COFRE:
            cofre += 2
            pistas.append(f"'{previas[-1]} chest'")
    for patron, motivo in _CUERPO_FUERTE:
        if patron.search(texto):
            cuerpo += 2
            pistas.append(motivo)
    for patron, motivo in _COFRE_FUERTE:
        if patron.search(texto):
            cofre += 2
            pistas.append(motivo)
    cuerpo += min(2, len(_CUERPO_DEBIL.findall(texto)))
    cofre += min(2, len(_COFRE_DEBIL.findall(texto)))
    if _PLURAL_SIN_DUENO.search(texto) and "posesivo" not in pistas:
        cofre += 1
    return cuerpo, cofre, ", ".join(pistas) or "palabras de alrededor"


def _decidir_chest(texto: str) -> Decision | None:
    if not _RE_CHEST.search(texto):
        return None
    if _COMODA.search(texto):
        return Decision("chest of drawers", "comoda", "cómoda", "chest of drawers")
    for patron, motivo in _FRASE_HECHA:
        if patron.search(texto):
            return Decision("chest", "frase_hecha", "", motivo)
    cuerpo, cofre, motivo = _puntos_chest(texto)
    if (cuerpo >= 2 and cofre == 0) or cuerpo >= cofre + 3:
        return Decision("chest", "pecho", "pecho", motivo)
    if (cofre >= 2 and cuerpo == 0) or cofre >= cuerpo + 3:
        return Decision("chest", "cofre", "cofre", motivo)
    return None


# --------------------------------------------------------------------------- "safe"
# "safe" es casi siempre adjetivo ("keep her safe", "Is that safe?", "Ella's safe now" = Ella is safe): solo
# se decide "caja fuerte" con pistas que no dejan duda. "her" y "Ella's" solo cuentan junto a un verbo de
# abrir o con palabras de caja fuerte en la frase.
_ADJ_SAFE = (r"(?:wall|metal|steel|iron|heavy|big|small|old|locked|hidden|electronic|digital|combination|"
             r"portable)")
# Genitivo de un nombre propio ("Andrea's", "Hilda's"), nunca una contracción ("it's safe to assume").
_CONTRACCIONES = ("He|She|It|That|There|Here|What|Who|Where|How|When|Why|Everything|Everyone|Everybody|"
                  "Nothing|Something|Somebody|Someone|Nobody|Anyone|Anything|Let|This|One")
_GENITIVO_NOMBRE = rf"(?!(?i:{_CONTRACCIONES})['’]s\b)[A-Z][\w-]*(?:['’]s|s['’])"
_DUENO_SAFE = rf"(?:(?i:the|a|an|this|that|{_POSESIVO})|{_GENITIVO_NOMBRE})"
_CONTEXTO_CAJA = re.compile(r"\b(?:open\w*|unlock\w*|keys?|codes?|combination|locks?|locked|money|cash|gold|"
                            r"jewel\w*|crack\w*|valuables|documents?|deposit\w*)\b", _I)
_SAFE_SUSTANTIVO = [
    (re.compile(r"\bsafes\b", _I), "plural"),
    (re.compile(rf"\b(?:the|an?)\s+(?:{_ADJ_SAFE}\s+)?safe(?=\s*(?:[.,!?;:…)\"'”’]|$))", _I), "the safe."),
    (re.compile(rf"\b(?:this|that|these|those)\s+{_ADJ_SAFE}\s+safe\b", _I), "this metal safe"),
    (re.compile(rf"\b(?:the|an?)\s+(?:{_ADJ_SAFE}\s+)?safe\s+(?:is|was|has|had|can|could|will|would|should|"
                r"must|might|won['’]t|isn['’]t|wasn['’]t|in|on|of|behind|under|near|next|by)\b", _I), "the safe is"),
    (re.compile(r"\bsafes?\s+(?:keys?|codes?|combination|combo|door|locks?|dial|password)\b", _I), "safe key"),
    (re.compile(rf"\b(?i:open\w*|unlock\w*|crack\w*|break\w*\s+into|rob\w*|blow\w*\s+open)\s+{_DUENO_SAFE}\s+"
                r"(?:\w+\s+)?(?i:safe)\b"), "open the safe"),
]
_SAFE_CON_DUENO = re.compile(rf"\b(?:(?i:{_POSESIVO})|{_GENITIVO_NOMBRE})\s+(?:\w+\s+)?(?i:safe)\b")
_SAFE_NO = re.compile(r"\bsafe\s+(?:and\s+sound|side|place|spot|house|zone|distance|bet|haven|room|word|sex|"
                      r"mode|area|space|passage|harbou?r|journey|trip|travels?|return|deposit)\b", _I)


def _decidir_safe(texto: str) -> Decision | None:
    if not re.search(r"\bsafes?\b", texto, _I):
        return None
    for patron, motivo in _SAFE_SUSTANTIVO:
        m = patron.search(texto)
        if m and not _SAFE_NO.search(texto[m.start():m.end() + 30]):
            return Decision("safe", "caja_fuerte", "caja fuerte", motivo)
    m = _SAFE_CON_DUENO.search(texto)
    if m and _CONTEXTO_CAJA.search(texto) and not _SAFE_NO.search(texto[m.start():m.end() + 30]):
        return Decision("safe", "caja_fuerte", "caja fuerte", "su caja fuerte (con llave, código...)")
    return None


# --------------------------------------------------------------------------- Palabras vulgares (W7)
# En los juegos para adultos el modelo suaviza, se inventa o cambia el órgano ("Eat that pussy" -> "Llévate esa
# pija"; "Fuck my pussy" -> "Fóllame con tu polla"): en un juego real fallaba 1 de cada 7 "pussy". Se pide la
# palabra de España en el glosario de la frase y se comprueba, salvo en insultos y otros sentidos ("Don't be a
# pussy", "the cock crowed", "Dick Grayson", "tit for tat"). El usuario elige las palabras en
# glosarios/glosario_adulto.json; "cum" solo se comprueba (verbo "correrse" o nombre "corrida", según la frase).
ARCHIVO_ADULTO = Path(__file__).resolve().parent.parent / "glosarios" / "glosario_adulto.json"


@dataclass(frozen=True)
class _Vulgar:
    clave: str                        # clave en glosario_adulto.json
    patron: re.Pattern                # la palabra en inglés
    defecto: str                      # traducción por defecto ("" = solo se comprueba)
    bien: str                         # formas españolas que valen (regex)
    excepcion: re.Pattern | None = None


_VULGARES = (
    _Vulgar("pussy", re.compile(r"\bpuss(?:y|ies)\b", _I), "coño", r"\bcoñ\w*|\bchoch\w*|\bchumin\w*|\bvagin\w*",
            re.compile(r"\bpuss(?:y|ied)\s+out\b|\bpussy[\s-]?(?:cat|whipped)\b|\bpocket\s+puss(?:y|ies)\b", _I)),
    _Vulgar("cock", re.compile(r"\bcocks?\b", _I), "polla", r"\bpoll\w*|\bpene\w*|\bverg\w*|\braboa?s?\b|\bmiembro",
            re.compile(r"\b(?:roosters?|crow(?:s|ed|ing)?|hens?|cock-a-doodle\w*)\b|"
                       r"\bcocks?\s+(?:the|his|her|my|a)\s+(?:gun|pistol|rifle|revolver|hammer|head|eyebrow)", _I)),
    _Vulgar("dick", re.compile(r"\bdicks?\b", _I), "polla", r"\bpoll\w*|\bpene\w*|\bverg\w*|\brabo"),
    _Vulgar("tits", re.compile(r"\btits?\b|\btitties\b", _I), "tetas", r"\btet\w+|\bpech\w+|\bsenos?\b|\bpez[oó]n\w*",
            re.compile(r"\btits\s+up\b|\btit\s+for\s+tat\b|\b(?:blue|great|coal)\s+tits?\b", _I)),
    _Vulgar("boobs", re.compile(r"\bboob(?:s|ies)?\b", _I), "tetas", r"\btet\w+|\bpech\w+|\bsenos?\b"),
    # "correrse" siempre con su pronombre: "me corro", "córrete", "correrte", "se corrió", "me voy a correr".
    # "Estoy corriendo" o "te haré correr" son de correr (ir deprisa): no valen.
    _Vulgar("cum", re.compile(r"\bcum(?:s|ming|med)?\b", _I), "",
            r"\b(?:me|te|se|nos|os)\s+(?:(?:voy|vas|va|vamos|vais|van|iba|ibas|iban|estoy|estás|está|estamos|"
            r"estaba|estabas|acabo|acabas|acaba|he|has|ha|hemos|había|habías|vuelvo|vuelves|vuelve|vas)\s+"
            r"(?:a\s+|de\s+)?)?(?:c-)*c[oó]rr\w*|\bc[oó]rr[eéi]\w*(?:me|te|se|nos|os)\b|\bcorrid[ao]s?\b|"
            r"\bsemen\b|\bleche\b|\blefa\b|\beyacul\w*",
            re.compile(r"\bcum\s+laude\b|\bsumma\s+cum\b", _I)),
    _Vulgar("blowjob", re.compile(r"\bblow\s?-?jobs?\b", _I), "mamada", r"\bmamad\w*|\bfelaci\w*"),
    _Vulgar("handjob", re.compile(r"\bhand\s?-?jobs?\b", _I), "paja", r"\bpaj\w+|\bmasturb\w*"),
    _Vulgar("dildo", re.compile(r"\bdildos?\b", _I), "consolador", r"\bconsolador\w*|\bdild\w*|\bvibrador\w*"),
    _Vulgar("clit", re.compile(r"\bclit(?:oris|s)?\b", _I), "clítoris", r"\bcl[ií]toris\b"),
    _Vulgar("nipples", re.compile(r"\bnipples?\b", _I), "pezón", r"\bpez[oó]n\w*"),
)
_VULGAR_POR_CLAVE = {v.clave: v for v in _VULGARES}
# Insultos: se traducen con un insulto igual de vulgar (el usuario: "así lo quiso el juego"), no con el órgano.
# Y3 (c): "What a pussy!" es un insulto ("¡Qué nenaza!") o, en una escena de sexo, admiración ("¡Qué coño!").
# - Con verbo ("you're a pussy", "don't be a dick", "acting like a dick") o a quien escucha ("you pussy!"):
#   siempre insulto. Seguida de un sustantivo ("pussy slayer", "dick pic"), nunca.
# - Exclamación ("What a pussy!", "Such a dick!"): decide la propia frase. Con pistas de sexo ("so wet", "lick",
#   "cock"...) es la parte del cuerpo; con pistas de cobardía ("ran away", "scared") o de mala persona ("rude",
#   "jerk"), insulto. Sin pistas, o con las dos, es DUDOSA: no se pide palabra en el glosario (el modelo decide
#   con la frase anterior) y se acepta tanto el insulto como la parte del cuerpo.
SENTIDOS_VULGARES = ("vulgar", "insulto", "dudoso")


@dataclass(frozen=True)
class _Insulto:
    clave: str             # clave en glosario_adulto.json
    defecto: str           # traducción por defecto
    bien: str              # formas españolas que valen (regex)
    siempre: re.Pattern    # con verbo o a quien escucha: insulto seguro
    exclamacion: re.Pattern  # "What a pussy!": lo decide el resto de la frase
    pistas: re.Pattern     # pistas de insulto (cobardía, mala persona)


_COPULA = r"(?:be|being|been|['’]re|['’]s|is|are|was|were|am|acting\s+like|act\s+like|acts\s+like)"
# Detrás de la palabra: fin de frase, puntuación o una palabra que no la convierte en sustantivo compuesto
# ("pussy slayer", "dick pic", "pussy juice" no son insultos).
_FIN_INSULTO = (r"(?=\s*(?:[.!?,…;:)\"”'’~]|$)|\s+(?:and|or|but|who|like|for|if|when|than|to|about|anyway|too|"
                r"man|dude|bro|now|again|right|huh|eh)\b)")


def _patrones_insulto(palabra: str, adjetivos: str, extra: str = "") -> tuple[re.Pattern, re.Pattern]:
    adj = rf"(?:(?:{adjetivos})\s+)?"
    siempre = re.compile(rf"\b{_COPULA}\s+(?:such\s+)?a\s+{adj}{palabra}{_FIN_INSULTO}|"
                         rf"\byou\s+{adj}{palabra}{_FIN_INSULTO}{extra}", _I)
    exclamacion = re.compile(rf"\b(?:what|such)\s+a\s+{adj}{palabra}{_FIN_INSULTO}", _I)
    return siempre, exclamacion


_INSULTOS = {
    "pussy": _Insulto(
        "pussy (insulto)", "nenaza",
        r"\bnenaz\w*|\bgallin\w*|\bcagad\w*|\bcobarde\w*|\bmaric\w*|\bmiedic\w*|\bblandeng\w*|\bcaguet\w*",
        *_patrones_insulto("pussy", "little|fucking|total|real|complete"),
        re.compile(r"\b(?:scared|afraid|fear\w*|chicken\w*|coward\w*|wimp\w*|wuss\w*|sissy|crybaby|cry|crying|"
                   r"cries|cried|whin\w*|quit\w*|weak\w*|loser|faint\w*|hid|hide|hiding|flinch\w*|trembl\w*)\b|"
                   r"\b(?:run(?:s|ning)?|ran)\s+(?:away|off)\b|\b(?:give|gave|giving)\s+up\b|\bman\s+up\b|"
                   r"\bgrow\s+a\s+pair\b|\b(?:back|backed|backing|chicken|chickened)\s+(?:out|down)\b", _I)),
    "dick": _Insulto(
        "dick (insulto)", "capullo",
        r"\bcapull\w*|\bgilipoll\w*|\bimb[eé]cil\w*|\bcabr[oó]n\w*|\bidiota\w*|\bpringad\w*|\bcretin\w*|\bmam[oó]n\w*",
        *_patrones_insulto("dick", "real|total|complete|fucking|stupid|little", r"|\bdick\s+move\b"),
        re.compile(r"\b(?:jerk|asshole|rude|mean|selfish|prick|bastard|douche\w*|arrogant|liar|lied|lying|"
                   r"cheat\w*|insult\w*|ignor\w*|dumped|stole|steal\w*|move)\b|\blaugh\w*\s+at\b", _I)),
}
# Pistas de sexo para la exclamación ("What a pussy! So wet...", "Mmm, lick it... what a dick!"). Se buscan en
# la frase SIN la exclamación (la palabra misma no cuenta). "have such a pussy" / "what a dick he has": el cuerpo.
_PISTAS_SEXO = re.compile(
    r"\b(?:wet|wetter|tight|tighter|juicy|pink|soak\w*|dripping|delicious|tasty|taste\w*|lick\w*|eat|eating|eats|"
    r"suck\w*|spread\w*|finger\w*|cocks?|dicks?|puss(?:y|ies)|cum\w*|moan\w*|stretch\w*|throb\w*|inside|horny|"
    r"naked|nude|ride|riding|thrust\w*|beautiful|gorgeous|lovely|sexy)\b|\bso\s+good\b|"
    r"\bfeels?\s+(?:so\s+)?(?:good|great|amazing|incredible)\b|\bfuck\s+(?:me|it|her|him|that|this)\b", _I)
_POSESION = re.compile(r"\b(?:have|has|had|got)\s+(?:such|what)\s+a\b", _I)


def _insulto_o_cuerpo(ins: _Insulto, texto: str) -> str | None:
    """"insulto", "cuerpo", "dudoso" o None (no es ninguna de las formas de insulto)."""
    if ins.siempre.search(texto):
        return "insulto"
    m = ins.exclamacion.search(texto)
    if m is None:
        return None
    resto = texto[:m.start()] + " " + texto[m.end():]
    sexo = bool(_PISTAS_SEXO.search(resto) or _POSESION.search(texto))
    insulto = bool(ins.pistas.search(resto))
    if sexo != insulto:
        return "cuerpo" if sexo else "insulto"
    return "dudoso"
# "Dick" como nombre: con mayúscula en mitad de la frase, seguido de otro nombre ("Dick Grayson") o con genitivo
# ("Dick's Diner", un restaurante, también al empezar la frase).
_NOMBRE_DICK = re.compile(r"(?<![.!?…]\s)(?<!^)\bDick\b|\bDick(?:['’]s)?\s+[A-Z]|\bDick['’]s\b")


_EN_POLLA = re.compile(r"\b(?:cocks?|dicks?)\b", _I)
_LATAM_A_ESPANA = ((re.compile(r"\bvergas\b", _I), "pollas"), (re.compile(r"\bverga\b", _I), "polla"),
                   (re.compile(r"\bpijas\b", _I), "pollas"), (re.compile(r"\bpija\b", _I), "polla"))
_LATAM_SIN_ARREGLO = (
    (re.compile(r"\bcum\w*\b", _I), re.compile(r"\bacab\w+", _I)),                   # "acabar" = correrse
    (re.compile(r"\bfuck\w*\b", _I), re.compile(r"\bc[oó]g\w+|\bcoj\w+", _I)),        # "coger" = follar
    (re.compile(r"\bpuss(?:y|ies)\b", _I), re.compile(r"\bvaginas?\b", _I)),          # "vagina" por "pussy"
)


def espanol_de_espana(original: str, traduccion: str) -> str | None:
    """Para entrenar (W8): algunas traducciones oficiales usan el vocabulario de Latinoamérica.
    "verga"/"pija" -> "polla" (las dos femeninas: el cambio es seguro). Devuelve None si la frase usa "acabar"
    por "cum", "coger" por "fuck" o "vagina" por "pussy": arreglarlo exige conjugar o cambiar el género, así que
    esos ejemplos se quitan."""
    for en, es in _LATAM_SIN_ARREGLO:
        if en.search(original) and es.search(traduccion):
            return None
    if _EN_POLLA.search(original):
        for patron, nueva in _LATAM_A_ESPANA:
            traduccion = patron.sub(lambda m, n=nueva: _igual_mayusculas(m.group(0), n), traduccion)
    return traduccion


@lru_cache(maxsize=1)
def terminos_adultos() -> dict[str, str]:
    """Traducción elegida para cada palabra vulgar (glosarios/glosario_adulto.json; si falta, la de por defecto).
    Un valor vacío desactiva esa palabra."""
    elegidas = {v.clave: v.defecto for v in _VULGARES}
    elegidas.update({ins.clave: ins.defecto for ins in _INSULTOS.values()})
    try:
        datos = json.loads(ARCHIVO_ADULTO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return elegidas
    for clave, valor in (datos.items() if isinstance(datos, dict) else ()):
        if clave in elegidas and isinstance(valor, str):
            elegidas[clave] = valor.strip()
    return elegidas


def _decidir_vulgares(texto: str) -> list[Decision]:
    decisiones = []
    elegidas = terminos_adultos()
    hay_minusculas = bool(re.search(r"[a-z]{3}", texto))
    for v in _VULGARES:
        if not v.patron.search(texto) or (v.excepcion is not None and v.excepcion.search(texto)):
            continue
        if hay_minusculas and all(m.group(0).isupper() for m in v.patron.finditer(texto)):
            continue  # "Call CLIT support!", "Try CUM cola!": sigla o marca en una frase normal, no la palabra
        if v.clave == "dick" and _NOMBRE_DICK.search(texto) and not re.search(r"\bdicks?\b", texto):
            continue  # "Dick Grayson", "Dick's Diner": un nombre (si además sale "dick" en minúscula, cuenta)
        ins = _INSULTOS.get(v.clave)
        sentido = _insulto_o_cuerpo(ins, texto) if ins is not None else None
        if sentido == "insulto":
            termino = elegidas.get(ins.clave, ins.defecto)
            if termino:
                decisiones.append(Decision(v.clave, "insulto", termino, "insulto"))
            continue
        if sentido == "dudoso":
            if elegidas.get(ins.clave, ins.defecto) or elegidas.get(v.clave, v.defecto):
                decisiones.append(Decision(v.clave, "dudoso", "", "insulto o parte del cuerpo, según la escena"))
            continue
        termino = elegidas.get(v.clave, v.defecto)
        if termino == "" and v.defecto:  # el usuario la ha desactivado
            continue
        decisiones.append(Decision(v.clave, "vulgar", termino, "palabra vulgar"))
    return decisiones


# --------------------------------------------------------------------------- API
@lru_cache(maxsize=8192)
def _decidir(texto: str) -> tuple[Decision, ...]:
    if not texto or not _RAPIDO.search(texto):
        return ()
    sentidos = [d for d in (_decidir_chest(texto), _decidir_safe(texto)) if d is not None]
    return tuple(sentidos + _decidir_vulgares(texto))


def decidir(texto: str) -> list[Decision]:
    """Sentidos que se pueden decidir con seguridad en ``texto`` (original en inglés)."""
    return list(_decidir(texto or ""))


def terminos(texto: str, ya: list[tuple[str, str]] | tuple = ()) -> list[tuple[str, str]]:
    """Términos para el GLOSARIO OBLIGATORIO de esta frase. No repite una palabra que ya cubre otro
    término (p. ej. "Chest Key" del glosario del usuario)."""
    cubiertas = " | ".join(en.lower() for en, _ in ya)
    salida = []
    for d in decidir(texto):
        if d.termino and d.palabra.lower() not in cubiertas:
            salida.append((d.palabra, d.termino))
    return salida


# Formas españolas de cada sentido: (bien, mal). "mal" sin "bien" en la traducción = sentido equivocado.
_COFRE_ES = r"\b(?:cofres?|ba[uú]l(?:es)?|arc[oó]n(?:es)?)\b"
_PECHO_ES = r"\b(?:pechos?|t[oó]rax|torsos?|bustos?|senos?|escotes?|delanteras?|pectorales)\b"
_SENTIDOS_ES = {
    "pecho": (re.compile(_PECHO_ES, _I), re.compile(_COFRE_ES, _I)),
    "cofre": (re.compile(_COFRE_ES + r"|\bcajas?\b|\barcas?\b", _I), re.compile(_PECHO_ES + r"|\btetas?\b", _I)),
    "frase_hecha": (None, re.compile(_COFRE_ES, _I)),
    "comoda": (re.compile(r"\bc[oó]modas?\b", _I), re.compile(_COFRE_ES + "|" + _PECHO_ES, _I)),
    # Sin "caja fuerte", un cofre o un adjetivo ("Llave de seguridad", "a salvo") es el sentido equivocado.
    "caja_fuerte": (re.compile(r"\bcajas?\s+(?:fuertes?|de\s+seguridad|blindadas?|de\s+caudales)\b", _I),
                    re.compile(_COFRE_ES + r"|\bseguridad\b|\bsegur[oa]s?\b|\ba\s+salvo\b", _I)),
}
_TETAS = re.compile(r"\btet(?:as?|itas?)\b", _I)
_TETAS_EN = re.compile(r"\b(?:tits?|titties|boobs?|boobies|jugs|melons|knockers|rack)\b", _I)


@lru_cache(maxsize=64)
def _bien_vulgar(clave: str, termino: str, insulto: bool = False) -> re.Pattern:
    """Formas que valen para una palabra vulgar (o su insulto): las de siempre y la que haya elegido el usuario."""
    extra = "|" + r"\b" + re.escape(termino) if termino else ""
    base = _INSULTOS[clave].bien if insulto else _VULGAR_POR_CLAVE[clave].bien
    return re.compile(base + extra, _I)


def _bien_de(d: Decision) -> re.Pattern:
    """Formas que valen para una decisión vulgar; si es dudosa, las del insulto y las de la parte del cuerpo."""
    if d.sentido != "dudoso":
        return _bien_vulgar(d.palabra, d.termino, d.sentido == "insulto")
    elegidas = terminos_adultos()
    cuerpo = _bien_vulgar(d.palabra, elegidas.get(d.palabra, ""))
    insulto = _bien_vulgar(d.palabra, elegidas.get(_INSULTOS[d.palabra].clave, ""), True)
    return re.compile(cuerpo.pattern + "|" + insulto.pattern, _I)


def sentido_equivocado(original: str, traduccion: str) -> list[Decision]:
    """Decisiones que la traducción NO respeta (vacía = bien o nada que comprobar).

    Para el pecho, "tetas" también cuenta como fallo si el inglés no es vulgar ("chest" es neutro)."""
    if not traduccion:
        return []
    fallos = []
    for d in decidir(original):
        if d.sentido in SENTIDOS_VULGARES:
            if not _bien_de(d).search(traduccion):
                fallos.append(d)  # suavizada, inventada o con otra parte del cuerpo
            continue
        bien, mal = _SENTIDOS_ES[d.sentido]
        tiene_bien = bien is not None and bool(bien.search(traduccion))
        if d.sentido == "pecho":
            # Si "chest" es sin duda el cuerpo, cualquier cofre sobra, aunque haya "pechos" por "breasts"
            # ("Sus enormes pechos presionan su cofre").
            if mal.search(traduccion) or (not tiene_bien and _TETAS.search(traduccion)
                                          and not _TETAS_EN.search(original)):
                fallos.append(d)
        elif mal.search(traduccion) and not tiene_bien:
            fallos.append(d)
    return fallos + organos_inventados(original, traduccion)


# Órganos que la traducción pone y el original no menciona ("Pound my ass!" -> "¡Mátame con tu polla!",
# "Eat my pussy!" -> "¡Lleva tu polla hasta mi coño!", "buttplugs" -> "plug de polla"): fallos de modelos
# antiguos que ninguna otra regla veía. Se aceptan sinónimos y genéricos ("weiner", "cooter", "taco", "crotch",
# "it") y la exclamación "¿Qué coño...?" por "What the fuck".
_GENITALES_EN = r"crotch|groin|junk|privates|genitals?|down\s+there|sex\b"
_ORGANOS = (
    ("polla", re.compile(r"\bpollas?\b", _I),
     re.compile(r"\b(?:cocks?|dicks?|penis\w*|members?|rods?|shafts?|pricks?|dongs?|schlongs?|w[ie]{2}ners?|willy|"
                r"boners?|erections?|hard-?ons?|chubs?|manhood|meat|tools?|peckers?|johnson|package|bulge|it|"
                r"thing|one|sausage|" + _GENITALES_EN + r")", _I)),
    ("coño", re.compile(r"\bcoños?\b", _I),
     re.compile(r"\b(?:pussy|pussies|cunts?|vagina\w*|snatch|twats?|slits?|cooch\w*|cooters?|tacos?|kitty|beaver|"
                r"muff|clams?|box|folds|petals|lips|honeypot|holes?|cherry|" + _GENITALES_EN + r")", _I)),
    ("tetas", re.compile(r"\btetas?\b", _I),
     re.compile(r"\b(?:tits?|titties|boob\w*|breasts?|chest|knockers|jugs|melons|rack|bust|bosom|nipples?|udders|"
                r"jiggl\w*)", _I)),
)
_EXCLAMACION_COÑO = re.compile(r"\bqu[eé]\s+coño\b|(?:^|[¡¿.!?…]\s*)coño\b|\bcoño\s*[,!.]", _I)
_TACO_EN = re.compile(r"\b(?:fuck\w*|hell|damn\w*|shit\w*|heck|crap)\b", _I)


def organos_inventados(original: str, traduccion: str) -> list[Decision]:
    original = original.replace("\\n", " ")  # "Cove's\npussy": el salto del juego va pegado a la palabra
    fallos = []
    for palabra, es, en in _ORGANOS:
        if not es.search(traduccion) or en.search(original):
            continue
        if palabra == "coño" and _TACO_EN.search(original) and _EXCLAMACION_COÑO.search(traduccion):
            continue  # "What the fuck!?" -> "¡¿Qué coño...?!": una exclamación, no el órgano
        fallos.append(Decision(palabra, "inventado", "", "el original no lo dice"))
    return fallos


_EXPLICACION = {
    "pecho": "'{p}' significa 'pecho' (parte del cuerpo), no 'cofre'.",
    "cofre": "'{p}' significa 'cofre' (un baúl o caja del tesoro), no 'pecho'.",
    "frase_hecha": "'{p}' forma parte de una frase hecha: tradúcela por su sentido, sin ningún cofre.",
    "comoda": "'{p}' es una 'cómoda' (el mueble con cajones).",
    "caja_fuerte": "'{p}' es una 'caja fuerte', no un cofre.",
}


def nota_reintento(fallos: list[Decision]) -> str:
    """Aviso para el reintento: "En esta frase 'chest' significa 'pecho' (parte del cuerpo), no 'cofre'."."""
    partes = []
    for d in fallos:
        if d.sentido == "insulto":
            partes.append(f"'{d.palabra}' aquí es un insulto: tradúcelo con un insulto igual de vulgar, como "
                          f"'{d.termino}', no con una parte del cuerpo.")
        elif d.sentido == "dudoso":
            ins = _INSULTOS[d.palabra]
            organo = terminos_adultos().get(d.palabra) or _VULGAR_POR_CLAVE[d.palabra].defecto
            partes.append(f"'{d.palabra}' puede ser un insulto ('{ins.defecto}') o la parte del cuerpo "
                          f"('{organo}'): mira la frase anterior para saber cuál; no lo suavices ni lo cambies "
                          "por otra palabra.")
        elif d.sentido == "vulgar":
            partes.append(f"'{d.palabra}' es '{d.termino}' (vulgar, como en el original): no lo suavices ni lo "
                          "cambies por otra palabra." if d.termino else
                          f"'{d.palabra}' es 'correrse' (verbo) o 'la corrida' (nombre): no lo suavices.")
        elif d.sentido == "inventado":
            partes.append(f"el original no dice '{d.palabra}': no añadas esa palabra; traduce la parte del cuerpo "
                          "(o la acción) que dice el original.")
        elif d.sentido in _EXPLICACION:
            partes.append(_EXPLICACION[d.sentido].format(p=d.palabra))
    return ("En esta frase " + " ".join(partes)) if partes else ""


def _igual_mayusculas(modelo: str, nueva: str) -> str:
    if modelo.isupper():
        return nueva.upper()
    if modelo[:1].isupper():
        return nueva[:1].upper() + nueva[1:]
    return nueva


_SUSTITUCIONES = {
    # Solo cambios seguros: los dos sustantivos son masculinos (el artículo no cambia).
    "pecho": [(re.compile(r"\bcofres\b", _I), "pechos"), (re.compile(r"\bcofre\b", _I), "pecho")],
    "cofre": [(re.compile(r"\bpechos\b", _I), "cofres"), (re.compile(r"\bpecho\b", _I), "cofre")],
}
# "un cofre fuerte" -> "una caja fuerte": cambia el género, así que se cambia también el determinante.
_MASC_A_FEM = {"el": "la", "un": "una", "este": "esta", "ese": "esa", "aquel": "aquella", "del": "de la",
               "al": "a la", "los": "las", "unos": "unas", "estos": "estas", "esos": "esas", "aquellos": "aquellas"}
_RE_COFRE_FUERTE = re.compile(r"\b(?:(el|un|este|ese|aquel|del|al|los|unos|estos|esos|aquellos)\s+)?"
                              r"(cofres?)\s+fuertes?\b", _I)


def _a_caja_fuerte(m: re.Match) -> str:
    det, nombre = m.group(1), m.group(2)
    caja = _igual_mayusculas(nombre, "cajas fuertes" if nombre.lower().endswith("s") else "caja fuerte")
    return f"{_igual_mayusculas(det, _MASC_A_FEM[det.lower()])} {caja}" if det else caja


def forzar_sentido(original: str, traduccion: str) -> str:
    """Último recurso tras los reintentos: cambia la palabra del otro sentido cuando es seguro hacerlo
    (cofre <-> pecho; "un cofre fuerte" -> "una caja fuerte"). Lo demás se deja como está."""
    resultado = traduccion
    for d in sentido_equivocado(original, traduccion):
        if d.sentido == "caja_fuerte":
            resultado = _RE_COFRE_FUERTE.sub(_a_caja_fuerte, resultado)
        for patron, nueva in _SUSTITUCIONES.get(d.sentido, ()):
            resultado = patron.sub(lambda m, n=nueva: _igual_mayusculas(m.group(0), n), resultado)
    return arreglar_articulos(resultado)


_MASCULINOS = r"(?:cofre|pecho|ba[uú]l)"
_DET_FEM = {"la": "el", "una": "un", "esta": "este", "esa": "ese", "aquella": "aquel", "otra": "otro",
            "alguna": "algún", "ninguna": "ningún", "nuestra": "nuestro", "vuestra": "vuestro",
            "las": "los", "unas": "unos", "estas": "estos", "esas": "esos", "aquellas": "aquellos",
            "otras": "otros", "algunas": "algunos", "nuestras": "nuestros", "vuestras": "vuestros"}
_RE_ART_SING = re.compile(r"\b(la|una|esta|esa|aquella|otra|alguna|ninguna|nuestra|vuestra)\s+((?:gran\s+)?"
                          + _MASCULINOS + r")\b", _I)
_RE_ART_PLUR = re.compile(r"\b(las|unas|estas|esas|aquellas|otras|algunas|nuestras|vuestras)\s+((?:\w+\s+)?"
                          r"(?:cofres|pechos|ba[uú]les))\b", _I)
_RE_CONTRACCION = re.compile(r"\b([Dd]e|[Aa])\s+([Ee]l)\s+(?=" + _MASCULINOS + r"s?\b|gran\s)")


def arreglar_articulos(traduccion: str) -> str:
    """"la cofre" -> "el cofre", "una cofre" -> "un cofre", "las cofres" -> "los cofres", "de la cofre" ->
    "del cofre". Solo para sustantivos que siempre son masculinos."""
    if not traduccion or not re.search(r"cofre|pecho|ba[uú]l", traduccion, _I):
        return traduccion

    def cambiar(m: re.Match) -> str:
        det = m.group(1)
        return f"{_igual_mayusculas(det, _DET_FEM[det.lower()])} {m.group(2)}"

    resultado = _RE_ART_PLUR.sub(cambiar, _RE_ART_SING.sub(cambiar, traduccion))
    return _RE_CONTRACCION.sub(lambda m: ("del " if m.group(1).lower() == "de" else "al ")
                               if m.group(1).islower() else ("Del " if m.group(1).lower() == "de" else "Al "),
                               resultado)
