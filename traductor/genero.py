"""Concordancia de género gramatical en español (protagonista, hablante y personajes).

Funciones PURAS (no importan nada del resto del paquete) para:

  - ``normalizar_genero``: convertir lo que escriba el usuario ("Hombre", "m", "female"...)
    en un valor canónico: ``hombre``, ``mujer``, ``neutro`` o ``desconocido``.
  - ``corregir_primera_persona``: "estoy cansada" -> "estoy cansado" si quien habla es hombre.
  - ``corregir_segunda_persona`` / ``corregir_vocativos``: "¿estás lista?", "¡bienvenida!",
    ", guapa." según el género de la persona a la que se habla.
  - ``corregir_tercera_persona`` / ``corregir_titulos``: "Ana está cansado" -> "Ana está cansada",
    "mi amigo Ana" -> "mi amiga Ana" cuando se conoce el género del personaje nombrado.
  - ``marcas_genero``: detectar si una traducción ya marca género en 1.ª/2.ª persona
    (sirve para decidir si una traducción antigua de la caché sigue siendo válida).

Reglas de seguridad (precisión antes que cobertura):
  - Solo se tocan construcciones en SINGULAR claramente predicativas. Nunca plurales
    ("estamos cansados") ni usos adverbiales ("estoy solo pensando" = "solo estoy pensando").
  - El adjetivo debe ir seguido de puntuación, fin de frase o una palabra "segura" (de, con,
    para, que, aquí, hoy...). Así "Eres buena persona" no se toca ("buena" concuerda con "persona").
  - Las formas verbales ambiguas entre 1.ª y 3.ª persona ("estaba", "era", "sería"...) solo se
    corrigen si el original inglés habla en primera persona ("I", "I'm", "me", "myself"...) y no
    hay un sujeto explícito de 3.ª persona justo delante ("ella estaba", "Ana era").
"""
from __future__ import annotations

import re
import unicodedata

HOMBRE = "hombre"
MUJER = "mujer"
NEUTRO = "neutro"
DESCONOCIDO = "desconocido"
GENEROS = (HOMBRE, MUJER, NEUTRO, DESCONOCIDO)

