"""ollama_proxy.py — Servidor Proxy de traducción para plugins como XUnity.AutoTranslator.

Mejoras de fiabilidad (oct-2026):
  - Deduplicación de peticiones en vuelo y bloqueo de generación para no saturar Ollama con hilos paralelos.
  - Si la traducción falla o no supera la puerta de calidad, responde HTTP 503 en lugar de HTTP 200 con
    el texto en inglés (evita que XUnity guarde el inglés como "traducción" permanente en disco).
  - Resuelve el perfil de juego aunque la carpeta lleve sufijos como ``_demo`` y lee el modelo preferido
    de ``workspace/<juego>/ajustes.json`` cuando no se pasa ``--modelo`` explícito.
  - Precalienta el modelo en VRAM al arrancar para evitar timeouts en el primer diálogo.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from traductor import config
from traductor.ollama import OllamaTranslator, TraduccionFallida, ruta_cache_por_defecto
from traductor.texto import evaluar_traduccion, tiene_fallo_grave, tiene_texto_visible
from traductor.unity_dialogos import TablaHablantes, ruta_tabla

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("ProxyUnity")


class TranslationHandler(BaseHTTPRequestHandler):
    translator: OllamaTranslator
    hablantes: TablaHablantes = TablaHablantes({})  # quién dice cada frase (si el juego lo guarda)
    _lock_vuelo = threading.Lock()
    _lock_gpu = threading.Lock()
    _en_vuelo: dict[str, threading.Event] = {}
    _resultados_vuelo: dict[str, tuple[int, str]] = {}

    def _responder(self, codigo: int, texto: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = texto.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _traducir_coordinado(self, text: str) -> tuple[int, str]:
        # Respuesta inmediata para textos de 1 carácter o sin letras visibles (evita saturar GPU y spam)
        texto_limpio_zalgo = re.sub(r"[\u0300-\u036f\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]", "", text)
        if len(text.strip()) <= 1 or not any(c.isalnum() for c in text):
            return (200, text)

        with self._lock_vuelo:
            evento_existente = self._en_vuelo.get(text)
            if evento_existente is not None:
                esperar = True
            else:
                evento_existente = threading.Event()
                self._en_vuelo[text] = evento_existente
                esperar = False

        if esperar:
            evento_existente.wait(timeout=120)
            with self._lock_vuelo:
                return self._resultados_vuelo.get(text, (503, ""))

        try:
            texto_a_traducir = texto_limpio_zalgo if (texto_limpio_zalgo != text and len(texto_limpio_zalgo.strip()) >= 2) else text
            with self._lock_gpu:
                traducido = self.translator.translate(texto_a_traducir, info=self.hablantes.info(text))
            problemas = evaluar_traduccion(texto_a_traducir, traducido)
            if tiene_fallo_grave(problemas):
                raise TraduccionFallida(f"rechazado por puerta de calidad ({problemas})")
            resultado = (200, traducido)
        except Exception as e:
            log.error("❌ [Unity] Error traduciendo '%s': %s", text[:80], e)
            resultado = (503, "")
        finally:
            with self._lock_vuelo:
                self._resultados_vuelo[text] = resultado
                self._en_vuelo.pop(text, None)
                evento_existente.set()
        return resultado

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._responder(200, '{"status": "ok"}', "application/json; charset=utf-8")
            return

        if parsed.path in ("/translate", "/"):
            params = parse_qs(parsed.query)
            text = params.get("text", [""])[0]

            if not text.strip() or not tiene_texto_visible(text):
                self._responder(200, text if text.strip() else "")
                return

            origen = params.get("from", ["en"])[0]
            destino = params.get("to", ["es"])[0]
            t0 = time.time()
            log.info("📩 [Unity] Solicitud (%s->%s): %s", origen, destino, text)

            codigo, traducido = self._traducir_coordinado(text)
            duracion = time.time() - t0
            if codigo == 200:
                log.info("✨ [Unity] Traducido (%.2fs): %s", duracion, traducido)
            self._responder(codigo, traducido)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        # Suprimir logs HTTP por defecto para que la salida de consola sea limpia
        pass


def iniciar_servidor_proxy(translator: OllamaTranslator, puerto: int = 11435, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class CustomHandler(TranslationHandler):
        _lock_vuelo = threading.Lock()
        _lock_gpu = threading.Lock()
        _en_vuelo = {}
        _resultados_vuelo = {}

    CustomHandler.translator = translator
    juego = getattr(translator.perfil, "juego", None)
    if isinstance(juego, str) and juego:
        CustomHandler.hablantes = TablaHablantes.cargar(ruta_tabla(juego))
        if len(CustomHandler.hablantes):
            log.info("🗣 %d frases con hablante conocido (sacado de los archivos del juego).",
                     len(CustomHandler.hablantes))
    servidor = ThreadingHTTPServer((host, puerto), CustomHandler)
    return servidor


def ajustar_prioridad_baja() -> None:
    """Reduce la prioridad de Ollama en Windows para que el juego siempre tenga preferencia en CPU/GPU."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            name = (p.info["name"] or "").lower()
            if any(x in name for x in ["llama-server", "ollama"]):
                try:
                    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                except Exception:
                    pass
    except Exception:
        pass


