"""Utilidades de texto compartidas por todos los pasos.

Antes había tres versiones distintas de la regex de etiquetas repartidas por los scripts;
ahora hay una sola definición aquí.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

# genero.py no importa nada del paquete: no hay ciclo de importación.
from .genero import corregir_primera_persona, es_genero_marcado

# --------------------------------------------------------------------------- Regex
# Etiquetas que la traducción DEBE conservar (se comparan con conteo):
#   %s %d %1 ... | \n \r literales | {0} {name} | [tag] [/tag] | \C[3] \I[12] \F[name]... | <br> <center> | \^ \! \|
# {…} y […] solo cuentan como etiqueta si NO tienen espacios y miden ≤ 40 caracteres: así
# '{name}', '[pic=2]' o '[/b]' son etiquetas, pero '{SEARCH DELETED}' o '{Lesson 1: Home Row}'
# son texto normal (antes se trataban como etiquetas y forzar_etiquetas las pegaba al principio).
PATRON_ETIQUETAS = re.compile(
    r"(%[sdfSDF]|%\d+|\\n|\\r|\{[^{}\s]{1,40}\}|\[[^\[\]\s]{1,40}\]|\\[A-Za-z]+\[[^\]]*\]|<[A-Za-z0-9_/]+>|\\[.!^$|><{}])"
)

# Todos los códigos de control (más amplio): se usa para medir el texto visible y para
# saber si una cadena tiene algo que traducir. Incluye \! \. \| \{ \} \^ \$ y <...>.
PATRON_CODIGOS = re.compile(
    r"(%[sdfSDF]|%\d+|\\n|\\r|\{[^{}\s]{1,40}\}|\[[^\[\]\s]{1,40}\]|\\[A-Za-z]+\[[^\]]*\]"
    r"|\\[A-Za-z{}<>|.!^$]|<[^>]*>)"
)

# Códigos de control al inicio de un diálogo (caja de nombre \N<...>, caras, esperas...).
# Se apartan antes de traducir y se vuelven a pegar intactos.
PATRON_PREFIJO = re.compile(
    r"^(?:\\N<[^>]*>|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}|.!^$<>](?![A-Za-z])|\s)+"
)

# Caja de nombre de quien habla: \N<\C[5]Nombre\C[0]>
PATRON_NOMBRE_HABLANTE = re.compile(r"\\N<(\\C\[\d+\])?([^>\\]+)(\\C\[\d+\])?>")

# Anchura aproximada que ocupan en pantalla los códigos que se expanden al mostrarse.
_ANCHO_CODIGO = {"N": 8, "P": 8, "V": 4, "I": 2, "G": 1}
_PATRON_ANCHO = re.compile(r"\\([A-Za-z]+)\[[^\]]*\]")


# --------------------------------------------------------------------------- Básicos
def tiene_letras(texto: str) -> bool:
    return any(c.isalpha() for c in texto)


def tiene_texto_visible(texto: str) -> bool:
    """True si, quitando los códigos de control, queda alguna letra que traducir."""
    return tiene_letras(PATRON_CODIGOS.sub("", texto))


def sanitizar(texto: str) -> str:
    """Fusiona saltos de línea reales que fragmentan oraciones.

    Los desarrolladores parten frases largas con saltos para que quepan en el bocadillo.
    Eso confunde a la IA, que recibe trozos sin sentido; aquí se unen en una sola oración.
    """
    limpio = texto.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r" {2,}", " ", limpio).strip()


sanitize_text = sanitizar  # nombre antiguo, por compatibilidad


def separar_prefijo(texto: str) -> tuple[str, str]:
    """'\\N<Ana>\\C[2]Hola' -> ('\\N<Ana>\\C[2]', 'Hola')."""
    m = PATRON_PREFIJO.match(texto)
    prefijo = m.group(0) if m else ""
    return prefijo, texto[len(prefijo):]


# --------------------------------------------------------------------------- Puntuación y separación
PATRON_PREFIJO_V21 = re.compile(
    r"^((?:NPC|[A-Za-z0-9]{2},[A-Za-z0-9]{2},[A-Za-z0-9]{2}|(?=[A-Za-z0-9><_\-\^!~*#@+=]{4,18}\.)[A-Za-z0-9><_\-\^!~*#@+=]*[A-Z][A-Za-z0-9><_\-\^!~*#@+=]*[A-Z][A-Za-z0-9><_\-\^!~*#@+=]*))\.(.*)$",
    re.DOTALL,
)
PATRON_PUNTO_PEGADO = re.compile(r"([a-záéíóúñ])\.([A-ZÁÉÍÓÚÑ¿¡])")
PATRON_ELIPSIS_PEGADA = re.compile(r"([a-záéíóúñA-ZÁÉÍÓÚÑ0-9!?]\.{2,})([A-ZÁÉÍÓÚÑ¿¡])")
PATRON_SIGNO_PEGADO = re.compile(r"([a-záéíóúñA-ZÁÉÍÓÚÑ0-9][?!]+)([A-ZÁÉÍÓÚÑ¿¡])")


def _separar_cuerpo_pegado(cuerpo: str) -> str:
    cuerpo = PATRON_ELIPSIS_PEGADA.sub(r"\1 \2", cuerpo)
    cuerpo = PATRON_PUNTO_PEGADO.sub(r"\1. \2", cuerpo)
    return PATRON_SIGNO_PEGADO.sub(r"\1 \2", cuerpo)


def corregir_puntuacion_pegada(texto: str) -> str:
    """Corrige oraciones pegadas sin espacio tras punto, puntos suspensivos, interrogación o exclamación.

    Conserva intactos los prefijos de sprite en RPG Maker (ej: 'HeFrOp.', 'MiHaEx^.' o 'Br,fr,op.')
    así como llamadas de código Javascript (ej: 'Galv.CACHE.load', 'ysp.VideoPlayer').
    """
    if not texto or not isinstance(texto, str):
        return texto
    if any(
        kw in texto
        for kw in ("SceneManager.", "Galv.", "StorageManager.", "PluginManager.", ".prototype.", "ysp.", "$game")
    ) or re.search(r"\b[A-Za-z_$][\w$]*\.[A-Za-z_$][\w$]*\s*\(", texto):
        return texto

    m_pref = PATRON_PREFIJO_V21.match(texto)
    if m_pref:
        pref = m_pref.group(1) + "."
        cuerpo = m_pref.group(2)
        return pref + _separar_cuerpo_pegado(cuerpo)

    return _separar_cuerpo_pegado(texto)


# --------------------------------------------------------------------------- Etiquetas
def extraer_etiquetas(texto: str) -> list[str]:
    return PATRON_ETIQUETAS.findall(texto)


def comparar_etiquetas(original: str, traducido: str) -> tuple[bool, list[str], list[str]]:
    """Devuelve (coinciden, faltan, sobran) comparando con conteo, no solo conjuntos."""
    c_orig, c_trad = Counter(extraer_etiquetas(original)), Counter(extraer_etiquetas(traducido))
    faltan = list((c_orig - c_trad).elements())
    sobran = list((c_trad - c_orig).elements())
    return not faltan and not sobran, faltan, sobran


def describir_fallo(faltan: list[str], sobran: list[str]) -> str:
    partes = []
    if faltan:
        partes.append(f"faltan {faltan}")
    if sobran:
        partes.append(f"sobran {sobran}")
    return "; ".join(partes) or "sin fallos"


# Pausas de RPG Maker: \! espera a que se pulse una tecla, \| espera 1 s, \. espera 1/4 s.
_PAUSAS = ("\\!", "\\|", "\\.")
# Fin de frase seguido de espacio: "Yeah... " | "¿Qué?» "
_FIN_DE_FRASE = re.compile(r"[.!?…]+[\"'”»)\]]*\s+")


def _colocar_pausas(original: str, traducido: str, pendientes: Counter) -> str:
    """Las pausas que el modelo perdió a mitad de frase van al mismo hueco entre frases de la traducción.

    'Yeah... \\!Becoming…' + 'Sí... ¡Ser…' -> 'Sí... \\!¡Ser…'. Al principio harían pulsar una tecla antes de
    ver el texto. Se quedan sin colocar (y siguen pendientes) si la traducción no tiene ese hueco.
    """
    huecos = [m.end() for m in _FIN_DE_FRASE.finditer(traducido) if m.end() < len(traducido)]
    if not huecos:
        return traducido
    inserciones: list[tuple[int, str]] = []
    for m in PATRON_ETIQUETAS.finditer(original):
        etiqueta = m.group(0)
        if etiqueta not in _PAUSAS or pendientes[etiqueta] <= 0:
            continue
        antes = original[:m.start()]
        if not tiene_texto_visible(antes) or not tiene_texto_visible(original[m.end():]):
            continue  # al principio o al final: lo hace forzar_etiquetas
        n = len(_FIN_DE_FRASE.findall(antes + " "))
        if n == 0:
            continue
        inserciones.append((huecos[min(n, len(huecos)) - 1], etiqueta))
        pendientes[etiqueta] -= 1
    for pos, etiqueta in sorted(inserciones, reverse=True):
        resto = traducido[pos:]
        if etiqueta == "\\|" and resto.startswith("|"):  # el modelo dejó la barra sin la "\"
            resto = resto[1:]
        traducido = traducido[:pos] + etiqueta + resto
    return traducido


def forzar_etiquetas(original: str, traducido: str) -> str:
    """Último recurso: añade las etiquetas que falten (respetando duplicados).

    Las que en el original estaban en la mitad final (p. ej. ``[pic=9]`` o ``</i>`` al cierre) se
    añaden al FINAL; el resto al principio. Antes se pegaban todas al principio.
    """
    _, faltan, _ = comparar_etiquetas(original, traducido)
    if not faltan:
        return traducido
    pendientes = Counter(faltan)
    traducido = _colocar_pausas(original, traducido, pendientes)
    if not +pendientes:
        return traducido
    mitad = len(original) / 2
    delante: list[str] = []
    detras: list[str] = []
    for m in PATRON_ETIQUETAS.finditer(original):
        etiqueta = m.group(0)
        if pendientes[etiqueta] <= 0:
            continue
        pendientes[etiqueta] -= 1
        if m.start() >= mitad:
            hueco = " " if m.start() > 0 and original[m.start() - 1].isspace() and not detras else ""
            detras.append(hueco + etiqueta)
        else:
            delante.append(etiqueta)
    resultado = traducido
    if delante:
        sep = "" if delante[-1].startswith("<") else " "
        resultado = "".join(delante) + sep + resultado
    if detras:
        cola = "".join(detras)
        m_pic = re.search(r"(\s*\[[A-Za-z]+=[^\]\s]*\])+$", resultado)
        if m_pic and all(et.strip().startswith("</") for et in detras):
            resultado = resultado[:m_pic.start()] + cola.lstrip() + m_pic.group(0)
        else:
            resultado = resultado + cola
    return resultado


# Etiquetas que el modelo puede inventar y que es seguro quitar si el original no las tenía.
_ETIQUETA_ELIMINABLE = re.compile(r"^(?:\[[^\]]*\]|\{[^}]*\}|<[^>]*>)$")


def _tipo_etiqueta(etiqueta: str) -> str:
    """'[pic=9]' -> '[pic', '<color=#f00>' -> '<color', '</i>' -> '</i'."""
    m = re.match(r"^([\[{<]/?[A-Za-z_]*)", etiqueta)
    return m.group(1).lower() if m else etiqueta


def quitar_etiquetas_inventadas(original: str, traducido: str) -> str:
    """Corrige etiquetas que el modelo ha añadido sin existir en el original.

    - Si alteró una etiqueta (``[pic=9]`` -> ``[pic=n]``) y falta la buena, la sustituye.
    - Si simplemente la inventó, la elimina.
    Solo actúa sobre etiquetas de tipo ``[...]``, ``{...}`` y ``<...>``.
    """
    ok, faltan, sobran = comparar_etiquetas(original, traducido)
    if ok or not sobran:
        return traducido
    resultado = traducido
    faltan_restantes = list(faltan)
    for extra in sobran:
        if not _ETIQUETA_ELIMINABLE.match(extra):
            continue
        tipo = _tipo_etiqueta(extra)
        sustituta = next((f for f in faltan_restantes if _tipo_etiqueta(f) == tipo), None)
        pos = resultado.rfind(extra)
        if pos < 0:
            continue
        if sustituta is not None:
            faltan_restantes.remove(sustituta)
            resultado = resultado[:pos] + sustituta + resultado[pos + len(extra):]
        else:
            resultado = resultado[:pos] + resultado[pos + len(extra):]
    resultado = re.sub(r" {2,}", " ", resultado).strip()
    return resultado


# --------------------------------------------------------------------------- Envoltorio
# Etiquetas "envolventes" que se pueden apartar antes de traducir y volver a pegar intactas:
# rich text (<i>, </i>, <color=#fff>, <size=20>...) y marcas tipo Pixel Crushers ([pic=3], [picc=11]...).
_TOKEN_ENVOLTORIO = (
    r"(?:</?[A-Za-z][A-Za-z0-9_-]*(?:=[^<>]*)?\s*/?>"
    r"|\[[A-Za-z]+=[^\]\s]*\]"
    r"|\[/?(?:f|a|auto|nosubtitle|em\d)\]"
    r"|\s)"
)
_PATRON_PREFIJO_ENV = re.compile(rf"^{_TOKEN_ENVOLTORIO}+")
_PATRON_SUFIJO_ENV = re.compile(rf"{_TOKEN_ENVOLTORIO}+$")


def separar_envoltorio(texto: str) -> tuple[str, str, str]:
    """'<i>Hola [x]</i> [pic=2]' -> ('<i>', 'Hola [x]', '</i> [pic=2]').

    Así el modelo solo ve el núcleo y no puede romper, perder ni inventar las etiquetas
    del principio y del final. Si el núcleo no tiene letras se devuelve ('', texto, '').
    """
    m = _PATRON_PREFIJO_ENV.match(texto)
    prefijo = m.group(0) if m else ""
    resto = texto[len(prefijo):]
    m = _PATRON_SUFIJO_ENV.search(resto)
    sufijo = m.group(0) if m else ""
    nucleo = resto[:len(resto) - len(sufijo)] if sufijo else resto
    if not tiene_letras(nucleo):
        return "", texto, ""
    return prefijo, nucleo, sufijo


# --------------------------------------------------------------------------- Longitud y saltos
def longitud_visible(texto: str) -> int:
    """Longitud aproximada en pantalla: los códigos de color no ocupan sitio y
    \\N[n] / \\V[n] / \\I[n] se cuentan por lo que ocupan al expandirse."""
    extra = sum(_ANCHO_CODIGO.get(m.group(1).upper(), 0) for m in _PATRON_ANCHO.finditer(texto))
    return len(PATRON_CODIGOS.sub("", texto)) + extra


def ajustar_lineas(texto: str, ancho: int) -> list[str]:
    """Reparte el texto en líneas de como mucho ``ancho`` caracteres VISIBLES.

    Antes se contaban los códigos (\\C[4]...) como texto y las líneas se cortaban antes de tiempo.
    """
    lineas: list[str] = []
    actual: list[str] = []
    largo = 0
    for palabra in texto.split():
        lp = longitud_visible(palabra)
        if actual and largo + 1 + lp > ancho:
            lineas.append(" ".join(actual))
            actual, largo = [palabra], lp
        else:
            largo += lp + (1 if actual else 0)
            actual.append(palabra)
    if actual:
        lineas.append(" ".join(actual))
    return lineas or [""]


def reinsertar_saltos(traducido: str, segmentos_originales: list[str]) -> str:
    """Recoloca los saltos '\\n' literales en la traducción, en los espacios más cercanos a la
    posición proporcional que tenían en el original (así el texto sigue cabiendo en la ventana)."""
    total = sum(len(s.strip()) for s in segmentos_originales) or 1
    espacios = [i for i, c in enumerate(traducido) if c == " "]
    elegidos: list[int] = []
    acumulado = 0
    for seg in segmentos_originales[:-1]:
        acumulado += len(seg.strip())
        objetivo = acumulado / total * len(traducido)
        candidatos = [s for s in espacios if not elegidos or s > elegidos[-1]]
        if not candidatos:
            break
        # Si en inglés el salto iba tras un final de frase, se prefiere un final de frase cercano
        fin_de_frase = seg.rstrip()[-1:] in ".!?…)"
        bonus = 0.25 * len(traducido) if fin_de_frase else 0

        def puntuacion(s: int) -> float:
            return abs(s - objetivo) - (bonus if traducido[s - 1] in ".!?…)" else 0)

        elegidos.append(min(candidatos, key=puntuacion))
    salida = list(traducido)
    for pos in elegidos:
        salida[pos] = "\\n"
    return "".join(salida)


reinsert_breaks = reinsertar_saltos  # nombre antiguo, por compatibilidad


# --------------------------------------------------------------------------- Limpieza de respuestas
_RUIDO_INICIAL = re.compile(r"^(?:Respuesta:|### Response:|Traducción:)\s*", re.IGNORECASE)
_NUMERACION = re.compile(r"^(?:\d+[.)]\s+|-\s+)")
# Ecos del prompt que el modelo a veces antepone: "Traducción de videojuego RPG del español de España: ..."
_ECO_PROMPT = re.compile(
    r"(?:Traducci[oó]n|Tu respuesta|Texto(?: RPG)?)[^:\n]{0,80}?(?:videojuego|RPG|espa[ñn]ol|ingl[eé]s)[^:\n]{0,60}:\s*",
    re.IGNORECASE,
)
_COLA_PROMPT = re.compile(r"\s*Traduce este texto[^\n]*$", re.IGNORECASE)
_TOKENS_ESPECIALES = ("<|im_start|>", "<|im_end|>", "<|eot_id|>", "<|end_of_text|>", "### Instruction")
_COMILLAS = [('"', '"'), ("'", "'"), ("“", "”"), ("«", "»")]


def _reemplazar_preservando_mayus(patron: str, reemplazo: str, texto: str) -> str:
    def _repl(m: re.Match) -> str:
         palabra = m.group(0)
         if palabra.isupper():
             return reemplazo.upper()
         if palabra[0].isupper():
             return reemplazo[0].upper() + reemplazo[1:]
         return reemplazo
    return re.sub(patron, _repl, texto, flags=re.IGNORECASE)


# Correcciones propias de los juegos de cada usuario (nombres de personajes y lugares que el modelo deforma,
# comodines del protagonista...). Viven en un archivo PRIVADO que no se sube al repositorio; el formato está en
# glosarios/correcciones_locales.ejemplo.json. Sin archivo, el retoque es solo el genérico.
ARCHIVO_CORRECCIONES_LOCALES = Path(__file__).resolve().parent.parent / "glosarios" / "correcciones_locales.json"


@lru_cache(maxsize=1)
def correcciones_locales() -> dict:
    """{'etapas': {etapa: [(si_original, buscar, flags, cambiar, preservar_mayusculas)]},
    'masculinos': set, 'femeninos': set} leídas de ARCHIVO_CORRECCIONES_LOCALES (vacío si no existe)."""
    try:
        datos = json.loads(ARCHIVO_CORRECCIONES_LOCALES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"etapas": {}, "masculinos": frozenset(), "femeninos": frozenset()}
    etapas = {}
    for etapa, reglas in (datos.get("etapas") or {}).items():
        compiladas = []
        for regla in reglas if isinstance(reglas, list) else ():
            try:
                si = re.compile(regla["si_original"]) if regla.get("si_original") else None
                flags = re.IGNORECASE if regla.get("ignorar_mayusculas") else 0
                re.compile(regla["buscar"], flags)
            except (KeyError, re.error, TypeError):
                continue  # una regla mal escrita no rompe la traducción
            compiladas.append((si, regla["buscar"], flags, regla.get("cambiar", ""),
                               bool(regla.get("preservar_mayusculas"))))
        etapas[etapa] = compiladas
    codigos = datos.get("codigos_hablante") or {}
    return {"etapas": etapas, "masculinos": frozenset(codigos.get("masculinos") or ()),
            "femeninos": frozenset(codigos.get("femeninos") or ())}


def _aplicar_locales(r: str, orig_low: str, etapa: str) -> str:
    for si, buscar, flags, cambiar, preservar in correcciones_locales()["etapas"].get(etapa, ()):
        if si is not None and not si.search(orig_low):
            continue
        r = _reemplazar_preservando_mayus(buscar, cambiar, r) if preservar else re.sub(buscar, cambiar, r, flags=flags)
    return r


def postprocesar_traduccion(texto: str, original: str = "") -> str:
    """Corrige errores recurrentes del LLM: bucles sin comas, tartamudeos en inglés,
    falsos amigos, calcos estructurales y signos de puntuación desemparejados."""
    if not texto:
        return texto
    r = texto
    orig_low = original.lower() if original else ""

    # 0a. Normalizar etiquetas HTML con espacios espurios añadidos por el LLM (< br >, < center >, etc.)
    r = re.sub(r"<\s*(/?)\s*(?:centro|centrar|centrado)\s*(/?)>", r"<\1center\2>", r, flags=re.IGNORECASE)
    r = re.sub(r"<\s*(/?)\s*([A-Za-z0-9_-]+)\s*(/?)>", r"<\1\2\3>", r)
    r = re.sub(r"<\s*>\s*", lambda _m: "<center>" if "<center>" in orig_low and "<center>" not in r.lower() else "", r)
    # Colapsar espacios entre etiquetas estructurales consecutivas (ej: <center> <br> <br> -> <center><br><br>)
    r = re.sub(r"(<(?:center|br|wordwrap|/center|/br)/?>)\s+(<(?:center|br|wordwrap|/center|/br)/?>)", r"\1\2", r, flags=re.IGNORECASE)
    r = re.sub(r"(<(?:center|br|wordwrap|/center|/br)/?>)\s+(<(?:center|br|wordwrap|/center|/br)/?>)", r"\1\2", r, flags=re.IGNORECASE)
    # Quitar espacios sobrantes pegados a etiquetas estructurales y su contenido
    r = re.sub(r"(<(?:center|wordwrap|br)/?>)\s+(?=\S)", r"\1", r, flags=re.IGNORECASE)
    r = re.sub(r"(</(?:center|wordwrap)/?>)\s+(?=\S)", r"\1", r, flags=re.IGNORECASE)
    r = re.sub(r"\s+(</(?:center|br|wordwrap)>)", r"\1", r, flags=re.IGNORECASE)

    # 0b. Reparar códigos de control de RPG Maker corrompidos por el LLM
    r = re.sub(r"\^\s*\\", r"\\^", r)
    r = re.sub(r"(?<!\\)\^", r"\\^", r)
    r = re.sub(r"\\\s*([A-Za-z]+)\s*\[\s*([^\]]+?)\s*\]", r"\\\1[\2]", r)
    r = re.sub(r"\\\s*([.!^$|><{}])", r"\\\1", r)
    # Reparar etiquetas de fuente tipo Yanfly (\fn<FontName>)
    r = re.sub(r"\\fn\\([A-Za-z0-9_-]+)", r"\\fn<\1>", r)
    r = re.sub(r"(?<!\\fn)<(Arial|Cinzel-Black|Cinzel-Regular|Times New Roman)>", r"\\fn<\1>", r, flags=re.IGNORECASE)
    r = re.sub(r"\\fn<([^>]+)>\s*\\n<[^>]*>", r"\\fn<\1>", r)
    if original and re.search(r"\\?\^\s*$", original):
        r = re.sub(r"(?:\s*\\\s*\^|\s*\^\s*\\|\s*(?<!\\)\^)\s*$", r"\\^", r)

    # 0c. Fugas de otros idiomas (alemán, francés) para respuestas monosilábicas o aisladas
    if "nein" not in orig_low:
        r = re.sub(r"\bNein\b", "No", r)
        r = re.sub(r"\bnein\b", "no", r)
    if "ja" not in orig_low and ("yes" in orig_low or orig_low.strip() == "yes"):
        r = re.sub(r"\bJa\b", "Sí", r)
        r = re.sub(r"\bja\b", "sí", r)
    if "oui" not in orig_low:
        r = re.sub(r"\bOui\b", "Sí", r)
        r = re.sub(r"\boui\b", "sí", r)
    if "non" not in orig_low and orig_low.strip() == "no":
        r = re.sub(r"\bNon\b", "No", r)
        r = re.sub(r"\bnon\b", "no", r)

    # 0d. Corrección determinista de opciones de interfaz mal traducidas
    if orig_low.strip() in ("always dash", "toggle sprint"):
        r = "Correr siempre"
    elif orig_low.strip() in ("command remember", "remember commands"):
        r = "Recordar comandos"
    elif orig_low.strip() == "fullscreen":
        r = "Pantalla completa"
    elif orig_low.strip() in ("low quality video", "low-quality video"):
        r = "Vídeo baja calidad"
    elif orig_low.strip() == "message speed":
        r = "Velocidad del texto"
    elif orig_low.strip() == "instant":
        r = "Instantáneo"
    elif orig_low.strip() == "shop at lovense":
        r = "Tienda Lovense"
    elif orig_low.strip() == "lovense remote":
        r = "Control Lovense"
    elif orig_low.strip() == "lovense intensity":
        r = "Intensidad Lovense"
    elif orig_low.strip() == "roll credits":
        r = "Ver créditos"
    elif orig_low.strip() == "credits":
        r = "Créditos"
    elif orig_low.strip() == "scene player":
        r = "Reproductor de escenas"
    elif orig_low.strip() == "play scene":
        r = "Ver escena"
    elif orig_low.strip() == "cloud save":
        r = "Guardado en la nube"
    elif orig_low.strip() == "chapter warp":
        r = "Saltar de capítulo"
    elif orig_low.strip() == "yes":
        r = "SÍ" if original.isupper() else ("Sí" if (original.istitle() or texto.istitle()) else "sí")
    elif orig_low.strip() == "no":
        r = "NO" if original.isupper() else ("No" if (original.istitle() or texto.istitle()) else "no")
    elif orig_low.strip() == "on":
        r = "SÍ"
    elif orig_low.strip() == "off":
        r = "NO"

    r = re.sub(r"\bSiempre Dasher\b", "Correr siempre", r, flags=re.IGNORECASE)
    r = re.sub(r"\bOrden Recuerda\b", "Recordar comandos", r, flags=re.IGNORECASE)
    r = _aplicar_locales(r, orig_low, "interfaz")

    # 0f. Corrección de "Miss" traducido erróneamente como "fallo" (falso amigo del inglés)
    r = re.sub(r"\bla\s+fallo\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+)", r"la señorita \1", r)
    r = re.sub(r"(?<!la\s)(?<!una\s)\bfallo\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+)", r"señorita \1", r)
    r = re.sub(r"\bFallo\s+(?!de\b)([A-ZÁÉÍÓÚ][a-záéíóúñ]+)", r"Señorita \1", r)
    r = re.sub(r",\s*fallo([.,!?])", r", señorita\1", r)
    r = re.sub(r"¡Fallo!\s*(?=[A-ZÁÉÍÓÚ¿¡])", "¡Señorita! ", r)
    r = re.sub(r"\bFALLO DEL LLAMADO AL CULO\b", "LLAMADA PARA FOLLAR FALLIDA", r, flags=re.IGNORECASE)
    r = re.sub(r"\bentonces mejor te muevas\b", "será mejor que te des prisa", r, flags=re.IGNORECASE)

    # 0g. Términos específicos de misiones y menú de móvil
    r = _reemplazar_preservando_mayus(r"\b(?:llamar\s+a\s+una\s+)?cita\s+de\s+soltero\b", "cita íntima", r)
    r = _reemplazar_preservando_mayus(r"\bpara\s+investigar\s+el\s+quejoso\b", "para investigar la denuncia por ruido", r)
    r = _reemplazar_preservando_mayus(r"\b(?:el\s+)?ruido\s+de\s+la\s+queja\b", "la queja por ruido", r)

    # 1. Bucle específico de "correr el riesgo de correr el riesgo..." (alucinación con 'cum')
    if re.search(r"correr\s+el\s+riesgo\s+de\s+correr", r, re.IGNORECASE):
        r = re.sub(
            r"\bno\s+corras\s+el\s+riesgo(?:\s+de\s+correr(?:\s+el(?:\s+riesgo)?)?)+(?:\s+(?:de|correr|el|riesgo))*",
            "no te corras dentro",
            r,
            flags=re.IGNORECASE,
        )
        r = re.sub(
            r"\ba\s+correr\s+el\s+riesgo(?:\s+de\s+correr(?:\s+el(?:\s+riesgo)?)?)+(?:\s+(?:de|correr|el|riesgo))*",
            "a correrte",
            r,
            flags=re.IGNORECASE,
        )
        reemplazo_cum = "correrme" if any(k in orig_low for k in ("i'm", "i am", "gonna", "going to")) else "córrete"
        r = re.sub(
            r"\bcorrer\s+el\s+riesgo(?:\s+de\s+correr(?:\s+el(?:\s+riesgo)?)?)+(?:\s+(?:de|correr|el|riesgo))*",
            reemplazo_cum,
            r,
            flags=re.IGNORECASE,
        )
        if ("¡" in r or "!" in orig_low) and not r.endswith(("!", "?", ".", "…", '"', "'")):
            r = r.rstrip() + "!"
        if "!" in orig_low and "¡" not in r and r.endswith("!"):
            r = "¡" + r.lstrip()

    # 2. Bucles generales de repetición de secuencias de palabras sin comas (4+ repeticiones)
    r_antes = r
    r = re.sub(
        r"\b([A-Za-zÁÉÍÓÚáéíóúñÑ]{2,}(?:\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]{1,15}){1,6})(?:\s+\1){3,}(?:\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]{1,15}){0,4}$",
        r"\1",
        r,
        flags=re.IGNORECASE,
    )
    r = re.sub(
        r"\b([A-Za-zÁÉÍÓÚáéíóúñÑ]{2,}(?:\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]{1,15}){1,6})(?:\s+\1){3,}",
        r"\1",
        r,
        flags=re.IGNORECASE,
    )
    if r != r_antes:
        r = re.sub(r"\s+\b(?:de|a|en|con|por|para|que|el|la|los|las|un|una)\s*$", "", r, flags=re.IGNORECASE)
        if "!" in r or "¡" in r:
            if not r.endswith(("!", "?", ".", "…")):
                r = r.rstrip() + "!"
        elif "¿" in r and not r.endswith("?"):
            r = r.rstrip() + "?"

    # 3. Tartamudeos con inicial inglesa residual ("R- correcto", "¡R- claro!", "¿Y-yah...?", "S-siento")
    r = re.sub(
        r"(^|[\s¡¿\"'(«])([A-Za-z])-\s+([A-Za-zÁÉÍÓÚáéíóúñÑ])([a-záéíóúñ]{2,})",
        lambda m: f"{m.group(1)}{m.group(3).upper() if m.group(2).isupper() else m.group(3).lower()}-{m.group(3).lower()}{m.group(4)}",
        r,
    )
    r = _reemplazar_preservando_mayus(r"\by-yah\b", "s-sí", r)
    r = _reemplazar_preservando_mayus(r"\b[rR]-derecha\b", "c-correcto", r)
    r = _reemplazar_preservando_mayus(r"\b[dD]-derecha\b", "c-correcto", r)
    r = re.sub(
        r"(?<![Ll]o\s)\b([Ss])-siento\b",
        lambda m: ("L-lo siento" if m.group(1).isupper() else "l-lo siento"),
        r,
    )

    # 4. Errores léxicos groseros y erratas verbales
    if "smoke" not in orig_low:
        r = _reemplazar_preservando_mayus(r"\bfúmeme\b", "fóllame", r)
        r = _reemplazar_preservando_mayus(r"\bfúmenme\b", "folladme", r)
    r = _reemplazar_preservando_mayus(r"\bvestamos\b", "vistamos", r)
    r = re.sub(r"\bVa[1I]erie\b", "Valerie", r)
    r = _reemplazar_preservando_mayus(r"\bmierda santa\b", "no me jodas", r)
    r = re.sub(r"¡Oh,\s*mi!", "¡Madre mía!", r)
    r = _reemplazar_preservando_mayus(r"\bcorrer de semen\b", "correrme", r)
    r = _reemplazar_preservando_mayus(r"\bte ayudaré a los dos\b", "os ayudaré a los dos", r)
    r = _reemplazar_preservando_mayus(r"\buna muestra segura\b", "una muerte segura", r)
    r = _reemplazar_preservando_mayus(r"\bel\s+vecino\s+Jaime\b", "la vecina Jaime", r)
    r = _reemplazar_preservando_mayus(r"\bun\s+vecino\s+llamado\s+Jaime\b", "una vecina llamada Jaime", r)
    r = _reemplazar_preservando_mayus(r"\bvecino\s+Jaime\b", "vecina Jaime", r)

    # 5. Calcos estructurales frecuentes del inglés y adaptación al español de España
    r = _reemplazar_preservando_mayus(r"\bluce como si\b", "parece como si", r)
    r = _reemplazar_preservando_mayus(r"\bluce como(?!\s+si\b)\b", "parece", r)
    r = _reemplazar_preservando_mayus(r"\bsuena como que\b", "parece que", r)
    r = _reemplazar_preservando_mayus(r"\bsuena como(?!\s+si\b)\b", "suena a", r)
    r = _reemplazar_preservando_mayus(r"\bno hace sentido\b", "no tiene sentido", r)
    r = _reemplazar_preservando_mayus(r"\bhace sentido\b", "tiene sentido", r)
    r = _reemplazar_preservando_mayus(r"\bmás temprano hoy\b", "hace un rato", r)
    r = _reemplazar_preservando_mayus(r"\bno puedo esperar a que\b", "me muero de ganas de que", r)
    r = _reemplazar_preservando_mayus(r"\bno puedo esperar (?:para|a)\b", "me muero de ganas de", r)
    r = _reemplazar_preservando_mayus(r"\bvergas\b", "pollas", r)
    r = _reemplazar_preservando_mayus(r"\bverga\b", "polla", r)
    r = _reemplazar_preservando_mayus(r"\bcomputadoras\b", "ordenadores", r)
    r = _reemplazar_preservando_mayus(r"\bcomputadora\b", "ordenador", r)
    r = _reemplazar_preservando_mayus(r"\bbinoculares\b", "prismáticos", r)
    r = _reemplazar_preservando_mayus(r"\bmaníes\b", "cacahuetes", r)
    r = _reemplazar_preservando_mayus(r"\bmanies\b", "cacahuetes", r)
    r = _reemplazar_preservando_mayus(r"\bclorinizaci[oó]n de choque\b", "cloración de choque", r)
    r = _reemplazar_preservando_mayus(r"\bvela llena de baches\b", "vela con relieve", r)
    r = _reemplazar_preservando_mayus(r"\bnota cryptica\b", "nota críptica", r)
    r = _reemplazar_preservando_mayus(r"\bestéreo port[aá]til\b", "radiocasete", r)
    r = _reemplazar_preservando_mayus(r"\bceniza de carbon\b", "ceniza de carbón", r)
    r = _reemplazar_preservando_mayus(r"\btalisman de los dioses\b", "talismán de los dioses", r)
    r = _reemplazar_preservando_mayus(r"\bllave de casillero\b", "llave de la taquilla", r)
    r = _reemplazar_preservando_mayus(r"\bremeras\b", "camisetas", r)
    r = _reemplazar_preservando_mayus(r"\bremera\b", "camiseta", r)
    r = _reemplazar_preservando_mayus(r"\b[ñn]uces\s+perforadas\b", "pezones perforados", r)
    r = _reemplazar_preservando_mayus(r"\bah[ií]gando\b", "ahogando", r)
    r = _reemplazar_preservando_mayus(r"\b(?:esas|estas)\s+viejas\s+juguetas\b", "esos juguetes viejos", r)
    r = _reemplazar_preservando_mayus(r"\bjuguetas\b", "juguetes", r)
    r = _reemplazar_preservando_mayus(r"\blaparte\b", "la parte", r)
    r = _reemplazar_preservando_mayus(r"\bcenaselegantes\b", "cenas elegantes", r)
    # "Fácil allí, cariño" ("Easy there") -> "Tranquila, cariño" (los nombres propios, en las correcciones locales)
    r = re.sub(
        r"\b([Ff]ácil)\s+(?:allí|ahí)(?=\s*,\s*(?:niña|chica|cariño|cielo|pequeña)\b)",
        lambda m: "Tranquila" if m.group(1)[0].isupper() else "tranquila",
        r,
    )
    r = _aplicar_locales(r, orig_low, "calcos")
    r = _reemplazar_preservando_mayus(r"\bfácil\s+(?:allí|ahí)\b", "tranquilo", r)
    r = _reemplazar_preservando_mayus(r"\bya se ha soltado la cateta\b", "ya se descubrió el pastel", r)
    r = _reemplazar_preservando_mayus(r"\bel gato (?:está|ha salido) fuera de la bolsa\b", "se ha descubierto el pastel", r)
    r = _reemplazar_preservando_mayus(r"\ben un jiffy\b", "en un santiamén", r)
    r = _reemplazar_preservando_mayus(r"\brata de alfombra\b", "mocoso", r)

    # 6. Correcciones dependientes del original en inglés
    if orig_low:
        if "tractor" in orig_low:
            r = _reemplazar_preservando_mayus(r"\b(?:tracto|tráctor)\b", "tractor", r)
        if "no way" in orig_low:
            r = _reemplazar_preservando_mayus(r"\bde ninguna manera\b", "ni de coña", r)

        if "curse" not in orig_low and re.search(r"\b(?:fuck\w*|damn\w*|dammit|shit\w*|hell\w*)\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bmaldici[oó]n,?\s+s[ií]\b", "joder, sí", r)
            r = _reemplazar_preservando_mayus(r"\bs[ií],\s*maldici[oó]n\b", "sí, joder", r)
            r = _reemplazar_preservando_mayus(r"(?<!la\s)(?<!una\s)(?<!esa\s)\bmaldici[oó]n\b", "joder", r)

        if re.search(r"\b(?:cum|cumming|came)\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bnecesito correr\b", "necesito correrme", r)
            r = _reemplazar_preservando_mayus(r"\bayudes a correr\b", "ayudes a correrme", r)
            r = _reemplazar_preservando_mayus(r"\bpuedes correr dentro\b", "puedes correrte dentro", r)
            r = _reemplazar_preservando_mayus(r"\bcorre en la boca\b", "córrete en la boca", r)
            r = _reemplazar_preservando_mayus(r"\bvoy\.\.\.\s*voy a acabar\b", "me... me voy a correr", r)
            r = _reemplazar_preservando_mayus(r"\btambién voy a acabar\b", "yo también me voy a correr", r)
            r = _reemplazar_preservando_mayus(r"\bvoy a acabar\b", "me voy a correr", r)
            r = _reemplazar_preservando_mayus(r"\bquiero acabar\b", "quiero correrme", r)
            r = _reemplazar_preservando_mayus(r"\bdejarías acabar\b", "dejarías correrme", r)
            r = _reemplazar_preservando_mayus(r"\bdéjame acabar\b", "déjame correrme", r)
            r = _reemplazar_preservando_mayus(r"\bvas a acabar\b", "te vas a correr", r)
            r = _reemplazar_preservando_mayus(r"\bvamos a acabar\b", "vamos a corrernos", r)
            r = _reemplazar_preservando_mayus(r"\bpudiera acabar\b", "pudiera correrme", r)
            r = _reemplazar_preservando_mayus(r"\btienes que acabar\b", "tienes que correrte", r)
            r = _reemplazar_preservando_mayus(r"\bte hice acabar\b", "te hice correrte", r)
            r = _reemplazar_preservando_mayus(r"\bhacerte acabar\b", "hacerte correr", r)
            r = _reemplazar_preservando_mayus(r"\bme vas a hacer acabar\b", "me vas a hacer correrme", r)
            r = _reemplazar_preservando_mayus(r"\bcasi acabas\b", "casi te corres", r)
            r = _reemplazar_preservando_mayus(r"\bacaba para mí\b", "córrete para mí", r)
            r = _reemplazar_preservando_mayus(r"\bacaba ahora\b", "córrete ahora", r)
            r = _reemplazar_preservando_mayus(r"\bacaba dentro\b", "córrete dentro", r)

        if re.search(r"\bfuck|\bpound", orig_low) and not re.search(r"\b(?:take|grab|pick|catch|hold)\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bcogiendo\b", "follando", r)
            r = _reemplazar_preservando_mayus(r"\bcogiste\b", "follaste", r)
            r = _reemplazar_preservando_mayus(r"\bcogió\b", "folló", r)
            r = _reemplazar_preservando_mayus(r"\bcogí\b", "follé", r)
            r = _reemplazar_preservando_mayus(r"\bcoger\b", "follar", r)

        if re.search(r"\bcar\b|\bcars\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bautos\b", "coches", r)
            r = _reemplazar_preservando_mayus(r"\bauto\b(?!-)", "coche", r)

        if re.search(r"\bconcrete\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bconcreto\b", "hormigón", r)

        if re.search(r"\blighter\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bencendedor\b", "mechero", r)

        if ("take my cock" in orig_low or "take my dick" in orig_low) and "out" not in orig_low:
            r = _reemplazar_preservando_mayus(r"\bsáqueme el pene de la boca\b", "mete mi polla en tu boca", r)
            r = _reemplazar_preservando_mayus(r"\bsáqueme el pene profundo\b", "tráguese mi polla hasta el fondo", r)
            r = _reemplazar_preservando_mayus(r"\bsáqueme el pene\b", "tráguese mi polla", r)
            r = _reemplazar_preservando_mayus(r"\bsácame el pene\b", "trágate mi polla", r)
            r = _reemplazar_preservando_mayus(r"\btoma mi polla\b", "trágate mi polla", r)

        if re.search(r"\bitem\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\belemento\b", "objeto", r)
            r = _reemplazar_preservando_mayus(r"\bart[ií]culo\b", "objeto", r)
        if re.search(r"\bitems\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\belementos\b", "objetos", r)
            r = _reemplazar_preservando_mayus(r"\bart[ií]culos\b", "objetos", r)
        if re.search(r"\bcharacter\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bcar[aá]cter\b", "personaje", r)
        if re.search(r"\bcharacters\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bcaracteres\b", "personajes", r)
        if re.search(r"\bsave\b", orig_low) and "money" not in orig_low:
            r = _reemplazar_preservando_mayus(r"\barchivo de ahorro\b", "archivo de guardado", r)
            r = _reemplazar_preservando_mayus(r"\bahorrar\b", "guardar", r)
        if re.search(r"\bswipe\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bdesliza\b", "roba", r)
            r = _reemplazar_preservando_mayus(r"\bdeslizar\b", "robar", r)
            r = _reemplazar_preservando_mayus(r"\bdeslizado\b", "robado", r)
        if re.search(r"\bparty\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bmiembros de la fiesta\b", "miembros del grupo", r)
            r = _reemplazar_preservando_mayus(r"\bmiembro de la fiesta\b", "miembro del grupo", r)
            r = _reemplazar_preservando_mayus(r"\blíder de la fiesta\b", "líder del grupo", r)
            if orig_low.strip() == "party":
                r = _reemplazar_preservando_mayus(r"^fiesta$", "grupo", r)

        r = _aplicar_locales(r, orig_low, "segun_original_1")

        if re.search(r"\bstud\s*muffin\b|\bstudmuffin\b", orig_low):
            r = _reemplazar_preservando_mayus(
                r"\b(?:panecillo|pollito)\s+de\s+estudiante\b|\bestudiante\s+de\s+primer\s+curso\b|\bpanz[oó]n\b|\bestudiante\b",
                "macizo",
                r,
            )
        elif re.search(r"\bstud\b", orig_low) and "student" not in orig_low:
            r = _reemplazar_preservando_mayus(
                r"\bestudiante\s+de\s+primer\s+curso\b|\bpanecillo\s+de\s+estudiante\b|\bestudiante\b",
                "guapetón",
                r,
            )

        if re.search(r"\bsugarplum\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bpanecillo\s+de\s+az[uú]car\b|\bciruela\s+de\s+az[uú]car\b", "bombón", r)
        elif re.search(r"\b(?:hey|hi|hello|sorry|thanks|thank you|fine|be|baby|give\s+\w+\s+some|needs?\s+some|show\s+\w+\s+some|any)\b.*\bsugar\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bd[aá]me\s+un\s+poco\s+de\s+az[uú]car\b|\bdime\s+un\s+poco\s+de\s+az[uú]car\b", "dame un poquito de cariño", r)
            r = _reemplazar_preservando_mayus(r"\bdale\s+un\s+poco\s+de\s+az[uú]car\b", "dale un poco de cariño", r)
            r = _reemplazar_preservando_mayus(r"\bnecesita\s+az[uú]car\b", "necesita un poco de cariño", r)
            r = _reemplazar_preservando_mayus(r"\ble\s+das\s+az[uú]car\b", "le das cariño", r)
            r = _reemplazar_preservando_mayus(r"(?<=,\s)az[uú]car(?=[.!?…\"'»]|$)", "cielo", r)

        if re.search(r"\bma[dk]e\s+a\s+fool\s+of\s+myself\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bme\s+he\s+hecho\s+una\s+tonter[ií]a\b|\bhice\s+una\s+tonter[ií]a\b", "he hecho el ridículo", r)

        if re.search(r"\binvite\s+us\s+girls\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\binvitarnos\s+chicas\b", "invitarnos a las chicas", r)

        # Nombres propios que el modelo hispaniza o deforma ("Henry" -> "Enrique"): en las correcciones locales
        r = _aplicar_locales(r, orig_low, "segun_original_2")

        if re.search(r"\btrain\b|\btrains\b", orig_low) and not re.search(r"\btraining\b|\btrainer\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bde la caravana\b", "del tren", r)
            r = _reemplazar_preservando_mayus(r"\bla caravana\b", "el tren", r)
            r = _reemplazar_preservando_mayus(r"\buna caravana\b", "un tren", r)
            r = _reemplazar_preservando_mayus(r"\bcaravanas\b", "trenes", r)
            r = _reemplazar_preservando_mayus(r"\bcaravana\b", "tren", r)

        if re.search(r"\bpocket\s+pussy\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bcoño\s+de\s+bolsillo\b|\bmasturbador\s+de\s+bolsillo\b|\bbolsillo\s+coño\b", "masturbador de bolsillo", r)

        if re.search(r"\bwet\s+pussy\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bchico\s+mojado\b", "coño mojado", r)

        if re.search(r"\bdrenched\s+pussy\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bchico\s+empapado\b", "coño empapado", r)

        r = _aplicar_locales(r, orig_low, "segun_original_3")

        if re.search(r"\bbooty\s+call\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\b(?:llamar\s+a\s+una\s+)?cita\s+de\s+soltero\b", "cita íntima", r)
            r = _reemplazar_preservando_mayus(r"\bllamada\s+de\s+botín\b", "cita íntima", r)

        if re.search(r"\bnoise\s+complaint\b", orig_low):
            r = _reemplazar_preservando_mayus(r"\bel\s+quejoso\b", "la denuncia por ruido", r)
            r = _reemplazar_preservando_mayus(r"\bqueja\s+de\s+ruido\b", "queja por ruido", r)
            r = _reemplazar_preservando_mayus(r"\bruido\s+de\s+la\s+queja\b", "queja por ruido", r)

    # 6b. Erratas de nombres propios y comodines del protagonista de cada juego: en las correcciones locales
    r = _aplicar_locales(r, orig_low, "erratas_nombres")

    # 6c. Correcciones gramaticales, modismos frecuentes y fugas a otros idiomas
    r = re.sub(r"\bBella come sempre\b", "Preciosa, como siempre", r, flags=re.IGNORECASE)
    r = re.sub(r"\bMój się(?:\s+na\s+niej)?\b", "Enséñamelo", r, flags=re.IGNORECASE)
    if orig_low and re.search(r"\boh,?\s*dear\b", orig_low):
        r = re.sub(
            r"¡?\b(?:Ay|Oh|Vaya),\s*querid[oa]\b!?",
            lambda m: "¡Vaya por Dios!" if m.group(0).startswith("¡") else "Vaya por Dios",
            r,
            flags=re.IGNORECASE,
        )
    r = re.sub(r"\bTantas\s+(músculos|agujeros)\b", r"Cuántos \1", r)
    r = re.sub(r"\btantas\s+(músculos|agujeros)\b", r"cuántos \1", r)
    r = re.sub(r"\bde la [Oo]ráculo\b", "del Oráculo", r)
    r = re.sub(r"\ba la [Oo]ráculo\b", "el Oráculo", r)
    r = re.sub(r"\bLa [Oo]ráculo\b", "El Oráculo", r)
    r = re.sub(r"\bla [Oo]ráculo\b", "el Oráculo", r)
    r = re.sub(r"\besta [Oo]ráculo\b", "este Oráculo", r)
    r = re.sub(r"\buna [Oo]ráculo\b", "un Oráculo", r)
    r = re.sub(
        r"\b(vas a|quieres|tienes que|puedes|debes|intenta|intentas)\s+(contener|unir|mantener|poner|quedar|ir|sentar|callar|vestir|desnudar|relajar|calmar|mover|acercar|alejar|esconder|preparar|concentrar|divertir|comportar)se\b",
        r"\1 \2te",
        r,
        flags=re.IGNORECASE,
    )
    r = re.sub(r"\bmantenete\b", "mantente", r, flags=re.IGNORECASE)
    r = re.sub(r"\bhicimos sexo\b", "tuvimos sexo", r, flags=re.IGNORECASE)
    r = re.sub(r"\bllamar a nosotros\b", "llamarnos", r, flags=re.IGNORECASE)

    # 7. Signos dobles de apertura desemparejados al cerrar (ej: "¡¿Qué haces!" -> "¡¿Qué haces?!")
    r = re.sub(r"(¡¿[^?!¡¿]+)!(\s*)$", r"\1?!\2", r)
    r = re.sub(r"(¿¡[^?!¡¿]+)\?(\s*)$", r"\1!?\2", r)

    return r


_PARES_ADJ_GENERO = (
    ("ocupado", "ocupada"),
    ("agotado", "agotada"),
    ("cansado", "cansada"),
    ("estresado", "estresada"),
    ("nervioso", "nerviosa"),
    ("seguro", "segura"),
    ("listo", "lista"),
    ("confundido", "confundida"),
    ("desesperado", "desesperada"),
    ("emocionado", "emocionada"),
    ("enamorado", "enamorada"),
    ("solo", "sola"),
    ("ansioso", "ansiosa"),
    ("dispuesto", "dispuesta"),
    ("celoso", "celosa"),
    ("honrado", "honrada"),
    ("agradecido", "agradecida"),
    ("sorprendido", "sorprendida"),
    ("asustado", "asustada"),
    ("preocupado", "preocupada"),
    ("encantado", "encantada"),
    ("atrapado", "atrapada"),
    ("satisfecho", "satisfecha"),
    ("muerto", "muerta"),
    ("preparado", "preparada"),
    ("acostumbrado", "acostumbrada"),
    ("interesado", "interesada"),
    ("metido", "metida"),
    ("convencido", "convencida"),
    ("dormido", "dormida"),
    ("despierto", "despierta"),
    ("levantado", "levantada"),
    ("perdido", "perdida"),
    ("repleto", "repleta"),
    ("lleno", "llena"),
    ("aburrido", "aburrida"),
    ("aturdido", "aturdida"),
    ("sincero", "sincera"),
    ("retrasado", "retrasada"),
    ("atascado", "atascada"),
    ("avergonzado", "avergonzada"),
    ("equivocado", "equivocada"),
    ("orgulloso", "orgullosa"),
    ("enfermo", "enferma"),
    ("loco", "loca"),
    ("borracho", "borracha"),
    ("harto", "harta"),
    ("relajado", "relajada"),
    ("tranquilo", "tranquila"),
    ("cómodo", "cómoda"),
    ("incómodo", "incómoda"),
    ("contento", "contenta"),
    ("enojado", "enojada"),
    ("enfadado", "enfadada"),
    ("molesto", "molesta"),
    ("involucrado", "involucrada"),
)
_VERBOS_1P_GENERO = (
    r"(?:estoy|estaré|estaba|estuve|he estado|había estado|puedo estar|podré estar|podría estar|"
    r"voy a estar|volver a estar|me siento|me sentí|me pongo|me puse|me he puesto|soy|estoy siendo|"
    r"fui|era|parecer|parezco|quedo|quedé|me quedo|me quedé|me he quedado|me había quedado|ando|sigo|seguí)"
)
_ADVERBIOS_1P_GENERO = (
    r"(?:\s+(?:tan|muy|bastante|demasiado|un|poco|algo|totalmente|completamente|"
    r"aún|todavía|mucho|incluso|realmente|verdaderamente|súper|más|menos|medio|bien)){0,4}"
)


def corregir_genero_hablante_v21(texto: str, prefijo_v21: str, ficha=None) -> str:
    """Ajusta los adjetivos en primera persona según el código de hablante de 2 letras que algunos juegos
    de RPG Maker ponen delante del diálogo ("HeFrOp.").

    - Con ``ficha`` (``FichaPersonajes`` del juego): el género sale de ``ficha.por_codigo(código)``
      y se corrige con ``genero.corregir_primera_persona``. Si el código no está en la ficha o su
      género no es hombre/mujer, el texto NO se toca (ante la duda, mejor no cambiar nada).
    - Sin ficha: los códigos de ``codigos_hablante`` de las correcciones locales (si las hay). Cada juego
      usa los suyos: el mismo código puede ser un hombre en un juego y una mujer en otro.
    """
    if not texto or not prefijo_v21 or len(prefijo_v21) < 2:
        return texto
    codigo = prefijo_v21[:2]
    if ficha is not None:
        personaje = ficha.por_codigo(codigo)
        if personaje is None or not es_genero_marcado(personaje.genero):
            return texto
        return corregir_primera_persona(texto, personaje.genero)
    locales = correcciones_locales()
    if codigo in locales["masculinos"]:
        es_masc = True
    elif codigo in locales["femeninos"]:
        es_masc = False
    else:
        return texto

    res = texto
    for masc, fem in _PARES_ADJ_GENERO:
        incorrecto = fem if es_masc else masc
        correcto = masc if es_masc else fem
        patron = re.compile(
            rf"\b(?:no\s+)?{_VERBOS_1P_GENERO}{_ADVERBIOS_1P_GENERO}\s+{incorrecto}\b",
            re.IGNORECASE,
        )

        def _sust(m: re.Match, inc: str = incorrecto, cor: str = correcto) -> str:
            s = m.group(0)
            rep = cor.capitalize() if s.endswith(inc.capitalize()) else cor
            return s[: -len(inc)] + rep

        res = patron.sub(_sust, res)

    inc_mismo = "misma" if es_masc else "mismo"
    cor_mismo = "mismo" if es_masc else "misma"
    res = re.sub(rf"\b(yo|a mí)\s+{inc_mismo}\b", rf"\1 {cor_mismo}", res, flags=re.IGNORECASE)
    return res


def limpiar_respuesta(respuesta: str, original: str = "") -> str:
    """Quita los restos típicos que añade el LLM (numeración, comillas, ecos del prompt...)."""
    r = respuesta.strip()
    for token in _TOKENS_ESPECIALES:
        if token in r:
            r = r.split(token)[0].strip()
    r = _RUIDO_INICIAL.sub("", r)
    if not _NUMERACION.match(original):
        r = _NUMERACION.sub("", r, count=1)

    ecos = list(_ECO_PROMPT.finditer(r))
    if ecos and r[ecos[-1].end():].strip():
        r = r[ecos[-1].end():].strip()
    r = _COLA_PROMPT.sub("", r).strip()

    # Descartar cabeceras y ecos de prompts de corrección multilínea
    if re.search(r"(?:Original|Origen|Texto original).*?\n\s*(?:Traducci[oó]n|Respuesta)\s*:\s*", r, re.IGNORECASE | re.DOTALL):
        r = re.split(r"(?:Traducci[oó]n|Respuesta)\s*:\s*", r, flags=re.IGNORECASE)[-1].strip()
    r = re.sub(
        r"^(?:Original(?:\s*\([^)]*\))?|Origen(?:\s*\([^)]*\))?|Texto original|Borrador(?:[^\n:]*)?|Traducci[oó]n(?: directa| con errores| corregida)?)\s*:\s*",
        "",
        r,
        flags=re.IGNORECASE,
    )
    if "Texto original:" in r and "Tu traducción:" in r:
        r = r.split("Tu traducción:", 1)[-1].strip()
    # Eco al final de la corrección: "Frase corregida. Borrador a corregir: frase vieja"
    eco = re.search(r"\s*(?:Borrador a corregir|Texto original)\s*:", r)
    if eco and eco.start() > 0 and r[:eco.start()].strip():
        r = r[:eco.start()].strip()

    # Evitar bucles de degeneración o tartamudeo infinito del LLM (ej: ¡R-¡R-¡R-... o R-R-R-...)
    r = re.sub(r"([¡¿]?[A-Za-zÁÉÍÓÚáéíóúñÑ]-[¡¿]?){4,}", r"\1\1", r)
    # Colapsar ráfagas degeneradas de signos de exclamación/interrogación (ej: ¡¿¡¡¡¡¡¡¡¡¡¡¡¡...)
    if not re.search(r"[!?]{6,}", original):
        r = re.sub(r"([¡!¿?])\1{5,}", r"\1\1\1", r)

    # Evitar bucles patológicos de repetición infinita de frases (solo si son 4+ repeticiones idénticas)
    # y NUNCA recortar texto legítimo tras comas.
    if original.count(",") < 3 and len(r) <= 600:
        patron_bucle = re.compile(r'((?:["\'«“]?[^,"\'«”\n]+["\'»”]?\s*,\s*){1,4}?)\1{3,}', re.IGNORECASE)
        r = patron_bucle.sub(r"\1\1", r)

    # Solo se quitan las comillas envolventes si el original no las tenía
    for abre, cierra in _COMILLAS:
        if len(r) >= 2 and r.startswith(abre) and r.endswith(cierra):
            if not (original.strip().startswith(abre) and original.strip().endswith(cierra)):
                r = r[1:-1].strip()
            break

    return postprocesar_traduccion(r, original)


# --------------------------------------------------------------------------- Control de calidad
# Palabras inequívocamente inglesas (no coinciden con palabras españolas comunes).
_PALABRAS_INGLES = re.compile(
    r"\b(?:"
    r"the|and|you|your|yours|yourself|with|without|from|that|this|these|those|"
    r"what|why|how|who|where|when|which|while|whether|"
    r"can|cannot|will|would|could|should|shall|might|must|"
    r"have|has|had|having|are|was|were|been|being|"
    r"not|don't|doesn't|didn't|can't|won't|wouldn't|couldn't|shouldn't|isn't|aren't|wasn't|weren't|"
    r"i'm|i've|i'll|i'd|you're|you've|you'll|he's|she's|it's|we're|they're|that's|there's|what's|who's|let's|"
    r"she|her|hers|herself|him|his|himself|they|them|their|theirs|themselves|our|ours|ourselves|"
    r"about|into|onto|upon|over|under|again|further|then|once|here|there|all|any|both|each|few|more|most|other|some|such|only|own|same|than|too|very|"
    r"just|now|even|still|already|always|never|often|sometimes|maybe|perhaps|please|thank|thanks|sorry|"
    r"get|gets|got|getting|make|makes|made|making|know|knows|knew|think|thinks|thought|"
    r"want|wants|wanted|need|needs|needed|feel|feels|felt|hear|hears|heard|see|sees|saw|seen|"
    r"look|looks|looked|looking|come|comes|came|coming|take|takes|took|taken|give|gives|gave|given|"
    r"tell|tells|told|ask|asks|asked|say|says|said|speak|speaks|spoke|talk|talks|talked|"
    r"find|found|keep|kept|leave|left|put|seem|seems|seemed|help|show|try|tried|call|called|"
    r"work|works|working|play|playing|run|running|walk|walking|stop|stopped|open|opened|close|closed|"
    r"door|room|house|place|time|day|night|morning|evening|man|woman|girl|boy|human|humans|people|person|"
    r"hand|hands|eyes|face|head|body|heart|voice|mind|life|death|blood|water|fire|light|dark|"
    r"good|better|best|bad|worse|worst|new|old|little|small|big|large|long|short|high|low|right|wrong|"
    r"sure|ready|able|free|full|empty|hard|soft|warm|cold|hot|sweet|nice|cute|pink|blue|green|black|white|"
    r"giggle|giggles|gasp|gasps|sigh|sighs|groan|groans|moan|moans|whisper|whispers|scream|screams|chuckle|chuckles|"
    r"dear|promise|quick|quickly|slowly|really|actually|probably|definitely|nothing|something|everything|anything|someone|anyone|everyone"
    r")\b",
    re.IGNORECASE,
)

def es_palabra_comun(palabra: str) -> bool:
    """True si ``palabra`` es UNA palabra inglesa muy corriente ("Fire", "Light", "Water", "Door")."""
    limpia = (palabra or "").strip()
    return bool(limpia) and " " not in limpia and _PALABRAS_INGLES.fullmatch(limpia) is not None


_INTERJECCIONES = re.compile(
    r"(?:o\.*k(?:\.*ay)?|\b(?:oh|no|eh|ah|uh|um|hmm+|mm+|shh+|hah+|aha+|ugh+|argh+|grr+|zzz+|huh|tsk|psst|yay|whoa|wow|ouch|oops|ha|he|hi|ho|bah|meh|pff+|uff+)\b)",
    re.IGNORECASE,
)
_SONIDOS_PUROS = re.compile(r"^[hmnpfguaeioáéíóúy!\?.\-~…,\s\"'()*]*$", re.IGNORECASE)
_IDENTIFICADOR = re.compile(r"^[A-Za-z][A-Za-z0-9_]*[A-Z][A-Za-z0-9_]*$")

_PATRON_FUGA_SCRIPTS = re.compile(
    r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0400-\u04ffąęśćżźłńřčšžůěďťňĄĘŚĆŻŹŁŃŘČŠŽŮĚĎŤŇ]"
)
_PATRON_FUGA_PALABRAS = re.compile(
    r"\b(?:come sempre|stanno facendo|chiacchiera|chiacchera|hanno bisogno|"
    r"questo|questa|quello|quella|perché|tutto bene|più|anche|sempre|"
    r"avec|dans|c'est|très|mais|vous|nous|"
    r"nicht|ich bin|aber|oder|schon|jetzt|"
    r"você|não|então|muito|também)\b",
    re.IGNORECASE,
)

# Ecos de la ficha de personajes del prompt (ver prompts.construir_instruccion y
# personajes.ContextoLinea.ficha). "PERSONAJES:" solo cuenta en MAYÚSCULAS (un menú puede
# traducirse legítimamente como "Personajes:") y las frases de la ficha solo cuentan con la
# etiqueta de género detrás ("...se dirige a Noelia (mujer)"), para no confundirlas con
# traducciones normales como "Probablemente se dirige a la estación".
_ECO_PERSONAJES = re.compile(
    r"PERSONAJES(?: POR FRASE)?:"
    r"|(?i:concuerda el g[ée]nero)"
    r"|(?i:probablemente se dirige a|es un pensamiento de)\s+[^()\n]{1,60}?\s*"
    r"\((?:hombre|mujer|neutro|desconocido)\)"
)

# Pesos de gravedad (para elegir el mejor candidato entre reintentos).
_PESO_PROBLEMA = {
    "vacia": 100,
    "fuga_idioma": 95,
    "eco_prompt": 90,
    "sin_traducir": 80,
    "repeticion": 70,
    "ingles_residual": 60,
    "longitud_corta": 50,
    "nombre_perdido": 40,
    "sentido_equivocado": 40,   # "chest" de cuerpo traducido "cofre" (ver traductor.ambiguas)
    "longitud_larga": 35,
    "etiquetas": 15,
}

# Problemas graves: si persisten tras los reintentos NO se guarda en la caché (se reintentará en otra sesión).
PROBLEMAS_GRAVES = frozenset({
    "vacia",
    "fuga_idioma",
    "eco_prompt",
    "sin_traducir",
    "repeticion",
    "ingles_residual",
    "longitud_corta",
    "longitud_larga",
})


def _es_onomatopeya_o_interjeccion(vis: str) -> bool:
    """True para gemidos/risas/interjecciones universales ('Mmmhh...', 'O..kay...', 'Oh no...', 'No')."""
    if len(vis) > 60:
        return False
    resto = _INTERJECCIONES.sub("", vis)
    return bool(_SONIDOS_PUROS.match(resto))


def _tiene_bucle_palabras(texto: str) -> bool:
    """Detecta en tiempo lineal O(n) si una secuencia de 1..5 palabras se repite 4+ veces seguidas."""
    palabras = [w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+", texto)]
    m = len(palabras)
    for k in range(1, 6):
        if m < k * 4:
            break
        for i in range(m - k * 4 + 1):
            bloque = palabras[i:i + k]
            if palabras[i + k:i + k * 4] == bloque * 3:
                return True
    return False


def evaluar_traduccion(original: str, traducido: str) -> list[str]:
    """Evalúa una traducción y devuelve una lista de códigos de problema (vacía = perfecta).

    Códigos posibles:
      - ``vacia``: la traducción no tiene letras visibles cuando el original sí las tenía.
      - ``sin_traducir``: el texto visible es idéntico al inglés y no es un nombre/onomatopeya.
      - ``ingles_residual``: quedan demasiadas palabras inglesas sin traducir.
      - ``eco_prompt``: se han colado marcadores de la plantilla (### Instruction, GLOSARIO,
        PERSONAJES, "Concuerda el género", "Probablemente se dirige a X (mujer)"...).
      - ``repeticion``: bucle degenerado de caracteres o palabras que no estaba en el original.
      - ``longitud_corta``: frase mutilada (< 42 % de la longitud original en frases de ≥ 35 car.).
      - ``longitud_larga``: alucinación o fusión de lotes (> 2.8x de la longitud original).
      - ``etiquetas``: faltan o sobran etiquetas de formato respecto al original.
    """
    if not tiene_texto_visible(original):
        return []
    vis_o = PATRON_CODIGOS.sub(" ", original).strip()
    vis_t = PATRON_CODIGOS.sub(" ", traducido or "").strip()
    if not vis_t or not tiene_letras(vis_t):
        return ["vacia"]

    problemas: list[str] = []
    norm_o = re.sub(r"\s+", " ", vis_o).strip().lower()
    norm_t = re.sub(r"\s+", " ", vis_t).strip().lower()

    palabras_o = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ']+", vis_o)
    en_o = _PALABRAS_INGLES.findall(vis_o)
    en_t = _PALABRAS_INGLES.findall(vis_t)

    if norm_o == norm_t:
        if _IDENTIFICADOR.match(vis_o) or _es_onomatopeya_o_interjeccion(vis_o):
            pass
        elif en_o or len(palabras_o) >= 3:
            problemas.append("sin_traducir")
        elif len(palabras_o) == 2 and not all(w[0].isupper() for w in palabras_o):
            problemas.append("sin_traducir")

    if "sin_traducir" not in problemas:
        en_t_reales = [w for w in en_t if w.lower() not in ("no", "me", "a", "he", "sin", "con", "real")]
        total_w = len(re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]+", vis_t))
        if len(en_t_reales) >= 3 and total_w > 0 and len(en_t_reales) >= total_w * 0.28:
            problemas.append("ingles_residual")
        elif len(en_t_reales) >= 5:
            problemas.append("ingles_residual")

    if re.search(
        r"###\s*(?:Instruction|Input|Response)|GLOSARIO OBLIGATORIO|CONTEXTO DEL JUEGO|CONVERSACIÓN PREVIA|"
        r"Usa esta conversaci[oó]n para entender el contexto|traduce [UÚ]NICAMENTE la frase del Input",
        traducido,
        re.IGNORECASE,
    ) or (_ECO_PERSONAJES.search(traducido) and not _ECO_PERSONAJES.search(original)):
        problemas.append("eco_prompt")

    if (_PATRON_FUGA_SCRIPTS.search(vis_t) and not _PATRON_FUGA_SCRIPTS.search(vis_o)) or (
        _PATRON_FUGA_PALABRAS.search(vis_t) and not _PATRON_FUGA_PALABRAS.search(vis_o)
    ):
        problemas.append("fuga_idioma")

    for m in re.finditer(r"(.)\1{9,}", vis_t):
        ch = m.group(1)
        if ch * 6 not in vis_o and ch not in "─━—-_=.*":
            problemas.append("repeticion")
            break
    if "repeticion" not in problemas and _tiene_bucle_palabras(vis_t) and not _tiene_bucle_palabras(vis_o):
        problemas.append("repeticion")

    len_o = len(re.sub(r"\s+", " ", vis_o))
    len_t = len(re.sub(r"\s+", " ", vis_t))
    if len_o >= 35 and len_t < len_o * 0.42:
        problemas.append("longitud_corta")
    elif len_o >= 20 and len_t > max(len_o * 2.8, len_o + 120):
        problemas.append("longitud_larga")

    ok_tags, _, _ = comparar_etiquetas(original, traducido)
    if not ok_tags:
        problemas.append("etiquetas")

    return problemas


# Nombres de personaje genéricos que SÍ se traducen ("Guard" -> "Guardia"): no se exige conservarlos.
_ROLES_GENERICOS = frozenset({
    "guard", "guards", "soldier", "villager", "merchant", "customer", "clerk", "bartender", "maid", "nurse",
    "doctor", "teacher", "student", "stranger", "kid", "child", "narrator", "system", "voice", "staff",
    "bandit", "thug", "monster", "demon", "angel", "shopkeeper", "receptionist", "cop", "officer", "police",
    "waiter", "waitress", "priest", "nun", "chef", "cook", "driver", "boss", "manager", "worker", "employee",
    "client", "host", "hostess", "guest", "captain", "knight", "witch", "king", "queen", "prince", "princess",
    "mom", "dad", "mother", "father", "sister", "brother", "grandma", "grandpa", "uncle", "aunt", "unknown",
    "lady", "gentleman", "guy", "dude", "sir", "madam", "master", "mistress", "slave", "pet", "fan", "fans",
    "crowd", "audience", "announcer", "speaker", "player", "hero", "heroine", "villain", "creature", "girls",
    "boys", "men", "women", "everyone", "nobody", "somebody", "both", "all", "group", "goon", "goons",
    "security", "guardian", "henchman", "minion", "enemy", "ghost", "spirit", "robot", "android",
    # Nombres que también son palabras inglesas corrientes ("Max texture size", "Hope is all we have")
    "max", "will", "may", "mark", "bill", "frank", "jack", "grace", "hope", "faith", "joy", "rose", "lily",
    "dawn", "summer", "angel", "sky", "star", "storm", "rain", "ruby", "amber", "jade", "pearl", "violet", "crystal",
    "olive", "sage", "ivy", "april", "june", "august", "honey", "candy", "cherry", "bunny", "kitty",
})


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes ('Sofía' -> 'sofia') para comparar nombres."""
    descompuesto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn").casefold()


