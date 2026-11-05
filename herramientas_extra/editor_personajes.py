"""editor_personajes.py — Editor de la ficha de personajes de un juego (Paso 0).

La ficha (``workspace/<juego>/personajes.json``) le dice al traductor quién es el protagonista y
si es hombre o mujer, y el género, alias y códigos de hablante del resto de personajes. Con ella
la IA no escribe "estoy cansada" cuando habla un chico ni "bienvenido" cuando saluda a una chica.
Normalmente la crea el Paso 0 (``0_analizar_juego.py``) y aquí se revisa:

  - Tabla con todos los personajes: nombre, rol, género, códigos/alias, líneas que dice,
    menciones, confianza del análisis automático y si ya lo has confirmado tú.
  - Panel inferior (o doble clic en una fila) para editar el personaje seleccionado.
  - Todo lo que edites se guarda con ``confirmado: true``: volver a analizar el juego ya no lo
    sobrescribe (ver ``FichaPersonajes.fusionar``).

Se abre desde el Centro de Control (``monitor_bandeja.py``) o en solitario::

    python herramientas_extra/editor_personajes.py --juego mi_juego
    python herramientas_extra/editor_personajes.py --ruta "D:\\Juegos\\Mi juego"
"""
from __future__ import annotations

import argparse
import ctypes
import inspect
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from traductor import config  # noqa: E402
from traductor.genero import DESCONOCIDO, GENEROS, HOMBRE, MUJER, NEUTRO, normalizar_genero  # noqa: E402
from traductor.personajes import ARCHIVO_PERSONAJES, ROLES, FichaPersonajes, Personaje, ruta_ficha  # noqa: E402

log = logging.getLogger(__name__)

SCRIPT_ANALIZADOR = RAIZ / "0_analizar_juego.py"
ICONO = RAIZ / "herramientas_extra" / "monitor_bandeja.ico"

# Paleta del Centro de Control (copiada de monitor_bandeja.py para no depender de pystray/PIL)
C_FONDO = "#0b0f19"
C_TARJETA = "#151c2f"
C_TARJETA_ALT = "#1b2338"
C_BORDE = "#232c45"
C_TEXTO = "#f8fafc"
C_SUAVE = "#94a3b8"
C_ACENTO = "#8b5cf6"
C_ACENTO_HOVER = "#7c3aed"
C_VERDE = "#10b981"
C_ROJO = "#ef4444"
C_AMBAR = "#f59e0b"
C_ANALIZAR = "#7e22ce"

# Colores del aviso superior según su nivel: (fondo, borde, texto)
COLORES_AVISO = {
    "error": ("#2b1520", C_ROJO, "#fca5a5"),
    "aviso": ("#2a2113", C_AMBAR, "#fcd34d"),
    "info": ("#1e1b3a", C_ACENTO, "#ddd6fe"),
}
COLORES_ESTADO = {"ok": C_VERDE, "info": C_SUAVE, "aviso": C_AMBAR, "error": C_ROJO}

COLOR_GENERO = {HOMBRE: "#93c5fd", MUJER: "#f9a8d4", NEUTRO: "#c4b5fd", DESCONOCIDO: "#fbbf24"}
TEXTO_GENERO = {HOMBRE: "♂ hombre", MUJER: "♀ mujer", NEUTRO: "⊘ neutro", DESCONOCIDO: "⚠ desconocido"}

# (id, título, ancho en px a 96 ppp, alineación)
COLUMNAS = (
    ("nombre", "Nombre", 170, "w"),
    ("rol", "Rol", 118, "w"),
    ("genero", "Género", 118, "w"),
    ("codigos", "Códigos / alias", 230, "w"),
    ("lineas", "Líneas", 64, "e"),
    ("menciones", "Menciones", 82, "e"),
    ("confianza", "Confianza", 82, "e"),
    ("confirmado", "Confirmado", 104, "center"),
)

REGLAS_TEXTO = (
    ("opciones_del_protagonista", "Las opciones de diálogo las dice el protagonista"),
    ("pensamientos_del_protagonista", "Los pensamientos «(…)» sin hablante son del protagonista"),
    ("npc_hablan_al_protagonista", "Cuando habla un personaje, se dirige al protagonista"),
)

AYUDA_PANEL = ("Alias y códigos van separados por comas. Código = cómo identifica el juego a quien habla "
               "(prefijo «He», cara «face:Actor1#0», Ren'Py «renpy:mc»…).")


# --------------------------------------------------------------------------- Utilidades
def nombre_bonito(juego: str | None) -> str:
    return juego.replace("_", " ").title() if juego else "Sin juego"


def _recortar(texto: str, maximo: int) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


def _aclarar(hex_str: str, factor: float = 1.18) -> str:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return hex_str
    r, g, b = (min(255, int(int(h[i:i + 2], 16) * factor)) for i in (0, 2, 4))
    return f"#{r:02x}{g:02x}{b:02x}"


def obtener_python_ejecutable() -> Path:
    """El Python con todas las dependencias (mismo criterio que ``monitor_bandeja.py``)."""
    venv_py = RAIZ / "venv_traductor" / "Scripts" / "python.exe"
    if venv_py.exists():
        return venv_py
    p310 = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python310" / "python.exe"
    if p310.exists():
        return p310
    actual = Path(sys.executable)
    consola = actual.with_name("python.exe")  # pythonw.exe no tiene salida de consola
    return consola if actual.name.lower() == "pythonw.exe" and consola.exists() else actual


def lista_desde_texto(texto: str) -> list[str]:
    """'He, Mc ,, face:Actor1#0' -> ['He', 'Mc', 'face:Actor1#0'] (sin vacíos ni repetidos)."""
    vistos: set[str] = set()
    res: list[str] = []
    for trozo in (texto or "").split(","):
        t = trozo.strip()
        if t and t not in vistos:
            vistos.add(t)
            res.append(t)
    return res


def texto_codigos_alias(p: Personaje) -> str:
    """Texto de la columna "Códigos / alias": 'cód: La  ·  alias: Laura, Lau'."""
    partes = []
    if p.codigos:
        partes.append("cód: " + ", ".join(p.codigos))
    if p.alias:
        partes.append("alias: " + ", ".join(p.alias))
    return "  ·  ".join(partes)


def ruta_ficha_juego(juego: str | None) -> Path:
    """``workspace/<juego>/personajes.json`` (el perfil se resuelve como en el resto del proyecto)."""
    return ruta_ficha(config.carpeta_juego(juego))


def leer_ficha(ruta: Path) -> tuple[FichaPersonajes | None, str]:
    """Lee una ficha. Devuelve ``(ficha, "")``, ``(None, "")`` si no existe o ``(None, motivo)`` si está dañada."""
    ruta = Path(ruta)
    if not ruta.is_file():
        return None, ""
    try:
        ficha = FichaPersonajes.cargar(ruta)
    except (ValueError, TypeError, AttributeError) as e:  # p. ej. "apariciones": "muchas"
        return None, f"datos con formato inesperado ({e})"
    if ficha is not None:
        return ficha, ""
    try:
        json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return None, str(e)
    return None, "formato no reconocido"


def _ultima_ruta_gui() -> Path | None:
    """Última carpeta de juego elegida en el Centro de Control (``workspace/config_gui.json``)."""
    try:
        datos = json.loads((config.DIR_WORKSPACE / "config_gui.json").read_text(encoding="utf-8"))
        ruta = str(datos.get("ultima_ruta") or "")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(ruta) if ruta else None


