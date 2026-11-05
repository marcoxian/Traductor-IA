"""Prueba de extremo a extremo: análisis (Paso 0) -> ficha -> perfil -> traducción -> inyección RPG Maker.

La misma frase inglesa ("I'm so tired.") la dicen una mujer (Laura) y el protagonista (hombre):
cada una debe quedar con su concordancia aunque el modelo (simulado) conteste siempre en masculino.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor import config
from traductor.analizador import analizar_y_guardar
from traductor.motores.rpgmaker import InyectorRPGMaker
from traductor.ollama import OllamaTranslator


def _cmd(code, params, indent=0):
    return {"code": code, "indent": indent, "parameters": params}


def _mensaje(texto):
    return [_cmd(101, ["", 0, 0, 2]), _cmd(401, [texto])]


RESPUESTAS = {
    "I'm so tired.": "Estoy tan cansado.",
    "I'm ready": "Estoy lista",
    "Laura is my mom. She is great.": "Laura es mi madre. Es genial.",
    "Are you ready, Laura?": "¿Estás listo, Laura?",
}


class TestFlujoGenero(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.parche = mock.patch.object(config, "DIR_WORKSPACE", self.ws)
        self.parche.start()
        self.juego = self.tmp / "Juego E2E"
        datos = self.juego / "www" / "data"
        datos.mkdir(parents=True)
        (datos / "System.json").write_text(json.dumps({"gameTitle": "E2E", "versionId": 1}), encoding="utf-8")
        (datos / "Actors.json").write_text(json.dumps([None, {"id": 1, "name": "William"}]), encoding="utf-8")
        lista_ce = []
        for codigo, valor in (("Mc", 1), ("He", 2)):
            lista_ce += [_cmd(355, [f'if ($gameVariables.value(26).includes("{codigo}")) {{']),
                         _cmd(655, [f"$gameVariables.setValue(27, {valor})"]), _cmd(655, ["}"])]
        for valor, ce in ((1, 2), (2, 3)):
            lista_ce += [_cmd(111, [1, 27, 0, valor, 0]), _cmd(117, [ce], 1), _cmd(0, [], 1), _cmd(412, [])]
        eventos = [None, {"id": 1, "name": "MESSAGE", "list": lista_ce},
                   {"id": 2, "name": "VOICE MC", "list": []}, {"id": 3, "name": "VOICE Laura", "list": []}]
        (datos / "CommonEvents.json").write_text(json.dumps(eventos), encoding="utf-8")
        comandos = (_mensaje("HeFrOp.I'm so tired.") + _mensaje("McFrOp.I'm so tired.")
                    + _mensaje("McFrOp.Laura is my mom. She is great.")
                    + _mensaje("McFrOp.Are you ready, Laura?")
                    + _mensaje("1Hero is here. He looks happy.")
                    + _mensaje("HeFrOp.Thanks, 1Hero.") + _mensaje("HeFrOp.Good night, 1Hero.")
                    + [_cmd(102, [["I'm ready"]]), _cmd(0, [])])
        (datos / "Map001.json").write_text(json.dumps({"events": [None, {"pages": [{"list": comandos}]}]}),
                                           encoding="utf-8")

    def tearDown(self):
        self.parche.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flujo_completo(self):
        ruta_ficha, informe = analizar_y_guardar("juego_e2e", self.juego)
        self.assertTrue(ruta_ficha.exists())
        ficha = informe.ficha
        self.assertEqual(ficha.protagonista().nombre, "1Hero")
        self.assertEqual(ficha.protagonista().genero, "hombre")
        self.assertEqual(ficha.por_codigo("He").nombre, "Laura")
        self.assertEqual(ficha.por_codigo("He").genero, "mujer")

        perfil = config.cargar_perfil("juego_e2e", auto_crear=False)
        self.assertIsNotNone(perfil.personajes)
        self.assertIn("Protagonista: 1Hero (hombre)", perfil.contexto)
        self.assertNotIn("SIEMPRE en masculino", perfil.contexto)  # la regla global antigua no se aplica

        prompts: list[str] = []

        def generar(prompt, num_predict, temperature=0.1):
            prompts.append(prompt)
            entrada = prompt.split("### Input:\n", 1)[1].split("\n\n### Response:", 1)[0].strip()
            return RESPUESTAS.get(entrada, entrada)

        traductor = OllamaTranslator(perfil=perfil, ruta_cache=self.tmp / "cache.json")
        traductor._generar = generar
        InyectorRPGMaker(self.juego, traductor).procesar()

        mapa = json.loads((self.juego / "www" / "data" / "Map001.json").read_text(encoding="utf-8"))
        textos = [c["parameters"][0] for c in mapa["events"][1]["pages"][0]["list"] if c["code"] == 401]
        opciones = [c["parameters"][0] for c in mapa["events"][1]["pages"][0]["list"] if c["code"] == 102]
        self.assertIn("HeFrOp.Estoy tan cansada.", textos)    # Laura (mujer)
        self.assertIn("McFrOp.Estoy tan cansado.", textos)    # protagonista (hombre)
        self.assertIn("McFrOp.¿Estás lista, Laura?", textos)  # se dirige a Laura por su nombre
        self.assertEqual(opciones, [["Estoy listo"]])           # la opción la dice el protagonista
        self.assertTrue(any("Habla Laura (mujer)" in p for p in prompts))
        self.assertTrue(any("Habla el protagonista, 1Hero (hombre)" in p for p in prompts))


if __name__ == "__main__":
    unittest.main()
