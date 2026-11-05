"""Prompts del traductor.

REGLA DE ORO: el modelo afinado se entrena con ``INSTRUCCION`` + ``PLANTILLA`` (ver
preparar_datos_v2.py y entrenar_v2.py). Al traducir se usa EXACTAMENTE la misma base y
solo se AÑADE detrás el contexto, el glosario y el historial. Si cambias ``INSTRUCCION``,
vuelve a generar el dataset y a entrenar.
"""
from __future__ import annotations

from typing import Iterable

# Instrucción base (idéntica en entrenamiento e inferencia).
INSTRUCCION = ("Traduce este texto al español de España de forma natural. Devuelve ÚNICAMENTE "
               "la traducción directa, sin números de lista, sin comillas y sin notas.")

# Variante para lotes numerados (modo turbo).
INSTRUCCION_LOTE = ("Traduce las siguientes frases al español de España de forma natural. "
                    "MANTÉN LA MISMA NUMERACIÓN EXACTA (ej: '1. traducción\\n2. traducción'). "
                    "No unas frases ni te saltes ninguna. No añadas comillas extra.")

# Plantilla estilo Alpaca con la que se entrenó el modelo.
PLANTILLA = "### Instruction:\n{}\n\n### Input:\n{}\n\n### Response:\n{}"


def formatear(instruccion: str, entrada: str, salida: str = "") -> str:
    """Rellena la plantilla de entrenamiento/inferencia."""
    return PLANTILLA.format(instruccion, entrada, salida)


def construir_instruccion(base: str,
                          contexto: str = "",
                          terminos: Iterable[tuple[str, str]] = (),
                          historial: Iterable[str] = (),
                          personajes: str = "",
                          personajes_lote: Iterable[tuple[int, str]] = ()) -> str:
    """Base + contexto del juego + personajes + reglas de glosario + frases anteriores (en ese orden).

    ``personajes`` es la ficha de UNA frase (quién habla, a quién y su género, ver
    ``traductor.personajes.ContextoLinea.ficha``). ``personajes_lote`` son las fichas de un lote
    numerado (modo turbo): ``[(1, "Habla Ana (mujer)."), (3, ...)]`` ->
    ``PERSONAJES POR FRASE: 1) Habla Ana (mujer); 3) ....``. Vacíos no añaden nada, así que
    el prompt de los juegos sin ficha de personajes es idéntico al de siempre.
    """
    partes = [base]
    if contexto:
        partes.append(f"CONTEXTO DEL JUEGO: {contexto}")
    if personajes:
        partes.append(f"PERSONAJES: {personajes}")
    por_frase = "; ".join(f"{n}) {ficha.strip().rstrip('.')}" for n, ficha in personajes_lote if ficha.strip())
    if por_frase:
        partes.append(f"PERSONAJES POR FRASE: {por_frase}.")
    terminos = list(terminos)
    if terminos:
        reglas = ", ".join(f"'{en}' = '{es}'" for en, es in terminos)
        partes.append(f"GLOSARIO OBLIGATORIO: {reglas}.")
    historial = list(historial)
    if historial:
        partes.append(f"(CONVERSACIÓN PREVIA: {' | '.join(historial)}. "
                      "Usa esta conversación para entender el contexto y dobles sentidos, pero traduce ÚNICAMENTE la frase del Input).")
    return " ".join(partes)


def instruccion_correccion(etiquetas: list[str], motivo: str) -> str:
    """Instrucción para autocorregir una traducción que ha roto códigos de formato."""
    lista = " ".join(etiquetas) if etiquetas else "(ninguna)"
    return ("Corrige las etiquetas de formato del borrador para que coincidan EXACTAMENTE con el original. "
            f"Códigos obligatorios: {lista}. Motivo: {motivo}. "
            "Devuelve ÚNICAMENTE la traducción final en español, sin prefijos ni notas.")


def entrada_correccion(original: str, traduccion: str) -> str:
    return f"Texto original: {original}\nBorrador a corregir: {traduccion}"
