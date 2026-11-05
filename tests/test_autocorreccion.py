"""La autocorrección de etiquetas no puede dar por buena una copia del original en inglés.

Caso real: a la traducción le faltaba una pausa ("\\!"); al pedir la corrección, el modelo devolvía el inglés con
la pausa bien puesta y, detrás, "Borrador a corregir: <la frase en español>". La parte en español rebajaba la
proporción de inglés y la comprobación de calidad no saltaba: la frase acababa en inglés en el juego."""
from __future__ import annotations

import unittest

from traductor.config import Perfil
from traductor.ollama import OllamaTranslator

ORIGINAL = r"Th-thank you! \!His lordship will be pleased!"
BORRADOR = "¡Gracias! ¡Su señoría estará contenta!"


class TestAutocorreccion(unittest.TestCase):
    def _traductor(self, respuesta: str) -> OllamaTranslator:
        t = OllamaTranslator(model_name="prueba", perfil=Perfil(contexto="CTX"))
        self.addCleanup(t.cerrar)
        t._generar = lambda prompt, max_tokens=None, **kw: respuesta
        return t

    def test_rechaza_la_copia_del_ingles_con_eco(self):
        t = self._traductor(ORIGINAL + "\nBorrador a corregir: " + BORRADOR)
        self.assertEqual(t.autocorrect(ORIGINAL, BORRADOR), r"¡Gracias! \!¡Su señoría estará contenta!")

    def test_acepta_una_correccion_en_espanol(self):
        t = self._traductor(r"¡Gracias! \!¡Su señoría estará encantada!")
        self.assertEqual(t.autocorrect(ORIGINAL, BORRADOR), r"¡Gracias! \!¡Su señoría estará encantada!")


if __name__ == "__main__":
    unittest.main()
