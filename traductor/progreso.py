"""Estado de progreso compartido entre el traductor y los monitores (bandeja y web).

El traductor escribe ``workspace/progreso_actual.json`` de forma atómica y con un
límite de frecuencia (no más de una escritura por segundo salvo eventos importantes).
Cualquier monitor (``monitor_bandeja.py``, ``servidor_progreso.py``) solo tiene que leer
ese archivo; así no dependen de rutas de logs ni de cifras estimadas a mano.

Formato (todas las claves son opcionales para el lector):
    {
      "juego": "treasure_of_nadia", "modelo": "IA_Traductora", "modo": "turbo",
      "estado": "preparando" | "traduciendo" | "completado" | "error" | "detenido",
      "porcentaje": 47.3,
      "frases_hechas": 15000, "frases_totales": 31700,
      "frases_nuevas": 9000, "frases_cache": 6000,
      "archivo_actual": "Map105.json", "archivos_hechos": 112, "archivos_totales": 218,
      "velocidad_fpm": 450.0, "eta_segundos": 2100,
      "ultimas_frases": [{"id": 9000, "texto": "..."}],   # la más reciente primero
      "mensaje": "", "pid": 1234, "inicio": 1791000000.0, "actualizado": 1791000100.0
    }
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from . import config

ARCHIVO_PROGRESO = config.DIR_WORKSPACE / "progreso_actual.json"
MAX_ULTIMAS_FRASES = 8
INTERVALO_ESCRITURA = 1.0  # segundos


def leer_progreso(ruta: Path = ARCHIVO_PROGRESO) -> dict[str, Any] | None:
    """Lee el estado actual. Devuelve None si no existe o está a medio escribir."""
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def proceso_vivo(pid: int | None) -> bool:
    """Comprueba si el proceso traductor sigue en marcha (para detectar cierres bruscos)."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            codigo = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(codigo)):
                return False
            return codigo.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