# --------------------------------------------------------------------------- Estado de la ficha
@dataclass
class EstadoFicha:
    """Situación de la ficha de personajes de un juego.

    La usa el Centro de Control para la cabecera ("Protagonista: Noelia (mujer) ✔") y para decidir
    si pregunta antes de traducir.
    """

    juego: str | None
    ruta: Path
    ficha: FichaPersonajes | None = None
    error: str = ""

    @property
    def existe(self) -> bool:
        return self.ficha is not None or bool(self.error)

    @property
    def danada(self) -> bool:
        return bool(self.error)

    @property
    def protagonista(self) -> Personaje | None:
        return self.ficha.protagonista() if self.ficha is not None else None

    def necesita_revision(self) -> bool:
        """True si conviene analizar/revisar antes de traducir: no hay ficha (o está dañada), o el
        protagonista falta, tiene género desconocido o no está confirmado."""
        p = self.protagonista
        return p is None or p.genero == DESCONOCIDO or not p.confirmado

    def accion_recomendada(self) -> str:
        """'analizar' si el juego no tiene ficha; 'revisar' (abrir el editor) en los demás casos."""
        return "analizar" if not self.existe else "revisar"

    def texto_cabecera(self) -> tuple[str, str]:
        """(texto, nivel) para la cabecera del Centro de Control. Nivel: ok, info, aviso o error."""
        if self.danada:
            return "🧑 personajes.json dañado: ábrelo en el editor", "error"
        if self.ficha is None:
            return "🧑 Personajes: sin analizar (Paso 0)", "info"
        p = self.protagonista
        otros = [x for x in self.ficha.pendientes_de_revisar() if x is not p]
        extra = f" · {len(otros)} por revisar" if otros else ""
        if p is None:
            return f"🧑 Ficha sin protagonista ⚠{extra}", "aviso"
        nombre = _recortar(p.nombre, 32)
        if p.genero == DESCONOCIDO:
            return f"🧑 Protagonista: {nombre} (género desconocido) ⚠{extra}", "aviso"
        if not p.confirmado:
            return f"🧑 Protagonista: {nombre} ({p.genero}) · sin confirmar{extra}", "aviso"
        return f"🧑 Protagonista: {nombre} ({p.genero}) ✔{extra}", ("aviso" if otros else "ok")

    def pregunta_antes_de_traducir(self) -> str:
        """Texto del aviso Sí/No/Cancelar que el Centro de Control muestra antes de traducir."""
        riesgo = ("Sin esa información la IA puede equivocarse con el género de los adjetivos "
                  "(«estoy cansado» / «estoy cansada», «bienvenido» / «bienvenida»).")
        if self.danada:
            motivo = ("No se pudo leer la ficha de personajes (personajes.json):\n"
                      f"{_recortar(self.error, 160)}\n\nMientras siga así se traduce como si no hubiera ficha.")
            si = "abrir el editor de personajes para corregirla"
        elif self.ficha is None:
            motivo = ("Este juego todavía no tiene ficha de personajes: el traductor no sabe quién es el "
                      "protagonista, si es hombre o mujer, ni quién habla en cada línea.\n\n" + riesgo)
            si = "analizar ahora los personajes (Paso 0) y revisar el resultado"
        else:
            p = self.protagonista
            if p is None:
                motivo = "La ficha de personajes no indica quién es el protagonista.\n\n" + riesgo
            elif p.genero == DESCONOCIDO:
                motivo = f"No se sabe si el protagonista ({p.nombre}) es hombre o mujer.\n\n" + riesgo
            else:
                motivo = (f"El protagonista se detectó automáticamente como {p.nombre} ({p.genero}), pero "
                          "todavía no lo has confirmado. Si fuera un error, la IA usaría el género "
                          "equivocado en todo el juego.")
            si = "abrir el editor de personajes para revisarlo"
        return (f"{motivo}\n\n¿Quieres revisarlo antes de traducir?\n\n"
                f"   • Sí: {si}.\n   • No: traducir igualmente.\n   • Cancelar: no hacer nada.")


def estado_ficha(juego: str | None) -> EstadoFicha:
    """Lee (sin modificar nada) la ficha de personajes de ``juego``."""
    ruta = ruta_ficha_juego(juego)
    ficha, error = leer_ficha(ruta)
    return EstadoFicha(juego=juego, ruta=ruta, ficha=ficha, error=error)