def _palabras_de_nombre(nombre: str) -> list[str]:
    """Palabras de un nombre que la traducción debe conservar ('Father Brian' -> ['brian'];
    'Old Man' o 'Guard' -> [], porque se traducen)."""
    return [w for w in re.findall(r"[^\W\d_]{3,}", _plano(nombre))
            if w not in _ROLES_GENERICOS and not _PALABRAS_INGLES.fullmatch(w)]


def nombres_perdidos(traducido: str, nombres, terminos=()) -> list[str]:
    """Los ``nombres`` (de personajes que nombra el original) que NO aparecen en la traducción.

    Sin mayúsculas ni tildes ("Sofia" = "Sofía") y aceptando la raíz de 4 letras en palabras de 5 o
    más ("Oracle" -> "Oráculo"). "SCN - Habitación de Marisa" -> "Sala de la Escuela..." pierde a Marisa.
    ``terminos`` son los pares (inglés, español) del glosario que aparecen en el original: si el
    glosario traduce el nombre ("Sister Judy" -> "Hermana Judith"), vale su forma en español.
    """
    destino = _plano(traducido or "")  # sin quitar códigos: "[Clara]" o "\C[2]Ana" llevan el nombre dentro

    def _sobrevive(palabra: str) -> bool:
        if len(palabra) >= 5:  # basta la raíz al principio de una palabra
            return re.search(rf"(?<!\w){re.escape(palabra[:4])}", destino) is not None
        return re.search(rf"(?<!\w){re.escape(palabra)}(?!\w)", destino) is not None

    perdidos: list[str] = []
    for nombre in nombres or ():
        palabras = _palabras_de_nombre(nombre)
        if not palabras or any(_sobrevive(w) for w in palabras):
            continue
        glosario = [es for en, es in terminos if nombre.casefold() in str(en).casefold() and es]
        if any(_plano(es) in destino for es in glosario):
            continue
        perdidos.append(nombre)
    return perdidos


