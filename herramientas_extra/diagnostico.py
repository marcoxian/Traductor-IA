"""diagnostico.py — Sistema de Diagnóstico, Depuración y Reporte para el Asistente IA.

Examina el entorno de ejecución completo:
1. Sistema operativo y binario de Python activo.
2. GPU, controladores NVIDIA y VRAM libre/total.
3. Estado del servidor Ollama y modelos de traducción instalados.
4. Estado del servidor web de progreso en vivo.
5. Estado del archivo de progreso y última sesión de traducción.
6. Detección del motor del juego activo según la ruta configurada.
7. Logs y trazas de error recientes (monitor_error.log, crash_gui.log).
8. Copia automáticamente el reporte al portapapeles de Windows para pasarlo a la IA con 1 clic (Ctrl+V).
"""
from __future__ import annotations

import argparse
import datetime
import importlib.metadata
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Asegurar UTF-8 en la consola de Windows para evitar errores con emojis y tildes en cp1252
for flujo in (sys.stdout, sys.stderr):
    try:
        flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
if os.name == "nt":
    os.system("")  # Habilita secuencias ANSI / VT100 en Windows CMD

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from traductor import config
from traductor.motores import detectar_motor
from traductor.progreso import ARCHIVO_PROGRESO, leer_progreso

ARCHIVO_REPORTE_ROOT = RAIZ / "reporte_diagnostico.txt"
ARCHIVO_REPORTE_WS = config.DIR_WORKSPACE / "reporte_diagnostico.txt"
LOG_MONITOR = RAIZ / "herramientas_extra" / "monitor_error.log"
LOG_CRASH = config.DIR_WORKSPACE / "crash_gui.log"
LOG_DEBUG_CMD = config.DIR_WORKSPACE / "depuracion_consola.log"


def obtener_espacio_disco(ruta: Path) -> str:
    """Devuelve espacio libre y total del disco que contiene la ruta."""
    try:
        total, used, free = shutil.disk_usage(ruta)
        gb = 1024 ** 3
        return f"{free / gb:.1f} GB libres de {total / gb:.1f} GB ({used / gb:.1f} GB usados)"
    except Exception as e:
        return f"No disponible ({e})"


def diagnosticar_gpu() -> dict:
    """Inspecciona la GPU NVIDIA y memoria mediante nvidia-smi y PyTorch."""
    resultado = {
        "disponible": False,
        "nombre": "No detectada",
        "driver": "Desconocido",
        "vram_total": "—",
        "vram_libre": "—",
        "cuda_version": "—",
        "torch_cuda": False,
        "torch_gpu": "—",
        "detalles": ""
    }

    # Probar nvidia-smi
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if proc.returncode == 0 and proc.stdout.strip():
            partes = [p.strip() for p in proc.stdout.strip().split(",")]
            if len(partes) >= 4:
                resultado["disponible"] = True
                resultado["nombre"] = partes[0]
                resultado["driver"] = partes[1]
                resultado["vram_total"] = partes[2]
                resultado["vram_libre"] = partes[3]
    except Exception as e:
        resultado["detalles"] = f"nvidia-smi no ejecutable: {e}"

    # Probar PyTorch si está importable
    try:
        import torch
        resultado["torch_cuda"] = bool(torch.cuda.is_available())
        if resultado["torch_cuda"]:
            resultado["torch_gpu"] = torch.cuda.get_device_name(0)
            resultado["cuda_version"] = getattr(torch.version, "cuda", "Desconocida")
    except Exception:
        pass

    return resultado


def diagnosticar_ollama(endpoint: str = config.OLLAMA_URL) -> dict:
    """Comprueba la conexión con el endpoint de Ollama y lista modelos instalados."""
    # Extraer el host base (ej. 'http://localhost:11434') si el endpoint trae '/api/generate'
    base = re.sub(r"/api(/.*)?$", "", endpoint.rstrip("/"))
    resultado = {
        "conectado": False,
        "endpoint": base,
        "modelos": [],
        "modelo_traductor_ok": False,
        "error": None
    }
    url = f"{base}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TraductorIA-Diag/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                modelos = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                resultado["conectado"] = True
                resultado["modelos"] = modelos
                resultado["modelo_traductor_ok"] = any("IA_Traductora" in m for m in modelos)
    except Exception as e:
        resultado["error"] = str(e)

    return resultado


