"""Submódulo de motores de videojuegos y estrategias de traducción."""
from __future__ import annotations

from .detector import detectar_motor
from .rpgmaker import InyectorRPGMaker
from .csv_locales import InyectorCSV
from .unity import inyectar_unity

__all__ = ["detectar_motor", "InyectorRPGMaker", "InyectorCSV", "inyectar_unity"]
