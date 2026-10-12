"""monitor_bandeja.py — Monitor de traducción en la bandeja del sistema (estilo Discord / Steam).

- Se queda en la bandeja (junto al reloj) con un icono que dibuja el porcentaje en un anillo.
- Al pasar el ratón por encima muestra el porcentaje, el archivo actual y el tiempo restante.
- La ventana solo aparece en la barra de tareas cuando la abres tú (doble clic / clic en el icono
  o volviendo a lanzar la aplicación). Minimizar, cerrar (X) o el botón "Minimizar a la bandeja"
  la esconden de nuevo. Para cerrarla del todo: clic derecho en el icono → Salir.
- Lee ``workspace/progreso_actual.json`` que escribe ``1_traducir_juego.py``.

Uso:
    pythonw herramientas_extra/monitor_bandeja.py              # abre la ventana
    pythonw herramientas_extra/monitor_bandeja.py --bandeja    # arranca escondido en la bandeja
    python  herramientas_extra/monitor_bandeja.py --acceso-directo   # crea acceso directo en el Escritorio
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pystray  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageTk  # noqa: E402

from traductor.progreso import ARCHIVO_PROGRESO, leer_progreso, proceso_vivo  # noqa: E402

APP_NOMBRE = "Traductor IA"
APP_ID = "TraductorIA.MonitorBandeja"
PUERTO_INSTANCIA = 50551          # una sola instancia: la segunda le pide a la primera que se muestre
URL_WEB = "http://localhost:5050"
INTERVALO_MS = 1000

# Paleta (a juego con el monitor web)
C_FONDO = "#0b0f19"
C_TARJETA = "#151c2f"
C_BORDE = "#232c45"
C_TEXTO = "#f8fafc"
C_SUAVE = "#94a3b8"
C_ACENTO = "#8b5cf6"
GRADIENTE = ((99, 102, 241), (168, 85, 247), (236, 72, 153))

ESTADOS = {
    #  estado       (texto,                   color del anillo / pastilla)
    "traduciendo": ("Traduciendo en vivo", (139, 92, 246)),
    "preparando": ("Preparando…", (99, 102, 241)),
    "completado": ("¡Completado!", (16, 185, 129)),
    "error": ("Error", (239, 68, 68)),
    "detenido": ("Detenido", (245, 158, 11)),
    "inactivo": ("Sin traducción en curso", (100, 116, 139)),
}


# --------------------------------------------------------------------------- Utilidades
def hex_rgb(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


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


def normalizar(datos: dict | None) -> dict:
    """Completa el estado leído y detecta traducciones cuyo proceso ya no existe."""
    if not datos:
        return {"estado": "inactivo", "porcentaje": 0.0, "ultimas_frases": []}
    datos = dict(datos)
    if datos.get("estado") in ("traduciendo", "preparando") and not proceso_vivo(datos.get("pid")):
        datos["estado"] = "detenido"
        datos["mensaje"] = "El proceso de traducción se cerró antes de terminar"
    datos.setdefault("ultimas_frases", [])
    return datos


def texto_tooltip(d: dict) -> str:
    """Texto al pasar el ratón por el icono (Windows admite como máximo 127 caracteres)."""
    estado = d.get("estado", "inactivo")
    lineas = [f"{APP_NOMBRE} · {nombre_bonito(d.get('juego', ''))}" if d.get("juego") else APP_NOMBRE]
    if estado == "inactivo":
        lineas.append("Sin traducción en curso")
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


# --------------------------------------------------------------------------- Dibujo
def crear_icono(pct: float, estado: str, tam: int = 64) -> Image.Image:
    """Icono de bandeja: anillo de progreso con el porcentaje (o un símbolo) en el centro."""
    s = tam * 4  # sobremuestreo para bordes suaves
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
    """Barra de progreso redondeada con degradado (dibujada con PIL para que quede suave)."""
    s = 3
    W, H = ancho * s, alto * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=(31, 39, 64, 255))
    relleno = int(W * max(0.0, min(1.0, fraccion)))
    if relleno > 0:
        relleno = max(relleno, H)  # que el extremo redondeado no se deforme
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


# --------------------------------------------------------------------------- Instancia única
def avisar_instancia_existente(mensaje: bytes) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PUERTO_INSTANCIA), timeout=1) as c:
            c.sendall(mensaje)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- Aplicación
class MonitorBandeja:
    def __init__(self, empezar_oculto: bool, servidor: socket.socket):
        self.cola: queue.Queue[str] = queue.Queue()
        self.servidor = servidor
        self.datos: dict = {}
        self._ultimo_id_frase: int | None = None
        self._clave_icono: tuple | None = None
        self._clave_barra: tuple | None = None
        self._estado_anterior: str | None = None
        self._saliendo = False

        self.root = tk.Tk()
        self.root.withdraw()  # evita el parpadeo inicial
        self.esc = self.root.winfo_fpixels("1i") / 96.0
        self.root.title(f"{APP_NOMBRE} — Monitor")
        self.root.configure(bg=C_FONDO)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.ocultar)
        self.root.bind("<Unmap>", self._al_minimizar)

        self._construir_ui()
        self._centrar()

        self.icono = pystray.Icon(
            "traductor_ia",
            crear_icono(0, "inactivo"),
            APP_NOMBRE,
            pystray.Menu(
                pystray.MenuItem("Mostrar ventana", lambda: self.cola.put("mostrar"), default=True),
                pystray.MenuItem("Abrir monitor web", lambda: self.cola.put("web")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", lambda: self.cola.put("salir")),
            ),
        )
        threading.Thread(target=self.icono.run, daemon=True).start()
        threading.Thread(target=self._escuchar_instancias, daemon=True).start()

        self.actualizar()
        if not empezar_oculto:
            self.root.after(150, self.mostrar)
        self.root.after(100, self._procesar_cola)

    # ----------------------------------------------------------------- Interfaz
    def px(self, valor: float) -> int:
        return int(valor * self.esc)

    def _construir_ui(self) -> None:
        f_titulo = ("Segoe UI Variable Display", 17, "bold")
        f_sub = ("Segoe UI", 9)
        f_pct = ("Segoe UI Variable Display", 34, "bold")
        f_etiqueta = ("Segoe UI", 8)
        f_valor = ("Segoe UI Semibold", 11)
        f_feed = ("Segoe UI", 9)
        self.ancho_barra = self.px(400)

        cont = tk.Frame(self.root, bg=C_FONDO, padx=self.px(22), pady=self.px(18))
        cont.pack(fill="both", expand=True)

        # Cabecera
        cab = tk.Frame(cont, bg=C_FONDO)
        cab.pack(fill="x")
        izq = tk.Frame(cab, bg=C_FONDO)
        izq.pack(side="left", fill="x", expand=True)
        self.lbl_juego = tk.Label(izq, text=APP_NOMBRE, font=f_titulo, fg=C_TEXTO, bg=C_FONDO, anchor="w")
        self.lbl_juego.pack(fill="x")
        self.lbl_sub = tk.Label(izq, text="Monitor de traducción con IA local", font=f_sub, fg=C_SUAVE,
                                bg=C_FONDO, anchor="w")
        self.lbl_sub.pack(fill="x")
        self.pastilla = tk.Label(cab, text="", font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_TARJETA,
                                 padx=self.px(10), pady=self.px(3))
        self.pastilla.pack(side="right", anchor="n", pady=self.px(4))

        # Tarjeta principal
        tarjeta = tk.Frame(cont, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                           padx=self.px(18), pady=self.px(16))
        tarjeta.pack(fill="x", pady=(self.px(16), self.px(12)))
        fila = tk.Frame(tarjeta, bg=C_TARJETA)
        fila.pack(fill="x")
        self.lbl_pct = tk.Label(fila, text="0%", font=f_pct, fg=C_TEXTO, bg=C_TARJETA)
        self.lbl_pct.pack(side="left")
        self.lbl_frases = tk.Label(fila, text="", font=("Segoe UI", 10), fg=C_SUAVE, bg=C_TARJETA)
        self.lbl_frases.pack(side="right", anchor="s", pady=self.px(10))
        self.barra = tk.Label(tarjeta, bg=C_TARJETA, bd=0)
        self.barra.pack(fill="x", pady=(self.px(6), self.px(14)))

        rejilla = tk.Frame(tarjeta, bg=C_TARJETA)
        rejilla.pack(fill="x")
        self.valores: dict[str, tk.Label] = {}
        for i, (clave, titulo) in enumerate((("archivo", "ARCHIVO ACTUAL"), ("archivos", "ARCHIVOS"),
                                             ("eta", "TIEMPO RESTANTE"), ("velocidad", "VELOCIDAD"))):
            celda = tk.Frame(rejilla, bg="#1b2338", padx=self.px(12), pady=self.px(8))
            celda.grid(row=i // 2, column=i % 2, sticky="nsew", padx=self.px(3), pady=self.px(3))
            tk.Label(celda, text=titulo, font=f_etiqueta, fg=C_SUAVE, bg="#1b2338", anchor="w").pack(fill="x")
            lbl = tk.Label(celda, text="—", font=f_valor, fg=C_TEXTO, bg="#1b2338", anchor="w")
            lbl.pack(fill="x")
            self.valores[clave] = lbl
        rejilla.columnconfigure(0, weight=1, uniform="c")
        rejilla.columnconfigure(1, weight=1, uniform="c")

        # Últimas frases
        feed = tk.Frame(cont, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                        padx=self.px(16), pady=self.px(12))
        feed.pack(fill="both", expand=True)
        tk.Label(feed, text="⚡ Últimas frases traducidas por la IA", font=("Segoe UI Semibold", 10),
                 fg=C_TEXTO, bg=C_TARJETA, anchor="w").pack(fill="x", pady=(0, self.px(8)))
        self.feed_lista = tk.Frame(feed, bg=C_TARJETA, height=self.px(190))
        self.feed_lista.pack(fill="both", expand=True)
        self.feed_lista.pack_propagate(False)
        self._f_feed = f_feed

        # Botones
        botones = tk.Frame(cont, bg=C_FONDO)
        botones.pack(fill="x", pady=(self.px(14), 0))
        self._boton(botones, "🌐  Monitor web", self.abrir_web, primario=False).pack(side="left")
        self._boton(botones, "⬇  Minimizar a la bandeja", self.ocultar, primario=True).pack(side="right")

    def _boton(self, padre: tk.Widget, texto: str, comando, primario: bool) -> tk.Label:
        normal = C_ACENTO if primario else C_TARJETA
        hover = "#a78bfa" if primario else "#1f2942"
        b = tk.Label(padre, text=texto, font=("Segoe UI Semibold", 10), fg=C_TEXTO, bg=normal, cursor="hand2",
                     padx=self.px(14), pady=self.px(7))
        b.bind("<Enter>", lambda _e: b.configure(bg=hover))
        b.bind("<Leave>", lambda _e: b.configure(bg=normal))
        b.bind("<Button-1>", lambda _e: comando())
        return b

    def _centrar(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"+{x}+{y}")

    # ----------------------------------------------------------------- Mostrar / ocultar
    def mostrar(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        if self.datos:
            # Mientras estaba escondida no se redibujaba: ponerla al día antes de que se vea
            self._actualizar_ventana(self.datos, self.datos.get("estado", "inactivo"),
                                     float(self.datos.get("porcentaje", 0.0)))
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def ocultar(self) -> None:
        # withdraw() quita la ventana de la barra de tareas; el icono sigue en la bandeja
        self.root.withdraw()

    def _al_minimizar(self, evento) -> None:
        if evento.widget is self.root and self.root.state() == "iconic":
            self.root.after(10, self.ocultar)

    def salir(self) -> None:
        self._saliendo = True
        try:
            self.icono.stop()
        except Exception:
            pass
        try:
            self.servidor.close()
        except OSError:
            pass
        self.root.destroy()

    # ----------------------------------------------------------------- Comunicación entre hilos
    def _procesar_cola(self) -> None:
        try:
            while True:
                orden = self.cola.get_nowait()
                if orden == "mostrar":
                    self.mostrar()
                elif orden == "web":
                    self.abrir_web()
                elif orden == "salir":
                    self.salir()
                    return
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
                        self.cola.put("mostrar")
                except OSError:
                    pass

    # ----------------------------------------------------------------- Monitor web
    def abrir_web(self) -> None:
        def tarea():
            try:
                urllib.request.urlopen(URL_WEB + "/api/progreso", timeout=1)
            except OSError:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                exe = str(pythonw if pythonw.exists() else sys.executable)
                subprocess.Popen([exe, str(RAIZ / "herramientas_extra" / "servidor_progreso.py")], cwd=str(RAIZ),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                time.sleep(1.5)
            webbrowser.open(URL_WEB)
        threading.Thread(target=tarea, daemon=True).start()

    # ----------------------------------------------------------------- Actualización periódica
    def actualizar(self) -> None:
        if self._saliendo:
            return
        bruto = leer_progreso(ARCHIVO_PROGRESO)
        if bruto is None and ARCHIVO_PROGRESO.exists() and self.datos:
            d = self.datos  # archivo a medio escribir: conservar lo último bueno
        else:
            d = normalizar(bruto)
        self.datos = d
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
        self.lbl_juego.configure(text=nombre_bonito(d.get("juego", "")) if d.get("juego") else APP_NOMBRE)
        detalles = [p for p in (d.get("modelo"), f"Modo {d['modo']}" if d.get("modo") else None) if p]
        self.lbl_sub.configure(text=" · ".join(detalles) or "Monitor de traducción con IA local")
        self.pastilla.configure(text=f"●  {texto_estado}", fg=hex_rgb(color))

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
            archivo, eta = "Esperando a 1_traducir_juego.py", "—"
        else:
            archivo, eta = d.get("archivo_actual") or "Analizando…", formatear_eta(d.get("eta_segundos"))
        self.valores["archivo"].configure(text=archivo[:38])
        tot_arch = d.get("archivos_totales", 0)
        self.valores["archivos"].configure(text=f"{d.get('archivos_hechos', 0)} / {tot_arch}" if tot_arch else "—")
        self.valores["eta"].configure(text=eta)
        fpm = d.get("velocidad_fpm") or 0
        self.valores["velocidad"].configure(text=f"{fpm:.0f} frases/min" if fpm else "—")

        # Solo se reconstruye la lista cuando la IA ha traducido algo nuevo (sin parpadeos)
        frases = d.get("ultimas_frases", [])
        id_top = frases[0]["id"] if frases else None
        if id_top != self._ultimo_id_frase:
            self._ultimo_id_frase = id_top
            for w in self.feed_lista.winfo_children():
                w.destroy()
            if not frases:
                tk.Label(self.feed_lista, text="Esperando diálogos…", font=self._f_feed, fg=C_SUAVE,
                         bg=C_TARJETA, anchor="w").pack(fill="x")
            for i, frase in enumerate(frases[:6]):
                fila = tk.Frame(self.feed_lista, bg="#1b2338")
                fila.pack(fill="x", pady=(0, self.px(4)))
                tk.Frame(fila, bg=C_ACENTO if i == 0 else "#4c4f8a", width=self.px(3)).pack(side="left", fill="y")
                tk.Label(fila, text=frase["texto"], font=self._f_feed, fg=C_TEXTO if i == 0 else "#cbd5e1",
                         bg="#1b2338", anchor="w", justify="left", wraplength=self.px(370),
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
            elif estado == "traduciendo" and anterior in ("inactivo", "completado", "detenido", "error"):
                self.icono.notify(f"Empezando a traducir {juego}.", APP_NOMBRE)
        except Exception:
            pass

    def ejecutar(self) -> None:
        self.root.mainloop()


# --------------------------------------------------------------------------- Acceso directo
def crear_acceso_directo() -> None:
    """Crea 'Traductor IA Monitor' en el Escritorio, sin ventana de consola y con icono propio."""
    ico = RAIZ / "herramientas_extra" / "monitor_bandeja.ico"
    crear_icono(75, "traduciendo", 256).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    destino = Path(os.path.expandvars(r"%USERPROFILE%\Desktop")) / "Traductor IA Monitor.lnk"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{exe}';$s.Arguments='\"{py}\"';$s.WorkingDirectory='{raiz}';"
        "$s.IconLocation='{ico}';$s.Description='Monitor de traducción en la bandeja';$s.Save()"
    ).format(lnk=destino, exe=pythonw if pythonw.exists() else sys.executable,
             py=Path(__file__).resolve(), raiz=RAIZ, ico=ico)
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    print(f"Acceso directo creado: {destino}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor de traducción en la bandeja del sistema.")
    parser.add_argument("--bandeja", action="store_true", help="Arrancar escondido en la bandeja")
    parser.add_argument("--acceso-directo", action="store_true", help="Crear acceso directo en el Escritorio")
    args = parser.parse_args()

    if args.acceso_directo:
        crear_acceso_directo()
        return

    # Si ya hay una instancia abierta, se le pide que se muestre (o nada si venimos con --bandeja)
    if avisar_instancia_existente(b"ping" if args.bandeja else b"mostrar"):
        return

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        servidor.bind(("127.0.0.1", PUERTO_INSTANCIA))
    except OSError:
        return
    servidor.listen(4)

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texto nítido en pantallas con escalado
        except (AttributeError, OSError):
            pass

    MonitorBandeja(empezar_oculto=args.bandeja, servidor=servidor).ejecutar()


if __name__ == "__main__":
    main()
