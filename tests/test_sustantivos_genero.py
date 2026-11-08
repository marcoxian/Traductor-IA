"""Sustantivos de persona tras "ser" ("soy un experto" -> "soy una experta"): traductor/genero.py."""
from __future__ import annotations

import unittest

from traductor.genero import (HOMBRE, MUJER, corregir_primera_persona, corregir_segunda_persona,
                              corregir_sustantivos, marcas_genero)


class TestPrimeraPersona(unittest.TestCase):
    def test_habla_una_mujer(self):
        casos = {
            ("Soy un explorador de verdad.", "I'm a real explorer."): "Soy una exploradora de verdad.",
            ("Ya soy un adulto.", "I'm an adult already."): "Ya soy una adulta.",
            ("Soy su socio.", "I'm her partner."): "Soy su socia.",
            ("¡Soy el elegido!", "I'm the chosen one!"): "¡Soy la elegida!",
            ("Soy un buen amigo.", "I'm a good friend."): "Soy una buena amiga.",
            ("Soy todo un experto.", "I'm quite the expert."): "Soy toda una experta.",
            ("Soy el maestro perfecto.", "I am the perfect master."): "Soy la maestra perfecta.",
            ("No soy un luchador.", "I'm not a fighter."): "No soy una luchadora.",
            ("Soy el único que puede decirlo.", "I'm the only one who can say it."): "Soy la única que puede decirlo.",
            ("Fui el primero en llegar.", "I was the first to arrive."): "Fui la primera en llegar.",
            ("Cuando era niño, veía la tele.", "When I was a kid, I watched TV."): "Cuando era niña, veía la tele.",
        }
        for (es, en), esperado in casos.items():
            with self.subTest(es):
                self.assertEqual(corregir_primera_persona(es, MUJER, en), esperado)

    def test_habla_un_hombre(self):
        self.assertEqual(corregir_primera_persona("Soy una buena amiga.", HOMBRE, "I'm a good friend."),
                         "Soy un buen amigo.")
        self.assertEqual(corregir_primera_persona("Fui la primera en llegar.", HOMBRE, "I was the first."),
                         "Fui el primero en llegar.")

    def test_lo_que_no_se_toca(self):
        casos = [
            ("Soy el único orco que queda.", "I'm the only orc left."),     # "único" + sustantivo que no está
            ("Soy tu hermano.", "I'm your brother."),                       # el inglés ya marca el género
            ("«Soy tu amigo», dijo él.", "\"I'm your friend,\" he said."),  # cita
            ("Mi madre era un ama de casa.", "My mom was a housewife."),   # 3.ª persona
            ("Ana era un experto.", "Ana was an expert."),                  # "era" con otro sujeto
        ]
        for es, en in casos:
            with self.subTest(es):
                self.assertEqual(corregir_primera_persona(es, MUJER, en), es)

    def test_era_sin_original_en_primera_persona_no_se_toca(self):
        self.assertEqual(corregir_sustantivos("Era un experto.", MUJER, "1", "He was an expert."), "Era un experto.")
        self.assertEqual(corregir_sustantivos("Era un experto.", MUJER, "1", None), "Era un experto.")


class TestSegundaPersonaYMarcas(unittest.TestCase):
    def test_segunda_persona(self):
        self.assertEqual(corregir_segunda_persona("Eres un experto, Ana.", MUJER), "Eres una experta, Ana.")
        self.assertEqual(corregir_segunda_persona("¿Eres la elegida?", HOMBRE), "¿Eres el elegido?")

    def test_marcas(self):
        self.assertEqual(marcas_genero("Soy un experto."), {"1m"})
        self.assertEqual(marcas_genero("Eres la elegida."), {"2f"})
        self.assertEqual(marcas_genero("Es un experto."), set())


if __name__ == "__main__":
    unittest.main()
