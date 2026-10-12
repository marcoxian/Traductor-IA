"""Utilidades de texto compartidas por todos los pasos.

Antes había tres versiones distintas de la regex de etiquetas repartidas por los scripts;
ahora hay una sola definición aquí.
"""
from __future__ import annotations

import re
from collections import Counter

# --------------------------------------------------------------------------- Regex
# Etiquetas que la traducción DEBE conservar (se comparan con conteo):
#   %s %d %1 ... | \n \r literales | {0} {name} | [tag] [/tag] | \C[3] \I[12] \F[name]...
PATRON_ETIQUETAS = re.compile(
    r"(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\])"
)

# Todos los códigos de control (más amplio): se usa para medir el texto visible y para
# saber si una cadena tiene algo que traducir. Incluye \! \. \| \{ \} \^ \$ y <...>.
PATRON_CODIGOS = re.compile(
    r"(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\]"
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
    r"^((?:[A-Za-z0-9]{2},[A-Za-z0-9]{2},[A-Za-z0-9]{2}|(?=[A-Za-z0-9><_-]{4,15}\.)[A-Za-z0-9><_-]*[A-Z][A-Za-z0-9><_-]*[A-Z][A-Za-z0-9><_-]*))\.(.*)$"
)
PATRON_PUNTO_PEGADO = re.compile(r"([a-záéíóúñ])\.([A-ZÁÉÍÓÚÑ¿¡])")
PATRON_SIGNO_PEGADO = re.compile(r"([a-záéíóúñ0-9][?!]+)([A-ZÁÉÍÓÚÑ¿¡])")


def corregir_puntuacion_pegada(texto: str) -> str:
    """Corrige oraciones pegadas sin espacio tras punto, interrogación o exclamación.

    Conserva intactos los prefijos de sprite en RPG Maker (ej: 'HeFrOp.' o 'Br,fr,op.')
    así como llamadas de código Javascript (ej: 'Galv.CACHE.load').
    """
    if not texto or not isinstance(texto, str):
        return texto
    if any(kw in texto for kw in ("SceneManager.", "Galv.", "StorageManager.", "PluginManager.", ".prototype.")):
        return texto

    m_pref = PATRON_PREFIJO_V21.match(texto)
    if m_pref:
        pref = m_pref.group(1) + "."
        cuerpo = m_pref.group(2)
        cuerpo_corr = PATRON_PUNTO_PEGADO.sub(r"\1. \2", cuerpo)
        cuerpo_corr = PATRON_SIGNO_PEGADO.sub(r"\1 \2", cuerpo_corr)
        return pref + cuerpo_corr

    t = PATRON_PUNTO_PEGADO.sub(r"\1. \2", texto)
    return PATRON_SIGNO_PEGADO.sub(r"\1 \2", t)


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


def forzar_etiquetas(original: str, traducido: str) -> str:
    """Último recurso: pega al inicio las etiquetas que falten (respetando duplicados)."""
    _, faltan, _ = comparar_etiquetas(original, traducido)
    return ("".join(faltan) + " " + traducido) if faltan else traducido


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
    if "Texto original:" in r and "Tu traducción:" in r:
        r = r.split("Tu traducción:", 1)[-1].strip()

    # Solo se quitan las comillas envolventes si el original no las tenía
    for abre, cierra in _COMILLAS:
        if len(r) >= 2 and r.startswith(abre) and r.endswith(cierra):
            if not (original.strip().startswith(abre) and original.strip().endswith(cierra)):
                r = r[1:-1].strip()
            break
    return r
