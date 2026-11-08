"""Cifras perdidas, cambiadas o inventadas (aviso leve "numeros" con reintento), eco del historial del modo
seguro y aviso "ustedes". Ningún test llama a Ollama."""
from __future__ import annotations

import unittest

from traductor.config import Perfil
from traductor.ollama import OllamaTranslator
from traductor.texto import (PROBLEMAS_LEVES_REINTENTO, evaluar_traduccion, numeros_cambiados,
                             numeros_del_original, tiene_fallo_grave)


class TestNumerosCambiados(unittest.TestCase):
    def test_cifras_perdidas_cambiadas_o_inventadas(self):
        self.assertEqual(numeros_cambiados("You have:5", "Tienes:"), ([5], []))
        self.assertEqual(numeros_cambiados("★Charm+178 ★Mood+8", "Encanto+96 Humor+8"), ([178], [96]))
        self.assertEqual(numeros_cambiados("Push 1000 times", "Empuja 1Lia"), ([1000], [1]))
        self.assertEqual(numeros_cambiados("Day 3005", "Día 2005"), ([3005], [2005]))
        self.assertEqual(numeros_cambiados("No reason~", "Sin razón~ Tagged as: Mi Juego 2"), ([], [2]))

    def test_mismas_cifras_aunque_se_escriban_distinto(self):
        self.assertEqual(numeros_cambiados("Pay 100,000 gold.", "Paga 100.000 de oro."), ([], []))
        self.assertEqual(numeros_cambiados("It costs 1.5 coins.", "Cuesta 1,5 monedas."), ([], []))
        self.assertEqual(numeros_cambiados("Come back at 11:00.", "Vuelve a las 11."), ([], []))
        self.assertEqual(numeros_cambiados("50 thousand coins", "50.000 monedas"), ([], []))
        self.assertEqual(numeros_cambiados("Push 1000000 times", "Empuja 1 millón de veces"), ([], []))
        self.assertEqual(numeros_cambiados("Code {0} and \\V[12] left", "Quedan el código {0} y \\V[12]"), ([], []))

    def test_numeros_escritos_con_letras(self):
        self.assertEqual(numeros_cambiados("They split into 2 teams.", "Se dividen en dos equipos."), ([], []))
        self.assertEqual(numeros_cambiados("4times", "Cuatro veces"), ([], []))
        self.assertEqual(numeros_cambiados("1st Round", "Primera ronda"), ([], []))
        self.assertEqual(numeros_cambiados("Over 32 tails", "Más de treinta y dos colas"), ([], []))
        self.assertEqual(numeros_cambiados("It took five tries.", "Hicieron falta 5 intentos."), ([], []))
        self.assertEqual(numeros_cambiados("A one-week trip", "Un viaje de 1 semana"), ([], []))
        # "a" no cuenta como "1": un "1" inventado se ve aunque la frase tenga artículos
        self.assertEqual(numeros_cambiados("I take a stance.", "Adopto la postura 1Lia."), ([], [1]))

    def test_evaluar_traduccion_lo_marca_como_leve(self):
        probs = evaluar_traduccion("You have:5", "Tienes:")
        self.assertIn("numeros", probs)
        self.assertFalse(tiene_fallo_grave(probs))
        self.assertIn("numeros", PROBLEMAS_LEVES_REINTENTO)
        self.assertEqual(evaluar_traduccion("You have:5", "Tienes:5"), [])
        self.assertEqual(numeros_del_original("★Charm+178 ★Mood+8 (1,000)"), ["178", "8", "1,000"])


class TestEcoHistorialYUstedes(unittest.TestCase):
    def test_eco_del_historial(self):
        eco = "[★Fuerza+12 ★Ánimo+3 -> ★Fuerza+12 ★Ánimo+3]"
        self.assertIn("eco_prompt", evaluar_traduccion("★Strength+40", eco))
        self.assertNotIn("eco_prompt", evaluar_traduccion("Press [A] -> jump", "[A] -> saltar"))

    def test_ustedes_es_aviso_sin_reintento(self):
        probs = evaluar_traduccion("You two think alike, huh?", "Ustedes dos piensan igual, ¿eh?")
        self.assertIn("ustedes", probs)
        self.assertNotIn("ustedes", PROBLEMAS_LEVES_REINTENTO)
        self.assertFalse(tiene_fallo_grave(probs))

    def test_ustedes_de_respeto_no_avisa(self):
        self.assertNotIn("ustedes", evaluar_traduccion("What can I do for you, ladies?",
                                                       "¿Qué puedo hacer por ustedes, señoras?"))
        self.assertNotIn("ustedes", evaluar_traduccion("You two think alike.", "Pensáis igual."))


class TestReintento(unittest.TestCase):
    def _traductor(self, respuestas) -> OllamaTranslator:
        t = OllamaTranslator(model_name="prueba", perfil=Perfil(contexto="CTX"), ruta_cache=None)
        self.addCleanup(t.cerrar)
        self.prompts: list[str] = []
        cola = list(respuestas)

        def generar(prompt, num_predict, temperature=0.1):
            self.prompts.append(prompt)
            return cola.pop(0) if len(cola) > 1 else cola[0]

        t._generar = generar
        return t

    def test_reintenta_con_las_cifras_del_original(self):
        t = self._traductor(["Encanto+96 Humor+10", "★Encanto+178 ★Humor+8"])
        self.assertEqual(t.translate("★Charm+178 ★Mood+8"), "★Encanto+178 ★Humor+8")
        self.assertEqual(len(self.prompts), 2)
        self.assertIn("Cifras del original: 178, 8.", self.prompts[1])

    def test_si_no_se_arregla_se_acepta_la_mejor(self):
        t = self._traductor(["Tienes:"])
        self.assertEqual(t.translate("You have:5"), "Tienes:")
        self.assertEqual(len(self.prompts), t.reintentos_calidad)

    def test_lote_retraduce_sola_la_frase_con_cifras_mal(self):
        t = self._traductor(["1. Hola, Ana.\n2. Tienes:", "Tienes:7"])
        t.tam_lote = 10
        self.assertEqual(t.traducir_textos(["Hello, Ana.", "You have:7"]), ["Hola, Ana.", "Tienes:7"])
        self.assertEqual(len(self.prompts), 2)

    def test_ustedes_no_pide_otro_intento(self):
        t = self._traductor(["Ustedes dos piensan igual."])
        self.assertEqual(t.translate("You two think alike."), "Ustedes dos piensan igual.")
        self.assertEqual(len(self.prompts), 1)


if __name__ == "__main__":
    unittest.main()
