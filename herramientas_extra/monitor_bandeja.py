"""monitor_bandeja.py — Centro de Control y Monitor en la Bandeja del Sistema (Estilo Steam / Discord).

Funcionalidades:
1. 📁 Selector de juego con Explorador de Windows nativo (filedialog) y memoria de última carpeta.
2. 🎮 Detección automática del motor (RPG Maker MV/MZ, Unity, Ren'Py, Godot) y perfil de juego.
3. 🔘 Centro de Acciones para todo el pipeline:
   - ⚡ Traducción con IA (Modo Turbo / Lotes x7 y Modo Seguro).
   - 📋 Control de calidad (Generar revisión CSV y Reparar etiquetas con IA).
   - 🩹 Parcheo y coherencia (Auditoría semántica de falsos amigos, Nombres, Parches).
   - 💾 Arreglar partidas guardadas de RPG Maker (.rpgsave).
   - 🛑 Botón para detener procesos en cualquier momento.
4. 📊 Monitor en Vivo con porcentaje, barra con gradiente, estadísticas y feed de frases.
5. 📜 Consola de registro en vivo integrada (sin necesidad de ventanas de consola negras).
6. 🔔 Minimizable a la bandeja junto al reloj: icono dinámico con %, tooltip al pasar el ratón,
   y notificaciones de Windows al completar tareas.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pystray  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageTk  # noqa: E402

from traductor import config  # noqa: E402
from traductor.motores import detectar_motor  # noqa: E402
from traductor.progreso import ARCHIVO_PROGRESO, leer_progreso, proceso_vivo  # noqa: E402

APP_NOMBRE = "Traductor IA"
APP_ID = "TraductorIA.CentroControl"
PUERTO_INSTANCIA = 50551
URL_WEB = "http://localhost:5050"
INTERVALO_MS = 1000
CONFIG_GUI_PATH = config.DIR_WORKSPACE / "config_gui.json"

# Paleta moderna en modo oscuro
C_FONDO = "#0b0f19"
C_TARJETA = "#151c2f"
C_TARJETA_ALT = "#1b2338"
C_BORDE = "#232c45"
C_TEXTO = "#f8fafc"
C_SUAVE = "#94a3b8"
C_ACENTO = "#8b5cf6"
C_ACENTO_HOVER = "#7c3aed"
C_TURBO = "#ec4899"
C_VERDE = "#10b981"
C_ROJO = "#ef4444"
C_AMBAR = "#f59e0b"
GRADIENTE = ((99, 102, 241), (168, 85, 247), (236, 72, 153))

ESTADOS = {
    "traduciendo": ("Traduciendo en vivo", (139, 92, 246)),
    "ejecutando": ("Ejecutando tarea…", (99, 102, 241)),
    "preparando": ("Preparando…", (99, 102, 241)),
    "completado": ("¡Completado!", (16, 185, 129)),
    "error": ("Error", (239, 68, 68)),
    "detenido": ("Detenido", (245, 158, 11)),
    "inactivo": ("En espera", (100, 116, 139)),
}


# --------------------------------------------------------------------------- Utilidades y Configuración
def hex_rgb(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def aclarar_hex(hex_str: str, factor: float = 1.18) -> str:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return hex_str
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    r = min(255, max(0, int(r * factor)))
    g = min(255, max(0, int(g * factor)))
    b = min(255, max(0, int(b * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def oscurecer_hex(hex_str: str, factor: float = 0.75) -> str:
    return aclarar_hex(hex_str, factor)


def fuente_pil(tam: int) -> ImageFont.ImageFont:
    for nombre in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def formatear_eta(segundos: int | None) -> str:
    if segundos is None:
        return "Calculando…"
    if segundos < 60:
        return "menos de 1 min"
    minutos = round(segundos / 60)
    if minutos < 60:
        return f"~{minutos} min"
    return f"~{minutos // 60} h {minutos % 60:02d} min"


def nombre_bonito(juego: str) -> str:
    return juego.replace("_", " ").title() if juego else "Sin juego"


def obtener_python_ejecutable() -> Path:
    """Busca el mejor ejecutable de Python con todas las dependencias instaladas."""
    venv_py = RAIZ / "venv_traductor" / "Scripts" / "python.exe"
    if venv_py.exists():
        return venv_py
    p310 = Path(r"C:\Users\marco\AppData\Local\Programs\Python\Python310\python.exe")
    if p310.exists():
        return p310
    return Path(sys.executable)


def cargar_config_gui() -> dict:
    if CONFIG_GUI_PATH.exists():
        try:
            return json.loads(CONFIG_GUI_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Buscar juego reciente por defecto
    default_game = Path(r"J:\SteamLibrary\steamapps\common\Treasure of Nadia")
    return {
        "ultima_ruta": str(default_game) if default_game.exists() else "",
        "ultimo_modelo": "IA_Traductora",
        "ultimo_modo": "turbo"
    }


def guardar_config_gui(datos: dict) -> None:
    try:
        config.DIR_WORKSPACE.mkdir(parents=True, exist_ok=True)
        CONFIG_GUI_PATH.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def obtener_modelos_ollama() -> list[str]:
    """Consulta la API local de Ollama para listar los modelos instalados."""
    try:
        req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5)
        datos = json.loads(req.read().decode("utf-8"))
        modelos = [m.get("name", "").split(":")[0] for m in datos.get("models", []) if m.get("name")]
        modelos = sorted(list(dict.fromkeys(modelos)))
        if "IA_Traductora" in modelos:
            modelos.remove("IA_Traductora")
            modelos.insert(0, "IA_Traductora")
        return modelos or ["IA_Traductora"]
    except Exception:
        return ["IA_Traductora", "llama3.1"]


def detectar_info_juego(ruta_str: str) -> dict:
    """Analiza la carpeta del juego y detecta el motor y perfil."""
    if not ruta_str:
        return {"motor": "No seleccionado", "perfil": "—", "valido": False, "descripcion": "Selecciona una carpeta"}
    p = Path(ruta_str)
    if not p.exists():
        return {"motor": "Ruta no encontrada", "perfil": "—", "valido": False, "descripcion": "La carpeta no existe"}
    motor = detectar_motor(p)
    nombre = config.resolver_juego(None, p)
    n_json = 0
    if (p / "www" / "data").exists():
        n_json = len(list((p / "www" / "data").glob("*.json")))
    elif (p / "data").exists():
        n_json = len(list((p / "data").glob("*.json")))

    desc = f"Motor: {motor}"
    if n_json > 0:
        desc += f" ({n_json} archivos JSON)"
    return {
        "motor": motor,
        "perfil": nombre,
        "valido": True,
        "descripcion": desc,
        "archivos_json": n_json
    }


def normalizar(datos: dict | None) -> dict:
    if not datos:
        return {"estado": "inactivo", "porcentaje": 0.0, "ultimas_frases": []}
    datos = dict(datos)
    if datos.get("estado") in ("traduciendo", "preparando") and not proceso_vivo(datos.get("pid")):
        datos["estado"] = "detenido"
        datos["mensaje"] = "El proceso de traducción se cerró antes de terminar"
    datos.setdefault("ultimas_frases", [])
    return datos


def texto_tooltip(d: dict) -> str:
    estado = d.get("estado", "inactivo")
    lineas = [f"{APP_NOMBRE} · {nombre_bonito(d.get('juego', ''))}" if d.get("juego") else APP_NOMBRE]
    if estado == "inactivo":
        lineas.append("En espera")
    elif estado == "completado":
        lineas.append("✔ 100% completado")
    elif estado == "error":
        lineas.append(f"✖ Error: {d.get('mensaje', '')}")
    else:
        pct = d.get("porcentaje", 0.0)
        lineas.append(f"{pct:.1f}% · {d.get('frases_hechas', 0):,}/{d.get('frases_totales', 0):,} frases".replace(",", "."))
        if estado == "detenido":
            lineas.append("⏸ Detenido")
        else:
            if d.get("archivo_actual"):
                lineas.append(f"{d['archivo_actual']} ({d.get('archivos_hechos', 0)}/{d.get('archivos_totales', 0)})")
            lineas.append(f"Quedan {formatear_eta(d.get('eta_segundos'))}")
    texto = "\n".join(lineas)
    return texto if len(texto) <= 127 else texto[:124] + "..."


# --------------------------------------------------------------------------- Dibujo de Iconos y Barras
def crear_icono(pct: float, estado: str, tam: int = 64) -> Image.Image:
    s = tam * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = ESTADOS.get(estado, ESTADOS["inactivo"])[1]
    grosor = int(s * 0.13)
    caja = (grosor // 2, grosor // 2, s - grosor // 2 - 1, s - grosor // 2 - 1)

    d.ellipse((0, 0, s - 1, s - 1), fill=(17, 22, 38, 255))
    d.arc(caja, 0, 360, fill=(51, 60, 90, 255), width=grosor)
    barrido = 360 if estado == "completado" else max(0.0, min(100.0, pct)) * 3.6
    if barrido > 0:
        d.arc(caja, -90, -90 + barrido, fill=color + (255,), width=grosor)

    centro = s / 2
    if estado == "completado":
        w = int(s * 0.075)
        d.line([(s * 0.30, s * 0.52), (s * 0.44, s * 0.66), (s * 0.71, s * 0.37)],
               fill=color + (255,), width=w, joint="curve")
    elif estado == "error":
        d.text((centro, centro), "!", font=fuente_pil(int(s * 0.55)), fill=color + (255,), anchor="mm")
    elif estado == "detenido":
        w, h = s * 0.09, s * 0.32
        for x in (centro - s * 0.09, centro + s * 0.09):
            d.rounded_rectangle((x - w / 2, centro - h / 2, x + w / 2, centro + h / 2), radius=w / 3,
                                fill=color + (255,))
    elif estado == "inactivo":
        d.text((centro, centro), "T", font=fuente_pil(int(s * 0.48)), fill=(203, 213, 225, 255), anchor="mm")
    else:
        numero = str(int(pct))
        tam_fuente = int(s * (0.50 if len(numero) < 2 else 0.42))
        d.text((centro, centro + s * 0.01), numero, font=fuente_pil(tam_fuente), fill=(255, 255, 255, 255),
               anchor="mm")
    return img.resize((tam, tam), Image.LANCZOS)


def crear_barra(ancho: int, alto: int, fraccion: float, completado: bool) -> Image.Image:
    s = 3
    W, H = ancho * s, alto * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=(31, 39, 64, 255))
    relleno = int(W * max(0.0, min(1.0, fraccion)))
    if relleno > 0:
        relleno = max(relleno, H)
        grad = Image.new("RGBA", (W, H))
        gd = ImageDraw.Draw(grad)
        for x in range(W):
            if completado:
                c = (16, 185, 129)
            else:
                t = x / max(1, W - 1) * (len(GRADIENTE) - 1)
                i = min(int(t), len(GRADIENTE) - 2)
                f = t - i
                c = tuple(int(GRADIENTE[i][k] + (GRADIENTE[i + 1][k] - GRADIENTE[i][k]) * f) for k in range(3))
            gd.line([(x, 0), (x, H)], fill=c + (255,))
        mascara = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mascara).rounded_rectangle((0, 0, relleno - 1, H - 1), radius=H // 2, fill=255)
        img.paste(grad, (0, 0), mascara)
    return img.resize((ancho, alto), Image.LANCZOS)


# --------------------------------------------------------------------------- Instancia Única
def avisar_instancia_existente(mensaje: bytes) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PUERTO_INSTANCIA), timeout=1) as c:
            c.sendall(mensaje)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- Aplicación Principal
class MonitorBandeja:
    def __init__(self, empezar_oculto: bool, servidor: socket.socket, modo_debug: bool = False):
        self.cola: queue.Queue[tuple] = queue.Queue()
        self.servidor = servidor
        self.datos: dict = {}
        self.config_gui = cargar_config_gui()
        self.proceso_actual: subprocess.Popen | None = None
        self.tarea_activa_nombre: str = ""
        self._saliendo = False
        self._ultimo_id_frase: int | None = None
        self._clave_icono: tuple | None = None
        self._clave_barra: tuple | None = None
        self._estado_anterior: str | None = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.esc = self.root.winfo_fpixels("1i") / 96.0
        self.root.title(f"{APP_NOMBRE} — Centro de Control y Traducción")
        self.root.configure(bg=C_FONDO)
        self.root.resizable(True, True)
        self.root.minsize(self.px(760), self.px(660))
        self.root.protocol("WM_DELETE_WINDOW", self.ocultar)
        self.root.bind("<Unmap>", self._al_minimizar)

        # Control de modo depuración
        self.var_modo_debug = tk.BooleanVar(value=modo_debug)

        # Captura automática de fallos y excepciones internas de la interfaz
        def _capturar_excepcion_gui(exc_type, exc_val, exc_tb):
            traza = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            self._agregar_log(f"\n💥 [ERROR INTERNO GUI]\n{traza}\n")
            try:
                (config.DIR_WORKSPACE / "crash_gui.log").write_text(traza, encoding="utf-8")
            except Exception:
                pass
            if self.var_modo_debug.get():
                messagebox.showerror(
                    "Error Interno GUI",
                    f"Se produjo un fallo en la interfaz:\n\n{exc_val}\n\nLos detalles se han registrado en la pestaña 'Consola de Salida' y en workspace/crash_gui.log"
                )
        self.root.report_callback_exception = _capturar_excepcion_gui

        self._construir_ui()
        self._centrar()

        # Icono en bandeja de sistema
        self.icono = pystray.Icon(
            "traductor_ia",
            crear_icono(0, "inactivo"),
            APP_NOMBRE,
            pystray.Menu(
                pystray.MenuItem("Mostrar Centro de Control", lambda: self.cola.put(("mostrar", None)), default=True),
                pystray.MenuItem("Abrir monitor web", lambda: self.cola.put(("web", None))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", lambda: self.cola.put(("salir", None))),
            ),
        )
        threading.Thread(target=self.icono.run, daemon=True).start()
        threading.Thread(target=self._escuchar_instancias, daemon=True).start()

        self.actualizar()
        if not empezar_oculto:
            self.root.after(150, self.mostrar)
        self.root.after(100, self._procesar_cola)

    def px(self, valor: float) -> int:
        return int(valor * self.esc)

    # ----------------------------------------------------------------- Construcción Visual
    def _construir_ui(self) -> None:
        f_titulo = ("Segoe UI Variable Display", 16, "bold")
        f_sub = ("Segoe UI", 9)
        f_btn = ("Segoe UI Semibold", 9)
        f_badge = ("Segoe UI Semibold", 9)
        self._f_feed = ("Segoe UI", 9)
        self.ancho_barra = self.px(540)

        # Contenedor raíz
        self.cont_principal = tk.Frame(self.root, bg=C_FONDO, padx=self.px(20), pady=self.px(16))
        self.cont_principal.pack(fill="both", expand=True)

        # 1. Cabecera
        cab = tk.Frame(self.cont_principal, bg=C_FONDO)
        cab.pack(fill="x", pady=(0, self.px(10)))

        izq = tk.Frame(cab, bg=C_FONDO)
        izq.pack(side="left", fill="x", expand=True)
        self.lbl_titulo = tk.Label(izq, text=f"🎮 {APP_NOMBRE} — Centro de Control", font=f_titulo, fg=C_TEXTO, bg=C_FONDO, anchor="w")
        self.lbl_titulo.pack(fill="x")
        self.lbl_subtitulo = tk.Label(izq, text="Traducción asistida por IA local • Detección de motores y herramientas",
                                      font=f_sub, fg=C_SUAVE, bg=C_FONDO, anchor="w")
        self.lbl_subtitulo.pack(fill="x")

        self.pastilla_estado = tk.Label(cab, text="● En espera", font=f_badge, fg=C_SUAVE, bg=C_TARJETA,
                                        padx=self.px(12), pady=self.px(4))
        self.pastilla_estado.pack(side="right", anchor="n", pady=self.px(2))

        # 2. Selector de Juego y Explorador de Windows (Siempre visible arriba)
        box_juego = tk.Frame(self.cont_principal, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                             padx=self.px(14), pady=self.px(10))
        box_juego.pack(fill="x", pady=(0, self.px(12)))

        fila_ruta = tk.Frame(box_juego, bg=C_TARJETA)
        fila_ruta.pack(fill="x")

        tk.Label(fila_ruta, text="Carpeta del juego:", font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_TARJETA).pack(side="left", padx=(0, self.px(8)))

        self.var_ruta = tk.StringVar(value=self.config_gui.get("ultima_ruta", ""))
        self.ent_ruta = tk.Entry(fila_ruta, textvariable=self.var_ruta, font=("Segoe UI", 9), bg=C_TARJETA_ALT,
                                 fg=C_TEXTO, insertbackground=C_ACENTO, relief="flat", highlightbackground=C_BORDE, highlightthickness=1)
        self.ent_ruta.pack(side="left", fill="x", expand=True, padx=(0, self.px(8)), ipady=self.px(4))
        self.var_ruta.trace_add("write", lambda *_: self._al_cambiar_ruta())

        self._btn_widget(fila_ruta, "📁 Examinar carpeta...", self.examinar_carpeta_juego, primario=True, font=f_btn).pack(side="left", padx=(0, self.px(6)))
        self._btn_widget(fila_ruta, "🔄", self._refrescar_info_juego, primario=False, font=f_btn, px_extra=8).pack(side="left")

        # Subfila con metadatos del juego y selector de modelo Ollama
        fila_meta = tk.Frame(box_juego, bg=C_TARJETA)
        fila_meta.pack(fill="x", pady=(self.px(8), 0))

        self.lbl_motor = tk.Label(fila_meta, text="Motor: Detectando...", font=("Segoe UI", 9), fg=C_SUAVE, bg=C_TARJETA)
        self.lbl_motor.pack(side="left", padx=(0, self.px(16)))

        self.lbl_perfil = tk.Label(fila_meta, text="Perfil: —", font=("Segoe UI", 9), fg=C_SUAVE, bg=C_TARJETA)
        self.lbl_perfil.pack(side="left", padx=(0, self.px(16)))

        tk.Label(fila_meta, text="Modelo Ollama:", font=("Segoe UI", 9), fg=C_SUAVE, bg=C_TARJETA).pack(side="left", padx=(self.px(10), self.px(6)))
        self.combo_modelo = ttk.Combobox(
            fila_meta,
            values=obtener_modelos_ollama(),
            state="readonly",
            width=18,
            postcommand=self._refrescar_modelos_combo
        )
        self.combo_modelo.set(self.config_gui.get("ultimo_modelo", "IA_Traductora"))
        self.combo_modelo.pack(side="left")
        self.combo_modelo.bind("<<ComboboxSelected>>", lambda _: self._guardar_config_actual())

        # 3. Barra de Pestañas de Navegación (Tabs modernas)
        nav = tk.Frame(self.cont_principal, bg=C_FONDO)
        nav.pack(fill="x", pady=(0, self.px(10)))

        self.tab_activa = "acciones"
        self.tabs_btns: dict[str, tk.Label] = {}
        self.tabs_frames: dict[str, tk.Frame] = {}

        self.tabs_btns["acciones"] = self._crear_tab_btn(nav, "⚡ Acciones & Herramientas", "acciones")
        self.tabs_btns["acciones"].pack(side="left", padx=(0, self.px(6)))

        self.tabs_btns["progreso"] = self._crear_tab_btn(nav, "📊 Progreso en Vivo", "progreso")
        self.tabs_btns["progreso"].pack(side="left", padx=(0, self.px(6)))

        self.tabs_btns["consola"] = self._crear_tab_btn(nav, "📜 Consola de Salida", "consola")
        self.tabs_btns["consola"].pack(side="left")

        # Botón de detener en la barra de pestañas (visible y accesible siempre)
        self.btn_detener = tk.Label(nav, text="🛑 Detener Proceso", font=("Segoe UI Semibold", 9), fg=C_TEXTO,
                                    bg="#374151", cursor="arrow", padx=self.px(12), pady=self.px(5))
        self.btn_detener.pack(side="right")
        self.btn_detener.bind("<Button-1>", lambda _: self.detener_proceso())

        # 4. Contenedor de Vistas
        self.vista_contenedor = tk.Frame(self.cont_principal, bg=C_FONDO)
        self.vista_contenedor.pack(fill="both", expand=True)

        self._construir_tab_acciones()
        self._construir_tab_progreso()
        self._construir_tab_consola()

        self.cambiar_tab("acciones")
        self._refrescar_info_juego()

        # 5. Barra Inferior con Enlaces Rápidos
        pie = tk.Frame(self.cont_principal, bg=C_FONDO)
        pie.pack(fill="x", pady=(self.px(10), 0))

        self._btn_widget(pie, "🌐 Monitor Web (Port 5050)", self.abrir_web, primario=False, font=f_btn).pack(side="left", padx=(0, self.px(6)))
        self._btn_widget(pie, "📂 Carpeta del Juego", self.abrir_carpeta_juego, primario=False, font=f_btn).pack(side="left", padx=(0, self.px(6)))
        self._btn_widget(pie, "📂 Carpeta Workspace", self.abrir_carpeta_workspace, primario=False, font=f_btn).pack(side="left")

        self._btn_widget(pie, "⬇ Minimizar a la Bandeja", self.ocultar, primario=True, font=f_btn).pack(side="right")

    # ----------------------------------------------------------------- Construcción de Pestañas
    def _crear_tab_btn(self, padre: tk.Widget, texto: str, clave: str) -> tk.Label:
        b = tk.Label(padre, text=texto, font=("Segoe UI Semibold", 9), fg=C_SUAVE, bg=C_TARJETA, cursor="hand2",
                     padx=self.px(14), pady=self.px(6))
        b.bind("<Button-1>", lambda _: self.cambiar_tab(clave))
        return b

    def cambiar_tab(self, clave: str) -> None:
        self.tab_activa = clave
        for k, btn in self.tabs_btns.items():
            if k == clave:
                btn.configure(bg=C_ACENTO, fg=C_TEXTO)
            else:
                btn.configure(bg=C_TARJETA, fg=C_SUAVE)
        for k, frame in self.tabs_frames.items():
            if k == clave:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

    # --- Pestaña 1: Acciones & Herramientas ---
    def _construir_tab_acciones(self) -> None:
        frame = tk.Frame(self.vista_contenedor, bg=C_FONDO)
        self.tabs_frames["acciones"] = frame

        # Grid de tarjetas
        grid = tk.Frame(frame, bg=C_FONDO)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1, uniform="col")
        grid.columnconfigure(1, weight=1, uniform="col")

        # Tarjeta 1: Traducción con IA
        card1 = self._crear_tarjeta(grid, "🚀 Traducción con IA (Paso 1)", 0, 0)
        self._btn_accion(card1, "⚡ Iniciar Traducción (Modo Turbo - Lotes x7)",
                         lambda: self.ejecutar_traduccion(turbo=True), color=C_TURBO,
                         desc="Traducción por bloques rápidos paralelos").pack(fill="x", pady=self.px(3))
        self._btn_accion(card1, "🛡️ Iniciar Traducción (Modo Seguro - Frase a frase)",
                         lambda: self.ejecutar_traduccion(turbo=False), color="#4338ca",
                         desc="Traducción con historial de contexto narrativo").pack(fill="x", pady=self.px(3))

        # Tarjeta 2: Revisión y Control de Calidad
        card2 = self._crear_tarjeta(grid, "📋 Revisión y Diagnóstico (Juegos con CSV: Pasos 2 y 3)", 0, 1)
        self._btn_accion(card2, "📄 Generar Hoja de Revisión (Paso 2)",
                         self.ejecutar_generar_revision, color="#2563eb",
                         desc="Crea revision_<juego>.csv comparando con originales").pack(fill="x", pady=self.px(3))
        self._btn_accion(card2, "🔧 Reparar Etiquetas con IA (Paso 3)",
                         self.ejecutar_reparar_etiquetas, color="#0284c7",
                         desc="Corrige códigos y formatos rotos automáticamente").pack(fill="x", pady=self.px(3))

        # Tarjeta 3: Corrección, Semántica y Parches
        card3 = self._crear_tarjeta(grid, "🩹 Parcheo y Semántica (Juegos con CSV: Pasos 4, 5 y 6)", 1, 0)
        self._btn_accion(card3, "🩹 Aplicar Parches y Diccionarios (Paso 4)",
                         self.ejecutar_aplicar_parches, color="#16a34a",
                         desc="Inyecta correcciones manuales en los archivos del juego").pack(fill="x", pady=self.px(3))
        self._btn_accion(card3, "👥 Traducir Nombres de Personajes (Paso 5)",
                         self.ejecutar_traducir_nombres, color="#0d9488",
                         desc="Unifica nombres de hablantes según la tabla").pack(fill="x", pady=self.px(3))
        self._btn_accion(card3, "🔍 Auditoría Semántica (Paso 6: Falsos Amigos)",
                         self.ejecutar_auditoria_semantica, color="#059669",
                         desc="Corrige party➔grupo, item➔objeto, save➔guardar...").pack(fill="x", pady=self.px(3))

        # Tarjeta 4: Partidas Guardadas y Utilidades RPG Maker
        card4 = self._crear_tarjeta(grid, "💾 Partidas y Utilidades RPG Maker (Paso 7)", 1, 1)
        self._btn_accion(card4, "💾 Arreglar Partida RPG Maker (.rpgsave)",
                         self.ejecutar_arreglar_partida, color="#d97706",
                         desc="Parchea archivos de guardado sin tener que reiniciar partida").pack(fill="x", pady=self.px(3))
        self._btn_accion(card4, "🔤 Separar Palabras / Oraciones Juntas",
                         self.ejecutar_separar_palabras_juntas, color="#0891b2",
                         desc="Corrige diálogos pegados tras puntos o signos en el juego").pack(fill="x", pady=self.px(3))
        self._btn_accion(card4, "🔍 Gestor RPG Maker (Buscar / Inspeccionar)",
                         self.abrir_gestor_rpgmaker_info, color="#7c3aed",
                         desc="Herramienta avanzada para escenas y diálogos").pack(fill="x", pady=self.px(3))

    def _crear_tarjeta(self, padre: tk.Widget, titulo: str, fila: int, col: int) -> tk.Frame:
        c = tk.Frame(padre, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                    padx=self.px(12), pady=self.px(10))
        c.grid(row=fila, column=col, sticky="nsew", padx=self.px(4), pady=self.px(4))
        tk.Label(c, text=titulo, font=("Segoe UI Variable Display", 10, "bold"), fg=C_TEXTO, bg=C_TARJETA, anchor="w").pack(fill="x", pady=(0, self.px(6)))
        return c

    def _btn_accion(self, padre: tk.Widget, titulo: str, comando, color: str, desc: str = "") -> tk.Frame:
        box = tk.Frame(padre, bg=C_TARJETA_ALT, cursor="hand2", padx=self.px(10), pady=self.px(6),
                       highlightbackground=C_BORDE, highlightthickness=1)
        lbl_t = tk.Label(box, text=titulo, font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_TARJETA_ALT, anchor="w")
        lbl_t.pack(fill="x")
        lbl_d = None
        if desc:
            lbl_d = tk.Label(box, text=desc, font=("Segoe UI", 7), fg=C_SUAVE, bg=C_TARJETA_ALT, anchor="w")
            lbl_d.pack(fill="x")

        def pintar_color():
            box.configure(bg=color, highlightbackground=color)
            lbl_t.configure(bg=color, fg="#ffffff")
            if lbl_d:
                lbl_d.configure(bg=color, fg="#f1f5f9")

        def pintar_normal():
            box.configure(bg=C_TARJETA_ALT, highlightbackground=C_BORDE)
            lbl_t.configure(bg=C_TARJETA_ALT, fg=C_TEXTO)
            if lbl_d:
                lbl_d.configure(bg=C_TARJETA_ALT, fg=C_SUAVE)

        def raton_sigue_dentro() -> bool:
            try:
                rx = box.winfo_rootx()
                ry = box.winfo_rooty()
                rw = box.winfo_width()
                rh = box.winfo_height()
                px = box.winfo_pointerx()
                py = box.winfo_pointery()
                return (rx <= px <= rx + rw) and (ry <= py <= ry + rh)
            except Exception:
                return False

        def al_entrar(_):
            pintar_color()

        def al_salir(_):
            def verificar():
                if not raton_sigue_dentro():
                    pintar_normal()
            box.after(25, verificar)

        elementos = (box, lbl_t) if lbl_d is None else (box, lbl_t, lbl_d)
        for w in elementos:
            w.bind("<Enter>", al_entrar)
            w.bind("<Leave>", al_salir)
            w.bind("<Button-1>", lambda _: comando())

        return box

    # --- Pestaña 2: Progreso en Vivo ---
    def _construir_tab_progreso(self) -> None:
        frame = tk.Frame(self.vista_contenedor, bg=C_FONDO)
        self.tabs_frames["progreso"] = frame

        # Tarjeta principal de barra y %
        tarjeta = tk.Frame(frame, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                           padx=self.px(18), pady=self.px(14))
        tarjeta.pack(fill="x", pady=(0, self.px(10)))

        fila = tk.Frame(tarjeta, bg=C_TARJETA)
        fila.pack(fill="x")
        self.lbl_pct = tk.Label(fila, text="0%", font=("Segoe UI Variable Display", 32, "bold"), fg=C_TEXTO, bg=C_TARJETA)
        self.lbl_pct.pack(side="left")
        self.lbl_frases = tk.Label(fila, text="", font=("Segoe UI", 10), fg=C_SUAVE, bg=C_TARJETA)
        self.lbl_frases.pack(side="right", anchor="s", pady=self.px(8))

        self.barra = tk.Label(tarjeta, bg=C_TARJETA, bd=0)
        self.barra.pack(fill="x", pady=(self.px(6), self.px(12)))

        # Rejilla 2x2 de métricas
        rejilla = tk.Frame(tarjeta, bg=C_TARJETA)
        rejilla.pack(fill="x")
        self.valores: dict[str, tk.Label] = {}
        for i, (clave, tit) in enumerate((("archivo", "ARCHIVO ACTUAL"), ("archivos", "ARCHIVOS"),
                                         ("eta", "TIEMPO RESTANTE"), ("velocidad", "VELOCIDAD"))):
            celda = tk.Frame(rejilla, bg=C_TARJETA_ALT, padx=self.px(10), pady=self.px(6))
            celda.grid(row=i // 2, column=i % 2, sticky="nsew", padx=self.px(3), pady=self.px(3))
            tk.Label(celda, text=tit, font=("Segoe UI", 7), fg=C_SUAVE, bg=C_TARJETA_ALT, anchor="w").pack(fill="x")
            lbl = tk.Label(celda, text="—", font=("Segoe UI Semibold", 10), fg=C_TEXTO, bg=C_TARJETA_ALT, anchor="w")
            lbl.pack(fill="x")
            self.valores[clave] = lbl
        rejilla.columnconfigure(0, weight=1, uniform="c")
        rejilla.columnconfigure(1, weight=1, uniform="c")

        # Feed en vivo de frases traducidas
        feed = tk.Frame(frame, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                        padx=self.px(14), pady=self.px(10))
        feed.pack(fill="both", expand=True)
        tk.Label(feed, text="⚡ Últimas frases traducidas por la IA", font=("Segoe UI Semibold", 9),
                 fg=C_TEXTO, bg=C_TARJETA, anchor="w").pack(fill="x", pady=(0, self.px(6)))

        self.feed_lista = tk.Frame(feed, bg=C_TARJETA)
        self.feed_lista.pack(fill="both", expand=True)

    # --- Pestaña 3: Consola de Salida y Herramientas de Depuración ---
    def _construir_tab_consola(self) -> None:
        frame = tk.Frame(self.vista_contenedor, bg=C_FONDO)
        self.tabs_frames["consola"] = frame

        barra_herramientas = tk.Frame(frame, bg=C_FONDO)
        barra_herramientas.pack(fill="x", pady=(0, self.px(8)))

        # Fila superior: Título y conmutador de Modo Depuración
        fila_sup = tk.Frame(barra_herramientas, bg=C_FONDO)
        fila_sup.pack(fill="x", pady=(0, self.px(6)))

        tk.Label(fila_sup, text="📜 Registro de ejecución y herramientas de depuración:",
                 font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_FONDO).pack(side="left")

        chk_debug = tk.Checkbutton(
            fila_sup,
            text="Modo Depuración (--debug)",
            variable=self.var_modo_debug,
            command=self._al_cambiar_modo_debug,
            font=("Segoe UI Semibold", 8),
            fg=C_TURBO,
            bg=C_FONDO,
            selectcolor=C_TARJETA,
            activebackground=C_FONDO,
            activeforeground=C_TURBO,
            cursor="hand2",
            bd=0,
            highlightthickness=0
        )
        chk_debug.pack(side="right")

        # Fila inferior: Botones de diagnóstico, soporte y consola CMD
        fila_botones = tk.Frame(barra_herramientas, bg=C_FONDO)
        fila_botones.pack(fill="x")

        self._btn_widget(fila_botones, "📋 Copiar Registro para la IA", self.copiar_registro_ia,
                         primario=True, font=("Segoe UI", 8, "bold"), px_extra=10).pack(side="left", padx=(0, self.px(6)))

        self._btn_widget(fila_botones, "🩺 Ejecutar Diagnóstico", self.ejecutar_diagnostico_ui,
                         primario=False, font=("Segoe UI", 8), px_extra=8).pack(side="left", padx=(0, self.px(6)))

        self._btn_widget(fila_botones, "🖥️ Abrir CMD del Entorno", self.abrir_consola_cmd,
                         primario=False, font=("Segoe UI", 8), px_extra=8).pack(side="left", padx=(0, self.px(6)))

        self._btn_widget(fila_botones, "🗑️ Limpiar", self.limpiar_consola,
                         primario=False, font=("Segoe UI", 8), px_extra=8).pack(side="right")

        cont_txt = tk.Frame(frame, bg="#070a13", highlightbackground=C_BORDE, highlightthickness=1)
        cont_txt.pack(fill="both", expand=True)

        self.txt_consola = tk.Text(cont_txt, bg="#070a13", fg="#e2e8f0", insertbackground=C_ACENTO,
                                   font=("Cascadia Mono", 9), wrap="word", relief="flat", state="disabled")
        scroll = tk.Scrollbar(cont_txt, command=self.txt_consola.yview)
        self.txt_consola.configure(yscrollcommand=scroll.set)

        scroll.pack(side="right", fill="y")
        self.txt_consola.pack(side="left", fill="both", expand=True, padx=self.px(6), pady=self.px(6))

    def _btn_widget(self, padre: tk.Widget, texto: str, comando, primario: bool, font=("Segoe UI Semibold", 9), px_extra: int = 14) -> tk.Label:
        normal = C_ACENTO if primario else C_TARJETA
        hover = C_ACENTO_HOVER if primario else "#1f2942"
        b = tk.Label(padre, text=texto, font=font, fg=C_TEXTO, bg=normal, cursor="hand2",
                     padx=self.px(px_extra), pady=self.px(6))
        b.bind("<Enter>", lambda _: b.configure(bg=hover))
        b.bind("<Leave>", lambda _: b.configure(bg=normal))
        b.bind("<Button-1>", lambda _: comando())
        return b

    # ----------------------------------------------------------------- Explorador de Archivos y Detección
    def examinar_carpeta_juego(self) -> None:
        """Abre el diálogo nativo de Windows para seleccionar la carpeta del juego."""
        inicial = self.var_ruta.get()
        if not inicial or not Path(inicial).exists():
            inicial = r"J:\SteamLibrary\steamapps\common"
            if not Path(inicial).exists():
                inicial = r"C:"

        carpeta = filedialog.askdirectory(parent=self.root, initialdir=inicial, title="Seleccionar carpeta del juego a traducir")
        if carpeta:
            self.var_ruta.set(str(Path(carpeta)))
            self._guardar_config_actual()
            self._refrescar_info_juego()

    def _al_cambiar_ruta(self) -> None:
        self._refrescar_info_juego()
        self._guardar_config_actual()

    def _guardar_config_actual(self) -> None:
        self.config_gui["ultima_ruta"] = self.var_ruta.get()
        self.config_gui["ultimo_modelo"] = self.combo_modelo.get()
        guardar_config_gui(self.config_gui)

    def _refrescar_info_juego(self) -> None:
        ruta = self.var_ruta.get()
        info = detectar_info_juego(ruta)
        if info["valido"]:
            self.lbl_motor.configure(text=f"🎮 {info['descripcion']}", fg=C_VERDE)
            self.lbl_perfil.configure(text=f"🏷️ Perfil: {info['perfil']}", fg=C_TEXTO)
            self.lbl_subtitulo.configure(text=f"Juego: {nombre_bonito(info['perfil'])} • {info['motor']}")
        else:
            self.lbl_motor.configure(text=f"⚠ {info['descripcion']}", fg=C_AMBAR)
            self.lbl_perfil.configure(text="Perfil: —", fg=C_SUAVE)

    # ----------------------------------------------------------------- Ejecución de Procesos en Segundo Plano
    def ejecutar_accion(self, cmd: list[str], nombre_tarea: str, cambiar_a_progreso: bool = False) -> None:
        """Lanza cualquier script en un hilo en segundo plano capturando su salida."""
        if self.proceso_actual and self.proceso_actual.poll() is None:
            messagebox.showwarning("Proceso en ejecución",
                                   f"Ya hay una tarea activa ({self.tarea_activa_nombre}).\n"
                                   "Usa el botón '🛑 Detener Proceso' si deseas cancelarla antes de iniciar otra.")
            return

        # Solo exigimos carpeta de juego si la tarea no es un diagnóstico global
        if "diagnóstico" not in nombre_tarea.lower():
            ruta = self.var_ruta.get()
            if not ruta or not Path(ruta).exists():
                messagebox.showerror("Ruta requerida", "Por favor, selecciona primero la carpeta del juego con el botón '📁 Examinar carpeta...'.")
                return

        cmd_final = list(cmd)
        if self.var_modo_debug.get() and "--debug" not in cmd_final and not any("diagnostico" in c for c in cmd_final):
            cmd_final.append("--debug")

        self.tarea_activa_nombre = nombre_tarea
        self.btn_detener.configure(bg=C_ROJO, cursor="hand2")
        self.pastilla_estado.configure(text=f"● {nombre_tarea}…", fg=C_TURBO)

        self._agregar_log(f"\n{'='*60}\n🚀 [INICIO] {nombre_tarea}\nComando: {' '.join(cmd_final)}\n{'='*60}\n")
        if cambiar_a_progreso:
            self.cambiar_tab("progreso")
        else:
            self.cambiar_tab("consola")

        def worker():
            try:
                py_exe = obtener_python_ejecutable()
                full_cmd = [str(py_exe)] + cmd_final
                self.proceso_actual = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(RAIZ),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )

                for linea in self.proceso_actual.stdout:
                    if linea:
                        self.cola.put(("log", linea.rstrip("\r\n")))

                rc = self.proceso_actual.wait()
                if rc == 0:
                    self.cola.put(("log", f"\n✔ [ÉXITO] {nombre_tarea} finalizada correctamente."))
                    self.cola.put(("fin_tarea", (True, nombre_tarea)))
                else:
                    self.cola.put(("log", f"\n✖ [AVISO] {nombre_tarea} finalizada con código de salida: {rc}."))
                    self.cola.put(("fin_tarea", (False, nombre_tarea)))
            except Exception as e:
                self.cola.put(("log", f"\n💥 [ERROR] Error ejecutando {nombre_tarea}: {e}"))
                self.cola.put(("fin_tarea", (False, nombre_tarea)))

        threading.Thread(target=worker, daemon=True).start()

    def detener_proceso(self) -> None:
        """Detiene de forma forzosa el proceso actual y su árbol de subprocesos."""
        if self.proceso_actual and self.proceso_actual.poll() is None:
            pid = self.proceso_actual.pid
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._agregar_log(f"\n🛑 [DETENIDO] Proceso (PID {pid}) terminado por el usuario.\n")
            except Exception as e:
                self._agregar_log(f"Error al detener proceso: {e}")
            self.btn_detener.configure(bg="#374151", cursor="arrow")
            self.pastilla_estado.configure(text="● Detenido", fg=C_AMBAR)
        else:
            self._agregar_log("No hay ningún proceso activo que detener.")

    def _es_rpgmaker_sin_csv(self, ruta_str: str) -> bool:
        if not ruta_str:
            return False
        p = Path(ruta_str)
        if not p.exists():
            return False
        info = detectar_info_juego(ruta_str)
        if info.get("motor") == "RPGMaker":
            return not any(p.glob("**/*.csv"))
        return False

    def ejecutar_traduccion(self, turbo: bool = True) -> None:
        ruta = self.var_ruta.get()
        modelo = self.combo_modelo.get() or "IA_Traductora"
        modo = "turbo" if turbo else "seguro"
        cmd = ["1_traducir_juego.py", "--ruta", ruta, "--modo", modo, "--modelo", modelo, "--sin-monitor"]
        nombre = f"Traducción ({'Modo Turbo' if turbo else 'Modo Seguro'})"
        self.ejecutar_accion(cmd, nombre, cambiar_a_progreso=True)

    def ejecutar_generar_revision(self) -> None:
        ruta = self.var_ruta.get()
        if self._es_rpgmaker_sin_csv(ruta):
            self.cambiar_tab("consola")
            self._agregar_log(
                "\nℹ️ [INFO DE COMPATIBILIDAD]:\n"
                "Este juego utiliza archivos JSON nativos de RPG Maker (Map*.json, etc.), no tablas CSV.\n"
                "• La traducción ya se inyectó directamente en los archivos del juego en el Paso 1.\n"
                "• Los Pasos 2 a 6 solo aplican a juegos basados en tablas CSV (Ren'Py, Godot o DKTools).\n"
                "• Si tienes una partida guardada previa, usa el Paso 7 (Arreglar Partida .rpgsave).\n"
            )
        cmd = ["2_generar_revision.py", "--ruta", ruta]
        self.ejecutar_accion(cmd, "Generar Hoja de Revisión (Paso 2)")

    def ejecutar_reparar_etiquetas(self) -> None:
        ruta = self.var_ruta.get()
        if self._es_rpgmaker_sin_csv(ruta):
            self.cambiar_tab("consola")
            self._agregar_log(
                "\nℹ️ [INFO DE COMPATIBILIDAD]:\n"
                "Los juegos de RPG Maker no utilizan hojas de revisión CSV; sus etiquetas ya se validan automáticamente al traducir.\n"
            )
        modelo = self.combo_modelo.get() or "IA_Traductora"
        cmd = ["3_reparar_etiquetas_ia.py", "--modelo", modelo]
        self.ejecutar_accion(cmd, "Reparar Etiquetas con IA (Paso 3)")

    def ejecutar_aplicar_parches(self) -> None:
        ruta = self.var_ruta.get()
        cmd = ["4_aplicar_parches.py", "--ruta", ruta]
        self.ejecutar_accion(cmd, "Aplicar Parches y Diccionarios (Paso 4)")

    def ejecutar_traducir_nombres(self) -> None:
        ruta = self.var_ruta.get()
        cmd = ["5_traducir_nombres_personajes.py", "--ruta", ruta]
        self.ejecutar_accion(cmd, "Traducir Nombres de Personajes (Paso 5)")

    def ejecutar_auditoria_semantica(self) -> None:
        ruta = self.var_ruta.get()
        cmd = ["6_auditoria_semantica.py", "--ruta", ruta]
        self.ejecutar_accion(cmd, "Auditoría Semántica (Paso 6: Falsos Amigos)")

    def ejecutar_arreglar_partida(self) -> None:
        ruta = self.var_ruta.get()
        cmd = ["7_arreglar_partida_rpgmaker.py", "--ruta", ruta]
        self.ejecutar_accion(cmd, "Arreglar Partida RPG Maker (.rpgsave)")

    def ejecutar_separar_palabras_juntas(self) -> None:
        ruta = self.var_ruta.get()
        cmd = ["herramientas_extra/separar_palabras_juntas.py", "--ruta", ruta]
        self.ejecutar_accion(cmd, "Separar Palabras y Oraciones Juntas")

    def abrir_gestor_rpgmaker_info(self) -> None:
        self.cambiar_tab("consola")
        self._agregar_log("\n🎭 Gestor RPG Maker disponible mediante línea de comandos:")
        self._agregar_log("  python herramientas_extra/gestor_rpgmaker.py buscar \"texto a buscar\"")
        self._agregar_log("  python herramientas_extra/gestor_rpgmaker.py inspeccionar --archivo Map012.json --evento 55")
        self._agregar_log("  python herramientas_extra/gestor_rpgmaker.py parchear --archivo Map012.json --buscar \"A\" --reemplazar \"B\"\n")

    def abrir_carpeta_juego(self) -> None:
        ruta = self.var_ruta.get()
        if ruta and Path(ruta).exists():
            os.startfile(ruta)
        else:
            messagebox.showwarning("Aviso", "Selecciona una carpeta válida primero.")

    def abrir_carpeta_workspace(self) -> None:
        if config.DIR_WORKSPACE.exists():
            os.startfile(config.DIR_WORKSPACE)

    def limpiar_consola(self) -> None:
        self.txt_consola.configure(state="normal")
        self.txt_consola.delete("1.0", "end")
        self.txt_consola.configure(state="disabled")

    def _al_cambiar_modo_debug(self) -> None:
        estado = "ACTIVADO" if self.var_modo_debug.get() else "DESACTIVADO"
        self._agregar_log(f"\n⚙ [MODO DEPURACIÓN] {estado}. Se incluirán argumentos detallados en las siguientes tareas.")

    def copiar_registro_ia(self) -> None:
        """Copia todo el texto de la consola junto con el entorno del sistema al portapapeles para soporte con IA."""
        contenido = self.txt_consola.get("1.0", "end-1c").strip()
        ahora = time.strftime("%Y-%m-%d %H:%M:%S")

        bloque = [
            "================================================================================",
            "📋 REPORTE DE CONSOLA Y ESTADO PARA SOPORTE CON LA IA (TRADUCTOR IA)",
            "================================================================================",
            f"Fecha: {ahora}",
            f"Carpeta del juego: {self.var_ruta.get() or 'No seleccionada'}",
            f"Modelo IA: {self.combo_modelo.get()}",
            f"Modo Depuración: {'SÍ (Activo)' if self.var_modo_debug.get() else 'NO'}",
            f"Python: {sys.executable} ({sys.version.splitlines()[0]})",
            "--------------------------------------------------------------------------------",
            "REGISTRO ACTUAL DE LA CONSOLA:",
            contenido if contenido else "(La consola estaba vacía al momento de copiar)",
            "================================================================================",
            "Fin del registro copiado."
        ]
        texto_final = "\n".join(bloque)

        # Copiar al portapapeles de Tkinter
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(texto_final)
            self.root.update()
        except Exception:
            pass

        # Asegurar copia con el clip nativo de Windows (fiable al 100%)
        if os.name == "nt":
            try:
                subprocess.run(
                    ["clip"],
                    input=texto_final.encode("utf-16le"),
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
            except Exception:
                pass

        # Guardar archivo de respaldo en workspace
        try:
            archivo_respaldo = config.DIR_WORKSPACE / "ultimo_registro_copiado.txt"
            archivo_respaldo.write_text(texto_final, encoding="utf-8")
        except Exception:
            pass

        self._agregar_log("\n📋 [COPIADO] El registro completo se ha copiado al portapapeles.")
        self._agregar_log("👉 Ahora solo ve a la ventana de chat con la IA y pulsa Ctrl + V para enviárselo.")

        messagebox.showinfo(
            "¡Registro Copiado!",
            "El registro completo de la consola se ha copiado a tu portapapeles de Windows.\n\n"
            "Ya puedes ir a la ventana de chat con la IA y pulsar Ctrl + V para pegarlo directamente."
        )

    def ejecutar_diagnostico_ui(self) -> None:
        """Lanza el diagnóstico completo del sistema y muestra los resultados en tiempo real."""
        cmd = ["herramientas_extra/diagnostico.py"]
        ruta = self.var_ruta.get()
        if ruta and Path(ruta).exists():
            cmd.extend(["--ruta", ruta])
        self.ejecutar_accion(cmd, "Diagnóstico Completo del Sistema", cambiar_a_progreso=False)

    def abrir_consola_cmd(self) -> None:
        """Abre una ventana de CMD interactiva de Windows preconfigurada con el entorno."""
        cmd_bat = RAIZ / "consola_cmd.bat"
        try:
            if cmd_bat.exists():
                os.startfile(cmd_bat)
            else:
                subprocess.Popen(["cmd.exe", "/k", "title Traductor IA - CMD"], cwd=str(RAIZ))
            self._agregar_log("🖥️ Consola interactiva CMD de Windows abierta.")
        except Exception as e:
            self._agregar_log(f"Error al abrir CMD: {e}")

    def _agregar_log(self, texto: str) -> None:
        self.txt_consola.configure(state="normal")
        self.txt_consola.insert("end", texto + "\n")
        self.txt_consola.see("end")
        self.txt_consola.configure(state="disabled")

    # ----------------------------------------------------------------- Mostrar / Ocultar / Bandeja
    def _centrar(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{max(w, self.px(760))}x{max(h, self.px(660))}+{x}+{y}")

    def _refrescar_modelos_combo(self) -> None:
        """Actualiza la lista de modelos de Ollama en el desplegable en tiempo real."""
        try:
            modelos = obtener_modelos_ollama()
            if hasattr(self, "combo_modelo"):
                self.combo_modelo["values"] = modelos
                if self.combo_modelo.get() not in modelos:
                    self.combo_modelo.set(modelos[0] if modelos else "IA_Traductora")
                    self._guardar_config_actual()
        except Exception:
            pass

    def mostrar(self) -> None:
        self._refrescar_modelos_combo()
        self.root.deiconify()
        self.root.state("normal")
        if self.datos:
            self._actualizar_ventana(self.datos, self.datos.get("estado", "inactivo"), float(self.datos.get("porcentaje", 0.0)))
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def ocultar(self) -> None:
        self.root.withdraw()

    def _al_minimizar(self, evento) -> None:
        if evento.widget is self.root and self.root.state() == "iconic":
            self.root.after(10, self.ocultar)

    def salir(self) -> None:
        self._saliendo = True
        self.detener_proceso()
        try:
            self.icono.stop()
        except Exception:
            pass
        try:
            self.servidor.close()
        except OSError:
            pass
        self.root.destroy()

    def _procesar_cola(self) -> None:
        try:
            while True:
                orden, payload = self.cola.get_nowait()
                if orden == "mostrar":
                    self.mostrar()
                elif orden == "web":
                    self.abrir_web()
                elif orden == "salir":
                    self.salir()
                    return
                elif orden == "log":
                    self._agregar_log(str(payload))
                elif orden == "fin_tarea":
                    exito, nombre = payload
                    self.btn_detener.configure(bg="#374151", cursor="arrow")
                    self.pastilla_estado.configure(text="● Completado" if exito else "● Finalizado con avisos",
                                                  fg=C_VERDE if exito else C_AMBAR)
                    try:
                        self.icono.notify(f"{nombre} finalizada.", APP_NOMBRE)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        self.root.after(100, self._procesar_cola)

    def _escuchar_instancias(self) -> None:
        while not self._saliendo:
            try:
                conexion, _ = self.servidor.accept()
            except OSError:
                return
            with conexion:
                try:
                    if conexion.recv(32).strip() == b"mostrar":
                        self.cola.put(("mostrar", None))
                except OSError:
                    pass

    def abrir_web(self) -> None:
        def tarea():
            try:
                urllib.request.urlopen(URL_WEB + "/api/progreso", timeout=1)
            except OSError:
                py_exe = obtener_python_ejecutable()
                subprocess.Popen([str(py_exe), str(RAIZ / "herramientas_extra" / "servidor_progreso.py")], cwd=str(RAIZ),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                time.sleep(1.5)
            webbrowser.open(URL_WEB)
        threading.Thread(target=tarea, daemon=True).start()

    # ----------------------------------------------------------------- Actualización Periódica
    def actualizar(self) -> None:
        if self._saliendo:
            return
        bruto = leer_progreso(ARCHIVO_PROGRESO)
        if bruto is None and ARCHIVO_PROGRESO.exists() and self.datos:
            d = self.datos
        else:
            d = normalizar(bruto)
        self.datos = d

        # Si hay proceso ejecutando una tarea no-traducción, reflejarlo
        if self.proceso_actual and self.proceso_actual.poll() is None and self.tarea_activa_nombre:
            if "Traducción" not in self.tarea_activa_nombre:
                estado = "ejecutando"
            else:
                estado = d.get("estado", "traduciendo")
        else:
            estado = d.get("estado", "inactivo")

        pct = float(d.get("porcentaje", 0.0))
        self._actualizar_bandeja(d, estado, pct)

        if self.root.state() != "withdrawn":
            self._actualizar_ventana(d, estado, pct)

        self._notificar_cambios(d, estado)
        self.root.after(INTERVALO_MS, self.actualizar)

    def _actualizar_bandeja(self, d: dict, estado: str, pct: float) -> None:
        clave = (estado, int(pct))
        if clave != self._clave_icono:
            self._clave_icono = clave
            imagen = crear_icono(pct, estado)
            self.icono.icon = imagen
            self._foto_ventana = ImageTk.PhotoImage(imagen.resize((32, 32), Image.LANCZOS))
            self.root.iconphoto(False, self._foto_ventana)
        titulo = texto_tooltip(d)
        if self.icono.title != titulo:
            self.icono.title = titulo

    def _actualizar_ventana(self, d: dict, estado: str, pct: float) -> None:
        texto_estado, color = ESTADOS.get(estado, ESTADOS["inactivo"])
        if not (self.proceso_actual and self.proceso_actual.poll() is None):
            self.pastilla_estado.configure(text=f"● {texto_estado}", fg=hex_rgb(color))

        self.lbl_pct.configure(text=f"{pct:.1f}%" if 0 < pct < 100 else f"{int(pct)}%")
        totales = d.get("frases_totales", 0)
        self.lbl_frases.configure(
            text=f"{d.get('frases_hechas', 0):,} / {totales:,} frases".replace(",", ".") if totales else "")

        clave_barra = (round(pct, 1), estado == "completado")
        if clave_barra != self._clave_barra:
            self._clave_barra = clave_barra
            self._foto_barra = ImageTk.PhotoImage(
                crear_barra(self.ancho_barra, self.px(12), pct / 100, estado == "completado"))
            self.barra.configure(image=self._foto_barra)

        if estado == "completado":
            archivo, eta = "Todos los archivos listos", "¡Terminado!"
        elif estado in ("error", "detenido"):
            archivo, eta = d.get("mensaje", "") or "—", "—"
        elif estado == "inactivo":
            archivo, eta = "En espera de acción", "—"
        else:
            archivo, eta = d.get("archivo_actual") or "Analizando…", formatear_eta(d.get("eta_segundos"))

        self.valores["archivo"].configure(text=archivo[:40])
        tot_arch = d.get("archivos_totales", 0)
        self.valores["archivos"].configure(text=f"{d.get('archivos_hechos', 0)} / {tot_arch}" if tot_arch else "—")
        self.valores["eta"].configure(text=eta)
        fpm = d.get("velocidad_fpm") or 0
        self.valores["velocidad"].configure(text=f"{fpm:.0f} frases/min" if fpm else "—")

        # Lista de feed en vivo
        frases = d.get("ultimas_frases", [])
        id_top = frases[0]["id"] if frases else None
        if id_top != self._ultimo_id_frase:
            self._ultimo_id_frase = id_top
            for w in self.feed_lista.winfo_children():
                w.destroy()
            if not frases:
                tk.Label(self.feed_lista, text="Esperando diálogos traducidos…", font=self._f_feed, fg=C_SUAVE,
                         bg=C_TARJETA, anchor="w").pack(fill="x")
            for i, frase in enumerate(frases[:6]):
                fila = tk.Frame(self.feed_lista, bg=C_TARJETA_ALT)
                fila.pack(fill="x", pady=(0, self.px(4)))
                tk.Frame(fila, bg=C_ACENTO if i == 0 else "#4c4f8a", width=self.px(3)).pack(side="left", fill="y")
                tk.Label(fila, text=frase["texto"], font=self._f_feed, fg=C_TEXTO if i == 0 else "#cbd5e1",
                         bg=C_TARJETA_ALT, anchor="w", justify="left", wraplength=self.px(480),
                         padx=self.px(10), pady=self.px(4)).pack(side="left", fill="x", expand=True)

    def _notificar_cambios(self, d: dict, estado: str) -> None:
        anterior, self._estado_anterior = self._estado_anterior, estado
        if anterior is None or anterior == estado:
            return
        juego = nombre_bonito(d.get("juego", ""))
        try:
            if estado == "completado":
                self.icono.notify(f"{juego} se ha traducido al 100%.", "✔ Traducción completada")
            elif estado == "error":
                self.icono.notify(d.get("mensaje", "Error desconocido")[:200], "✖ Error en la traducción")
        except Exception:
            pass

    def ejecutar(self) -> None:
        self.root.mainloop()


# --------------------------------------------------------------------------- Acceso Directo
def crear_acceso_directo() -> None:
    """Crea 'Traductor IA Monitor' en el Escritorio, sin consola y con icono propio."""
    ico = RAIZ / "herramientas_extra" / "monitor_bandeja.ico"
    crear_icono(75, "traduciendo", 256).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = RAIZ / "venv_traductor" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(r"C:\Users\marco\AppData\Local\Programs\Python\Python310\pythonw.exe")

    destino = Path(os.path.expandvars(r"%USERPROFILE%\Desktop")) / "Traductor IA Monitor.lnk"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{exe}';$s.Arguments='\"{py}\"';$s.WorkingDirectory='{raiz}';"
        "$s.IconLocation='{ico}';$s.Description='Centro de Control y Monitor de Traducción';$s.Save()"
    ).format(lnk=destino, exe=pythonw, py=Path(__file__).resolve(), raiz=RAIZ, ico=ico)
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    print(f"Acceso directo creado: {destino}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Centro de Control y Monitor de Traducción en la Bandeja.")
    parser.add_argument("--bandeja", action="store_true", help="Arrancar escondido en la bandeja")
    parser.add_argument("--acceso-directo", action="store_true", help="Crear acceso directo en el Escritorio")
    parser.add_argument("--debug", action="store_true", help="Arrancar en modo depuración con registros detallados")
    args = parser.parse_args()

    if args.acceso_directo:
        crear_acceso_directo()
        return

    try:
        if avisar_instancia_existente(b"ping" if args.bandeja else b"mostrar"):
            return

        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            servidor.bind(("127.0.0.1", PUERTO_INSTANCIA))
            servidor.listen(4)
        except OSError:
            servidor.close()
            servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass

        MonitorBandeja(empezar_oculto=args.bandeja, servidor=servidor, modo_debug=args.debug).ejecutar()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        try:
            (RAIZ / "herramientas_extra" / "monitor_error.log").write_text(err_msg, encoding="utf-8")
        except Exception:
            pass
        if os.name == "nt":
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Error al iniciar el Centro de Control:\n\n{e}\n\nLos detalles se han guardado en herramientas_extra/monitor_error.log",
                    "Traductor IA - Error",
                    0x10
                )
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
