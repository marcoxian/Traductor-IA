"""Q1: preparar, instalar y deshacer la copia corregida de XUnity sin tocar nunca workspace/ ni juegos reales."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas_extra"))

import instalar_correccion as ic  # noqa: E402
from traductor import config  # noqa: E402


class TestInstalarCorreccion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        parche = mock.patch.object(config, "DIR_WORKSPACE", self.tmp / "workspace")
        parche.start()
        self.addCleanup(parche.stop)
        (self.tmp / "workspace" / "juego_x").mkdir(parents=True)
        self.juego = self.tmp / "Juego X"
        self.txt = self.juego / "BepInEx" / "Translation" / "es" / "Text" / ic.NOMBRE
        self.txt.parent.mkdir(parents=True)
        self.txt.write_bytes(b"I'm tired.=Estoy cansado.\r\nHello.=Hola.\r\n")
        self.abiertos: list[str] = []
        parche = mock.patch.object(ic, "procesos_del_juego", lambda ruta: list(self.abiertos))
        parche.start()
        self.addCleanup(parche.stop)

    def _preparar_y_corregir(self) -> Path:
        copia = ic.preparar(self.juego, "juego_x")
        copia.write_bytes(b"I'm tired.=Estoy cansada.\r\nHello.=Hola.\r\n")  # lo que haría la auditoría
        return copia

    def test_instalar_y_deshacer(self):
        copia = self._preparar_y_corregir()
        self.assertEqual(ic.estado(self.juego, "juego_x").texto(), "Hay una copia corregida lista para instalar.")
        self.assertIn("Instalada", ic.instalar(self.juego, "juego_x"))
        self.assertEqual(self.txt.read_bytes(), copia.read_bytes())
        self.assertTrue(ic.estado(self.juego, "juego_x").instalada)
        self.assertIn("ya estaba instalada", ic.instalar(self.juego, "juego_x"))
        self.assertIn("original", ic.deshacer(self.juego, "juego_x"))
        self.assertEqual(self.txt.read_bytes(), b"I'm tired.=Estoy cansado.\r\nHello.=Hola.\r\n")
        self.assertIn("ya tiene el archivo original", ic.deshacer(self.juego, "juego_x"))

    def test_no_instala_con_el_juego_abierto(self):
        self._preparar_y_corregir()
        self.abiertos = ["JuegoX.exe"]
        with self.assertRaises(ic.ErrorInstalacion) as e:
            ic.instalar(self.juego, "juego_x")
        self.assertIn("JuegoX.exe", str(e.exception))
        self.assertIn(b"Estoy cansado.", self.txt.read_bytes())  # no se ha tocado

    def test_no_pisa_frases_nuevas_del_juego(self):
        self._preparar_y_corregir()
        self.txt.write_bytes(self.txt.read_bytes() + b"Bye.=Adios.\r\n")  # el juego guardó una frase nueva
        with self.assertRaises(ic.ErrorInstalacion):
            ic.instalar(self.juego, "juego_x")
        self.assertIn(b"Bye.=Adios.", self.txt.read_bytes())

    def test_no_deshace_si_el_juego_cambio_tras_instalar(self):
        self._preparar_y_corregir()
        ic.instalar(self.juego, "juego_x")
        self.txt.write_bytes(self.txt.read_bytes() + b"Bye.=Adios.\r\n")
        with self.assertRaises(ic.ErrorInstalacion):
            ic.deshacer(self.juego, "juego_x")
        self.assertIn(b"Bye.=Adios.", self.txt.read_bytes())

    def test_copia_sin_correcciones_y_sin_copia(self):
        with self.assertRaises(ic.ErrorInstalacion):
            ic.instalar(self.juego, "juego_x")  # aún no hay copia
        ic.preparar(self.juego, "juego_x")
        self.assertIn("no tiene ninguna corrección", ic.instalar(self.juego, "juego_x"))

    def test_juego_sin_xunity(self):
        otro = self.tmp / "Otro"
        otro.mkdir()
        with self.assertRaises(ic.ErrorInstalacion):
            ic.preparar(otro, "juego_x")
        self.assertEqual(ic.estado(otro, "juego_x").texto(), "Este juego no tiene archivo de traducciones de XUnity.")


if __name__ == "__main__":
    unittest.main()
