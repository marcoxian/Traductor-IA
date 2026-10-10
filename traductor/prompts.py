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
                          historial: Iterable[str] = ()) -> str:
    """Base + contexto del juego + reglas de glosario + frases anteriores (en ese orden)."""
    partes = [base]
    if contexto:
        partes.append(f"CONTEXTO OBLIGATORIO: {contexto}")
    terminos = list(terminos)
    if terminos:
        reglas = ", ".join(f"'{en}' = '{es}'" for en, es in terminos)
        partes.append(f"REGLAS ESTRICTAS DE GLOSARIO: {reglas}.")
    historial = list(historial)
    if historial:
        partes.append(f"(TEXTOS ANTERIORES para contexto: {' | '.join(historial)}. "
                      "RECUERDA: Traduce SOLO el texto del Input, NO el contexto).")
    return " ".join(partes)


def instruccion_correccion(etiquetas: list[str], motivo: str) -> str:
    """Instrucción para autocorregir una traducción que ha roto códigos de formato.

    Antes la corrección se mandaba como si fuera un texto más a traducir, envuelta otra vez
    en "Traduce este texto...", y el modelo acababa traduciendo las propias instrucciones.
    """
    lista = " ".join(etiquetas) if etiquetas else "(ninguna)"
    return ("Corrige la traducción al español de España del Input. Debe conservar EXACTAMENTE "
            f"estos códigos de formato, sin añadir ni quitar ninguno: {lista}. "
            f"Error detectado: {motivo}. Devuelve ÚNICAMENTE el texto corregido, sin comillas ni notas.")


def entrada_correccion(original: str, traduccion: str) -> str:
    return f"Original (inglés): {original}\nTraducción con errores: {traduccion}"
