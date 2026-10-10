"""Detección automática del motor de juego y directorio de datos."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def detectar_motor(ruta_juego: Path) -> str:
    """Escanea la ruta del juego para determinar qué motor utiliza.

    Orden de comprobación prioritario:
    1. RPG Maker (MV/MZ o RGSS): comprobado antes que CSV genéricos para no confundir
       plugins de traducción con Godot.
    2. Unity: UnityPlayer.dll o carpeta *_Data.
    3. Godot: archivos .pck o proyectos con .csv de localización.
    4. Unreal: Engine/Binaries o estructura de Unreal.
    5. Unknown: si no se reconoce un patrón conocido.
    """
    if not ruta_juego.exists():
        log.error("La ruta especificada no existe: %s", ruta_juego)
        return "Unknown"

    # 1. RPG Maker: www/data (MV), data (MZ), o librerías RGSS (XP/VX/VX Ace)
    if (ruta_juego / "www" / "data").exists() or (ruta_juego / "data").exists():
        log.info("Motor RPG Maker (MV/MZ) detectado por estructura de carpetas de datos.")
        return "RPGMaker"
    if any(ruta_juego.glob("*.rgss*")):
        log.info("Motor RPG Maker clásico detectado (.rgss).")
        return "RPGMaker"

    # 2. Unity
    if (ruta_juego / "UnityPlayer.dll").exists() or any(ruta_juego.glob("*_Data")):
        log.info("Motor Unity detectado (Compatible con XUnity.AutoTranslator).")
        return "Unity"

    # 3. Godot
    if any(ruta_juego.glob("*.pck")) or any(ruta_juego.glob("**/*.csv")):
        log.info("Motor Godot / CSV detectado.")
        return "Godot"

    # 4. Unreal Engine
    if (ruta_juego / "Engine" / "Binaries").exists():
        log.info("Motor Unreal Engine detectado.")
        return "Unreal"

    log.warning("No se detectó un patrón de motor reconocible en %s.", ruta_juego)
    return "Unknown"
