"""Inyector de configuración para Unity y XUnity.AutoTranslator."""
from __future__ import annotations

import configparser
import logging
from pathlib import Path
from .. import config

log = logging.getLogger(__name__)


def inyectar_unity(ruta_juego: Path, modelo: str = config.MODELO_POR_DEFECTO, endpoint: str = config.OLLAMA_URL) -> Path:
    """Configura el framework BepInEx y XUnity.AutoTranslator para usar la IA local.

    Crea o actualiza AutoTranslatorConfig.ini apuntando al modelo y endpoint configurados.
    """
    log.info("Configurando framework BepInEx y XUnity.AutoTranslator...")

    auto_translator_dir = ruta_juego / "BepInEx" / "config"
    auto_translator_dir.mkdir(parents=True, exist_ok=True)
    config_path = auto_translator_dir / "AutoTranslatorConfig.ini"

    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # Preserva mayúsculas y minúsculas

    if config_path.exists():
        try:
            cfg.read(config_path, encoding="utf-8")
        except Exception as e:
            log.warning("No se pudo leer la configuración previa de AutoTranslator: %s", e)

    if "Service" not in cfg:
        cfg["Service"] = {}
    cfg["Service"]["Endpoint"] = "CustomHTTP"

    # Plantilla de llamada HTTP a Ollama usando el modelo y endpoint dinámicos
    template = f'{{"model": "{modelo}", "prompt": "{{0}}", "stream": false}}'
    cfg["CustomHTTP"] = {
        "Url": endpoint,
        "Method": "POST",
        "RequestTemplate": template,
        "ResponsePath": "response",
    }

    if "General" not in cfg:
        cfg["General"] = {}
    cfg["General"]["Language"] = "es"
    cfg["General"]["FromLanguage"] = "en"

    with open(config_path, "w", encoding="utf-8") as f:
        cfg.write(f)

    log.info("¡Éxito! Archivo de AutoTranslator generado en: %s", config_path)
    return config_path