def diagnosticar_servidor_web(url: str = "http://localhost:5050") -> dict:
    """Comprueba el estado del servidor web de progreso en vivo."""
    resultado = {"activo": False, "url": url, "error": None}
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/estado", headers={"User-Agent": "TraductorIA-Diag/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                resultado["activo"] = True
    except Exception as e:
        resultado["error"] = str(e)
    return resultado


def leer_ultimas_lineas_archivo(ruta: Path, n: int = 25) -> list[str]:
    """Devuelve las últimas n líneas de un archivo de texto con manejo de codificación seguro."""
    if not ruta.exists() or ruta.stat().st_size == 0:
        return []
    try:
        contenido = ruta.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            contenido = ruta.read_text(encoding="cp1252", errors="replace")
        except Exception:
            return [f"[Error al leer archivo {ruta.name}]"]

    lineas = contenido.strip().splitlines()
    return lineas[-n:] if len(lineas) > n else lineas


def diagnosticar_paquetes() -> dict[str, str]:
    """Comprueba las versiones de los paquetes clave de Python de forma rápida y sin importar módulos pesados."""
    paquetes = [
        ("pystray", "pystray"),
        ("Pillow (PIL)", "Pillow"),
        ("flask", "Flask"),
        ("flask_cors", "Flask-Cors"),
        ("requests", "requests"),
        ("torch", "torch"),
        ("unsloth", "unsloth"),
        ("transformers", "transformers"),
    ]
    resultado = {}
    for nombre_visible, dist in paquetes:
        try:
            ver = importlib.metadata.version(dist)
            resultado[nombre_visible] = ver
        except importlib.metadata.PackageNotFoundError:
            # Fallback a importar por si está en site-packages sin metadata
            try:
                mod = __import__(dist.lower().replace("-", "_"))
                resultado[nombre_visible] = getattr(mod, "__version__", "Instalado")
            except Exception:
                resultado[nombre_visible] = "NO INSTALADO"
        except Exception as e:
            resultado[nombre_visible] = f"Error: {e}"

    # Chequeo rápido de tkinter
    try:
        import tkinter
        resultado["tkinter"] = f"OK (Tcl/Tk {getattr(tkinter, 'TkVersion', '')})"
    except Exception as e:
        resultado["tkinter"] = f"Error: {e}"

    return resultado


