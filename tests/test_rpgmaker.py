"""Pruebas unitarias para el motor de RPG Maker (extracción, sincronización e inyección)."""
from __future__ import annotations

import unittest
from pathlib import Path
from traductor.config import Perfil
from traductor.motores.rpgmaker import InyectorRPGMaker


class MockTranslator:
    def __init__(self):
        self.perfil = Perfil(glosario={}, contexto="", nombres_protegidos={"Brad": r"\b[Bb]rad\b"})
        self.llamadas: list[str] = []

    def traducir_textos(self, textos: list[str]) -> list[str]:
        self.llamadas.extend(textos)
        # Mock traducción: prefijo ESP:
        return [f"ESP:{t}" for t in textos]


class TestRPGMaker(unittest.TestCase):
    def setUp(self):
        self.translator = MockTranslator()
        self.inyector = InyectorRPGMaker(Path("."), self.translator)

    def test_extraccion_e_inyeccion_completa(self):
        # JSON simulado con diálogo (401), opciones (102), scripts (355), audio y términos
        datos_simulados = {
            "name": "Sword of Justice",
            "description": "A very powerful sword used by ancient heroes in battles.",
            # Objeto de audio que no debe traducirse
            "bgm": {"name": "Theme01", "volume": 90, "pitch": 100},
            "events": [
                None,
                {
                    "pages": [
                        {
                            "list": [
                                # Diálogo code 401 consecutivo
                                {"code": 401, "parameters": ["Hello there,"], "indent": 0},
                                {"code": 401, "parameters": ["how are you today?"], "indent": 0},
                                # Code 102 (Opciones presentadas al jugador)
                                {"code": 102, "parameters": [["I am fine", "Not so good"]], "indent": 0},
                                # Code 402 (Bifurcación)
                                {"code": 402, "parameters": [0, "I am fine"], "indent": 0},
                                # Code 355 (Script setValue 21 con prefijo de sprite)
                                {
                                    "code": 355,
                                    "parameters": ['$gameVariables.setValue(21, "Br,fr,op.Smells like rain.");'],
                                    "indent": 0
                                },
                                # Code 355 (Script setValue 21 SIN prefijo de sprite, frase con punto)
                                {
                                    "code": 355,
                                    "parameters": ['$gameVariables.setValue(21, "Failed the exam. Please study more.");'],
                                    "indent": 0
                                },
                                {"code": 0, "parameters": [], "indent": 0}
                            ]
                        }
                    ]
                }
            ]
        }

        # 1. Extracción
        cola = []
        self.inyector._extraer(datos_simulados, cola)

        # Verificaciones de extracción
        self.assertIn("Sword of Justice", cola)
        self.assertIn("A very powerful sword used by ancient heroes in battles.", cola)
        self.assertNotIn("Theme01", cola)  # Audio ignorado
        self.assertIn("Hello there, how are you today?", cola)  # 401 agrupado
        self.assertIn("I am fine", cola)  # 102 opción 1
        self.assertIn("Not so good", cola)  # 102 opción 2
        self.assertIn("Smells like rain.", cola)  # 355 texto tras el prefijo
        self.assertIn("Failed the exam. Please study more.", cola)  # 355 texto completo sin prefijo

        # 2. Traducción mock
        traducciones = self.translator.traducir_textos(cola)
        self.assertEqual(len(cola), len(traducciones))

        # 3. Inyección
        iterador = iter(traducciones)
        self.inyector._inyectar(datos_simulados, iterador)

        # Verificar que el iterador se consumió al 100% sin desincronización
        with self.assertRaises(StopIteration):
            next(iterador)

        # Verificar que los datos se inyectaron correctamente
        self.assertEqual(datos_simulados["name"], "ESP:Sword of Justice")
        self.assertEqual(datos_simulados["bgm"]["name"], "Theme01")  # No modificado

        cmds = datos_simulados["events"][1]["pages"][0]["list"]
        # Code 401 inyectado
        self.assertTrue(cmds[0]["parameters"][0].startswith("ESP:Hello there,"))
        # Code 102 inyectado
        self.assertEqual(cmds[1]["parameters"][0][0], "ESP:I am fine")
        self.assertEqual(cmds[1]["parameters"][0][1], "ESP:Not so good")
        # Code 355 script reensamblado con prefijo intacto
        self.assertIn('$gameVariables.setValue(21, "Br,fr,op.ESP:Smells like rain.");', cmds[3]["parameters"][0])
        # Code 355 script sin prefijo reensamblado intacto sin romper oraciones
        self.assertIn('$gameVariables.setValue(21, "ESP:Failed the exam. Please study more.");', cmds[4]["parameters"][0])

    def test_reparar_partidas_lzstring(self):
        import importlib
        import json
        mod = importlib.import_module("7_arreglar_partida_rpgmaker")
        self.assertIsNotNone(mod.lzstring, "lzstring debe estar disponible")

        compresor = mod.lzstring.LZString()
        partida = {
            "party": {"name": "Equipo Heroico"},
            "inventario": ["tímida y tímida", "Normal"],
            "mapa": {"titulo": "introducciones de caracteres"}
        }
        reemplazos = {"tímida y tímida": "tímida", "introducciones de caracteres": "introducción de los personajes"}
        cambios = mod.reparar_cadenas(partida, {}, reemplazos)
        self.assertEqual(cambios, 2)
        self.assertEqual(partida["inventario"][0], "tímida")
        self.assertEqual(partida["mapa"]["titulo"], "introducción de los personajes")

        # Comprimir a LZString y descomprimir
        raw_json = json.dumps(partida)
        comprimido = compresor.compressToBase64(raw_json)
        descomprimido = compresor.decompressFromBase64(comprimido)
        self.assertEqual(json.loads(descomprimido), partida)


if __name__ == "__main__":
    unittest.main()
