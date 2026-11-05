"""1_traducir_juego.py — Traductor automático con IA local (Ollama).

Paso 1 del pipeline de traducción de videojuegos.
Soporta motores: RPG Maker (MV/MZ), Godot / CSV (DKTools), Unity (BepInEx/XUnity).
Si el juego aún no tiene ficha de personajes (workspace/<juego>/personajes.json), antes de traducir
la crea con el analizador del Paso 0 (--sin-analisis lo desactiva; --analizar-ia usa también la IA).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from traductor import config
from traductor.motores import InyectorCSV, InyectorRenPy, InyectorRPGMaker, detectar_motor, inyectar_unity
from traductor.motores.unity import archivo_xunity, repasar_xunity
from traductor.unity_dialogos import TablaHablantes, preparar_tabla, ruta_tabla
from traductor.ollama import OllamaNoDisponible, OllamaTranslator, ruta_cache_por_defecto
from traductor.progreso import EstadoProgreso
from traductor.registro import configurar_logging

log = logging.getLogger(__name__)


class GameEngineInjector:
    """Clase principal que orquesta la detección e inyección de traducción."""

    def __init__(self, ruta_juego: str | Path,
                 archivo_objetivo: str | None = None,
                 modelo: str | None = None,
                 modo: str = "seguro",
                 juego: str | None = None,
                 endpoint: str = config.OLLAMA_URL,
                 motor_forzado: str | None = None,
                 abrir_monitor: bool = True,
                 monitor_en_bandeja: bool = False,
                 analizar_personajes: bool = True,
                 analizar_con_ia: bool = False,
                 solo_genero: bool = False):
        self.ruta_juego = Path(ruta_juego)
        self.archivo_objetivo = archivo_objetivo
        self.modelo = modelo
        self.modo = modo
        self.motor_forzado = motor_forzado

        # Resolver perfil de juego (glosario activo + contexto específico)
        nombre_juego = config.resolver_juego(juego, self.ruta_juego)
        self.perfil = config.cargar_perfil(nombre_juego, ruta_juego=self.ruta_juego,
                                           analizar=analizar_personajes, usar_ia=analizar_con_ia)
        # Paso 0 automático: sin personajes.json el traductor no sabe quién es el protagonista
        # ni el género de cada personaje, así que se analiza el juego antes de traducir.
        if analizar_personajes and nombre_juego and self.perfil.personajes is None:
            analizar_ficha_personajes(nombre_juego, self.ruta_juego, usar_ia=analizar_con_ia)
            if config.ruta_personajes(nombre_juego).exists():
                self.perfil = config.cargar_perfil(nombre_juego, ruta_juego=self.ruta_juego, analizar=False)
        mostrar_ficha_personajes(self.perfil)
        # Modelo: --modelo; si no, el de workspace/<juego>/ajustes.json; si no (o "auto"), el automático
        # (v4 con ficha de personajes, v1 sin ella). Se decide DESPUÉS del Paso 0, que puede crear la ficha.
        eleccion = modelo or config.ajustes_juego(nombre_juego).get("modelo")  # lo pedido o lo guardado
        modelo = config.modelo_para_juego(nombre_juego, modelo)
        self.modelo = modelo
        if config.es_automatico(eleccion):
            log.info("🤖 Modelo automático: %s (%s).", modelo, config.modelo_automatico(nombre_juego)[1])
        log.info("Cargado %s (Modelo: %s)", self.perfil.resumen(), self.modelo)

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
        # Frases que el modelo falla al primer intento y arregla en un reintento -> ejemplos para reentrenar
        self.translator.activar_casos_dificiles()
        # --solo-genero: se conserva lo ya traducido (por otro modelo o lo que ya tiene el juego) y solo se
        # retraducen las frases con marcas de género y las que faltan
        self.solo_genero = solo_genero
        if solo_genero:
            self.translator.reaprovechar_cache_de()
        # Estado compartido con monitor_bandeja.py y servidor_progreso.py
        self.progreso = EstadoProgreso(nombre_juego, modelo, modo)
        self.translator.progreso = self.progreso

        if abrir_monitor:
            lanzar_monitor(en_bandeja=monitor_en_bandeja)

    def run(self) -> None:
        try:
            self._run()
        except KeyboardInterrupt:
            self.progreso.detenido()
            raise
        except SystemExit:
            raise
        except Exception as e:
            self.progreso.fallo(str(e))
            raise

    def _run(self) -> None:
        try:
            self.translator.comprobar_conexion()
        except OllamaNoDisponible as e:
            log.error("Error conectando con la IA: %s", e)
            self.progreso.fallo(str(e))
            sys.exit(1)

        motor = self.motor_forzado
        if not motor:
            if self.archivo_objetivo and self.archivo_objetivo.lower().endswith(".json"):
                log.info("Forzando motor RPG Maker por extensión de archivo (%s).", self.archivo_objetivo)
                motor = "RPGMaker"
            else:
                motor = detectar_motor(self.ruta_juego)

        log.info("--- Iniciando proceso con motor: %s (Modo: %s) ---", motor, self.modo.upper())
        self.progreso.estado = "traduciendo"
        self.progreso.guardar(forzar=True)

        try:
            if motor == "RPGMaker":
                inyector = InyectorRPGMaker(self.ruta_juego, self.translator, self.archivo_objetivo,
                                            reaprovechar_traduccion=self.solo_genero)
                inyector.procesar()
            elif motor == "Godot":
                inyector_csv = InyectorCSV(self.ruta_juego, self.translator,
                                           reaprovechar_traduccion=self.solo_genero)
                inyector_csv.procesar()
            elif motor == "RenPy":
                InyectorRenPy(self.ruta_juego, self.translator, self.archivo_objetivo).procesar()
            elif motor == "Unity" and self.solo_genero:
                # Juego de Unity ya traducido: repasar _AutoGeneratedTranslations.txt (sin abrir el proxy)
                juego = self.perfil.juego
                preparar_tabla(juego, self.ruta_juego)
                ruta_txt = archivo_xunity(self.ruta_juego)
                if not ruta_txt.exists():
                    log.error("No hay traducciones de XUnity que repasar en %s.", ruta_txt)
                else:
                    tabla = TablaHablantes.cargar(ruta_tabla(juego)) if juego else TablaHablantes({})
                    repasar_xunity(ruta_txt, self.translator, tabla)
            elif motor == "Unity":
                inyectar_unity(self.ruta_juego, modelo=self.modelo, endpoint=self.translator.endpoint,
                               juego=self.perfil.juego)
                import ollama_proxy
                log.info("Iniciando servidor proxy de traducción para Unity en tiempo real...")
                ollama_proxy.ejecutar_proxy(self.translator)
            elif motor == "Unreal":
                log.warning("El motor Unreal Engine aún no tiene inyección directa automatizada.")
            else:
                log.error("No se pudo determinar una estrategia para el juego en %s.", self.ruta_juego)
        finally:
            self.translator.cerrar()

        stats = self.translator.estadisticas
        log.info("--- Proceso completado --- (Nuevas: %d | Caché: %d | Autocorregidas: %d)",
                 stats["traducidas"], stats["cache"], stats["autocorregidas"])
        self.progreso.finalizar(cache=stats["cache"])


def analizar_ficha_personajes(juego: str, ruta_juego: Path, usar_ia: bool = False) -> bool:
    """Crea ``workspace/<juego>/personajes.json`` con el analizador del Paso 0.

    Devuelve True si se ha generado la ficha. Si el analizador no existe o falla, se avisa y se
    traduce como siempre (sin ficha): nunca impide traducir.
    """
    log.info("🔎 No hay ficha de personajes para '%s': analizando el juego (protagonista, "
             "personajes y su género)...", juego)
    try:
        from traductor.analizador import analizar_y_guardar
    except Exception as e:
        log.warning("⚠ No se pudo cargar el analizador de personajes (%s). Se traduce sin ficha.", e)
        return False
    try:
        ruta, informe = analizar_y_guardar(juego, ruta_juego, usar_ia=usar_ia)
    except Exception as e:
        log.warning("⚠ El análisis de personajes ha fallado (%s). Se traduce sin ficha.", e)
        return False
    for aviso in getattr(informe, "avisos", None) or []:
        log.warning("  ⚠ %s", aviso)
    if ruta is None:
        log.warning("⚠ El análisis no ha generado personajes.json. Se traduce sin ficha.")
        return False
    log.info("👥 Ficha de personajes creada en: %s", ruta)
    return True


def mostrar_ficha_personajes(perfil: config.Perfil) -> None:
    """Resume la ficha de personajes y avisa de los personajes importantes que conviene revisar."""
    ficha = perfil.personajes
    if ficha is None:
        log.info("👥 Sin ficha de personajes (personajes.json): se usa la regla global de siempre "
                 "(protagonista en masculino).")
        return
    log.info("👥 Personajes: %s", ficha.resumen())
    pendientes = ficha.pendientes_de_revisar()
    for p in pendientes:
        log.warning("  ⚠ Revisa en personajes.json: %s [%s, confianza %d%%]",
                    p.etiqueta(), p.rol, round(p.confianza * 100))
    if pendientes:
        log.warning("  Corrige la ficha (Centro de Control > Personajes, o editando %s) para evitar "
                    "adjetivos de hombre/mujer donde no toca.", config.ruta_personajes(perfil.juego))


def lanzar_monitor(en_bandeja: bool = False) -> None:
    """Arranca herramientas_extra/monitor_bandeja.py.
    Por defecto abre la ventana para que el usuario la vea de inmediato y pueda minimizarla.
    Si ya hay una instancia abierta, la trae al frente sin duplicar iconos."""
    import subprocess
    script = config.RAIZ / "herramientas_extra" / "monitor_bandeja.py"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    cmd = [exe, str(script)]
    if en_bandeja:
        cmd.append("--bandeja")
    try:
        subprocess.Popen(cmd, cwd=str(config.RAIZ))
        log.info("Monitor de traducción iniciado automáticamente.")
    except OSError as e:
        log.warning("No se pudo abrir el monitor: %s", e)


def main(default_mode: str = "seguro") -> None:
    parser = argparse.ArgumentParser(description="Auto-Inyector de IA Traductora Local en Videojuegos.")
    parser.add_argument("--ruta", type=str, required=True, help="Ruta de la carpeta del juego.")
    parser.add_argument("--archivo", type=str, required=False, help="Traducir solo un archivo específico (ej. System.json o Map005.json)")
    parser.add_argument("--modelo", type=str, default=None,
                        help="Modelo de Ollama o 'auto' (por defecto el de workspace/<juego>/ajustes.json o el "
                             f"automático: {config.MODELO_CON_FICHA} si el juego tiene ficha de personajes, "
                             f"{config.MODELO_SIN_FICHA} si no)")
    parser.add_argument("--modo", choices=["seguro", "turbo"], default=default_mode, help="Modo seguro (frase a frase con contexto) o turbo (en lotes)")
    parser.add_argument("--turbo", action="store_true", help="Atajo para forzar modo turbo")
    parser.add_argument("--juego", type=str, required=False, help="Perfil de juego dentro de workspace/<juego>/")
    parser.add_argument("--motor", type=str, choices=["RPGMaker", "RenPy", "Godot", "Unity", "Unreal"], help="Forzar el motor de juego")
    parser.add_argument("--endpoint", type=str, default=config.OLLAMA_URL, help="URL de la API de Ollama")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    parser.add_argument("--sin-monitor", action="store_true",
                        help="No abrir automáticamente la aplicación del monitor")
    parser.add_argument("--bandeja", action="store_true",
                        help="Arrancar el monitor directamente escondido en la bandeja (sin mostrar la ventana)")
    parser.add_argument("--sin-analisis", action="store_true",
                        help="No analizar los personajes del juego aunque falte personajes.json (Paso 0)")
    parser.add_argument("--analizar-ia", action="store_true",
                        help="Usar también la IA (Ollama) al analizar los personajes (más lento)")
    parser.add_argument("--solo-genero", action="store_true",
                        help="Juego ya traducido: conserva su traducción (la del juego o la caché de otro modelo) "
                             "y solo retraduce las frases con marcas de género y las que faltan. Útil al cambiar "
                             "a un modelo que acierta más el género sin retraducir el juego entero")

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
        abrir_monitor=not args.sin_monitor,
        monitor_en_bandeja=args.bandeja,
        analizar_personajes=not args.sin_analisis,
        analizar_con_ia=args.analizar_ia,
        solo_genero=args.solo_genero,
    )
    injector.run()


if __name__ == "__main__":
    main(default_mode="seguro")
