"""Pruebas del estado de progreso compartido (traductor/progreso.py)."""
import json
import tempfile
import unittest
from pathlib import Path

from traductor.progreso import EstadoProgreso, leer_progreso


class TestEstadoProgreso(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / "progreso_actual.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ciclo_completo(self):
        p = EstadoProgreso("mi_juego", "IA_Traductora", "turbo", ruta=self.ruta)
        self.assertEqual(leer_progreso(self.ruta)["estado"], "preparando")

        p.definir_totales(frases=100, archivos=2)
        p.inicio_archivo("Map001.json", 1, 40)
        p.avance_archivo(20)
        self.assertAlmostEqual(p.porcentaje(), 20.0)
        p.fin_archivo()
        self.assertEqual(p.frases_hechas, 40)
        self.assertEqual(p.archivos_hechos, 1)

        p.inicio_archivo("Map002.json", 2, 60)
        p.avance_archivo(30)
        self.assertAlmostEqual(p.porcentaje(), 70.0)
        p.finalizar(cache=10)

        datos = leer_progreso(self.ruta)
        self.assertEqual(datos["estado"], "completado")
        self.assertEqual(datos["porcentaje"], 100.0)
        self.assertEqual(datos["archivos_hechos"], 2)

    def test_nunca_marca_100_antes_de_terminar(self):
        p = EstadoProgreso("j", "m", "seguro", ruta=self.ruta)
        p.definir_totales(frases=10, archivos=1)
        p.inicio_archivo("A.json", 1, 10)
        p.avance_archivo(10)
        self.assertLess(p.porcentaje(), 100.0)

    def test_ultimas_frases_mas_reciente_primero(self):
        p = EstadoProgreso("j", "m", "turbo", ruta=self.ruta)
        for i in range(12):
            p.frase_nueva(f"frase {i}")
        p.guardar(forzar=True)
        frases = json.loads(self.ruta.read_text(encoding="utf-8"))["ultimas_frases"]
        self.assertEqual(len(frases), 8)
        self.assertEqual(frases[0]["texto"], "frase 11")
        self.assertEqual(frases[0]["id"], 12)

    def test_error_y_detenido(self):
        p = EstadoProgreso("j", "m", "turbo", ruta=self.ruta)
        p.fallo("Ollama no responde")
        self.assertEqual(leer_progreso(self.ruta)["estado"], "error")
        p.detenido()
        self.assertEqual(leer_progreso(self.ruta)["estado"], "detenido")


if __name__ == "__main__":
    unittest.main()
