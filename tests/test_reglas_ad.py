"""Reglas del bloque AD: tratamiento en vocativo sin artículo e inglés corto con signos de español."""
from __future__ import annotations

import unittest

from traductor.gramatica import arreglar_tratamiento_vocativo
from traductor.texto import evaluar_traduccion, postprocesar_traduccion


class TestTratamientoVocativo(unittest.TestCase):
    def test_quita_el_articulo(self):
        self.assertEqual(
            arreglar_tratamiento_vocativo("Mr. Lopez, we have a problem.", "El Sr. Lopez, tenemos un problema."),
            "Sr. Lopez, tenemos un problema.")

    def test_femenino_y_doctor(self):
        self.assertEqual(
            arreglar_tratamiento_vocativo("Ms. Lopez, I assure you.", "La Sra. Lopez, se lo aseguro."),
            "Sra. Lopez, se lo aseguro.")
        self.assertEqual(
            arreglar_tratamiento_vocativo("Dr. Vega, come in!", "¡El Dr. Vega, pase!"), "¡Dr. Vega, pase!")

    def test_no_toca_si_no_es_vocativo(self):
        # El original habla DE él, no A él: el artículo es correcto.
        self.assertEqual(
            arreglar_tratamiento_vocativo("I saw Mr. Lopez yesterday.", "Vi ayer al Sr. Lopez."),
            "Vi ayer al Sr. Lopez.")
        self.assertEqual(
            arreglar_tratamiento_vocativo("Mr. Lopez is late.", "El Sr. Lopez llega tarde."),
            "El Sr. Lopez llega tarde.")

    def test_en_el_flujo_completo(self):
        r = postprocesar_traduccion("El Sr. Lopez, necesito hablar con usted.",
                                    "Mr. Lopez, I need a word with you.")
        self.assertTrue(r.startswith("Sr. Lopez,"), r)


class TestInglesEnMayusculas(unittest.TestCase):
    def test_detecta_ingles_con_signos_espanoles(self):
        self.assertIn("ingles_residual",
                      evaluar_traduccion("That fucking door is stuck!", "¡DAMN THAT DOOR IS STUCK!"))

    def test_palabras_inglesas_con_silabas_espanolas(self):
        # "la" dentro de "PLEASE" o "es" dentro de "THESE" no son señal de español
        self.assertIn("ingles_residual",
                      evaluar_traduccion("Please, take these away!", "¡PLEASE TAKE THESE AWAY!"))

    def test_no_marca_espanol_normal(self):
        self.assertEqual(evaluar_traduccion("That fucking door is stuck!", "¡Joder, la puerta se ha atascado!"), [])


if __name__ == "__main__":
    unittest.main()
