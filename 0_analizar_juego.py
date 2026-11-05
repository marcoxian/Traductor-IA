"""0_analizar_juego.py — Paso 0: protagonista, personajes principales y su género.

Analiza los textos ORIGINALES del juego (RPG Maker, Ren'Py, CSV de localización o XUnity en Unity)
y crea o actualiza ``workspace/<juego>/personajes.json``. El traductor usa esa ficha para saber
quién habla en cada línea y no poner adjetivos de hombre o de mujer donde no toca.

Uso:
    python 0_analizar_juego.py --ruta "D:\\Juegos\\MiJuego"
    python 0_analizar_juego.py --ruta "..." --ia            # pide ayuda a la IA local en los dudosos
    python 0_analizar_juego.py --ruta "..." --simular       # solo muestra el informe, no escribe nada

Lo que marques como confirmado (a mano o con el editor de personajes) no se sobrescribe al
volver a analizar.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from traductor import config
from traductor.analizador import analizar_y_guardar
from traductor.registro import configurar_logging

log = logging.getLogger("analizar_juego")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paso 0: detecta protagonista, personajes y su género (personajes.json).")
    parser.add_argument("--ruta", required=True, help="Carpeta del juego (o carpeta de datos de RPG Maker)")
    parser.add_argument("--juego", help="Perfil en workspace/<juego>/ (por defecto se deduce de la carpeta)")
    parser.add_argument("--motor", choices=["RPGMaker", "RenPy", "Unity", "CSV"], help="Forzar el motor del juego")
    parser.add_argument("--ia", action="store_true", help="Consultar a la IA local (Ollama) los personajes dudosos")
    parser.add_argument("--modelo-ia", help="Modelo de Ollama para el análisis (por defecto llama3.1 u otro general)")
    parser.add_argument("--simular", action="store_true", help="Mostrar el informe sin escribir nada")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    args = parser.parse_args(argv)
    configurar_logging(detallado=args.debug)

    ruta = Path(args.ruta)
    if not ruta.exists():
        log.error("No existe la carpeta del juego: %s", ruta)
        return 1
    juego = config.resolver_juego(args.juego, ruta)
    if not juego:
        log.error("No se pudo deducir el nombre del perfil; indícalo con --juego.")
        return 1

    destino, informe = analizar_y_guardar(juego, ruta, usar_ia=args.ia, modelo_ia=args.modelo_ia,
                                          simular=args.simular, motor=args.motor)
    print(informe.texto_informe())
    if args.simular:
        print("[SIMULACIÓN] No se ha escrito nada.")
    elif destino is None:
        print("No se ha creado la ficha de personajes (no se encontraron personajes).")
        return 2
    else:
        print(f"✔ Ficha de personajes guardada en: {destino}")
        print("  Revísala (sobre todo el protagonista y los marcados con ⚠) en el Centro de Control >")
        print("  «✏️ Revisar / editar personajes», o editando ese archivo. Lo que confirmes no se pisará.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
