"""Pruebas del motor Ren'Py (traductor/motores/renpy.py): rellenar game/tl/<idioma>/*.rpy."""
from __future__ import annotations

import codecs
import shutil
import tempfile
import unittest
from pathlib import Path

from traductor.motores.detector import detectar_motor
from traductor.motores.renpy import InyectorRenPy, ajustar_porcentajes, buscar_pendientes, escapar, leer_cadenas
from traductor.personajes import FichaPersonajes, Personaje

TL = '''# TODO: Translation updated at 2026-11-04 10:00

# game/script.rpy:10
translate spanish start_a1b2c3d4:

    # m "Aah! I'm so tired."
    m "Aah! I'm so tired."

# game/script.rpy:12
translate spanish start_b2c3d4e5:

    # voice "audio/mia01.ogg"
    # m happy "Line one.\\nLine two."
    voice "audio/mia01.ogg"
    m happy "Line one.\\nLine two." with dissolve

# game/script.rpy:14
translate spanish start_c3d4e5f6:

    #"You run upstairs as fast as you can..."
    n "You run upstairs as fast as you can..."

# game/script.rpy:16
translate spanish start_d4e5f6a7:

    # mc "She said \\"hi\\" to me."
    mc "Ya traducido."

# game/script.rpy:18
translate spanish start_e5f6a7b8:

    # "Eileen" "Hello there."
    "Eileen" "Hello there."

# game/script.rpy:20
translate french start_f6a7b8c9:

    # m "Bonjour?"
    m "Bonjour?"

translate spanish strings:

    # game/screens.rpy:100
    old "Start"
    new "Start"

    old "Load"
    new "Cargar"

    old "Quit game"
    new ""

    old "{b}[points]{/b}"
    new "{b}[points]{/b}"
'''


class _Traductor:
    """Traductor falso: 'ES<texto>' y guarda lo que le llega."""

    def __init__(self):
        self.recibido = []
        self.infos = []
        self.perfil = None

    def traducir_textos(self, textos, info=None):
        self.recibido += list(textos)
        self.infos += list(info or [None] * len(textos))
        return [f"ES<{t}>" for t in textos]


