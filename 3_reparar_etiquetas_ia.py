"""3_reparar_etiquetas_ia.py — Reparación asistida por IA de etiquetas y formato.

Lee una hoja de revisión (revision_<juego>.csv) generada en el paso 2, detecta
filas con códigos rotos o longitud truncada y solicita a Ollama que las repare
conservando exactamente las etiquetas de formato.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from traductor import config
from traductor.ollama import OllamaTranslator
from traductor.registro import configurar_logging
from traductor.texto import comparar_etiquetas, forzar_etiquetas


def buscar_archivo_revision() -> Path | None:
    candidatos = list(Path(".").glob("revision_*.csv")) + list(config.DIR_WORKSPACE.glob("*/revision_*.csv"))
    return candidatos[0] if candidatos else None


def main():
    parser = argparse.ArgumentParser(description="Reparar etiquetas de formato usando Ollama.")
    parser.add_argument("--archivo", help="Ruta al archivo CSV de revisión (por defecto busca revision_*.csv)")
    parser.add_argument("--modelo", default=config.MODELO_POR_DEFECTO, help="Modelo de Ollama a usar")
    parser.add_argument("--endpoint", default=config.OLLAMA_URL, help="URL del endpoint de Ollama")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    args = parser.parse_args()

    configurar_logging(detallado=args.debug)

    if args.archivo:
        archivo_path = Path(args.archivo)
    else:
        archivo_path = buscar_archivo_revision()

    if not archivo_path or not archivo_path.exists() or archivo_path.stat().st_size == 0:
        print(f"\n{'='*70}")
        print("ℹ️  [INFORMACIÓN DE REPARACIÓN DE ETIQUETAS]")
        print(f"{'='*70}")
        print("No se encontró ningún archivo de revisión 'revision_*.csv' con fallos pendientes.")
        print("• En juegos de RPG Maker (como Treasure of Nadia), los códigos se conservan automáticamente.")
        print("• Este paso solo es necesario si generaste una hoja de revisión en el Paso 2 con errores detectados.")
        print("✔ No hay ninguna etiqueta rota que reparar.")
        print(f"{'='*70}\n")
        return

    print(f"Cargando archivo de revisión: {archivo_path}")
    filas = []
    with open(archivo_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        filas = list(reader)

    if not filas:
        print(f"\n{'='*70}")
        print("ℹ️  [INFORMACIÓN DE REPARACIÓN DE ETIQUETAS]")
        print(f"{'='*70}")
        print("El archivo de revisión no tiene ninguna línea pendiente de corregir (0 errores detectados).")
        print("✔ Todas las etiquetas están en perfecto estado.")
        print(f"{'='*70}\n")
        return

    translator = OllamaTranslator(model_name=args.modelo, endpoint=args.endpoint)
    try:
        translator.comprobar_conexion()
    except Exception as e:
        print(f"Aviso al comprobar conexión con Ollama: {e}")

    corregidas = 0
    total = len(filas)
    print(f"Procesando {total} filas con el modelo {args.modelo}...")

    for i, row in enumerate(filas, 1):
        if row.get("correccion", "").strip():
            continue

        texto_ingles = row.get("ingles", "")
        texto_traduccion_mala = row.get("traduccion_ia", "")
        problema = row.get("problema", "")

        if "LONGITUD" in problema:
            print(f"[{i}/{total}] Retraduciendo longitud truncada...")
            traduccion_reparada = translator.translate(texto_ingles)
        else:
            print(f"[{i}/{total}] Arreglando etiquetas/orden...")
            traduccion_reparada = translator.autocorrect(texto_ingles, texto_traduccion_mala)

        ok, _, _ = comparar_etiquetas(texto_ingles, traduccion_reparada)
        if ok or "LONGITUD" in problema:
            row["correccion"] = traduccion_reparada
            corregidas += 1
            print(f"  ✔ OK: {traduccion_reparada[:50]}...")
        else:
            print("  ⚠ Fallback: forzando etiquetas faltantes.")
            row["correccion"] = forzar_etiquetas(texto_ingles, traduccion_reparada)
            corregidas += 1

        # Guardado incremental cada 10 filas para no perder progreso
        if i % 10 == 0:
            with open(archivo_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=filas[0].keys(), delimiter=";")
                writer.writeheader()
                writer.writerows(filas)

    # Guardado final
    with open(archivo_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=filas[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(filas)

    print(f"¡Proceso completado! {corregidas} líneas corregidas guardadas en {archivo_path}.")


if __name__ == "__main__":
    main()