def generar_reporte_completo(ruta_juego: str | None = None) -> str:
    """Genera el informe completo de diagnóstico en formato Markdown estructurado."""
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lineas = [
        "================================================================================",
        "          🛠️ REPORTE DE DIAGNÓSTICO Y DEPURACIÓN — TRADUCTOR IA",
        "================================================================================",
        f"Fecha y Hora: {ahora}",
        f"Directorio Raíz: {RAIZ}",
        "",
        "--- [1] SISTEMA OPERATIVO Y ENTORNO PYTHON ---",
        f"• Sistema Operativo: {platform.system()} {platform.release()} (Versión: {platform.version()})",
        f"• Arquitectura: {platform.machine()} ({platform.architecture()[0]})",
        f"• Procesador: {platform.processor() or 'Desconocido'}",
        f"• Espacio en Disco ({RAIZ.drive or 'J:'}): {obtener_espacio_disco(RAIZ)}",
        f"• Python Ejecutable: {sys.executable}",
        f"• Python Versión: {sys.version.splitlines()[0]}",
        f"• Entorno Virtual: {'SÍ (Activo)' if sys.prefix != sys.base_prefix else 'NO (Python global)'}",
        "",
        "--- [2] HARDWARE Y GPU (NVIDIA / CUDA) ---"
    ]

    gpu = diagnosticar_gpu()
    if gpu["disponible"]:
        lineas.append(f"• Tarjeta Gráfica: {gpu['nombre']}")
        lineas.append(f"• Driver NVIDIA: {gpu['driver']}")
        lineas.append(f"• VRAM Libre / Total: {gpu['vram_libre']} / {gpu['vram_total']}")
    else:
        lineas.append(f"• Tarjeta Gráfica: {gpu['nombre']} (Aviso: nvidia-smi no detectó GPU dedicada)")
        if gpu["detalles"]:
            lineas.append(f"  Detalle: {gpu['detalles']}")

    if gpu["torch_cuda"]:
        lineas.append(f"• PyTorch CUDA: DISPONIBLE (Dispositivo: {gpu['torch_gpu']} • CUDA {gpu['cuda_version']})")
    else:
        lineas.append("• PyTorch CUDA: No detectado en este ejecutable (ejecución por CPU para PyTorch)")

    lineas.append("")
    lineas.append("--- [3] SERVICIO DE IA (OLLAMA) ---")
    ollama = diagnosticar_ollama()
    if ollama["conectado"]:
        lineas.append(f"• Estado: CONECTADO y RESPONDIENDO ({ollama['endpoint']})")
        lineas.append(f"• Modelos Instalados ({len(ollama['modelos'])}): {', '.join(ollama['modelos']) if ollama['modelos'] else 'Ninguno'}")
        if ollama["modelo_traductor_ok"]:
            lineas.append("• Modelo 'IA_Traductora': PRESENTE Y LISTO ✔")
        else:
            lineas.append("• Modelo 'IA_Traductora': NO ENCONTRADO en Ollama ⚠ (Ejecuta 'ollama create IA_Traductora -f Modelfile')")
    else:
        lineas.append(f"• Estado: DESCONECTADO O NO RESPONDE ({ollama['endpoint']}) ✖")
        lineas.append(f"• Causa detectada: {ollama['error']}")
        lineas.append("• Sugerencia: Inicia Ollama en Windows ('ollama serve' o abre la aplicación Ollama).")

    lineas.append("")
    lineas.append("--- [4] SERVICIOS AUXILIARES ---")
    web = diagnosticar_servidor_web()
    lineas.append(f"• Monitor Web (http://localhost:5050): {'ACTIVO ✔' if web['activo'] else 'Inactivo (Se iniciará al traducir)'}")

    # Paquetes clave
    paquetes = diagnosticar_paquetes()
    lineas.append("• Dependencias Python:")
    for pkg, ver in paquetes.items():
        lineas.append(f"  - {pkg:<14}: {ver}")

    # Juego seleccionado
    ruta_eval = ruta_juego
    if not ruta_eval:
        cfg_gui = RAIZ / "workspace" / "config_gui.json"
        if cfg_gui.exists():
            try:
                ruta_eval = json.loads(cfg_gui.read_text(encoding="utf-8")).get("ultima_ruta")
            except Exception:
                pass

    lineas.append("")
    lineas.append("--- [5] JUEGO ACTIVO Y MOTOR DETECTADO ---")
    if ruta_eval and Path(ruta_eval).exists():
        p_juego = Path(ruta_eval)
        motor = detectar_motor(p_juego)
        perfil = config.resolver_juego(None, p_juego)
        lineas.append(f"• Carpeta del Juego: {p_juego}")
        lineas.append(f"• Motor Detectado: {motor}")
        lineas.append(f"• Perfil de Juego Asignado: {perfil}")
    elif ruta_eval:
        lineas.append(f"• Carpeta configurada ({ruta_eval}): NO EXISTE O NO ES ACCESIBLE ⚠")
    else:
        lineas.append("• Ninguna carpeta de juego seleccionada aún.")

    # Progreso de traducción actual
    lineas.append("")
    lineas.append("--- [6] ESTADO DEL PROCESO DE TRADUCCIÓN ---")
    prog = leer_progreso()
    if prog:
        lineas.append(f"• Estado Actual: {prog.get('estado', 'desconocido').upper()}")
        lineas.append(f"• Juego: {prog.get('juego', '—')}")
        lineas.append(f"• Modo: {prog.get('modo', '—')} | Modelo: {prog.get('modelo', '—')}")
        lineas.append(f"• Progreso: {prog.get('porcentaje', 0):.1f}% ({prog.get('frases_hechas', 0)} / {prog.get('frases_totales', 0)} frases)")
        lineas.append(f"• Archivo en Curso: {prog.get('archivo_actual') or 'Ninguno'}")
        if prog.get("mensaje"):
            lineas.append(f"• Mensaje / Aviso: {prog.get('mensaje')}")
    else:
        lineas.append("• No hay ninguna sesión de traducción registrada en workspace/progreso_actual.json.")

    # Registros de error
    lineas.append("")
    lineas.append("--- [7] REGISTRO DE ERRORES RECIENTES ---")
    errores_encontrados = False

    if LOG_CRASH.exists() and LOG_CRASH.stat().st_size > 0:
        lineas.append("▼ Últimas líneas de crash_gui.log:")
        for l in leer_ultimas_lineas_archivo(LOG_CRASH, 20):
            lineas.append(f"  {l}")
        errores_encontrados = True

    if LOG_MONITOR.exists() and LOG_MONITOR.stat().st_size > 0:
        lineas.append("▼ Últimas líneas de monitor_error.log:")
        for l in leer_ultimas_lineas_archivo(LOG_MONITOR, 20):
            lineas.append(f"  {l}")
        errores_encontrados = True

    if not errores_encontrados:
        lineas.append("• No se registran errores recientes en los archivos de log principales.")

    lineas.append("")
    lineas.append("================================================================================")
    lineas.append("Fin del reporte. Puedes copiar y pegar todo este bloque en el chat de la IA.")
    lineas.append("================================================================================")

    return "\n".join(lineas)