# --------------------------------------------------------------------------- Editor
class EditorPersonajes:
    """Ventana (``tk.Toplevel``) para revisar y editar la ficha de personajes de un juego."""

    def __init__(self, master: tk.Misc | None, juego: str, ruta_juego: str | Path | None = None, *,
                 al_guardar: Callable[[FichaPersonajes], None] | None = None,
                 al_cerrar: Callable[[], None] | None = None):
        self.juego = juego
        self.ruta_juego = Path(ruta_juego) if ruta_juego else None
        self.ruta = ruta_ficha_juego(juego)
        self.al_guardar = al_guardar
        self.al_cerrar = al_cerrar

        self.ficha = FichaPersonajes()
        self.existia = False
        self.error_carga = ""
        self._items: dict[str, Personaje] = {}      # iid de la tabla -> personaje
        self._iid_de: dict[int, str] = {}           # id(personaje) -> iid
        self._editados: set[int] = set()            # id(personaje) que se guardarán como confirmados
        self._originales: dict[int, str] = {}       # id(personaje) -> nombre leído del archivo
        self._actual: Personaje | None = None       # personaje cargado en el panel
        self._modificado = False
        self._cargando_panel = False
        self._cerrada = False
        self._ocupado = False
        self._proceso: subprocess.Popen | None = None
        self._cola: queue.Queue[tuple[str, object]] = queue.Queue()
        self._salida_analisis: list[str] = []
        self._orden: tuple[str, bool] | None = None
        self._bloqueables: list[tk.Label] = []

        self.ventana = tk.Toplevel(master)
        self.ventana.editor = self  # type: ignore[attr-defined]  # para que el Centro de Control lo encuentre
        self.esc = self.ventana.winfo_fpixels("1i") / 96.0
        self._configurar_estilos()
        self._construir_ui()
        self._cargar()
        self._poblar()
        self._cargar_panel(None)
        self._actualizar_aviso()
        self._actualizar_titulo()
        self._estado("Consejo: doble clic en una fila para editarla. Lo que cambies se guarda como "
                     "confirmado y el análisis automático ya no lo tocará.")
        self._colocar()

    def px(self, valor: float) -> int:
        return int(valor * self.esc)

    # ----------------------------------------------------------------- Construcción visual
    def _configurar_estilos(self) -> None:
        """Tabla oscura SIN cambiar el tema global de ttk (el Centro de Control usa 'vista')."""
        st = ttk.Style(self.ventana)
        # El tema 'vista' dibuja la tabla y sus cabeceras con elementos nativos que ignoran los
        # colores: se crean copias de los elementos del tema 'default' solo para este estilo.
        for elemento in ("Personajes.Treeview.field", "Personajes.Treeheading.cell",
                         "Personajes.Treeheading.border"):
            try:
                st.element_create(elemento, "from", "default")
            except tk.TclError:
                pass  # ya creado por otra ventana del editor
        try:
            st.layout("Personajes.Treeview", [("Personajes.Treeview.field", {
                "sticky": "nswe", "border": "1", "children": [("Treeview.padding", {
                    "sticky": "nswe", "children": [("Treeview.treearea", {"sticky": "nswe"})]})]})])
            st.layout("Personajes.Treeview.Heading", [
                ("Personajes.Treeheading.cell", {"sticky": "nswe"}),
                ("Personajes.Treeheading.border", {"sticky": "nswe", "children": [
                    ("Treeheading.padding", {"sticky": "nswe", "children": [
                        ("Treeheading.image", {"side": "right", "sticky": ""}),
                        ("Treeheading.text", {"sticky": "we"})]})]}),
            ])
        except tk.TclError as e:  # si el tema no lo permite, la tabla se ve con colores nativos
            log.debug("No se pudo personalizar la tabla: %s", e)
        st.configure("Personajes.Treeview", background=C_TARJETA_ALT, fieldbackground=C_TARJETA_ALT,
                     foreground=C_TEXTO, rowheight=self.px(26), borderwidth=0, font=("Segoe UI", 9))
        st.map("Personajes.Treeview", background=[("selected", C_ACENTO)], foreground=[("selected", "#ffffff")])
        st.configure("Personajes.Treeview.Heading", background=C_TARJETA, foreground=C_SUAVE, relief="flat",
                     borderwidth=1, font=("Segoe UI Semibold", 9))
        st.map("Personajes.Treeview.Heading", background=[("active", C_BORDE)])

    def _construir_ui(self) -> None:
        v = self.ventana
        v.configure(bg=C_FONDO)
        v.minsize(self.px(840), self.px(620))
        v.protocol("WM_DELETE_WINDOW", self.cerrar)
        v.bind("<Control-s>", lambda _e: (self.guardar(), "break")[1])
        # Si otra parte del programa destruye la ventana, deja de sondear y de tocar sus widgets
        v.bind("<Destroy>", lambda e: setattr(self, "_cerrada", True) if str(e.widget) == str(v) else None,
               add="+")
        try:
            if ICONO.exists():
                v.iconbitmap(str(ICONO))
        except tk.TclError:
            pass

        cont = tk.Frame(v, bg=C_FONDO, padx=self.px(18), pady=self.px(14))
        cont.pack(fill="both", expand=True)

        # 1. Cabecera
        self.cab = tk.Frame(cont, bg=C_FONDO)
        self.cab.pack(fill="x")
        self.lbl_titulo = tk.Label(self.cab, text="", font=("Segoe UI Variable Display", 15, "bold"),
                                   fg=C_TEXTO, bg=C_FONDO, anchor="w")
        self.lbl_titulo.pack(fill="x")
        self.lbl_sub = tk.Label(self.cab, text="", font=("Segoe UI", 8), fg=C_SUAVE, bg=C_FONDO, anchor="w")
        self.lbl_sub.pack(fill="x")

        # 2. Aviso superior (solo se muestra si hace falta: ver _actualizar_aviso)
        fondo, borde, color = COLORES_AVISO["aviso"]
        self.aviso = tk.Frame(cont, bg=fondo, highlightthickness=1, highlightbackground=borde,
                              padx=self.px(12), pady=self.px(8))
        self.lbl_aviso = tk.Label(self.aviso, text="", font=("Segoe UI Semibold", 9), fg=color, bg=fondo,
                                  anchor="w", justify="left", wraplength=self.px(780))
        self.lbl_aviso.pack(fill="x")
        self.fila_aviso = tk.Frame(self.aviso, bg=fondo)
        self._boton(self.fila_aviso, "🔎 Analizar el juego ahora", self.volver_a_analizar,
                    color=C_ANALIZAR).pack(side="left", padx=(0, self.px(6)))
        self._boton(self.fila_aviso, "➕ Empezar con una ficha vacía", self.empezar_vacia).pack(side="left")

        # 3. Barra de la tabla con las acciones sobre la selección
        self.barra_tabla = tk.Frame(cont, bg=C_FONDO)
        self.barra_tabla.pack(fill="x", pady=(self.px(10), self.px(6)))
        self.lbl_contador = tk.Label(self.barra_tabla, text="Personajes", font=("Segoe UI Semibold", 10),
                                     fg=C_TEXTO, bg=C_FONDO)
        self.lbl_contador.pack(side="left")
        for texto, comando in (("✔ Confirmar selección", self.confirmar_seleccion),
                               ("★ Marcar protagonista", self.marcar_protagonista),
                               ("🗑 Eliminar", self.eliminar),
                               ("➕ Añadir personaje", self.anadir)):
            self._boton(self.barra_tabla, texto, comando).pack(side="right", padx=(self.px(6), 0))

        # 4. Parte de abajo (se empaqueta antes que la tabla para que nunca quede recortada)
        self.lbl_estado = tk.Label(cont, text="", font=("Segoe UI", 8), fg=C_SUAVE, bg=C_FONDO, anchor="w",
                                   justify="left")
        self.lbl_estado.pack(side="bottom", fill="x", pady=(self.px(6), 0))
        self._construir_pie(cont)
        self._construir_reglas(cont)
        self._construir_panel(cont)

        # 5. Tabla
        marco = tk.Frame(cont, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1)
        marco.pack(fill="both", expand=True)
        self.tabla = ttk.Treeview(marco, columns=[c[0] for c in COLUMNAS], show="headings",
                                  selectmode="extended", style="Personajes.Treeview", height=10)
        for col, titulo, ancho, ancla in COLUMNAS:
            self.tabla.heading(col, text=titulo, anchor=ancla, command=lambda c=col: self._ordenar(c))
            self.tabla.column(col, width=self.px(ancho), minwidth=self.px(48), anchor=ancla,
                              stretch=col in ("nombre", "codigos"))
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.tabla.pack(side="left", fill="both", expand=True)
        for genero, color in COLOR_GENERO.items():
            self.tabla.tag_configure(f"g_{genero}", foreground=color)
        self.tabla.tag_configure("prota", font=("Segoe UI Semibold", 9))
        self.tabla.bind("<<TreeviewSelect>>", self._al_seleccionar)
        self.tabla.bind("<Double-1>", self._doble_clic)
        self.tabla.bind("<Delete>", lambda _e: self.eliminar())

        # Los textos largos se ajustan al ancho de la ventana
        cont.bind("<Configure>", self._al_redimensionar)

    def _construir_panel(self, padre: tk.Widget) -> None:
        panel = tk.Frame(padre, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                         padx=self.px(12), pady=self.px(8))
        panel.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        self.panel = panel
        self.lbl_panel = tk.Label(panel, text="", font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_TARJETA,
                                  anchor="w")
        self.lbl_panel.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, self.px(6)))

        self.var_nombre = tk.StringVar()
        self.var_rol = tk.StringVar()
        self.var_genero = tk.StringVar()
        self.var_alias = tk.StringVar()
        self.var_codigos = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_confirmado = tk.BooleanVar(value=False)

        def etiqueta(texto: str, fila: int, col: int) -> None:
            tk.Label(panel, text=texto, font=("Segoe UI", 9), fg=C_SUAVE, bg=C_TARJETA).grid(
                row=fila, column=col, sticky="e", padx=(self.px(10) if col else 0, self.px(6)), pady=self.px(3))

        etiqueta("Nombre", 1, 0)
        self.ent_nombre = self._entrada(panel, self.var_nombre)
        self.ent_nombre.grid(row=1, column=1, sticky="ew", pady=self.px(3), ipady=self.px(3))
        etiqueta("Rol", 1, 2)
        self.cmb_rol = ttk.Combobox(panel, textvariable=self.var_rol, values=ROLES, state="readonly", width=14)
        self.cmb_rol.grid(row=1, column=3, sticky="w", pady=self.px(3))
        etiqueta("Género", 1, 4)
        self.cmb_genero = ttk.Combobox(panel, textvariable=self.var_genero, values=GENEROS, state="readonly",
                                       width=13)
        self.cmb_genero.grid(row=1, column=5, sticky="w", pady=self.px(3))
        self.chk_confirmado = tk.Checkbutton(
            panel, text="Confirmado", variable=self.var_confirmado, command=self._al_cambiar_confirmado,
            font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_TARJETA, selectcolor=C_TARJETA_ALT,
            activebackground=C_TARJETA, activeforeground=C_TEXTO, highlightthickness=0, bd=0, cursor="hand2")
        self.chk_confirmado.grid(row=1, column=6, sticky="w", padx=(self.px(12), 0))

        etiqueta("Alias", 2, 0)
        self.ent_alias = self._entrada(panel, self.var_alias)
        self.ent_alias.grid(row=2, column=1, sticky="ew", pady=self.px(3), ipady=self.px(3))
        etiqueta("Códigos", 2, 2)
        self.ent_codigos = self._entrada(panel, self.var_codigos)
        self.ent_codigos.grid(row=2, column=3, columnspan=4, sticky="ew", pady=self.px(3), ipady=self.px(3))

        etiqueta("Descripción", 3, 0)
        self.ent_desc = self._entrada(panel, self.var_desc)
        self.ent_desc.grid(row=3, column=1, columnspan=5, sticky="ew", pady=self.px(3), ipady=self.px(3))
        self.btn_aplicar = self._boton(panel, "✔ Aplicar cambios", self._aplicar_desde_boton, primario=True)
        self.btn_aplicar.grid(row=3, column=6, sticky="e", padx=(self.px(12), 0))

        self.lbl_evidencia = tk.Label(panel, text=AYUDA_PANEL, font=("Segoe UI", 8), fg=C_SUAVE, bg=C_TARJETA,
                                      anchor="w", justify="left", wraplength=self.px(780))
        self.lbl_evidencia.grid(row=4, column=0, columnspan=7, sticky="ew", pady=(self.px(4), 0))
        panel.columnconfigure(1, weight=3)
        panel.columnconfigure(3, weight=1)

        for cmb in (self.cmb_rol, self.cmb_genero):
            cmb.bind("<<ComboboxSelected>>", self._aplicar_panel)
        for ent in (self.ent_nombre, self.ent_alias, self.ent_codigos, self.ent_desc):
            ent.bind("<Return>", self._aplicar_panel)
            ent.bind("<FocusOut>", self._aplicar_panel)

    def _construir_reglas(self, padre: tk.Widget) -> None:
        caja = tk.Frame(padre, bg=C_TARJETA, highlightbackground=C_BORDE, highlightthickness=1,
                        padx=self.px(12), pady=self.px(6))
        caja.pack(side="bottom", fill="x", pady=(self.px(8), 0))
        tk.Label(caja, text="⚙ Reglas para la IA", font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=C_TARJETA,
                 anchor="w").grid(row=0, column=0, columnspan=2, sticky="w")
        self.vars_reglas: dict[str, tk.BooleanVar] = {}
        for i, (clave, texto) in enumerate(REGLAS_TEXTO):
            var = tk.BooleanVar(value=True)
            tk.Checkbutton(caja, text=texto, variable=var, command=lambda c=clave: self._al_cambiar_regla(c),
                           font=("Segoe UI", 9), fg=C_TEXTO, bg=C_TARJETA, selectcolor=C_TARJETA_ALT,
                           activebackground=C_TARJETA, activeforeground=C_TEXTO, highlightthickness=0, bd=0,
                           cursor="hand2").grid(row=1 + i // 2, column=i % 2, sticky="w", padx=(0, self.px(18)))
            self.vars_reglas[clave] = var
        self.lbl_regla = tk.Label(caja, text="", font=("Segoe UI", 8, "italic"), fg=C_SUAVE, bg=C_TARJETA,
                                  anchor="w", justify="left", wraplength=self.px(780))
        self.lbl_regla.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(self.px(4), 0))

    def _construir_pie(self, padre: tk.Widget) -> None:
        pie = tk.Frame(padre, bg=C_FONDO)
        pie.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        self._boton(pie, "Cerrar", self.cerrar, bloqueable=False).pack(side="right")
        self._boton(pie, "💾 Guardar", self.guardar, primario=True).pack(side="right", padx=(0, self.px(6)))
        self.btn_analizar = self._boton(pie, "🔎 Volver a analizar", self.volver_a_analizar, color=C_ANALIZAR)
        self.btn_analizar.pack(side="right", padx=(0, self.px(6)))
        self.btn_informe = self._boton(pie, "📄 Ver informe del análisis", self.ver_informe, bloqueable=False)

    def _entrada(self, padre: tk.Widget, variable: tk.StringVar) -> tk.Entry:
        return tk.Entry(padre, textvariable=variable, font=("Segoe UI", 9), bg=C_TARJETA_ALT, fg=C_TEXTO,
                        insertbackground=C_ACENTO, relief="flat", highlightbackground=C_BORDE,
                        highlightcolor=C_ACENTO, highlightthickness=1, disabledbackground=C_TARJETA,
                        disabledforeground=C_SUAVE)

    def _boton(self, padre: tk.Widget, texto: str, comando: Callable[[], object], *, primario: bool = False,
               color: str | None = None, bloqueable: bool = True) -> tk.Label:
        """Botón plano como los del Centro de Control. Los 'bloqueables' no responden durante un análisis."""
        normal = color or (C_ACENTO if primario else C_TARJETA_ALT)
        hover = C_ACENTO_HOVER if primario and not color else _aclarar(normal, 1.35 if not color else 1.18)
        b = tk.Label(padre, text=texto, font=("Segoe UI Semibold", 9), fg=C_TEXTO, bg=normal, cursor="hand2",
                     padx=self.px(12), pady=self.px(5))

        def _clic(_e) -> None:
            if bloqueable and self._ocupado:
                return
            comando()

        b.bind("<Button-1>", _clic)
        b.bind("<Enter>", lambda _e: b.configure(bg=hover) if not (bloqueable and self._ocupado) else None)
        b.bind("<Leave>", lambda _e: b.configure(bg=normal))
        if bloqueable:
            self._bloqueables.append(b)
        return b

    def _colocar(self) -> None:
        """Tamaño y posición iniciales (sin forzar el dibujado, así se puede ocultar antes de mostrarse)."""
        v = self.ventana
        sw, sh = v.winfo_screenwidth(), v.winfo_screenheight()
        ancho = min(self.px(1000), max(self.px(840), sw - 40))
        alto = min(self.px(760), max(self.px(620), sh - 80))
        x = max(0, (sw - ancho) // 2)
        y = max(0, (sh - alto) // 3)
        v.geometry(f"{ancho}x{alto}+{x}+{y}")
        v.lift()

    def _al_redimensionar(self, evento: tk.Event) -> None:
        ancho = max(self.px(300), evento.width - self.px(60))
        for lbl in (self.lbl_aviso, self.lbl_regla, self.lbl_evidencia):
            if int(lbl.cget("wraplength")) != ancho:
                lbl.configure(wraplength=ancho)

    # ----------------------------------------------------------------- Datos
    def _cargar(self) -> None:
        """Lee la ficha del disco (o empieza una vacía) y olvida los cambios sin guardar."""
        ficha, self.error_carga = leer_ficha(self.ruta)
        self.existia = self.ruta.is_file()
        self.ficha = ficha or FichaPersonajes()
        self._editados.clear()
        self._modificado = False
        self._actual = None
        self._originales = {id(p): p.nombre for p in self.ficha.personajes}
        for clave, var in self.vars_reglas.items():
            var.set(bool(self.ficha.reglas.get(clave, True)))
        if self.error_carga:
            log.warning("No se pudo leer %s: %s", self.ruta, self.error_carga)

    def _valores(self, p: Personaje) -> tuple:
        if p.confirmado:
            confirmado = "✔ sí"
        elif id(p) in self._editados:
            confirmado = "✎ al guardar"
        else:
            confirmado = "—"
        return (
            p.nombre,
            "★ protagonista" if p.es_protagonista else p.rol,
            TEXTO_GENERO.get(p.genero, p.genero),
            texto_codigos_alias(p),
            p.apariciones,
            p.menciones,
            f"{round(p.confianza * 100)} %" if p.confianza else "—",
            confirmado,
        )

    def _etiquetas(self, p: Personaje) -> tuple[str, ...]:
        return (f"g_{p.genero}", "prota") if p.es_protagonista else (f"g_{p.genero}",)

    def _clave_orden(self, col: str) -> Callable[[Personaje], object]:
        orden_rol = {r: i for i, r in enumerate(ROLES)}
        orden_genero = {g: i for i, g in enumerate(GENEROS)}
        claves: dict[str, Callable[[Personaje], object]] = {
            "nombre": lambda p: p.nombre.casefold(),
            "rol": lambda p: orden_rol.get(p.rol, 9),
            "genero": lambda p: orden_genero.get(p.genero, 9),
            "codigos": lambda p: texto_codigos_alias(p).casefold(),
            "lineas": lambda p: p.apariciones,
            "menciones": lambda p: p.menciones,
            "confianza": lambda p: p.confianza,
            "confirmado": lambda p: p.confirmado or id(p) in self._editados,
        }
        return claves[col]

    def _poblar(self) -> None:
        """Rellena la tabla conservando la selección (por identidad del personaje)."""
        seleccion = {id(p) for p in self._seleccionados()}
        foco = self._items.get(self.tabla.focus())
        self.tabla.delete(*self.tabla.get_children())
        self._items.clear()
        self._iid_de.clear()
        personajes = list(self.ficha.personajes)
        if self._orden:
            col, inverso = self._orden
            personajes.sort(key=self._clave_orden(col), reverse=inverso)
        for p in personajes:
            iid = self.tabla.insert("", "end", values=self._valores(p), tags=self._etiquetas(p))
            self._items[iid] = p
            self._iid_de[id(p)] = iid
        restaurar = [self._iid_de[i] for i in seleccion if i in self._iid_de]
        if restaurar:
            self.tabla.selection_set(restaurar)
        if foco is not None and id(foco) in self._iid_de:
            self.tabla.focus(self._iid_de[id(foco)])
            self.tabla.see(self._iid_de[id(foco)])
        for col, titulo, _ancho, _ancla in COLUMNAS:
            flecha = ""
            if self._orden and self._orden[0] == col:
                flecha = " ▼" if self._orden[1] else " ▲"
            self.tabla.heading(col, text=titulo + flecha)

    def _refrescar_fila(self, p: Personaje) -> None:
        iid = self._iid_de.get(id(p))
        if iid is not None and self.tabla.exists(iid):
            self.tabla.item(iid, values=self._valores(p), tags=self._etiquetas(p))

    def _seleccionados(self) -> list[Personaje]:
        return [self._items[i] for i in self.tabla.selection() if i in self._items]

    def _personaje_foco(self) -> Personaje | None:
        """El personaje con el foco de la tabla (o el primero seleccionado)."""
        seleccion = self.tabla.selection()
        foco = self.tabla.focus()
        if foco and foco in seleccion:
            return self._items.get(foco)
        return self._items.get(seleccion[0]) if seleccion else None

    def _seleccionar(self, p: Personaje) -> None:
        iid = self._iid_de.get(id(p))
        if iid is None:
            return
        self.tabla.selection_set(iid)
        self.tabla.focus(iid)
        self.tabla.see(iid)
        self._cargar_panel(p)

    def _otro_con_nombre(self, nombre: str, excluir: Personaje) -> Personaje | None:
        """Otro personaje que ya usa ``nombre`` como nombre o alias (sin distinguir mayúsculas)."""
        buscado = nombre.casefold()
        for p in self.ficha.personajes:
            if p is not excluir and buscado in {n.casefold() for n in p.nombres()}:
                return p
        return None

    def _nombre_libre(self, base: str) -> str:
        nombre, n = base, 2
        while any(p.nombre.casefold() == nombre.casefold() for p in self.ficha.personajes):
            nombre, n = f"{base} {n}", n + 1
        return nombre

    def _quitar_otros_protagonistas(self, p: Personaje) -> list[Personaje]:
        """Solo puede haber un protagonista: los demás pasan a 'principal'."""
        degradados = [o for o in self.ficha.personajes if o is not p and o.es_protagonista]
        for o in degradados:
            o.rol = "principal"
            self._refrescar_fila(o)
        return degradados

    def _unico_protagonista(self) -> list[Personaje]:
        """Red de seguridad al guardar: si hay varios protagonistas se queda el marcado en esta
        sesión, luego el confirmado y luego el que más aparece."""
        protas = [p for p in self.ficha.personajes if p.es_protagonista]
        if len(protas) <= 1:
            return []
        protas.sort(key=lambda p: (id(p) not in self._editados, not p.confirmado, -(p.apariciones + p.menciones)))
        for p in protas[1:]:
            p.rol = "principal"
        return protas[1:]

    # ----------------------------------------------------------------- Panel de edición
    def _habilitar_panel(self, activo: bool) -> None:
        estado_ent = "normal" if activo else "disabled"
        for ent in (self.ent_nombre, self.ent_alias, self.ent_codigos, self.ent_desc):
            ent.configure(state=estado_ent)
        for cmb in (self.cmb_rol, self.cmb_genero):
            cmb.configure(state="readonly" if activo else "disabled")
        self.chk_confirmado.configure(state="normal" if activo else "disabled")

    def _cargar_panel(self, p: Personaje | None) -> None:
        self._cargando_panel = True
        try:
            self._actual = p
            if p is None:
                for var in (self.var_nombre, self.var_rol, self.var_genero, self.var_alias, self.var_codigos,
                            self.var_desc):
                    var.set("")
                self.var_confirmado.set(False)
                self.lbl_panel.configure(text="✏️ Selecciona un personaje de la tabla para editarlo")
                self.lbl_evidencia.configure(text=AYUDA_PANEL)
                self._habilitar_panel(False)
                return
            self.var_nombre.set(p.nombre)
            self.var_rol.set(p.rol)
            self.var_genero.set(p.genero)
            self.var_alias.set(", ".join(p.alias))
            self.var_codigos.set(", ".join(p.codigos))
            self.var_desc.set(p.descripcion)
            self.var_confirmado.set(p.confirmado or id(p) in self._editados)
            self.lbl_panel.configure(text=f"✏️ Editando: {p.nombre}")
            pistas = ", ".join(p.evidencia[:10])
            self.lbl_evidencia.configure(text=f"Pistas del análisis: {pistas}" if pistas else AYUDA_PANEL)
            self._habilitar_panel(not self._ocupado)
        finally:
            self._cargando_panel = False

    def _aplicar_desde_boton(self) -> None:
        if self._actual is None:
            self._estado("Selecciona primero un personaje de la tabla.", "aviso")
        elif not self._aplicar_panel():
            self._estado(f"No hay cambios que aplicar en «{self._actual.nombre}».")

    def _aplicar_panel(self, _evento: tk.Event | None = None) -> bool:
        """Pasa lo escrito en el panel al personaje seleccionado. Devuelve True si cambió algo."""
        p = self._actual
        if p is None or self._cargando_panel or self._ocupado or self._cerrada:
            return False
        try:
            nombre = " ".join(self.var_nombre.get().split())
            rol = self.var_rol.get().strip() or p.rol
            genero = normalizar_genero(self.var_genero.get()) if self.var_genero.get().strip() else p.genero
            alias = lista_desde_texto(self.var_alias.get())
            codigos = lista_desde_texto(self.var_codigos.get())
            descripcion = self.var_desc.get().strip()
        except tk.TclError:  # la ventana se está cerrando
            return False
        rol = rol if rol in ROLES else p.rol
        cambios: list[str] = []

        if nombre != p.nombre:
            otro = self._otro_con_nombre(nombre, p) if nombre else None
            if not nombre:
                self._estado(f"El nombre no puede quedar vacío: se mantiene «{p.nombre}».", "error")
                self.var_nombre.set(p.nombre)
            elif otro is not None:
                self._estado(f"«{nombre}» ya es el nombre o un alias de «{otro.nombre}»: se mantiene «{p.nombre}».",
                             "error")
                self.var_nombre.set(p.nombre)
            else:
                anterior, p.nombre = p.nombre, nombre
                cambios.append("nombre")
                # El nombre que venía del juego se conserva como alias: así se le sigue reconociendo
                # en las cajas de nombre del juego y al volver a analizar.
                if (self._originales.get(id(p)) == anterior
                        and anterior.casefold() not in {a.casefold() for a in alias}):
                    alias.insert(0, anterior)
                    self.var_alias.set(", ".join(alias))
        alias = [a for a in alias if a.casefold() != p.nombre.casefold()]

        if alias != p.alias:
            p.alias = alias
            cambios.append("alias")
        if codigos != p.codigos:
            p.codigos = codigos
            cambios.append("códigos")
        if descripcion != p.descripcion:
            p.descripcion = descripcion
            cambios.append("descripción")
        if genero != p.genero:
            p.genero = genero
            cambios.append("género")
        if rol != p.rol:
            if rol == "protagonista":
                self._quitar_otros_protagonistas(p)
            p.rol = rol
            cambios.append("rol")
        if not cambios:
            return False

        self._editados.add(id(p))
        self.var_confirmado.set(True)
        self._refrescar_fila(p)
        self.lbl_panel.configure(text=f"✏️ Editando: {p.nombre}")
        self._marcar_modificado()
        mensaje = f"«{p.nombre}»: {', '.join(cambios)} actualizado (se guardará como confirmado)."
        repetidos = self._codigos_o_alias_repetidos(p)
        if repetidos:
            self._estado(f"{mensaje} Ojo: {repetidos}", "aviso")
        else:
            self._estado(mensaje)
        self._actualizar_aviso()
        return True

    def _codigos_o_alias_repetidos(self, p: Personaje) -> str:
        """Avisa si un código o alias de ``p`` ya lo usa otro personaje (el primero 'ganaría')."""
        avisos = []
        for otro in self.ficha.personajes:
            if otro is p:
                continue
            comunes_cod = set(p.codigos) & set(otro.codigos)
            comunes_ali = {a.casefold() for a in p.alias} & {n.casefold() for n in otro.nombres()}
            if comunes_cod or comunes_ali:
                avisos.append(f"«{otro.nombre}» también usa {', '.join(sorted(comunes_cod | comunes_ali))}")
        return "; ".join(avisos[:3])

    def _al_cambiar_confirmado(self) -> None:
        p = self._actual
        if p is None or self._cargando_panel:
            return
        if self.var_confirmado.get():
            self._editados.add(id(p))
            self._estado(f"«{p.nombre}» se guardará como confirmado.")
        else:
            self._editados.discard(id(p))
            p.confirmado = False
            self._estado(f"«{p.nombre}» ya no está confirmado: un nuevo análisis podrá cambiarlo.")
        self._refrescar_fila(p)
        self._marcar_modificado()
        self._actualizar_aviso()

    def _al_cambiar_regla(self, clave: str) -> None:
        self.ficha.reglas[clave] = bool(self.vars_reglas[clave].get())
        self._marcar_modificado()
        self._actualizar_aviso()

    # ----------------------------------------------------------------- Eventos de la tabla
    def _al_seleccionar(self, _evento: tk.Event | None = None) -> None:
        if self._cargando_panel:
            return
        p = self._personaje_foco()
        if p is self._actual:
            return
        self._aplicar_panel()  # lo escrito en el panel es del personaje anterior
        self._cargar_panel(p)

    def _doble_clic(self, evento: tk.Event) -> str | None:
        if self.tabla.identify_region(evento.x, evento.y) not in ("cell", "tree"):
            return None
        iid = self.tabla.identify_row(evento.y)
        if not iid or iid not in self._items:
            return None
        try:
            indice = int(self.tabla.identify_column(evento.x).lstrip("#")) - 1
        except ValueError:
            indice = 0
        col = COLUMNAS[indice][0] if 0 <= indice < len(COLUMNAS) else "genero"
        self.tabla.selection_set(iid)
        self.tabla.focus(iid)
        self._al_seleccionar()
        if self._ocupado:
            return "break"
        if col == "confirmado":
            self.var_confirmado.set(not self.var_confirmado.get())
            self._al_cambiar_confirmado()
        elif col == "nombre":
            self.ent_nombre.focus_set()
            self.ent_nombre.select_range(0, "end")
        elif col == "codigos":
            self.ent_alias.focus_set()
            self.ent_alias.icursor("end")
        else:
            cmb = self.cmb_rol if col == "rol" else self.cmb_genero
            cmb.focus_set()

            def _desplegar() -> None:  # abre la lista directamente (si Tk lo permite)
                try:
                    cmb.tk.call("ttk::combobox::Post", cmb)
                except tk.TclError:
                    pass

            cmb.after_idle(_desplegar)
        return "break"

    def _ordenar(self, col: str) -> None:
        actual = self._orden
        if actual and actual[0] == col:
            self._orden = (col, not actual[1])
        else:  # los números, de mayor a menor la primera vez
            self._orden = (col, col in ("lineas", "menciones", "confianza", "confirmado"))
        self._poblar()

    # ----------------------------------------------------------------- Acciones
    def anadir(self) -> None:
        """Añade un personaje nuevo (rol 'principal', género desconocido) y lo deja listo para escribir."""
        self._aplicar_panel()
        p = Personaje(nombre=self._nombre_libre("Nuevo personaje"), genero=DESCONOCIDO, rol="principal")
        self._nuevo_personaje(p)
        self._estado("Escribe el nombre y elige el género del nuevo personaje.")

    def empezar_vacia(self) -> None:
        """Ficha vacía: crea solo al protagonista para que el usuario indique nombre y género."""
        if self.ficha.personajes:
            return
        if not self.ficha.titulo:
            self.ficha.titulo = nombre_bonito(self.juego)
        p = Personaje(nombre=self._nombre_libre("Protagonista"), genero=DESCONOCIDO, rol="protagonista")
        self._nuevo_personaje(p)
        self._estado("Escribe el nombre del protagonista y elige su género; después añade a los personajes "
                     "principales con «➕ Añadir personaje».")

    def _nuevo_personaje(self, p: Personaje) -> None:
        self.ficha.personajes.append(p)
        self._editados.add(id(p))
        self._marcar_modificado()
        self._poblar()
        self._seleccionar(p)
        self._actualizar_aviso()
        self.ent_nombre.focus_set()
        self.ent_nombre.select_range(0, "end")

    def eliminar(self) -> None:
        self._aplicar_panel()
        seleccion = self._seleccionados()
        if not seleccion:
            self._estado("Selecciona en la tabla los personajes que quieras quitar.", "aviso")
            return
        nombres = ", ".join(p.nombre for p in seleccion[:6]) + ("…" if len(seleccion) > 6 else "")
        if not messagebox.askyesno(
                "Eliminar personajes",
                f"¿Quitar de la ficha a: {nombres}?\n\nSi vuelves a analizar el juego, el análisis podría "
                "añadirlos otra vez (sin confirmar).", parent=self.ventana):
            return
        quitar = {id(p) for p in seleccion}
        self._cargar_panel(None)
        self.ficha.personajes = [p for p in self.ficha.personajes if id(p) not in quitar]
        self._editados -= quitar
        for i in quitar:
            self._originales.pop(i, None)
        self._marcar_modificado()
        self._poblar()
        self._actualizar_aviso()
        self._estado(f"Eliminados {len(quitar)} personaje(s). Pulsa «💾 Guardar» para conservar el cambio.")

    def marcar_protagonista(self) -> None:
        self._aplicar_panel()
        p = self._personaje_foco()
        if p is None:
            self._estado("Selecciona primero al personaje que es el protagonista.", "aviso")
            return
        degradados = self._quitar_otros_protagonistas(p)
        p.rol = "protagonista"
        self._editados.add(id(p))
        self._refrescar_fila(p)
        self._cargar_panel(p)
        self._marcar_modificado()
        self._actualizar_aviso()
        mensaje = f"★ «{p.nombre}» es ahora el protagonista."
        if degradados:
            mensaje += f" {', '.join(o.nombre for o in degradados)} pasa(n) a «principal»."
        if p.genero == DESCONOCIDO:
            self._estado(mensaje + " Indica su género en el panel.", "aviso")
            self.cmb_genero.focus_set()
        else:
            self._estado(mensaje)

    def confirmar_seleccion(self) -> None:
        """Marca como revisados los personajes seleccionados (sin cambiar nada más)."""
        self._aplicar_panel()
        seleccion = self._seleccionados()
        if not seleccion:
            self._estado("Selecciona en la tabla los personajes que ya has revisado.", "aviso")
            return
        for p in seleccion:
            self._editados.add(id(p))
            self._refrescar_fila(p)
        if self._actual is not None and id(self._actual) in self._editados:
            self.var_confirmado.set(True)
        self._marcar_modificado()
        self._actualizar_aviso()
        desconocidos = [p.nombre for p in seleccion if p.genero == DESCONOCIDO]
        mensaje = f"{len(seleccion)} personaje(s) se guardarán como confirmados."
        if desconocidos:
            self._estado(f"{mensaje} Ojo: {', '.join(desconocidos[:5])} tiene(n) género desconocido "
                         "(la IA no aplicará concordancia para ellos).", "aviso")
        else:
            self._estado(mensaje)

    def guardar(self) -> bool:
        """Guarda la ficha (los personajes editados quedan ``confirmado: true``). Devuelve True si lo logra."""
        if self._ocupado:
            self._estado("Espera a que termine el análisis para guardar.", "aviso")
            return False
        self._aplicar_panel()
        notas: list[str] = []
        degradados = self._unico_protagonista()
        if degradados:
            notas.append(f"solo puede haber un protagonista: {', '.join(p.nombre for p in degradados)} "
                         "pasa(n) a «principal»")
        for p in self.ficha.personajes:
            if id(p) in self._editados:
                p.confirmado = True
        self.ficha.reindexar()
        try:
            if self.error_carga and self.ruta.is_file():
                copia = self.ruta.with_name(self.ruta.name + ".danado")
                shutil.copy2(self.ruta, copia)
                notas.append(f"copia del archivo dañado en {copia.name}")
            self._crear_perfil_si_falta()
            self.ficha.guardar(self.ruta)
        except OSError as e:
            log.error("No se pudo guardar %s: %s", self.ruta, e)
            messagebox.showerror("No se pudo guardar", f"No se pudo escribir {self.ruta}:\n\n{e}",
                                 parent=self.ventana)
            return False
        log.info("Ficha de personajes guardada en %s (%s)", self.ruta, self.ficha.resumen())
        self.existia = True
        self.error_carga = ""
        self._editados.clear()
        self._modificado = False
        self._originales = {id(p): p.nombre for p in self.ficha.personajes}
        self._poblar()
        self._cargar_panel(self._personaje_foco())
        self._actualizar_aviso()
        self._actualizar_titulo()
        self._estado("✔ Guardado: " + self.ficha.resumen() + (". " + "; ".join(notas) + "." if notas else "."),
                     "ok")
        if self.al_guardar is not None:
            try:
                self.al_guardar(self.ficha)
            except Exception:  # un fallo del aviso no debe deshacer el guardado
                log.exception("Error al avisar del guardado de la ficha")
        return True

    def _crear_perfil_si_falta(self) -> None:
        """Si el juego aún no tiene carpeta en workspace/, crea su perfil base (ajustes, glosario,
        contexto) igual que haría la primera traducción, pero SIN lanzar el analizador."""
        if self.ruta.parent.is_dir():
            return
        try:
            if "analizar" not in inspect.signature(config.inicializar_perfil_nuevo).parameters:
                return  # versión antigua: escribiría "Hombre por defecto" en contexto.txt
            config.inicializar_perfil_nuevo(self.juego, self.ruta_juego, analizar=False)
        except Exception as e:  # el perfil base es opcional: la ficha se guarda igualmente
            log.warning("No se pudo crear el perfil base de %s (%s); se guarda solo la ficha.", self.juego, e)

    def recargar(self, preguntar: bool = True) -> bool:
        """Vuelve a leer la ficha del disco (p. ej. tras un análisis lanzado desde el Centro de Control)."""
        if self._ocupado or self._cerrada:
            return False
        if self._modificado and preguntar and not messagebox.askyesno(
                "Recargar la ficha",
                "La ficha de personajes ha cambiado en el disco (por ejemplo, tras un nuevo análisis).\n\n"
                "¿Descartar tus cambios sin guardar y recargarla?", parent=self.ventana):
            return False
        self._cargar()
        self._poblar()
        self._cargar_panel(None)
        self._actualizar_aviso()
        self._actualizar_titulo()
        self._estado(f"Ficha recargada: {self.ficha.resumen()}." if self.ficha.personajes
                     else "Ficha recargada desde el disco.")
        return True

    def mostrar(self) -> None:
        if self._cerrada:
            return
        self.ventana.deiconify()
        self.ventana.lift()
        self.ventana.focus_force()

    def cerrar(self) -> None:
        if self._cerrada:
            return
        self._aplicar_panel()
        if self._ocupado:
            if not messagebox.askyesno("Análisis en curso", "Se está analizando el juego.\n\n"
                                       "¿Detener el análisis y cerrar el editor?", parent=self.ventana):
                return
            self._detener_analisis()
        if self._modificado:
            respuesta = messagebox.askyesnocancel(
                "Cambios sin guardar", "¿Guardar los cambios de la ficha de personajes antes de cerrar?",
                parent=self.ventana)
            if respuesta is None or (respuesta and not self.guardar()):
                return
        self._cerrada = True
        try:
            self.ventana.destroy()
        except tk.TclError:
            pass
        if self.al_cerrar is not None:
            try:
                self.al_cerrar()
            except Exception:
                log.exception("Error al avisar del cierre del editor de personajes")

    # ----------------------------------------------------------------- Análisis (Paso 0)
    def volver_a_analizar(self) -> None:
        """Lanza ``0_analizar_juego.py`` en segundo plano y recarga la ficha al terminar."""
        if self._ocupado:
            return
        if not SCRIPT_ANALIZADOR.exists():
            messagebox.showerror("Falta el analizador",
                                 f"No se encuentra {SCRIPT_ANALIZADOR.name} en {RAIZ}.", parent=self.ventana)
            return
        self._aplicar_panel()
        ruta = self._ruta_para_analizar()
        if ruta is None:
            return
        if self._modificado:
            respuesta = messagebox.askyesnocancel(
                "Cambios sin guardar",
                "Tienes cambios sin guardar.\n\n¿Guardarlos antes de volver a analizar?\n"
                "(Lo que confirmes se respeta: el análisis no lo sobrescribe.)\n\n"
                "   • Sí: guardar y analizar.\n   • No: descartar los cambios y analizar.\n"
                "   • Cancelar: no hacer nada.", parent=self.ventana)
            if respuesta is None or (respuesta and not self.guardar()):
                return
        cmd = [str(obtener_python_ejecutable()), str(SCRIPT_ANALIZADOR), "--ruta", str(ruta), "--juego",
               str(self.juego)]
        log.info("Analizando personajes: %s", " ".join(cmd))
        self._salida_analisis = []
        self._poner_ocupado(True)
        self._estado(f"🔎 Analizando {ruta.name}… (puede tardar un poco en juegos grandes)", "info")
        threading.Thread(target=self._hilo_analisis, args=(cmd,), daemon=True).start()
        self.ventana.after(150, self._sondear_analisis)

    def _ruta_para_analizar(self) -> Path | None:
        if self.ruta_juego and self.ruta_juego.is_dir():
            return self.ruta_juego
        ultima = _ultima_ruta_gui()
        if ultima and ultima.is_dir() and config.resolver_juego(None, ultima) == self.juego:
            self.ruta_juego = ultima
            return ultima
        inicial = ultima.parent if ultima and ultima.parent.is_dir() else Path.home()
        carpeta = filedialog.askdirectory(
            parent=self.ventana, initialdir=str(inicial) if inicial.is_dir() else None,
            title=f"Carpeta del juego «{nombre_bonito(self.juego)}» para analizarlo")
        if not carpeta:
            return None
        elegida = Path(carpeta)
        perfil = config.resolver_juego(None, elegida)
        if perfil != self.juego and not messagebox.askyesno(
                "¿Otro juego?",
                f"La carpeta elegida corresponde al perfil «{perfil}», pero estás editando «{self.juego}».\n\n"
                f"¿Analizarla igualmente y guardar el resultado en la ficha de «{self.juego}»?",
                parent=self.ventana):
            return None
        self.ruta_juego = elegida
        return elegida

    def _hilo_analisis(self, cmd: list[str]) -> None:
        """Hilo secundario: ejecuta el analizador y pasa su salida a la cola (Tk solo se toca en el principal)."""
        try:
            entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
            self._proceso = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1, cwd=str(RAIZ), env=entorno,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert self._proceso.stdout is not None
            for linea in self._proceso.stdout:
                self._cola.put(("linea", linea.rstrip("\r\n")))
            self._cola.put(("fin", self._proceso.wait()))
        except Exception as e:
            self._cola.put(("error", str(e)))

    def _sondear_analisis(self) -> None:
        if self._cerrada or not self.ventana.winfo_exists():
            return
        try:
            while True:
                tipo, dato = self._cola.get_nowait()
                if tipo == "linea":
                    texto = str(dato)
                    self._salida_analisis.append(texto)
                    if texto.strip():
                        self._estado(f"🔎 Analizando… {_recortar(texto, 110)}", "info")
                elif tipo == "fin":
                    self._fin_analisis(dato == 0, f"código de salida {dato}")
                    return
                else:
                    self._fin_analisis(False, str(dato))
                    return
        except queue.Empty:
            pass
        self.ventana.after(150, self._sondear_analisis)

    def _fin_analisis(self, ok: bool, detalle: str) -> None:
        self._proceso = None
        self._poner_ocupado(False)
        if self._salida_analisis and not self.btn_informe.winfo_ismapped():
            self.btn_informe.pack(side="left")
        if not ok:
            ultimas = "\n".join(self._salida_analisis[-12:]) or "(sin salida)"
            self._estado(f"✖ El análisis falló ({detalle}). Pulsa «📄 Ver informe del análisis».", "error")
            messagebox.showerror("El análisis falló",
                                 f"0_analizar_juego.py terminó con error ({detalle}).\n\nÚltimas líneas:\n{ultimas}",
                                 parent=self.ventana)
            return
        self._cargar()
        self._poblar()
        self._cargar_panel(None)
        self._actualizar_aviso()
        self._actualizar_titulo()
        self._estado(f"✔ Análisis terminado: {self.ficha.resumen()}. Revisa sobre todo al protagonista.", "ok")
        if self.al_guardar is not None:  # la ficha del disco ha cambiado
            try:
                self.al_guardar(self.ficha)
            except Exception:
                log.exception("Error al avisar del nuevo análisis")

    def _detener_analisis(self) -> None:
        proceso = self._proceso
        if proceso is not None and proceso.poll() is None:
            try:
                proceso.kill()
            except OSError:
                pass
        self._poner_ocupado(False)

    def _poner_ocupado(self, ocupado: bool) -> None:
        self._ocupado = ocupado
        for b in self._bloqueables:
            b.configure(fg=C_SUAVE if ocupado else C_TEXTO, cursor="watch" if ocupado else "hand2")
        self._habilitar_panel(not ocupado and self._actual is not None)

    def ver_informe(self) -> None:
        """Muestra la salida completa del último análisis (informe y avisos del Paso 0)."""
        if not self._salida_analisis:
            self._estado("Todavía no se ha analizado el juego desde esta ventana.")
            return
        top = tk.Toplevel(self.ventana)
        top.title("Informe del análisis de personajes")
        top.configure(bg=C_FONDO)
        top.geometry(f"{self.px(860)}x{self.px(520)}")
        texto = tk.Text(top, bg="#070a13", fg="#e2e8f0", font=("Cascadia Mono", 9), wrap="none", relief="flat")
        barra = ttk.Scrollbar(top, orient="vertical", command=texto.yview)
        texto.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        texto.pack(side="left", fill="both", expand=True, padx=self.px(6), pady=self.px(6))
        texto.insert("1.0", "\n".join(self._salida_analisis))
        texto.configure(state="disabled")

    # ----------------------------------------------------------------- Avisos y estado
    def _avisos(self) -> tuple[list[str], str, bool]:
        """(líneas, nivel, mostrar botones de analizar/empezar) del aviso superior."""
        if self.error_carga:
            return ([f"No se pudo leer {ARCHIVO_PERSONAJES}: {_recortar(self.error_carga, 180)}",
                     "Si guardas, el archivo dañado se conserva como copia (.danado) antes de sobrescribirlo."],
                    "error", False)
        if not self.ficha.personajes:
            if self.existia:
                return (["La ficha de personajes está vacía. Analiza el juego o añade a mano al protagonista "
                         "y a los personajes principales."], "info", True)
            return (["Este juego todavía no tiene ficha de personajes. Analízalo (recomendado) o empieza una "
                     "ficha vacía y añade a mano al protagonista y a los personajes principales."], "info", True)
        lineas: list[str] = []
        prota = self.ficha.protagonista()
        if prota is None:
            lineas.append("⚠ No hay ningún protagonista: selecciónalo en la tabla y pulsa «★ Marcar protagonista».")
        elif prota.genero == DESCONOCIDO:
            lineas.append(f"⚠ El protagonista ({prota.nombre}) no tiene género: indícalo para que la IA no se "
                          "equivoque con los adjetivos («cansado» / «cansada»).")
        elif not (prota.confirmado or id(prota) in self._editados):
            lineas.append(f"⚠ El protagonista ({prota.nombre}, {prota.genero}) se detectó automáticamente: "
                          "compruébalo y confírmalo.")
        pendientes = [p for p in self.ficha.pendientes_de_revisar() if p is not prota and id(p) not in self._editados]
        if pendientes:
            nombres = ", ".join(f"{p.nombre} ({p.genero})" for p in pendientes[:6])
            lineas.append(f"⚠ {len(pendientes)} personaje(s) principal(es) por revisar (género desconocido o "
                          f"poco fiable): {nombres}{'…' if len(pendientes) > 6 else ''}.")
        return lineas, ("aviso" if lineas else ""), False

    def _actualizar_aviso(self) -> None:
        lineas, nivel, con_botones = self._avisos()
        if not lineas:
            self.aviso.pack_forget()
        else:
            fondo, borde, color = COLORES_AVISO[nivel]
            self.aviso.configure(bg=fondo, highlightbackground=borde)
            self.lbl_aviso.configure(text="\n".join(lineas), bg=fondo, fg=color)
            self.fila_aviso.configure(bg=fondo)
            if con_botones:
                self.fila_aviso.pack(fill="x", pady=(self.px(8), 0))
            else:
                self.fila_aviso.pack_forget()
            self.aviso.pack(fill="x", pady=(self.px(10), 0), after=self.cab)
        regla = self.ficha.regla_protagonista()
        if regla:
            self.lbl_regla.configure(text=f"Regla que recibirá la IA: «{regla}»", fg=C_SUAVE)
        else:
            self.lbl_regla.configure(text="La IA todavía no recibirá ninguna regla sobre el protagonista: "
                                          "márcalo e indica su género.", fg=C_AMBAR)
        total = len(self.ficha.personajes)
        con_genero = len(self.ficha.con_genero_conocido())
        self.lbl_contador.configure(text=f"Personajes ({total}, {con_genero} con género)" if total else "Personajes")
        self.btn_analizar.configure(text="🔎 Volver a analizar" if self.existia else "🔎 Analizar el juego")

    def _actualizar_titulo(self) -> None:
        titulo = self.ficha.titulo or nombre_bonito(self.juego)
        marca = "● " if self._modificado else ""
        self.ventana.title(f"{marca}Personajes — {titulo}")
        self.lbl_titulo.configure(text=f"🧑‍🤝‍🧑 Personajes y contexto · {titulo}")
        partes = [str(self.ruta)]
        if self.ficha.motor:
            partes.append(f"motor: {self.ficha.motor}")
        if not self.existia:
            partes.append("aún no existe")
        if self._modificado:
            partes.append("cambios sin guardar")
        self.lbl_sub.configure(text="  ·  ".join(partes))

    def _marcar_modificado(self) -> None:
        if not self._modificado:
            self._modificado = True
            self._actualizar_titulo()

    def _estado(self, texto: str, nivel: str = "info") -> None:
        if not self._cerrada:
            self.lbl_estado.configure(text=texto, fg=COLORES_ESTADO.get(nivel, C_SUAVE))


# --------------------------------------------------------------------------- API pública
def abrir_editor(master: tk.Misc | None, juego: str | None, ruta_juego: str | Path | None = None, *,
                 al_guardar: Callable[[FichaPersonajes], None] | None = None,
                 al_cerrar: Callable[[], None] | None = None) -> tk.Toplevel:
    """Abre el editor de la ficha de personajes de ``juego`` y devuelve su ventana.

    ``juego`` se resuelve igual que en el resto del proyecto (``config.resolver_juego``); si es None
    se deduce de ``ruta_juego``. La ventana lleva el editor en ``ventana.editor`` (con ``recargar()``
    y ``mostrar()``). ``al_guardar(ficha)`` se llama tras guardar o volver a analizar y
    ``al_cerrar()`` al cerrar la ventana.
    """
    resuelto = config.resolver_juego(juego, ruta_juego)
    if not resuelto:
        raise ValueError("Indica el juego (perfil de workspace/) o la carpeta del juego.")
    editor = EditorPersonajes(master, resuelto, ruta_juego, al_guardar=al_guardar, al_cerrar=al_cerrar)
    return editor.ventana


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Editor de la ficha de personajes (protagonista, géneros, alias y códigos) de un juego.")
    parser.add_argument("--juego", help="Perfil en workspace/ (p. ej. mi_juego o \"Mi Juego\")")
    parser.add_argument("--ruta", help="Carpeta del juego (el perfil se deduce de su nombre)")
    parser.add_argument("--debug", action="store_true", help="Mostrar mensajes de depuración")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    if not args.juego and not args.ruta:
        parser.error("indica --juego o --ruta")
    if args.ruta and not Path(args.ruta).is_dir():
        parser.error(f"no existe la carpeta del juego: {args.ruta}")
    juego = config.resolver_juego(args.juego, args.ruta)
    if not juego:
        parser.error("no se pudo deducir el perfil del juego")

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TraductorIA.EditorPersonajes")
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.withdraw()
    abrir_editor(root, juego, args.ruta, al_cerrar=root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