class TestRenPy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tl = self.tmp / "game" / "tl" / "spanish"
        self.tl.mkdir(parents=True)
        (self.tmp / "game" / "script.rpy").write_text('define m = Character("Mia")\n', encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_buscar_pendientes(self):
        pend = buscar_pendientes(TL.splitlines(keepends=True), "spanish")
        textos = [p.original for p in pend]
        self.assertEqual(textos, ["Aah! I'm so tired.", "Line one.\\nLine two.",
                                  "You run upstairs as fast as you can...", "Hello there.", "Start", "Quit game"])
        por_texto = {p.original: p for p in pend}
        self.assertEqual(por_texto["Aah! I'm so tired."].info().codigo, "renpy:m")
        self.assertEqual(por_texto["Line one.\\nLine two."].info().codigo, "renpy:m")  # con atributo 'happy'
        # "n" puede ser un personaje (define n = Character("Nora")): se pasa como código y decide la ficha
        self.assertEqual(por_texto["You run upstairs as fast as you can..."].info().codigo, "renpy:n")
        self.assertEqual(por_texto["Hello there."].info().hablante, "Eileen")           # hablante como cadena
        self.assertIsNone(por_texto["Start"].info())                                     # interfaz

    def test_n_es_narrador_o_personaje_segun_la_ficha(self):
        from traductor.personajes import resolver_linea
        pend = {p.original: p for p in buscar_pendientes(TL.splitlines(keepends=True), "spanish")}
        info = pend["You run upstairs as fast as you can..."].info()
        sin_n = FichaPersonajes([Personaje("Mia", "mujer", "principal", codigos=["renpy:m"])])
        self.assertIsNone(resolver_linea(sin_n, "You run upstairs.", info).hablante)   # narrador
        con_n = FichaPersonajes([Personaje("Nora", "mujer", "principal", codigos=["renpy:n"])])
        self.assertEqual(resolver_linea(con_n, "You run upstairs.", info).hablante.nombre, "Nora")
        # "narrator" sí es siempre el narrador
        narr = buscar_pendientes(['translate spanish x:\n', '    # narrator "Hi."\n', '    narrator "Hi."\n'],
                                 "spanish")
        self.assertIsNone(narr[0].info())

    def test_leer_cadenas_incluye_lo_traducido(self):
        cadenas = leer_cadenas(TL.splitlines(keepends=True), "spanish")
        por_texto = {c.original: c for c in cadenas}
        self.assertEqual(por_texto['She said \\"hi\\" to me.'].actual, "Ya traducido.")
        self.assertEqual(por_texto['She said \\"hi\\" to me.'].quien, "mc")
        self.assertEqual(por_texto["Load"].actual, "Cargar")
        self.assertNotIn("Bonjour?", por_texto)                                          # otro idioma

    def test_procesar_rellena_y_es_idempotente(self):
        ruta = self.tl / "script.rpy"
        ruta.write_bytes(codecs.BOM_UTF8 + TL.replace("\n", "\r\n").encode("utf-8"))
        falso = _Traductor()
        escritas = InyectorRenPy(self.tmp, falso).procesar()
        self.assertEqual(escritas, 6)
        datos = ruta.read_bytes()
        self.assertTrue(datos.startswith(codecs.BOM_UTF8))
        texto = datos[3:].decode("utf-8")
        self.assertNotIn("\n", texto.replace("\r\n", ""))  # los saltos \r\n se conservan
        self.assertIn('    m "ES<Aah! I\'m so tired.>"\r\n', texto)
        self.assertIn('    m happy "ES<Line one.\\nLine two.>" with dissolve\r\n', texto)  # \n reinsertado
        self.assertIn('    voice "audio/mia01.ogg"\r\n', texto)                               # intacto
        self.assertIn('    mc "Ya traducido."', texto)                                         # ya estaba traducido
        self.assertIn('    "Eileen" "ES<Hello there.>"', texto)
        self.assertIn('    m "Bonjour?"', texto)                                               # otro idioma: no
        self.assertIn('    new "ES<Start>"', texto)
        self.assertIn('    new "Cargar"', texto)
        self.assertIn('    new "ES<Quit game>"', texto)
        self.assertIn('    new "{b}[points]{/b}"', texto)  # sin texto visible: no se traduce
        self.assertTrue(ruta.with_name("script.rpy.original").exists())
        self.assertEqual(falso.recibido[1], "Line one. Line two.")  # el modelo recibe la frase entera
        # Segunda pasada: nada pendiente
        self.assertEqual(InyectorRenPy(self.tmp, _Traductor()).procesar(), 0)

    def test_avisa_al_monitor(self):
        # El monitor recibe el total de frases y de archivos, el archivo actual y el avance.
        (self.tl / "script.rpy").write_text(TL, encoding="utf-8")
        (self.tl / "vacio.rpy").write_text("translate spanish strings:\n\n    old \"Hola\"\n    new \"Hola mundo\"\n",
                                           encoding="utf-8")

        class _Progreso:
            def __init__(self):
                self.eventos = []

            def definir_totales(self, frases, archivos):
                self.eventos.append(("totales", frases, archivos))

            def inicio_archivo(self, nombre, indice, n):
                self.eventos.append(("inicio", nombre, indice, n))

            def avance_archivo(self, hechas):
                self.eventos.append(("avance", hechas))

            def fin_archivo(self):
                self.eventos.append(("fin",))

        falso = _Traductor()
        falso.progreso = _Progreso()
        InyectorRenPy(self.tmp, falso, tam_bloque=4).procesar()
        self.assertEqual(falso.progreso.eventos, [
            ("totales", 6, 1),                    # "vacio.rpy" no tiene nada pendiente: no cuenta
            ("inicio", "script.rpy", 1, 6),
            ("avance", 4), ("avance", 6),
            ("fin",),
        ])

    def test_idioma_con_mayuscula(self):
        # Carpeta "Spanish" junto a otro idioma y bloques "translate Spanish": se traduce igual.
        shutil.rmtree(self.tl)
        tl = self.tmp / "game" / "tl" / "Spanish"
        tl.mkdir(parents=True)
        (self.tmp / "game" / "tl" / "French").mkdir()
        (tl / "script.rpy").write_text(TL.replace("translate spanish", "translate Spanish"), encoding="utf-8")
        inyector = InyectorRenPy(self.tmp, _Traductor())
        self.assertEqual(inyector.carpeta_tl().name, "Spanish")
        self.assertEqual(inyector.procesar(), 6)

    def test_escapar_comillas(self):
        self.assertEqual(escapar('Dijo "hola".'), 'Dijo \\"hola\\".')
        self.assertEqual(escapar('Ya \\"escapada\\"'), 'Ya \\"escapada\\"')

    def test_escapar_saltos_reales(self):
        """Un salto real deja la cadena abierta y Ren'Py no arranca ("Could not parse string")."""
        self.assertEqual(escapar("{i}Seguirá...{/i}\nNota"), "{i}Seguirá...{/i}\\nNota")
        self.assertEqual(escapar("Uno\r\nDos"), "Uno\\nDos")
        self.assertEqual(escapar("Ya \\nescrito"), "Ya \\nescrito")

    def test_ajustar_porcentajes(self):
        """'10%%' en inglés: la traducción también debe doblar el signo, o Ren'Py lo lee como código."""
        self.assertEqual(ajustar_porcentajes("Pay a 10%% fee.", "Paga un 10% de recargo."), "Paga un 10%% de recargo.")
        self.assertEqual(ajustar_porcentajes("Pay a 10%% fee.", "Paga un 10%% de recargo."), "Paga un 10%% de recargo.")
        self.assertEqual(ajustar_porcentajes("Pay 10% now.", "Paga 10% ya."), "Paga 10% ya.")
        self.assertEqual(ajustar_porcentajes("Get 5 percent equity.", "Consigue un 5 % de capital."),
                         "Consigue un 5 %% de capital.")
        self.assertEqual(ajustar_porcentajes("%(name)s has 10%%.", "%(name)s tiene 10%."), "%(name)s tiene 10%.")

    def test_sin_carpeta_tl(self):
        shutil.rmtree(self.tmp / "game" / "tl")
        self.assertEqual(InyectorRenPy(self.tmp, _Traductor()).procesar(), 0)

    def test_detector(self):
        self.assertEqual(detectar_motor(self.tmp), "RenPy")

    def test_codigo_renpy_solo_exacto(self):
        ficha = FichaPersonajes([Personaje("Reda", "mujer", "principal", codigos=["Re"]),
                                 Personaje("Mia", "mujer", "principal", codigos=["renpy:m"])])
        self.assertEqual(ficha.por_codigo("renpy:m").nombre, "Mia")
        self.assertIsNone(ficha.por_codigo("renpy:x"))      # antes caía en el código de hablante 'Re'
        self.assertEqual(ficha.por_codigo("ReFrOp").nombre, "Reda")


if __name__ == "__main__":
    unittest.main()