# Cola en inglés pegada SIN espacio al final (U2): el corpus de KDE con que se entrenó traía el contexto de
# la traducción pegado ("Exportar documento resaltado a HTMLName", "POZOConstellation name (optional)") y los
# modelos lo repiten en rótulos en mayúsculas ("ÁRBOL IZQUIERDOConstellation name (optional)"). La cola es la
# ÚLTIMA palabra con mayúscula inicial pegada a una letra ("HTML|Name", "ESTRELLAS|Constellation name") y lo
# que la sigue hasta el final; si justo delante hay MAYÚSCULAS pegadas a una minúscula ("sentencia|QOCI|Result")
# y no están en el original, también son de la cola.
_COLA_PEGADA = re.compile(r"(?<=[^\W\d_])(?P<palabra>[A-Z][a-z]{2,})(?:\s+\(?[a-z]+\)?){0,5}\s*$")
# Mayúsculas pegadas justo antes de la cola ("sentencia|QOCI|Result", "Lisu|K|Charselect", "(malabar)|K|...").
_MAYUSCULAS_PEGADAS = re.compile(r"(?<=[a-záéíóúüñ)])[A-Z]+$")
# Las colas de unidades empiezan en minúscula: "zPa" + "amount in units (real)".
_COLA_UNIDADES = re.compile(r"(?<=[^\W\d_])(?:amount in units \(real\)|unit description in lists)\s*$")
# Solo estas colas (las que se repiten en el corpus de KDE, sin las que también son palabras españolas como
# "General", "Media" o "Error"): las palabras pegadas a propósito ("LuciaObsesionada", "#HogarDulceHogar",
# "\\nRetroceso") no se tocan.
_COLAS_CONOCIDAS = frozenset(
    "Name Comment Stencils Constellation Description Country Shortcut Language Charselect Possessive The Query "
    "Class Database Runner Nakshatra Aspect Style Box Planet Unknown Status Dialog House Page Xml Result Units "
    "Keywords Select Phonebook Month Exp Zodiac Menu Rect Default Model Sql Action Job New Screen About This "
    "Noun Sort Generic".split())


