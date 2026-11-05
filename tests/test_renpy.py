"""Pruebas del motor Ren'Py (traductor/motores/renpy.py): rellenar game/tl/<idioma>/*.rpy."""
from __future__ import annotations

import codecs
import shutil
import tempfile
import unittest
from pathlib import Path

from traductor.motores.detector import detectar_motor
from traductor.motores.renpy import InyectorRenPy, buscar_pendientes, escapar
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
        self.assertIsNone(por_texto["You run upstairs as fast as you can..."].info())   # narrador
        self.assertEqual(por_texto["Hello there."].info().hablante, "Eileen")           # hablante como cadena
        self.assertIsNone(por_texto["Start"].info())                                     # interfaz

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

    def test_escapar_comillas(self):
        self.assertEqual(escapar('Dijo "hola".'), 'Dijo \\"hola\\".')
        self.assertEqual(escapar('Ya \\"escapada\\"'), 'Ya \\"escapada\\"')

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
