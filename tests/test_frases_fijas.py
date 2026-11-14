"""Bloque AD-5: frases fijas del perfil (juegos de palabras traducidos a mano) y dos calcos nuevos
("It's not like that" -> "No es así de fácil", "nice rack" -> "buena panza").

Ningún test llama a Ollama (``_generar`` está simulado) ni toca workspace/ real. Frases inventadas."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor import config, modismos
from traductor.config import Perfil
from traductor.ollama import OllamaTranslator

FIJAS = {"We {i}penne{/i} try.": "{i}Pasta{/i} con intentarlo.",
         "Is your {i}battery{/i} low, mate?": "¿Te has quedado sin {i}pilas{/i}, tío?"}


def _claves(original: str, traduccion: str) -> list[str]:
    return [m.clave for m in modismos.calcos(original, traduccion)]


class TestFrasesFijasPerfil(unittest.TestCase):
    def test_solo_la_frase_entera(self):
        p = Perfil(frases_fijas=FIJAS)
        self.assertEqual(p.traduccion_exacta("We {i}penne{/i} try."), "{i}Pasta{/i} con intentarlo.")
        self.assertEqual(p.traduccion_exacta("  We {i}penne{/i} try. "), "  {i}Pasta{/i} con intentarlo. ")
        for otro in ("We penne try.", "We {i}penne{/i} try. Really.", "we {i}penne{/i} try.", ""):
            self.assertIsNone(p.traduccion_exacta(otro), otro)
        self.assertIsNone(Perfil().traduccion_exacta("We {i}penne{/i} try."))

    def test_no_cambia_los_terminos_ni_la_huella(self):
        base, con_fijas = Perfil(contexto="x"), Perfil(contexto="x", frases_fijas=FIJAS)
        self.assertEqual(con_fijas.huella(), base.huella())
        self.assertEqual(con_fijas.terminos_para("We {i}penne{/i} try."), base.terminos_para("We {i}penne{/i} try."))

    def test_leer_y_cargar_perfil(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            ruta = workspace / "juego_x" / config.ARCHIVO_FRASES_FIJAS
            ruta.parent.mkdir(parents=True)
            ruta.write_text(json.dumps({"_info": "nota", **FIJAS, "Vacía": " "}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(config.leer_frases_fijas(ruta), FIJAS)
            self.assertEqual(config.leer_frases_fijas(workspace / "no_existe.json"), {})
            with mock.patch.object(config, "DIR_WORKSPACE", workspace):
                perfil = config.cargar_perfil("juego_x", auto_crear=False)
            self.assertEqual(perfil.traduccion_exacta("Is your {i}battery{/i} low, mate?"),
                             "¿Te has quedado sin {i}pilas{/i}, tío?")
            self.assertIn("2 frases fijas", perfil.resumen())


class TestFrasesFijasTraductor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _traductor(self, **kw) -> OllamaTranslator:
        t = OllamaTranslator(model_name="modelo_prueba", perfil=Perfil(frases_fijas=FIJAS),
                             ruta_cache=self.tmp / "cache.json", **kw)
        self.addCleanup(t.cerrar)
        t._generar = mock.MagicMock(return_value="Lo intentaremos con los canelones.")
        return t

    def test_la_frase_fija_no_pasa_por_el_modelo(self):
        for tam_lote in (1, 20):
            t = self._traductor(tam_lote=tam_lote)
            self.assertEqual(t.traducir_textos(["We {i}penne{/i} try.", "Is your {i}battery{/i} low, mate?"]),
                             ["{i}Pasta{/i} con intentarlo.", "¿Te has quedado sin {i}pilas{/i}, tío?"])
            t._generar.assert_not_called()
            self.assertEqual(t.translate("We {i}penne{/i} try."), "{i}Pasta{/i} con intentarlo.")
            t._generar.assert_not_called()

    def test_no_se_siembra_la_traduccion_vieja(self):
        # --solo-genero: la traducción que ya tiene el juego no debe ganar a la frase fija
        t = self._traductor()
        self.assertFalse(t.sembrar_traduccion("We {i}penne{/i} try.", "Lo intentaremos con los canelones."))


class TestNoEsAsiDeFacil(unittest.TestCase):
    def test_detecta_el_calco(self):
        self.assertIn("it's not like that", _claves("It's not like that, Rosa.", "No es así de fácil, Rosa."))
        self.assertIn("it's not like that", _claves("Hey… it’s not like that.", "Oye... no es como eso."))

    def test_bien_traducido_no_avisa(self):
        for bien in ("No es lo que piensas, Rosa.", "No es eso, Rosa.", "No es lo que parece, Rosa."):
            self.assertNotIn("it's not like that", _claves("It's not like that, Rosa.", bien))

    def test_arreglo_seguro(self):
        self.assertEqual(modismos.arreglar("Hey... it's not like that, Rosa.", "Oye... No es así de fácil, Rosa."),
                         "Oye... No es lo que piensas, Rosa.")
        self.assertEqual(modismos.arreglar("It's not like that.", "no es como eso."), "no es lo que piensas.")
        # sin "not like that" en el inglés, o si habla de algo fácil, no se toca
        self.assertEqual(modismos.arreglar("It's not that simple.", "No es así de fácil."), "No es así de fácil.")
        self.assertEqual(modismos.arreglar("It's not like that easy.", "No es así de fácil."), "No es así de fácil.")

    def test_si_el_ingles_habla_de_facil_no_cuenta(self):
        self.assertNotIn("it's not like that",
                         _claves("It's not like that easy, Rosa.", "No es así de fácil, Rosa."))


class TestRackSonTetas(unittest.TestCase):
    def test_detecta_panza_y_cadera(self):
        self.assertIn("rack (tetas)", _claves("Wow, check out that rack!", "¡Vaya, mira esa panza!"))
        self.assertIn("rack (tetas)", _claves("She has a rack as big as Rosa's.",
                                              "Tiene una cadera tan grande como la de Rosa."))

    def test_bien_traducido_o_estante_no_avisa(self):
        self.assertNotIn("rack (tetas)", _claves("We both like a good rack.",
                                                 "A los dos nos gustan unas buenas tetas."))
        self.assertNotIn("rack (tetas)", _claves("Leave it on the luggage rack.", "Déjalo en la barra del equipaje."))
        self.assertNotIn("rack (tetas)", _claves("A rack of lamb, please.", "Un costillar de cordero con panza."))


if __name__ == "__main__":
    unittest.main()