def vigilar_juego(pid: int | None, juego_slug: str | None) -> None:
    """Monitorea el proceso del juego mediante el kernel de Windows y se apaga en 5ms cuando el juego se cierra."""
    def _bucle():
        import ctypes
        target_pid = pid
        if not target_pid and juego_slug:
            try:
                import psutil
                palabras = [p for p in juego_slug.replace("_", " ").split() if len(p) > 2]
                for _ in range(15):
                    for p in psutil.process_iter(["name"]):
                        try:
                            pname = (p.info["name"] or "").lower()
                            if any(palabra in pname for palabra in palabras):
                                target_pid = p.pid
                                break
                        except Exception:
                            pass
                    if target_pid:
                        break
                    time.sleep(1)
            except Exception:
                pass

        if not target_pid or target_pid <= 0:
            return

        SYNCHRONIZE = 0x00100000
        hProcess = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(target_pid))
        if hProcess:
            log.info("👁️ Kernel de Windows vigilando cierre del juego (PID: %d)...", target_pid)
            try:
                ctypes.windll.kernel32.WaitForSingleObject(hProcess, 0xFFFFFFFF)
            finally:
                ctypes.windll.kernel32.CloseHandle(hProcess)

            log.info("🛑 Juego cerrado detectado por el kernel. Finalizando servidor proxy...")
            try:
                os._exit(0)
            except Exception:
                pass

    hilo = threading.Thread(target=_bucle, daemon=True)
    hilo.start()


def ejecutar_proxy(translator: OllamaTranslator, puerto: int = 11435, host: str = "127.0.0.1", pid: int | None = None, juego: str | None = None) -> None:
    ajustar_prioridad_baja()
    vigilar_juego(pid, juego)
    try:
        servidor = iniciar_servidor_proxy(translator, puerto, host)
    except OSError as e:
        import requests
        try:
            r = requests.get(f"http://{host}:{puerto}/health", timeout=2)
            if r.status_code == 200:
                log.info("ℹ️ El servidor proxy de traducción ya está activo en http://%s:%d/translate", host, puerto)
                log.info("🎮 Puedes abrir el juego directamente; los textos se traducirán automáticamente.")
                return
        except Exception:
            pass
        log.error("❌ El puerto %d está ocupado por otra aplicación: %s", puerto, e)
        raise

    log.info("============================================================")
    log.info("🚀 Servidor Proxy de Traducción para Unity ACTIVO")
    log.info("🌐 Escuchando en: http://%s:%d/translate (perfil: %s | modelo: %s)",
             host, puerto, translator.perfil.juego or "global", translator.model_name)
    log.info("🎮 Abre tu juego en Steam/PC para que los textos se traduzcan en tiempo real")
    log.info("⏹  Presiona Ctrl+C o el botón 'Detener' para finalizar la sesión")
    log.info("============================================================")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("Deteniendo servidor proxy...")
    finally:
        servidor.server_close()
        translator.cerrar()
        log.info("Servidor proxy detenido.")


def _rutas_ejecutable_ollama() -> list[str]:
    import shutil
    local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    candidatos = [
        shutil.which("ollama"),
        str(Path(local_app) / "Programs" / "Ollama" / "ollama app.exe"),
        str(Path(local_app) / "Programs" / "Ollama" / "ollama.exe"),
    ]
    return [c for c in candidatos if c and Path(c).exists()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Proxy de traducción para XUnity.AutoTranslator")
    parser.add_argument("--juego", "-j", help="Nombre o slug del juego para cargar su perfil")
    parser.add_argument("--modelo", "-m", default=None, help="Modelo de Ollama a usar")
    parser.add_argument("--endpoint", "-e", default=config.OLLAMA_URL, help="Endpoint de Ollama")
    parser.add_argument("--puerto", "-p", type=int, default=11435, help="Puerto del proxy HTTP")
    parser.add_argument("--pid", type=int, default=None, help="PID del juego a vigilar para cerrarse con él")
    parser.add_argument("--debug", action="store_true", help="Activar modo depuración")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    juego_resuelto = config.resolver_perfil_existente(args.juego)
    modelo = config.modelo_para_juego(juego_resuelto, args.modelo)
    if config.es_automatico(args.modelo or config.ajustes_juego(juego_resuelto).get("modelo")):
        log.info("🤖 Modelo automático: %s (%s).", modelo, config.modelo_automatico(juego_resuelto)[1])

    perfil = config.cargar_perfil(juego_resuelto)
    ruta_cache = ruta_cache_por_defecto(juego_resuelto, modelo)
    translator = OllamaTranslator(
        model_name=modelo,
        endpoint=args.endpoint,
        perfil=perfil,
        ruta_cache=ruta_cache,
        usar_historial=True,
    )
    translator.activar_casos_dificiles()  # frases arregladas en un reintento -> ejemplos para reentrenar
    try:
        translator.comprobar_conexion()
    except Exception as e:
        log.warning("Ollama no responde en %s (%s). Intentando iniciar el servicio...", args.endpoint, e)
        import subprocess
        iniciado = False
        for exe in _rutas_ejecutable_ollama():
            try:
                cmd = [exe] if "app" in exe.lower() else [exe, "serve"]
                subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                iniciado = True
                break
            except Exception:
                pass
        if iniciado:
            log.info("Esperando a que Ollama esté listo...")
            for _ in range(20):
                time.sleep(0.5)
                try:
                    translator.comprobar_conexion()
                    log.info("Ollama conectado correctamente.")
                    break
                except Exception:
                    pass
            else:
                log.error("No se pudo conectar con Ollama tras iniciarlo: %s", e)
                sys.exit(1)
        else:
            log.error("No se pudo conectar con Ollama ni encontrar su ejecutable: %s", e)
            sys.exit(1)

    log.info("Precalentando modelo '%s' en VRAM...", modelo)
    translator.precalentar()
    ejecutar_proxy(translator, puerto=args.puerto, pid=args.pid, juego=args.juego)


if __name__ == "__main__":
    main()
