"""1_traducir_juego.py — Traductor automático con IA local (Ollama).

Paso 1 del pipeline de traducción de videojuegos.
Soporta motores: RPG Maker (MV/MZ), Godot / CSV (DKTools), Unity (BepInEx/XUnity).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from traductor import config
from traductor.motores import InyectorCSV, InyectorRPGMaker, detectar_motor, inyectar_unity
from traductor.ollama import OllamaNoDisponible, OllamaTranslator, ruta_cache_por_defecto
from traductor.registro import configurar_logging

log = logging.getLogger(__name__)


class GameEngineInjector:
    """Clase principal que orquesta la detección e inyección de traducción."""

    def __init__(self, ruta_juego: str | Path,
                 archivo_objetivo: str | None = None,
                 modelo: str = config.MODELO_POR_DEFECTO,
                 modo: str = "seguro",
                 juego: str | None = None,
                 endpoint: str = config.OLLAMA_URL,
                 motor_forzado: str | None = None):
        self.ruta_juego = Path(ruta_juego)
        self.archivo_objetivo = archivo_objetivo
        self.modelo = modelo
        self.modo = modo
        self.motor_forzado = motor_forzado

        # Resolver perfil de juego (glosario activo + contexto específico)
        nombre_juego = config.resolver_juego(juego, self.ruta_juego)
        self.perfil = config.cargar_perfil(nombre_juego)
        log.info("Cargado %s", self.perfil.resumen())

        # Configuración del traductor según el modo
        es_turbo = (modo.lower() == "turbo")
        tam_lote = 20 if es_turbo else 1
        usar_historial = not es_turbo

        cache_path = ruta_cache_por_defecto(nombre_juego, modelo)
        self.translator = OllamaTranslator(
            model_name=modelo,
            endpoint=endpoint,
            perfil=self.perfil,
            tam_lote=tam_lote,
            usar_historial=usar_historial,
            ruta_cache=cache_path,
        )

    def run(self) -> None:
        try:
            self.translator.comprobar_conexion()
        except OllamaNoDisponible as e:
            log.error("Error conectando con la IA: %s", e)
            sys.exit(1)

        motor = self.motor_forzado
        if not motor:
            if self.archivo_objetivo and self.archivo_objetivo.lower().endswith(".json"):
                log.info("Forzando motor RPG Maker por extensión de archivo (%s).", self.archivo_objetivo)
                motor = "RPGMaker"
            else:
                motor = detectar_motor(self.ruta_juego)

        log.info("--- Iniciando proceso con motor: %s (Modo: %s) ---", motor, self.modo.upper())

        try:
            if motor == "RPGMaker":
                inyector = InyectorRPGMaker(self.ruta_juego, self.translator, self.archivo_objetivo)
                inyector.procesar()
            elif motor == "Godot":
                inyector_csv = InyectorCSV(self.ruta_juego, self.translator)
                inyector_csv.procesar()
            elif motor == "Unity":
                inyectar_unity(self.ruta_juego, modelo=self.modelo, endpoint=self.translator.endpoint)
            elif motor == "Unreal":
                log.warning("El motor Unreal Engine aún no tiene inyección directa automatizada.")
            else:
                log.error("No se pudo determinar una estrategia para el juego en %s.", self.ruta_juego)
        finally:
            self.translator.cerrar()

        stats = self.translator.estadisticas
        log.info("--- Proceso completado --- (Nuevas: %d | Caché: %d | Autocorregidas: %d)",
                 stats["traducidas"], stats["cache"], stats["autocorregidas"])


def main(default_mode: str = "seguro") -> None:
    parser = argparse.ArgumentParser(description="Auto-Inyector de IA Traductora Local en Videojuegos.")
    parser.add_argument("--ruta", type=str, required=True, help="Ruta de la carpeta del juego.")
    parser.add_argument("--archivo", type=str, required=False, help="Traducir solo un archivo específico (ej. System.json o Map005.json)")
    parser.add_argument("--modelo", type=str, default=config.MODELO_POR_DEFECTO, help="Modelo de Ollama a usar (por defecto IA_Traductora)")
    parser.add_argument("--modo", choices=["seguro", "turbo"], default=default_mode, help="Modo seguro (frase a frase con contexto) o turbo (en lotes)")
    parser.add_argument("--turbo", action="store_true", help="Atajo para forzar modo turbo")
    parser.add_argument("--juego", type=str, required=False, help="Perfil de juego dentro de workspace/<juego>/")
    parser.add_argument("--motor", type=str, choices=["RPGMaker", "Godot", "Unity", "Unreal"], help="Forzar el motor de juego")
    parser.add_argument("--endpoint", type=str, default=config.OLLAMA_URL, help="URL de la API de Ollama")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")

    args = parser.parse_args()
    configurar_logging(detallado=args.debug)

    modo_final = "turbo" if args.turbo else args.modo

    injector = GameEngineInjector(
        ruta_juego=args.ruta,
        archivo_objetivo=args.archivo,
        modelo=args.modelo,
        modo=modo_final,
        juego=args.juego,
        endpoint=args.endpoint,
        motor_forzado=args.motor,
    )
    injector.run()


if __name__ == "__main__":
    main(default_mode="seguro")