# --------------------------------------------------------------------------- Normalización
_SINONIMOS = {
    HOMBRE: {"hombre", "h", "v", "varon", "masculino", "masc", "male", "man", "boy", "chico", "el",
             "he", "him", "macho", "senor", "chaval"},
    MUJER: {"mujer", "f", "fem", "femenino", "female", "woman", "girl", "chica", "ella",
            "she", "her", "hembra", "senora", "chavala"},
    NEUTRO: {"neutro", "n", "neutral", "no binario", "nobinario", "no-binario", "nb", "non-binary",
             "nonbinary", "they", "elle", "grupo", "variable", "jugador", "a elegir", "elegible"},
}


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar_genero(valor, convencion: str | None = None) -> str:
    """'Hombre', 'h', 'masculino', 'male' -> 'hombre'; 'Mujer', 'f', 'female' -> 'mujer'...

    La letra suelta 'm' es AMBIGUA ('mujer' en español, 'male' en inglés): solo se interpreta
    si se indica ``convencion='es'`` (m = mujer, como ``--genero h|m``) o ``convencion='en'``
    (m = male). Sin convención devuelve 'desconocido' para no adivinar mal.
    Cualquier valor no reconocido devuelve 'desconocido'.
    """
    if valor is None:
        return DESCONOCIDO
    limpio = _sin_tildes(str(valor)).strip().lower()
    limpio = re.sub(r"[()\[\]{}.:;,]", " ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    if not limpio:
        return DESCONOCIDO
    if limpio == "m":
        return {"es": MUJER, "en": HOMBRE}.get(convencion or "", DESCONOCIDO)
    for canonico, sinonimos in _SINONIMOS.items():
        if limpio in sinonimos:
            return canonico
    # Textos más largos: "Hombre (por defecto)", "mujer joven", "male (default)"
    primera = limpio.split(" ")[0]
    if len(primera) > 1:
        for canonico, sinonimos in _SINONIMOS.items():
            if primera in sinonimos:
                return canonico
    return DESCONOCIDO


def convencion_de(valores) -> str | None:
    """Deduce si una lista de géneros escritos a mano usa letras en español (h/m) o inglés (m/f)."""
    letras = {_sin_tildes(str(v)).strip().lower() for v in valores if v is not None}
    if "h" in letras or "v" in letras:
        return "es"
    if "f" in letras or "male" in letras or "female" in letras:
        return "en"
    return None


def es_genero_marcado(genero: str) -> bool:
    """True si el género permite aplicar concordancia masculina o femenina."""
    return genero in (HOMBRE, MUJER)


def etiqueta_genero(genero: str) -> str:
    """Texto corto para prompts e informes ('hombre', 'mujer', 'neutro', 'desconocido')."""
    return genero if genero in GENEROS else DESCONOCIDO


# --------------------------------------------------------------------------- Léxico
# Adjetivos y participios en singular (masculino, femenino) que se usan de forma predicativa.
# Se excluyen a propósito palabras con usos no adjetivales frecuentes: bajo, medio, claro,
# mismo (se trata aparte), junto, todo, otro, cierto... "solo" tiene tratamiento especial.
PARES_ADJ_GENERO: tuple[tuple[str, str], ...] = tuple(dict.fromkeys((
    ("ocupado", "ocupada"), ("agotado", "agotada"), ("cansado", "cansada"),
    ("estresado", "estresada"), ("nervioso", "nerviosa"), ("seguro", "segura"),
    ("listo", "lista"), ("confundido", "confundida"), ("desesperado", "desesperada"),
    ("emocionado", "emocionada"), ("enamorado", "enamorada"), ("ansioso", "ansiosa"),
    ("dispuesto", "dispuesta"), ("celoso", "celosa"), ("honrado", "honrada"),
    ("agradecido", "agradecida"), ("sorprendido", "sorprendida"), ("asustado", "asustada"),
    ("preocupado", "preocupada"), ("encantado", "encantada"), ("atrapado", "atrapada"),
    ("satisfecho", "satisfecha"), ("muerto", "muerta"), ("preparado", "preparada"),
    ("acostumbrado", "acostumbrada"), ("interesado", "interesada"), ("metido", "metida"),
    ("convencido", "convencida"), ("dormido", "dormida"), ("despierto", "despierta"),
    ("levantado", "levantada"), ("perdido", "perdida"), ("repleto", "repleta"),
    ("lleno", "llena"), ("aburrido", "aburrida"), ("aturdido", "aturdida"),
    ("sincero", "sincera"), ("retrasado", "retrasada"), ("atascado", "atascada"),
    ("avergonzado", "avergonzada"), ("equivocado", "equivocada"), ("orgulloso", "orgullosa"),
    ("enfermo", "enferma"), ("loco", "loca"), ("borracho", "borracha"), ("harto", "harta"),
    ("relajado", "relajada"), ("tranquilo", "tranquila"), ("cómodo", "cómoda"),
    ("incómodo", "incómoda"), ("contento", "contenta"), ("enojado", "enojada"),
    ("enfadado", "enfadada"), ("molesto", "molesta"), ("involucrado", "involucrada"),
    ("excitado", "excitada"), ("cachondo", "cachonda"), ("mojado", "mojada"),
    ("empapado", "empapada"), ("desnudo", "desnuda"), ("vestido", "vestida"),
    ("casado", "casada"), ("soltero", "soltera"), ("divorciado", "divorciada"),
    ("comprometido", "comprometida"), ("obsesionado", "obsesionada"), ("decidido", "decidida"),
    ("impresionado", "impresionada"), ("asombrado", "asombrada"),
    ("cabreado", "cabreada"), ("frustrado", "frustrada"), ("decepcionado", "decepcionada"),
    ("deprimido", "deprimida"), ("humillado", "humillada"), ("ofendido", "ofendida"),
    ("herido", "herida"), ("lastimado", "lastimada"), ("dolorido", "dolorida"),
    ("mareado", "mareada"), ("drogado", "drogada"), ("colocado", "colocada"),
    ("sentado", "sentada"), ("tumbado", "tumbada"), ("acostado", "acostada"),
    ("escondido", "escondida"), ("encerrado", "encerrada"), ("atado", "atada"),
    ("bloqueado", "bloqueada"), ("liado", "liada"), ("calmado", "calmada"),
    ("hambriento", "hambrienta"), ("sediento", "sedienta"), ("halagado", "halagada"),
    ("serio", "seria"), ("curioso", "curiosa"), ("vivo", "viva"), ("salvado", "salvada"),
    ("protegido", "protegida"), ("aliviado", "aliviada"), ("animado", "animada"),
    ("motivado", "motivada"), ("centrado", "centrada"), ("distraído", "distraída"),
    ("despistado", "despistada"), ("callado", "callada"), ("quieto", "quieta"),
    ("atento", "atenta"), ("implicado", "implicada"), ("obligado", "obligada"),
    ("condenado", "condenada"), ("jodido", "jodida"), ("acabado", "acabada"),
    ("tentado", "tentada"), ("intrigado", "intrigada"), ("fascinado", "fascinada"),
    ("asqueado", "asqueada"), ("aterrado", "aterrada"), ("aterrorizado", "aterrorizada"),
    ("horrorizado", "horrorizada"), ("alterado", "alterada"), ("agobiado", "agobiada"),
    ("abrumado", "abrumada"), ("enterado", "enterada"), ("informado", "informada"),
    ("nuevo", "nueva"), ("guapo", "guapa"), ("bonito", "bonita"), ("precioso", "preciosa"),
    ("hermoso", "hermosa"), ("feo", "fea"), ("gordo", "gorda"), ("delgado", "delgada"),
    ("flaco", "flaca"), ("alto", "alta"), ("pequeño", "pequeña"), ("viejo", "vieja"),
    ("tonto", "tonta"), ("estúpido", "estúpida"), ("bueno", "buena"), ("malo", "mala"),
    ("rico", "rica"), ("famoso", "famosa"), ("perfecto", "perfecta"), ("afortunado", "afortunada"),
    ("desafortunado", "desafortunada"), ("cariñoso", "cariñosa"), ("generoso", "generosa"),
    ("tímido", "tímida"), ("vago", "vaga"), ("duro", "dura"),
)))

_FEM_DE = {m: f for m, f in PARES_ADJ_GENERO}
_MASC_DE = {f: m for m, f in PARES_ADJ_GENERO}
_ADJ_MASC = "|".join(sorted(_FEM_DE, key=len, reverse=True))
_ADJ_FEM = "|".join(sorted(_MASC_DE, key=len, reverse=True))

_L = r"[\wáéíóúüñÁÉÍÓÚÜÑ]"  # carácter de palabra (incluye tildes aunque re ya es Unicode)

# Separación entre palabras: espacios o una pausa de diálogo ("tengo que estar... tranquila",
# "estoy-... cansada", "estoy~ lista"). Tras una pausa solo se sigue si lo siguiente va en
# minúscula: "No lo estoy... Tranquilo, Juan." es otra frase (y otro destinatario).
_PAUSA = r"(?:\s*(?:\.{2,}|…|-+|—|~)+\s*(?=(?-i:[a-záéíóúüñ]))|\s+)"
# Tartamudeo delante de la palabra: "c-cansada", "t-tan".
_TARTAMUDEO = rf"(?:{_L}{{1,2}}-)?"

# Intensificadores que pueden ir entre el verbo y el adjetivo ("estoy aún más cansada").
_ADV = (r"(?:" + _PAUSA + _TARTAMUDEO +
        r"(?:tan|muy|bastante|demasiado|un\s+poco|un\s+tanto|poco|algo|totalmente|completamente|"
        r"aún|todavía|mucho|incluso|realmente|verdaderamente|súper|super|más|menos|medio|bien|"
        r"ya|también|tampoco|casi|absolutamente|tremendamente|increíblemente|tan\s+solo|"
        r"algo\s+más|un\s+poquito|un\s+pelín|re|requete)){0,4}")
# Lo que separa el último verbo/intensificador del adjetivo.
_ANTES_ADJ = _PAUSA + _TARTAMUDEO

# Lo que puede ir DETRÁS del adjetivo para considerarlo predicativo (y no "buena persona").
_TRAS_ADJ = (
    r"(?=\s*(?:[.,;:!?…)\]\"»”'~*\-—]|<|\\|$|\s+(?:de|del|en|con|para|por|y|e|o|u|pero|que|como|a|al|"
    r"sin|porque|si|cuando|mientras|hoy|ahora|aquí|ahí|allí|allá|ya|también|tampoco|contigo|conmigo|"
    r"todavía|aún|otra|desde|hasta|hacia|tras|ante|entre|sobre|esta|este|esto|eso|ni|nunca|siempre|"
    r"así|antes|después|luego|mañana|anoche|ayer|nada|aunque|pues|mientras|joder|tío|tía|cariño|"
    r"mamá|papá|hoy|perdón|lo|la|le|te|me|se)\b))"
)

# 1.ª persona: formas inequívocas (llevan "me" o son exclusivas de "yo").
_V1_SEGURAS = (
    r"estoy|estuve|estaré|he estado|habré estado|"
    r"me siento|me sentía|me sentí|me he sentido|me sentiré|me sentiría|"
    r"me pongo|me ponía|me puse|me he puesto|me pondré|me pondría|"
    r"me quedo|me quedaba|me quedé|me he quedado|me había quedado|me quedaré|me quedaría|"
    r"me veo|me veía|me vi|me he visto|me noto|me notaba|me encuentro|me encontraba|"
    r"me he vuelto|me volví|me vuelvo|me estoy poniendo|me estoy quedando|me estoy sintiendo|"
    r"soy|fui|seré|he sido|parezco|ando|sigo|seguí|"
    r"voy a estar|voy a quedarme|voy a sentirme|voy a ser|voy a ponerme|"
    r"puedo estar|podré estar|debo estar|tengo que estar|necesito estar|quiero estar|estoy siendo"
)
# 1.ª persona: formas que coinciden con la 3.ª ("(yo/ella) estaba cansada").
_V1_AMBIGUAS = (
    r"estaba|estaría|esté|estuviera|estuviese|había estado|habría estado|"
    r"era|sería|sea|fuera|fuese|había sido|habría sido|parecía|andaba|seguía|"
    r"iba a estar|iba a ser|podría estar|debería estar|tenía que estar"
)
_V2 = (
    r"estás|estabas|estuviste|estarás|estarías|estés|estuvieras|estuvieses|has estado|habías estado|"
    r"habrás estado|te sientes|te sentías|te sentiste|te has sentido|te sentirás|te sentirías|"
    r"te pones|te ponías|te pusiste|te has puesto|te pondrás|te quedas|te quedabas|te quedaste|"
    r"te has quedado|te quedarás|te ves|te veías|te viste|te notas|te encuentras|te has vuelto|"
    r"te volviste|eres|eras|fuiste|serás|serías|seas|fueras|fueses|has sido|pareces|parecías|"
    r"andas|andabas|sigues|seguías|vas a estar|vas a quedarte|vas a ser|puedes estar|podrías estar|"
    r"debes estar|deberías estar|tienes que estar|estás siendo|te estás poniendo|te estás quedando"
)
_V3 = (
    r"está|estaba|estuvo|estará|estaría|esté|ha estado|había estado|es|era|fue|será|sería|"
    r"parece|parecía|se siente|se sentía|se sintió|se ha sentido|se ve|se veía|se vio|se nota|"
    r"se quedó|se queda|se ha quedado|se había quedado|se puso|se pone|se ha puesto|se ha vuelto|"
    r"se volvió|anda|andaba|sigue|seguía|va a estar|va a ser|puede estar|debe estar|tiene que estar"
)

# Palabras que pueden ir justo antes del verbo SIN ser su sujeto ("Pero estaba cansada",
# "creo que estaba cansada"). Cualquier otra palabra delante se trata como posible sujeto
# de 3.ª persona ("mi madre estaba cansada", "Ana era guapa") y bloquea la corrección.
_NO_SUJETO = {
    "pero", "y", "e", "ya", "entonces", "antes", "ayer", "hoy", "cuando", "si", "que", "porque",
    "aunque", "bueno", "vale", "oh", "ah", "eh", "sí", "no", "mientras", "luego", "después",
    "también", "tampoco", "quizá", "quizás", "creo", "supongo", "solo", "sólo", "todavía", "aún",
    "siempre", "nunca", "jamás", "anoche", "ahora", "mm", "hmm", "uf", "uff", "jo", "joder", "vaya",
    "dios", "bah", "venga", "pues", "total", "obviamente", "claro", "realmente", "sinceramente", "tal",
    "como", "cómo", "yo", "a", "en", "de", "con", "por", "para", "sin", "mañana", "allí", "aquí", "ahí",
    "donde", "dónde", "adonde", "qué", "cuándo", "hasta", "desde", "según", "tan", "muy", "más",
    "menos", "lo", "me", "te", "se", "ni", "o", "u", "sabía", "pensaba", "creía", "dije", "noto",
    "siento", "parece", "cuando", "vez", "rato", "momento", "mal", "bien", "así", "incluso",
}
_SUJETO_3P_PRON = re.compile(
    r"\b(?:él|ella|usted|eso|esto|aquello|nadie|alguien|nada|todo)\s+(?:no\s+|ya\s+|también\s+|"
    r"nunca\s+|siempre\s+|todavía\s+|aún\s+)?$", re.IGNORECASE)
_PALABRA_PREVIA = re.compile(rf"({_L}+)\s+(?:no\s+|ya\s+|también\s+|nunca\s+|siempre\s+)?$")

# Inglés: el original tiene un "yo" + verbo copulativo ("I was", "I'm", "I felt"...).
_EN_1P_COPULA = re.compile(
    r"(?<![\w'’])I(?:\s*(?:'m|’m|'d|’d|'ll|’ll|'ve|’ve)|\s+(?:am|was|were|would|will|have|had|feel|felt|"
    r"seem|seemed|look|looked|get|got|became|become|keep|kept|stay|stayed|must|might|could|should|"
    r"used\s+to|can|cannot|can't|can’t|don't|don’t|didn't|didn’t|wasn't|wasn’t|won't|won’t|'m))(?![\w'’])"
    r"|(?<![\w'’])Im(?![\w'’])"
)
# Inglés: hay un sujeto de 3.ª persona con verbo copulativo ("she was", "Ana is", "Mom's").
_EN_NEUTROS = {"It", "That", "This", "There", "What", "Here", "Where", "Who", "How", "Which",
               "Everything", "Nothing", "Something", "Anything", "Today", "Tonight", "Now", "I"}
_EN_3P_COPULA = re.compile(
    r"(?<![\w'’])(?P<suj>she|he|She|He|SHE|HE|[A-Z][a-z]+)(?:\s*(?:'s|’s|'d|’d|'ll|’ll)|\s+(?:is|was|were|"
    r"would|will|has|had|feels|felt|seems|seemed|looks|looked|gets|got|became|keeps|kept|stays|stayed|"
    r"isn't|isn’t|wasn't|wasn’t))(?![\w'’])"
)


# Otro sujeto en inglés ("She may be evil", "it would be that serious"): las formas españolas
# ambiguas ("sea", "sería", "era") pueden referirse a él, así que no se tocan.
_EN_OTRO_SUJETO = re.compile(
    r"(?<![\w'’])(?:she|he|it|they|this|that|which|who|everything|nothing|something|someone|everyone|"
    r"nobody|everybody)(?:\s*(?:'s|’s|'d|’d|'ll|’ll|'re|’re)|\s+(?:is|was|were|are|would|will|may|might|"
    r"must|can|could|should|seems|seemed|looks|looked|gets|got|became|feels|felt|isn't|isn’t|wasn't|"
    r"wasn’t|won't|won’t|wouldn't|wouldn’t|has|had|been))(?![\w'’])", re.IGNORECASE)


def _original_en_primera_persona(original: str) -> bool:
    """True si el inglés dice algo de "yo" y no hay otro sujeto que haga ambiguas las formas verbales."""
    if not _EN_1P_COPULA.search(original):
        return False
    if _EN_OTRO_SUJETO.search(original):
        return False
    for m in _EN_3P_COPULA.finditer(original):
        if m.group("suj") not in _EN_NEUTROS:
            return False
    return True


# Partes entre comillas: lo que se cita no es lo que quien habla dice de sí.
_COMILLAS = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")


def _fuera_de_comillas(texto: str, funcion) -> str:
    """Aplica ``funcion`` solo a los trozos que no están entre comillas.
    Si toda la frase va entre comillas, se trata como texto normal."""
    visible = texto.strip()
    if not _COMILLAS.search(texto) or (_COMILLAS.fullmatch(visible) is not None):
        return funcion(texto)
    trozos: list[str] = []
    ultimo = 0
    for m in _COMILLAS.finditer(texto):
        trozos.append(funcion(texto[ultimo:m.start()]))
        trozos.append(m.group(0))
        ultimo = m.end()
    trozos.append(funcion(texto[ultimo:]))
    return "".join(trozos)


def _con_mayusculas_de(modelo: str, palabra: str) -> str:
    if modelo.isupper() and len(modelo) > 1:
        return palabra.upper()
    if modelo[:1].isupper():
        return palabra[:1].upper() + palabra[1:]
    return palabra


def _cambiar_palabras(texto: str, mapa: dict[str, str]) -> str:
    return re.sub(rf"{_L}+", lambda w: _con_mayusculas_de(w.group(0), mapa.get(w.group(0).lower(), w.group(0))),
                  texto)


def _cambiar_final(m: re.Match, mapa: dict[str, str], grupo_adj: str = "adj") -> str:
    """Cambia el adjetivo del grupo ``grupo_adj`` y, si el patrón los recoge (grupo 'coord'), los que
    van coordinados detrás: "cansada y harta" -> "cansado y harto"."""
    adj = m.group(grupo_adj)
    nuevo = mapa.get(adj.lower())
    if not nuevo:
        return m.group(0)
    base = m.start(0)
    texto = m.group(0)
    if "coord" in m.re.groupindex and m.group("coord"):
        inicio, fin = m.span("coord")
        texto = texto[: inicio - base] + _cambiar_palabras(m.group("coord"), mapa) + texto[fin - base:]
    inicio, fin = m.span(grupo_adj)
    return texto[: inicio - base] + _con_mayusculas_de(adj, nuevo) + texto[fin - base:]


# "solo" solo se toca cuando significa "sin compañía" (va al final o seguido de lugar/compañía).
_SOLO_CONTEXTO = (r"(?=\s*(?:[.,;:!?…)\"»”'~]|$|\s+(?:aquí|ahí|allí|en\b|con\b|y\b|otra\s+vez|"
                  r"de\s+nuevo|esta\s+noche|hoy|ahora|siempre|nunca|todo\s+el|toda\s+la|en\s+casa)))")


def _patron(verbos: str, adjetivos: str) -> re.Pattern:
    # Adjetivos coordinados detrás del primero ("lista y preparada"). Solo con "y/e/o/u/ni", no con
    # comas: en "¿Estás lista, guapa?" lo de detrás de la coma es un vocativo y va aparte.
    coord = (rf"(?:\s+(?:y|e|o|u|ni)\s+(?:(?:tan|muy|más|bastante|algo|un\s+poco)\s+)?"
             rf"(?:{adjetivos})(?!{_L}))")
    return re.compile(
        rf"(?<!{_L})(?P<verbo>{verbos}){_ADV}{_ANTES_ADJ}(?P<adj>{adjetivos})(?!{_L})"
        rf"(?P<coord>{coord}*){_TRAS_ADJ}",
        re.IGNORECASE,
    )


def _patron_solo(verbos: str, forma: str) -> re.Pattern:
    return re.compile(
        rf"(?<!{_L})(?P<verbo>{verbos}){_ADV}{_ANTES_ADJ}(?P<adj>{forma})(?!{_L}){_SOLO_CONTEXTO}",
        re.IGNORECASE,
    )


_P1_SEG = {HOMBRE: _patron(_V1_SEGURAS, _ADJ_FEM), MUJER: _patron(_V1_SEGURAS, _ADJ_MASC)}
_P1_AMB = {HOMBRE: _patron(_V1_AMBIGUAS, _ADJ_FEM), MUJER: _patron(_V1_AMBIGUAS, _ADJ_MASC)}
_P1_SOLO_SEG = {HOMBRE: _patron_solo(_V1_SEGURAS, "sola"), MUJER: _patron_solo(_V1_SEGURAS, "solo")}
_P1_SOLO_AMB = {HOMBRE: _patron_solo(_V1_AMBIGUAS, "sola"), MUJER: _patron_solo(_V1_AMBIGUAS, "solo")}
_P2 = {HOMBRE: _patron(_V2, _ADJ_FEM), MUJER: _patron(_V2, _ADJ_MASC)}
_P2_SOLO = {HOMBRE: _patron_solo(_V2, "sola"), MUJER: _patron_solo(_V2, "solo")}
_MAPA = {HOMBRE: _MASC_DE, MUJER: _FEM_DE}
_MAPA_SOLO = {HOMBRE: {"sola": "solo"}, MUJER: {"solo": "sola"}}

# Patrones "yo misma"/"tú mismo": la clave es el género CORRECTO; detectan la forma incorrecta.
_MISMO_1P = {
    HOMBRE: re.compile(r"\b(yo|a\s+mí|conmigo|por\s+mí|de\s+mí|para\s+mí)\s+misma\b", re.IGNORECASE),
    MUJER: re.compile(r"\b(yo|a\s+mí|conmigo|por\s+mí|de\s+mí|para\s+mí)\s+mismo\b", re.IGNORECASE),
}
_MISMO_2P = {
    HOMBRE: re.compile(r"\b(tú|a\s+ti|contigo|por\s+ti|de\s+ti|para\s+ti)\s+misma\b", re.IGNORECASE),
    MUJER: re.compile(r"\b(tú|a\s+ti|contigo|por\s+ti|de\s+ti|para\s+ti)\s+mismo\b", re.IGNORECASE),
}


def _cambiar_mismo(texto: str, patron: re.Pattern, genero: str) -> str:
    correcto = "mismo" if genero == HOMBRE else "misma"

    def _sust(m: re.Match) -> str:
        palabra = m.group(0)[len(m.group(1)):].strip()
        return f"{m.group(1)} {_con_mayusculas_de(palabra, correcto)}"

    return patron.sub(_sust, texto)


def _hay_sujeto_3p(previo: str) -> bool:
    """True si justo antes del verbo hay un posible sujeto de 3.ª persona ("ella", "Ana", "mi madre")."""
    if re.search(r"\byo\s+(?:no\s+|ya\s+|también\s+)?$", previo, re.IGNORECASE):
        return False
    if _SUJETO_3P_PRON.search(previo):
        return True
    m = _PALABRA_PREVIA.search(previo)
    if not m:
        return False
    return m.group(1).lower() not in _NO_SUJETO


def _aplicar_ambiguas(texto: str, patron: re.Pattern, mapa: dict[str, str]) -> str:
    """Corrige formas ambiguas 1.ª/3.ª persona salvo que haya un sujeto de 3.ª persona delante."""
    trozos: list[str] = []
    ultimo = 0
    for m in patron.finditer(texto):
        previo = texto[max(0, m.start() - 40):m.start()]
        trozos.append(texto[ultimo:m.start()])
        trozos.append(m.group(0) if _hay_sujeto_3p(previo) else _cambiar_final(m, mapa))
        ultimo = m.end()
    trozos.append(texto[ultimo:])
    return "".join(trozos)


def corregir_primera_persona(texto: str, genero: str, original: str | None = None) -> str:
    """Ajusta los adjetivos que quien habla dice de sí mismo/a ("estoy cansada" -> "estoy cansado").

    ``original`` (inglés) permite corregir también las formas verbales ambiguas ("estaba", "era"...)
    cuando el original está claramente en primera persona del singular.
    """
    if not texto or genero not in (HOMBRE, MUJER):
        return texto
    mapa = _MAPA[genero]
    ambiguas = original is not None and _original_en_primera_persona(original)

    def _corregir(trozo: str) -> str:
        res = _P1_SEG[genero].sub(lambda m: _cambiar_final(m, mapa), trozo)
        res = _P1_SOLO_SEG[genero].sub(lambda m: _cambiar_final(m, _MAPA_SOLO[genero]), res)
        if ambiguas:
            res = _aplicar_ambiguas(res, _P1_AMB[genero], mapa)
            res = _aplicar_ambiguas(res, _P1_SOLO_AMB[genero], _MAPA_SOLO[genero])
        return _cambiar_mismo(res, _MISMO_1P[genero], genero)

    return _fuera_de_comillas(texto, _corregir)


# --------------------------------------------------------------------------- 2.ª persona y vocativos
_PARES_VOCATIVO = (
    ("bienvenido", "bienvenida"), ("querido", "querida"), ("guapo", "guapa"),
    ("precioso", "preciosa"), ("tonto", "tonta"), ("chico", "chica"), ("amigo", "amiga"),
    ("hermano", "hermana"), ("tío", "tía"), ("muchacho", "muchacha"), ("pequeño", "pequeña"),
    ("niño", "niña"), ("señor", "señora"), ("jefe", "jefa"), ("hijo", "hija"), ("bobo", "boba"),
    ("cabrón", "cabrona"), ("chaval", "chavala"),
)
_VOC_MAPA = {HOMBRE: {f: m for m, f in _PARES_VOCATIVO}, MUJER: {m: f for m, f in _PARES_VOCATIVO}}
_VOC_FORMAS = {  # formas INCORRECTAS a buscar según el género correcto
    HOMBRE: "|".join(sorted((f for m, f in _PARES_VOCATIVO if m != "bienvenido"), key=len, reverse=True)),
    MUJER: "|".join(sorted((m for m, f in _PARES_VOCATIVO if m != "bienvenido"), key=len, reverse=True)),
}
_FIN_VOC = r"(?=\s*(?:[.!?…,;:)\"»”'~]|$))"
# "dar la bienvenida" es un sustantivo (siempre femenino): no se toca.
_NO_ES_SALUDO = r"(?<!la\s)(?<!una\s)(?<!su\s)(?<!tu\s)(?<!mi\s)(?<!nuestra\s)(?<!vuestra\s)(?<!esa\s)(?<!esta\s)"
# "siempre es bienvenido que vuelva": impersonal, no habla de nadie.
_NO_IMPERSONAL = r"(?!\s+que\b)"


def _patrones_vocativo(genero: str) -> list[re.Pattern]:
    formas = _VOC_FORMAS[genero]
    bienvenida = "bienvenida" if genero == HOMBRE else "bienvenido"
    return [
        # ", guapa." / ", querida!" / ", chica?" (al final o entre comas)
        re.compile(rf"(?<=,)\s*(?:mi\s+)?(?P<adj>{formas})(?!{_L}){_FIN_VOC}", re.IGNORECASE),
        # "¡Guapa!" / "Querida, ..." al principio de frase
        re.compile(rf"(?:^|(?<=[¡¿])|(?<=[.!?…]\s))(?:mi\s+)?(?P<adj>{formas})(?!{_L})(?=\s*[,!?…])",
                   re.IGNORECASE),
        # "bienvenida" en singular como saludo (no "dar la bienvenida" ni el impersonal "es bienvenido que")
        re.compile(rf"(?<!{_L}){_NO_ES_SALUDO}(?P<adj>{bienvenida})(?!{_L}){_NO_IMPERSONAL}", re.IGNORECASE),
    ]


_P_VOC = {HOMBRE: _patrones_vocativo(HOMBRE), MUJER: _patrones_vocativo(MUJER)}


def corregir_vocativos(texto: str, genero: str) -> str:
    """Ajusta saludos y apelativos dirigidos a quien escucha ("¡Bienvenida, guapa!")."""
    if not texto or genero not in (HOMBRE, MUJER):
        return texto
    mapa = _VOC_MAPA[genero]
    res = texto
    for patron in _P_VOC[genero]:
        res = patron.sub(lambda m: _cambiar_final(m, mapa), res)
    return res


def corregir_segunda_persona(texto: str, genero: str) -> str:
    """Ajusta lo que se dice de la persona a la que se habla ("¿estás lista?" -> "¿estás listo?")."""
    if not texto or genero not in (HOMBRE, MUJER):
        return texto
    mapa = _MAPA[genero]

    def _corregir(trozo: str) -> str:
        res = _P2[genero].sub(lambda m: _cambiar_final(m, mapa), trozo)
        res = _P2_SOLO[genero].sub(lambda m: _cambiar_final(m, _MAPA_SOLO[genero]), res)
        res = _cambiar_mismo(res, _MISMO_2P[genero], genero)
        return corregir_vocativos(res, genero)

    return _fuera_de_comillas(texto, _corregir)


# --------------------------------------------------------------------------- 3.ª persona con nombre
_PARES_TITULO = (
    ("amigo", "amiga"), ("novio", "novia"), ("vecino", "vecina"), ("compañero", "compañera"),
    ("jefe", "jefa"), ("hermano", "hermana"), ("primo", "prima"), ("tío", "tía"),
    ("hijo", "hija"), ("señor", "señora"), ("querido", "querida"), ("pequeño", "pequeña"),
    ("chico", "chica"), ("abuelo", "abuela"), ("maestro", "maestra"), ("profesor", "profesora"),
    ("doctor", "doctora"), ("viejo", "vieja"), ("adorado", "adorada"), ("amado", "amada"),
    ("estimado", "estimada"),
)
_TIT_MAPA = {HOMBRE: {f: m for m, f in _PARES_TITULO}, MUJER: {m: f for m, f in _PARES_TITULO}}
_TIT_FORMAS = {
    HOMBRE: "|".join(sorted((f for _, f in _PARES_TITULO), key=len, reverse=True)),
    MUJER: "|".join(sorted((m for m, _ in _PARES_TITULO), key=len, reverse=True)),
}
# Solo artículos definidos: "una novia 1Hero" es casi siempre "una novia, 1Hero" (vocativo sin coma).
_ARTICULOS = {HOMBRE: {"a la": "al", "de la": "del", "la": "el"},
              MUJER: {"al": "a la", "del": "de la", "el": "la"}}


def _patron_nombre(nombre: str) -> str:
    return rf"(?<!{_L}){re.escape(nombre)}(?!{_L})"


# Si el nombre va tras una preposición ("el padre de Ana no está enojado") NO es el sujeto.
_PREPOSICION_PREVIA = re.compile(
    r"(?<!\w)(?:de|del|a|al|con|para|por|sin|sobre|entre|hacia|según|contra|tras|ante|desde|hasta|como)\s+$",
    re.IGNORECASE)
# Lo que puede ir delante de un título/relación + nombre ("mi amiga Ana", "Hola, querida Ana").
# Tras un sustantivo ("una mujer pequeña 1Hero") el adjetivo es de ese sustantivo, no del nombre.
_PALABRAS_ANTES_DE_TITULO = {
    "mi", "tu", "su", "nuestro", "nuestra", "vuestro", "vuestra", "el", "la", "este", "esta", "ese", "esa",
    "aquel", "aquella", "al", "del", "hola", "adiós", "oye", "eh", "gracias"}


_ABREN_CLAUSULA = {"que", "y", "e", "pero", "porque", "cuando", "si", "aunque", "como", "ya", "también",
                   "o", "u", "ni", "pues", "entonces", "mientras", "donde", "creo", "sé", "parece", "seguro",
                   "quizá", "quizás", "ahora", "hoy", "ayer", "todavía", "aún", "oh", "ah", "vaya", "mira", "bueno"}


def _inicio_de_clausula(previo: str) -> bool:
    """True si el nombre abre oración/cláusula: inicio, puntuación o 'que', 'y', 'pero'..."""
    previo = previo.rstrip()
    if not previo or previo[-1] in ",;:.!?¡¿…(\"'«“-—":
        return True
    m = re.search(rf"({_L}+)$", previo)
    return bool(m) and m.group(1).lower() in _ABREN_CLAUSULA


def _titulo_permitido(previo: str) -> bool:
    """True si lo que precede al título es inicio, puntuación o una palabra funcional ('mi', 'la'...)."""
    previo = previo.rstrip()
    if not previo or previo[-1] in ",;:.!?¡¿…(\"'«“-—":
        return True
    m = re.search(rf"({_L}+)$", previo)
    return bool(m) and m.group(1).lower() in _PALABRAS_ANTES_DE_TITULO


def corregir_titulos(texto: str, nombre: str, genero: str) -> str:
    """'mi amigo Ana' -> 'mi amiga Ana'; 'la jefa Bradley' -> 'el jefe Bradley'."""
    if not texto or not nombre or genero not in (HOMBRE, MUJER) or nombre not in texto:
        return texto
    mapa = _TIT_MAPA[genero]
    articulos = r"a\s+la|de\s+la|la" if genero == HOMBRE else "al|del|el"
    patron = re.compile(
        rf"(?:(?P<art>(?<!{_L})(?:{articulos})\s+))?(?<!{_L})(?P<adj>{_TIT_FORMAS[genero]})\s+"
        rf"(?={_patron_nombre(nombre)}(?P<tras>\s*[.!?…~]|\s*$)?)",
        re.IGNORECASE,
    )

    def _sust(m: re.Match) -> str:
        if m.group("tras") is not None:
            return m.group(0)  # "Me alegra ser tu doctora 1Hero." -> 1Hero es un vocativo sin coma
        if re.search(r"(?<!\w)(?:un|una|unos|unas)\s+$", m.string[max(0, m.start() - 6):m.start()], re.IGNORECASE):
            return m.group(0)  # "encontrar una novia Carla para..." -> vocativo sin coma
        if not m.group("art") and not _titulo_permitido(m.string[:m.start()]):
            return m.group(0)  # "una mujer pequeña 1Hero": el adjetivo es de "mujer"
        adj = m.group("adj")
        nuevo_adj = _con_mayusculas_de(adj, mapa.get(adj.lower(), adj))
        art = m.group("art") or ""
        if art:
            palabra = art.strip()
            nuevo_art = _ARTICULOS[genero].get(re.sub(r"\s+", " ", palabra.lower()), palabra)
            art = art.replace(palabra, _con_mayusculas_de(palabra, nuevo_art), 1)
        return f"{art}{nuevo_adj} "

    res = patron.sub(_sust, texto)
    if genero == HOMBRE:
        res = re.sub(rf"(?<!{_L})([Ss])eñorita\s+(?={_patron_nombre(nombre)})", lambda m: f"{m.group(1)}eñor ", res)
    return res


def corregir_tercera_persona(texto: str, nombre: str, genero: str) -> str:
    """'Ana está cansado' -> 'Ana está cansada' cuando se sabe que Ana es mujer."""
    if not texto or not nombre or genero not in (HOMBRE, MUJER) or nombre not in texto:
        return texto
    mapa = _MAPA[genero]
    adjetivos = _ADJ_FEM if genero == HOMBRE else _ADJ_MASC
    patron = re.compile(
        rf"{_patron_nombre(nombre)}\s+(?:no\s+|ya\s+|también\s+|nunca\s+|siempre\s+|todavía\s+|aún\s+)?"
        rf"(?:{_V3}){_ADV}{_ANTES_ADJ}(?P<adj>{adjetivos})(?!{_L}){_TRAS_ADJ}"
    )
    def _sust(m: re.Match) -> str:
        previo = m.string[:m.start()]
        if _PREPOSICION_PREVIA.search(previo[-12:]):
            return m.group(0)  # "el padre de Ana no está enojado": el sujeto es "el padre"
        if not _inicio_de_clausula(previo):
            return m.group(0)  # "la cosa en la que trabaja Emily es seria": Emily no es el sujeto de "es"
        return _cambiar_final(m, mapa)

    res = patron.sub(_sust, texto)
    incorrecta, correcta = ("misma", "mismo") if genero == HOMBRE else ("mismo", "misma")
    res = re.sub(rf"({_patron_nombre(nombre)})\s+{incorrecta}(?!{_L})", lambda m: f"{m.group(1)} {correcta}", res)
    return corregir_titulos(res, nombre, genero)


# --------------------------------------------------------------------------- Detección
_DET1 = {HOMBRE: _patron(_V1_SEGURAS, _ADJ_MASC), MUJER: _patron(_V1_SEGURAS, _ADJ_FEM)}
_DET1_YO = {
    HOMBRE: re.compile(rf"\byo\s+(?:no\s+)?(?:{_V1_AMBIGUAS}){_ADV}{_ANTES_ADJ}(?:{_ADJ_MASC})(?!{_L})", re.IGNORECASE),
    MUJER: re.compile(rf"\byo\s+(?:no\s+)?(?:{_V1_AMBIGUAS}){_ADV}{_ANTES_ADJ}(?:{_ADJ_FEM})(?!{_L})", re.IGNORECASE),
}
_DET2 = {HOMBRE: _patron(_V2, _ADJ_MASC), MUJER: _patron(_V2, _ADJ_FEM)}
_DET_BIENVENIDO = {
    HOMBRE: re.compile(rf"(?<!{_L}){_NO_ES_SALUDO}bienvenido(?!{_L}){_NO_IMPERSONAL}", re.IGNORECASE),
    MUJER: re.compile(rf"(?<!{_L}){_NO_ES_SALUDO}bienvenida(?!{_L}){_NO_IMPERSONAL}", re.IGNORECASE),
}
# Para detectar "yo mismo" (masculino) se usa el patrón que busca "mismo", que es el de MUJER.
_DET_MISMO_1P = {HOMBRE: _MISMO_1P[MUJER], MUJER: _MISMO_1P[HOMBRE]}
_DET_MISMO_2P = {HOMBRE: _MISMO_2P[MUJER], MUJER: _MISMO_2P[HOMBRE]}


def marcas_genero(texto: str) -> set[str]:
    """Marcas de género en 1.ª y 2.ª persona del singular presentes en una traducción.

    Devuelve un subconjunto de {'1m', '1f', '2m', '2f'}:
      '1m' = quien habla se describe en masculino ("estoy cansado", "yo mismo"),
      '2f' = se describe en femenino a quien escucha ("¿estás lista?", "¡bienvenida!")...
    """
    if not texto:
        return set()
    marcas: set[str] = set()
    for genero, letra in ((HOMBRE, "m"), (MUJER, "f")):
        if _DET1[genero].search(texto) or _DET1_YO[genero].search(texto) or _DET_MISMO_1P[genero].search(texto):
            marcas.add(f"1{letra}")
        if _DET2[genero].search(texto) or _DET_BIENVENIDO[genero].search(texto) or _DET_MISMO_2P[genero].search(texto):
            marcas.add(f"2{letra}")
    return marcas


def contradice_genero(texto: str, persona: str, genero: str) -> bool:
    """True si ``texto`` marca la ``persona`` ('1' o '2') con el género contrario a ``genero``."""
    if genero not in (HOMBRE, MUJER):
        return False
    contraria = "f" if genero == HOMBRE else "m"
    return f"{persona}{contraria}" in marcas_genero(texto)


# --------------------------------------------------------------------------- Inglés con género
# Palabras inglesas que fijan el género de una PERSONA (tratamientos, parentesco, pareja, insultos).
# Sirven para no fabricar ejemplos imposibles al invertir el género de alguien: "Thank you, sir" no
# puede decírsele a una mujer. Quedan fuera las que casi siempre significan otra cosa ("miss" = echar
# de menos, "pretty" = bastante, "god" en "oh my god"); "man" entra aunque a veces sea interjección:
# es mejor perder un ejemplo que enseñar uno falso.
_EN_PERSONA = {
    HOMBRE: re.compile(
        r"\b(?:man|men|boys?|guys?|dudes?|bros?|brothers?|sons?|sirs?|mister|mr|gentlem[ae]n|husbands?|"
        r"boyfriends?|kings?|princes?|lords?|handsome|studs?|daddy|dads?|fathers?|grandpas?|uncles?|"
        r"nephews?|hero(?:es)?|lads?|fellas?|priests?|monks?|waiters?|policem[ae]n)\b",
        re.IGNORECASE),
    MUJER: re.compile(
        r"\b(?:wom[ae]n|girls?|lady|ladies|ma['’]?am|madam|sisters?|sis|daughters?|wife|wives|"
        r"girlfriends?|queens?|princess(?:es)?|mommy|moms?|mothers?|grandmas?|aunts?|nieces?|heroines?|"
        r"lass(?:es)?|gals?|mistress(?:es)?|nuns?|witch(?:es)?|actress(?:es)?|waitress(?:es)?|"
        r"goddess(?:es)?|bitch(?:es)?|sluts?|whores?)\b",
        re.IGNORECASE),
}


def personas_con_genero_en(texto: str) -> set[str]:
    """Géneros que el INGLÉS fija con palabras de persona.

    "Thank you, sir." -> {'hombre'}; "Good girl." -> {'mujer'}; "I'm ready." -> set().
    No mira pronombres (he/she): en un diálogo casi siempre hablan de otra persona.
    """
    if not texto:
        return set()
    return {genero for genero, patron in _EN_PERSONA.items() if patron.search(texto)}