class EstadoProgreso:
    """Acumula el progreso del traductor y lo vuelca a disco periódicamente."""

    def __init__(self, juego: str | None, modelo: str, modo: str,
                 ruta: Path = ARCHIVO_PROGRESO):
        self.ruta = ruta
        self._lock = threading.Lock()
        self._ultima_escritura = 0.0
        self._ultimas: deque[dict[str, Any]] = deque(maxlen=MAX_ULTIMAS_FRASES)
        self._id_frase = 0
        self._inicio = time.time()
        self._primera_nueva: float | None = None

        # Totales globales (si el motor los conoce de antemano)
        self.frases_totales = 0
        self.archivos_totales = 0
        # Progreso acumulado de archivos ya terminados
        self._frases_archivos_previos = 0
        self.archivos_hechos = 0
        # Archivo en curso
        self.archivo_actual = ""
        self._frases_archivo_total = 0
        self._frases_archivo_hechas = 0

        self.frases_nuevas = 0
        self.estado = "preparando"
        self.mensaje = ""
        self.datos_base = {"juego": juego or "", "modelo": modelo, "modo": modo}
        self.guardar(forzar=True)

    # ----------------------------------------------------------------- API del motor
    def definir_totales(self, frases: int, archivos: int) -> None:
        self.frases_totales = max(0, frases)
        self.archivos_totales = max(0, archivos)
        self.estado = "traduciendo"
        self.guardar(forzar=True)

    def inicio_archivo(self, nombre: str, indice: int, n_frases: int) -> None:
        self.archivo_actual = nombre
        self.archivos_hechos = max(0, indice - 1)
        self._frases_archivo_total = max(0, n_frases)
        self._frases_archivo_hechas = 0
        self.estado = "traduciendo"
        self.guardar(forzar=True)

    def avance_archivo(self, hechas: int) -> None:
        """Número de frases del archivo actual ya resueltas (caché + nuevas)."""
        self._frases_archivo_hechas = min(max(hechas, self._frases_archivo_hechas),
                                          self._frases_archivo_total or hechas)
        self.guardar()

    def fin_archivo(self) -> None:
        self._frases_archivos_previos += self._frases_archivo_total
        self._frases_archivo_total = 0
        self._frases_archivo_hechas = 0
        self.archivos_hechos += 1
        self.guardar()

    def frase_nueva(self, texto: str) -> None:
        """Registra una frase recién traducida por la IA (no las de caché)."""
        with self._lock:
            if self._primera_nueva is None:
                self._primera_nueva = time.time()
            self.frases_nuevas += 1
            self._id_frase += 1
            self._ultimas.appendleft({"id": self._id_frase, "texto": texto.replace("\n", " ")[:200]})
        self.guardar()

    def finalizar(self, cache: int = 0) -> None:
        self.estado = "completado"
        self.archivos_hechos = self.archivos_totales or self.archivos_hechos
        self._frases_archivos_previos = self.frases_totales or self._frases_archivos_previos
        self._frases_archivo_total = self._frases_archivo_hechas = 0
        self.archivo_actual = ""
        self.mensaje = f"Nuevas: {self.frases_nuevas} | Caché: {cache}"
        self.guardar(forzar=True)

    def fallo(self, mensaje: str) -> None:
        self.estado = "error"
        self.mensaje = mensaje[:300]
        self.guardar(forzar=True)

    def detenido(self) -> None:
        self.estado = "detenido"
        self.mensaje = "Traducción interrumpida por el usuario"
        self.guardar(forzar=True)

    # ----------------------------------------------------------------- Cálculos
    @property
    def frases_hechas(self) -> int:
        return self._frases_archivos_previos + self._frases_archivo_hechas

    def porcentaje(self) -> float:
        if self.estado == "completado":
            return 100.0
        if self.frases_totales:
            return round(min(99.9, self.frases_hechas * 100 / self.frases_totales), 1)
        if self.archivos_totales:
            fraccion = (self._frases_archivo_hechas / self._frases_archivo_total
                        if self._frases_archivo_total else 0)
            return round(min(99.9, (self.archivos_hechos + fraccion) * 100 / self.archivos_totales), 1)
        return 0.0

    def _velocidad_y_eta(self) -> tuple[float, int | None]:
        """Velocidad en frases nuevas/min y segundos restantes estimados."""
        if self._primera_nueva is None or self.frases_nuevas < 5:
            return 0.0, None
        minutos = max((time.time() - self._primera_nueva) / 60, 1 / 60)
        fpm = self.frases_nuevas / minutos
        restantes = max(0, self.frases_totales - self.frases_hechas) if self.frases_totales else 0
        eta = int(restantes / fpm * 60) if fpm > 0 and restantes else None
        return round(fpm, 1), eta

    def a_dict(self) -> dict[str, Any]:
        fpm, eta = self._velocidad_y_eta()
        with self._lock:
            ultimas = list(self._ultimas)
        return {
            **self.datos_base,
            "estado": self.estado,
            "porcentaje": self.porcentaje(),
            "frases_hechas": self.frases_hechas,
            "frases_totales": self.frases_totales,
            "frases_nuevas": self.frases_nuevas,
            "frases_cache": max(0, self.frases_hechas - self.frases_nuevas),
            "archivo_actual": self.archivo_actual,
            "archivos_hechos": self.archivos_hechos,
            "archivos_totales": self.archivos_totales,
            "velocidad_fpm": fpm,
            "eta_segundos": eta,
            "ultimas_frases": ultimas,
            "mensaje": self.mensaje,
            "pid": os.getpid(),
            "inicio": self._inicio,
            "actualizado": time.time(),
        }

    # ----------------------------------------------------------------- Persistencia
    def guardar(self, forzar: bool = False) -> None:
        ahora = time.time()
        if not forzar and ahora - self._ultima_escritura < INTERVALO_ESCRITURA:
            return
        self._ultima_escritura = ahora
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.ruta.with_name(self.ruta.name + ".tmp")
            tmp.write_text(json.dumps(self.a_dict(), ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.ruta)
        except OSError:
            # Un monitor leyendo el archivo justo en ese instante no debe tumbar la traducción
            pass