def copiar_al_portapapeles(texto: str) -> bool:
    """Copia texto al portapapeles de Windows usando clip.exe nativo o tkinter."""
    # Método 1: clip nativo de Windows (no falla nunca)
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["clip"],
                input=texto.encode("utf-16le"),
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if proc.returncode == 0:
                return True
        except Exception:
            pass

    # Método 2: tkinter
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(texto)
        root.update()
        root.destroy()
        return True
    except Exception:
        pass

    return False


def guardar_reporte(texto: str) -> tuple[Path, Path]:
    """Guarda el reporte en disco en la raíz y en workspace."""
    config.DIR_WORKSPACE.mkdir(parents=True, exist_ok=True)
    ARCHIVO_REPORTE_WS.write_text(texto, encoding="utf-8")
    ARCHIVO_REPORTE_ROOT.write_text(texto, encoding="utf-8")
    return ARCHIVO_REPORTE_ROOT, ARCHIVO_REPORTE_WS


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico y Depuración del Traductor IA.")
    parser.add_argument("--ruta", help="Ruta de la carpeta del juego a inspeccionar")
    parser.add_argument("--no-clip", action="store_true", help="No copiar automáticamente al portapapeles")
    parser.add_argument("--solo-guardar", action="store_true", help="Guardar archivo sin imprimir en consola")
    args = parser.parse_args()

    reporte = generar_reporte_completo(ruta_juego=args.ruta)
    p_root, _ = guardar_reporte(reporte)

    copiado = False
    if not args.no_clip:
        copiado = copiar_al_portapapeles(reporte)

    if not args.solo_guardar:
        print(reporte)
        print()
        if copiado:
            print("========================================================================")
            print("📋 ¡REPORTE COPIADO AUTOMÁTICAMENTE AL PORTAPAPELES!")
            print("Puedes ir a tu chat con la IA y pulsar Ctrl + V para enviármelo directamente.")
            print(f"Copia guardada en: {p_root.name}")
            print("========================================================================")
        else:
            print(f"Reporte guardado en: {p_root}")


if __name__ == "__main__":
    main()
