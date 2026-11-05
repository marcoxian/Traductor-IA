"""W2-W4: el traductor usa el sentido decidido de "chest"/"safe" (glosario de la frase, reintento con aviso,
cambio seguro al final, lotes, caché y traducción ya existente). Ningún test llama a Ollama."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor.config import Perfil
from traductor.ollama import OllamaTranslator

CUERPO = "Want me to stab you in the chest again, miracle boy?"
COFRE = "Bring the chest to Tanya."


class TestTerminosDelPerfil(unittest.TestCase):
    def test_glosario_de_la_frase(self):
        p = Perfil(contexto="CTX")
        self.assertIn(("chest", "pecho"), p.terminos_para(CUERPO))
        self.assertIn(("chest", "cofre"), p.terminos_para(COFRE))
        self.assertEqual(p.terminos_para("Open the door."), [])            # nada que decidir: como siempre
        self.assertEqual(p.terminos_para(CUERPO, con_ambiguas=False), [])  # los lotes no lo usan
        self.assertEqual(Perfil(contexto="CTX", palabras_ambiguas=False).terminos_para(CUERPO), [])

    def test_el_glosario_del_usuario_manda(self):
        p = Perfil(contexto="CTX", glosario={"Chest Key": "Llave de cofre"})
        self.assertEqual(p.terminos_para("Buy the Chest Key."), [("Chest Key", "Llave de cofre")])


class TestTraductor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ruta = Path(tmp.name) / "cache_prueba.json"

    def _traductor(self, respuestas, perfil: Perfil | None = None, ruta_cache=None) -> OllamaTranslator:
        t = OllamaTranslator(model_name="prueba", perfil=perfil or Perfil(contexto="CTX"), ruta_cache=ruta_cache)
        self.addCleanup(t.cerrar)
        self.prompts: list[str] = []
        cola = list(respuestas)

        def generar(prompt, num_predict, temperature=0.1):
            self.prompts.append(prompt)
            return cola.pop(0) if len(cola) > 1 else cola[0]

        t._generar = generar
        return t

    def test_pide_el_sentido_y_reintenta_si_sale_al_reves(self):
        t = self._traductor(["¿Quieres que te apuñale otra vez en el cofre, chico milagro?",
                             "¿Quieres que te apuñale otra vez en el pecho, chico milagro?"])
        self.assertEqual(t.translate(CUERPO), "¿Quieres que te apuñale otra vez en el pecho, chico milagro?")
        self.assertIn("'chest' = 'pecho'", self.prompts[0])                     # en el glosario de la frase
        self.assertIn("'chest' significa 'pecho' (parte del cuerpo)", self.prompts[1])  # aviso del reintento
        self.assertEqual(t.estadisticas["sentido_corregido"], 1)

    def test_si_el_modelo_insiste_se_cambia_cofre_por_pecho(self):
        t = self._traductor(["Solo con mirar ese cofre tan viril me late el corazón."])
        self.assertEqual(t.translate("Just looking at that manly chest has my heart thumping."),
                         "Solo con mirar ese pecho tan viril me late el corazón.")
        self.assertEqual(len(self.prompts), t.reintentos_calidad)

    def test_frase_sin_decidir_no_cambia(self):
        t = self._traductor(["¿Tienes el cofre?"])
        self.assertEqual(t.translate("You have the chest?"), "¿Tienes el cofre?")
        self.assertNotIn("GLOSARIO", self.prompts[0])
        self.assertEqual(len(self.prompts), 1)

    def test_articulos_de_cofre(self):
        t = self._traductor(["Hay una cofre en el gimnasio que deberías encontrar."])
        self.assertEqual(t.translate("There’s a chest in the gym you should find."),
                         "Hay un cofre en el gimnasio que deberías encontrar.")

    def test_lote_retraduce_sola_la_frase_al_reves(self):
        t = self._traductor(["1. Lleva el cofre a Tanya.\n2. ¿Quieres que te apuñale otra vez en el cofre?",
                             "¿Quieres que te apuñale otra vez en el pecho?"])
        t.tam_lote = 10
        self.assertEqual(t.traducir_textos([COFRE, CUERPO]),
                         ["Lleva el cofre a Tanya.", "¿Quieres que te apuñale otra vez en el pecho?"])
        self.assertNotIn("'chest' =", self.prompts[0])   # el lote no lleva el sentido de una sola frase
        self.assertIn("'chest' = 'pecho'", self.prompts[1])
        self.assertEqual(len(self.prompts), 2)

    def test_cache_con_el_sentido_equivocado_no_sirve(self):
        perfil = Perfil(contexto="CTX")
        viejo = self._traductor(["x"], perfil, self.ruta)
        viejo.cache.set(viejo._clave(CUERPO, perfil.terminos_para(CUERPO)), "¿Te apuñalo en el cofre?")
        viejo.cache.guardar()
        t = self._traductor(["¿Te apuñalo otra vez en el pecho?"], perfil, self.ruta)
        self.assertEqual(t.translate(CUERPO), "¿Te apuñalo otra vez en el pecho?")
        self.assertEqual(t.estadisticas["cache_sentido_descartada"], 1)

    def test_traduccion_del_juego_al_reves_no_se_reaprovecha(self):
        t = self._traductor(["x"])
        self.assertFalse(t.sembrar_traduccion(CUERPO, "¿Quieres que te apuñale en el cofre otra vez?"))
        self.assertEqual(t.estadisticas["reaprovechadas_sentido_descartadas"], 1)
        self.assertTrue(t.sembrar_traduccion(COFRE, "Lleva el cofre a Tanya."))


if __name__ == "__main__":
    unittest.main()