def quitar_cola_pegada(original: str, traducido: str) -> str:
    """Quita esa cola si NO está en el original ("PlayStation", "iPhone" o "McDonald" sí lo están: no se
    tocan). Si no quedaría nada con letras, se deja como estaba. Repite por si hay dos ("AudexGenericName")."""
    original = original or ""
    actual = traducido
    for _ in range(3):
        if not actual:
            return traducido
        u = _COLA_UNIDADES.search(actual)
        if u is not None:
            actual = actual[:u.start()].rstrip()
            continue
        m = _COLA_PEGADA.search(actual)
        if m is None or m.group("palabra") not in _COLAS_CONOCIDAS or m.group("palabra") in original:
            break
        if m.start() >= 2 and actual[m.start() - 2] == "\\":  # "...\\nNombre": salto de línea escrito, no cola
            break
        inicio = m.start()
        pegadas = _MAYUSCULAS_PEGADAS.search(actual[:inicio])
        if pegadas is not None and pegadas.group(0) not in original:
            inicio = pegadas.start()
        elif actual[:inicio].endswith("Q") and inicio >= 2 and actual[inicio - 2].isupper() \
                and not re.search(r"Q\b", original):
            inicio -= 1  # prefijo de Qt ("...la DTD" + "QXml")
        actual = actual[:inicio].rstrip()
    return actual if re.search(r"[^\W\d_]", actual or "") else traducido


