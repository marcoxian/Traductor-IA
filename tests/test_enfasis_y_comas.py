"""Énfasis {i}…{/i} que el modelo pierde y mayúscula indebida tras una coma."""
from __future__ import annotations

import unittest

from traductor.texto import comparar_etiquetas, forzar_etiquetas, minuscula_tras_coma, postprocesar_traduccion


class PruebasEnfasisPerdido(unittest.TestCase):
    def test_palabra_igual_en_la_traduccion(self):
        orig = "A leak in her {i}pons{/i} is bad."
        res = forzar_etiquetas(orig, "Una fuga en su pons es mala.")
        self.assertEqual(res, "Una fuga en su {i}pons{/i} es mala.")
        self.assertTrue(comparar_etiquetas(orig, res)[0])

    def test_frase_entera(self):
        orig = "{i}I can't believe it.{/i}"
        res = forzar_etiquetas(orig, "No me lo puedo creer.")
        self.assertEqual(res, "{i}No me lo puedo creer.{/i}")

    def test_hueco_relativo_sin_dejar_parejas_vacias(self):
        orig = "She {i}should{/i} be awake by now, really."
        res = forzar_etiquetas(orig, "Ella debería estar despierta ya, de verdad.")
        self.assertNotIn("{i}{/i}", res)
        self.assertTrue(comparar_etiquetas(orig, res)[0])

    def test_dos_parejas(self):
        orig = "A {i}basilar{/i} leak on the {i}pons{/i} now."
        res = forzar_etiquetas(orig, "Una fuga basilar en el pons ahora.")
        self.assertEqual(res, "Una fuga {i}basilar{/i} en el {i}pons{/i} ahora.")

    def test_sin_pareja_no_cambia_el_comportamiento(self):
        self.assertEqual(forzar_etiquetas(r"\C[1]\C[2]Texto", "Texto")[:10].count("\C"), 2)


class PruebasMinusculaTrasComa(unittest.TestCase):
    def test_casos(self):
        casos = [
            ("Maggie, ¿Realmente quieres ir?", "Maggie, ¿realmente quieres ir?"),
            ("Bueno, No puedo discutir con eso.", "Bueno, no puedo discutir con eso."),
            ("Sabes, Puedo andar muy despacio.", "Sabes, puedo andar muy despacio."),
            ("Sí, No", "Sí, No"),                      # última palabra: puede ser un menú
            ("Hola, Maggie, ¿Qué tal?", "Hola, Maggie, ¿qué tal?"),
            ("Oye, Pedro está aquí.", "Oye, Pedro está aquí."),  # nombre propio: no se toca
            ("Vamos, Coop.", "Vamos, Coop."),
        ]
        for entrada, esperado in casos:
            with self.subTest(entrada=entrada):
                self.assertEqual(minuscula_tras_coma(entrada), esperado)

    def test_en_el_postproceso(self):
        self.assertEqual(postprocesar_traduccion("Maggie, ¿Realmente lo sabes?", "Maggie, really, do you know?"),
                         "Maggie, ¿realmente lo sabes?")


if __name__ == "__main__":
    unittest.main()