def gravedad(problemas: list[str]) -> int:
    """Puntuación numérica de gravedad (0 = sin problemas)."""
    return sum(_PESO_PROBLEMA.get(p, 10) for p in problemas)


def tiene_fallo_grave(problemas: list[str]) -> bool:
    """True si hay algún problema que impide dar por buena y cachear la traducción."""
    return any(p in PROBLEMAS_GRAVES for p in problemas)


_GUIA_REINTENTO = {
    "vacia": "Devuelve la traducción completa en español (no devuelvas una respuesta vacía ni solo símbolos).",
    "fuga_idioma": "El texto anterior se tradujo a otro idioma (chino, ruso, italiano, polaco, etc.). Tradúcelo EXCLUSIVAMENTE al español de España.",
    "sin_traducir": "El texto anterior quedó en inglés sin traducir. Tradúcelo íntegramente al español de España.",
    "ingles_residual": "No dejes palabras ni fragmentos en inglés; traduce toda la oración al español de España.",
    "eco_prompt": "Devuelve ÚNICAMENTE la frase traducida, sin repetir las instrucciones ni el glosario.",
    "repeticion": "Evita repetir palabras o signos en bucle; escribe una oración natural y concisa.",
    "longitud_corta": "Traduce TODAS las oraciones del original sin omitir ni recortar ninguna parte.",
    "longitud_larga": "Traduce únicamente la frase indicada, sin añadir explicaciones ni texto extra.",
    "etiquetas": "Conserva exactamente las etiquetas de formato del original.",
    "nombre_perdido": "Conserva los nombres propios de los personajes tal y como aparecen en el original.",
}


def nota_reintento(problemas: list[str]) -> str:
    """Genera una indicación breve para añadir al final de la instrucción en un reintento."""
    notas = [_GUIA_REINTENTO[p] for p in problemas if p in _GUIA_REINTENTO]
    return " ".join(notas)
