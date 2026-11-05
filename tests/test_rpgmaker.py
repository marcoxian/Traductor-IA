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
                                # Code 655 (Continuación de script con prefijo de sprite y modificador ^)
                                {
                                    "code": 655,
                                    "parameters": ['$gameVariables.setValue(21, "MiHaEx^.Wait for me!");'],
                                    "indent": 0
                                },
                                # Code 355 (V25 para mensajes SMS / teléfono)
                                {
                                    "code": 355,
                                    "parameters": ['$gameVariables.setValue(25, "Incoming call from office phone.");'],
                                    "indent": 0
                                },
                                # Code 355 (V107 para nombres de objetos encontrados)
                                {
                                    "code": 355,
                                    "parameters": ['$gameVariables.setValue(107, "Oracle of the Seraph");'],
                                    "indent": 0
                                },
                                # Code 401 con <wordwrap> y prefijo de expresión
                                {
                                    "code": 401,
                                    "parameters": ["<wordwrap>MiHaEx^.Don't leave me here!"],
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
        self.assertIn("Wait for me!", cola)  # 655 texto extraído sin el prefijo MiHaEx^.
        self.assertIn("Incoming call from office phone.", cola)  # V25 mensaje de teléfono
        self.assertIn("Oracle of the Seraph", cola)  # V107 objeto encontrado
        self.assertIn("Don't leave me here!", cola)  # 401 texto extraído sin <wordwrap> ni MiHaEx^.

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
        # Code 655 script reensamblado con prefijo MiHaEx^. intacto
        self.assertIn('$gameVariables.setValue(21, "MiHaEx^.ESP:Wait for me!");', cmds[5]["parameters"][0])
        # Code 355 script V25 reensamblado
        self.assertIn('$gameVariables.setValue(25, "ESP:Incoming call from office phone.");', cmds[6]["parameters"][0])
        # Code 355 script V107 reensamblado
        self.assertIn('$gameVariables.setValue(107, "ESP:Oracle of the Seraph");', cmds[7]["parameters"][0])
        # Code 401 con <wordwrap> y MiHaEx^. preservados al inicio
        self.assertTrue(cmds[8]["parameters"][0].startswith("<wordwrap>MiHaEx^.ESP:Don't leave me here!"))

    def test_reparar_partidas_lzstring(self):
        import importlib
        import json
        mod = importlib.import_module("7_arreglar_partida_rpgmaker")

        partida = {
            "party": {"name": "Equipo Heroico"},
            "inventario": ["tímida y tímida", "¡Fúmeme!"],
            "mapa": {"titulo": "introducciones de caracteres"}
        }
        reemplazos = {"tímida y tímida": "tímida", "introducciones de caracteres": "introducción de los personajes"}
        cambios = mod.reparar_cadenas(partida, {}, reemplazos)
        self.assertEqual(cambios, 3)
        self.assertEqual(partida["inventario"][0], "tímida")
        self.assertEqual(partida["inventario"][1], "¡Fóllame!")
        self.assertEqual(partida["mapa"]["titulo"], "introducción de los personajes")

        if mod.lzstring is not None:
            compresor = mod.lzstring.LZString()
            raw_json = json.dumps(partida)
            comprimido = compresor.compressToBase64(raw_json)
            descomprimido = compresor.decompressFromBase64(comprimido)
            self.assertEqual(json.loads(descomprimido), partida)

    def test_reparar_partidas_preserva_botones_sistema_y_audio(self):
        import importlib
        mod = importlib.import_module("7_arreglar_partida_rpgmaker")

        partida_sistema = {
            "system": {
                "_gBtns": {"@a": [None, {"id": 1, "image": "Skip"}, {"id": 2, "image": "Hide"}]}
            },
            "audio_se": {"name": "Poison", "volume": 50, "pitch": 100},
            "variables": {"@a": ["ON", "OFF", "tímida y tímida"]},
            "dialogo": "Br,fr,op.Hola mundo."
        }
        diccionario = {"Skip": "Saltar", "Poison": "Veneno", "ON": "Sí", "OFF": "No"}
        reemplazos = {"tímida y tímida": "tímida"}

        cambios = mod.reparar_cadenas(partida_sistema, diccionario, reemplazos)
        # Solo debe cambiar "tímida y tímida" -> "tímida"
        self.assertEqual(cambios, 1)
        self.assertEqual(partida_sistema["system"]["_gBtns"]["@a"][1]["image"], "Skip")
        self.assertEqual(partida_sistema["audio_se"]["name"], "Poison")
        self.assertEqual(partida_sistema["variables"]["@a"][0], "ON")
        self.assertEqual(partida_sistema["variables"]["@a"][2], "tímida")
        # El diálogo con etiqueta Br,fr,op. no debe sufrir espacios raros
        self.assertEqual(partida_sistema["dialogo"], "Br,fr,op.Hola mundo.")

    def test_no_traduce_nombres_internos(self):
        # Casos reales de Otro Juego: el jugador nunca ve estos nombres
        dialogo = [{"code": 401, "parameters": ["Hello there."], "indent": 0}, {"code": 0, "parameters": []}]
        mapa = {"displayName": "", "events": [None, {"id": 1, "name": "Chloe - AFTER", "x": 3, "y": 4,
                                                     "note": "", "pages": [{"list": dialogo}]}]}
        comunes = [None, {"id": 1, "name": "SCN - Marina Brians Room", "trigger": 0, "switchId": 1,
                          "list": [{"code": 401, "parameters": ["Nice room."], "indent": 0}]}]
        tileset = [None, {"id": 1, "name": "Outside", "mode": 1, "flags": [], "tilesetNames": ["A1"], "note": ""}]
        objeto = [None, {"id": 1, "name": "Ultra-Lube", "description": "Very slippery.", "price": 10}]
        mapinfos = [None, {"id": 1, "name": "Chloe's House", "parentId": 0, "order": 1, "expanded": False}]
        for datos, esperado in ((mapa, ["Hello there."]), (comunes, ["Nice room."]), (tileset, []),
                                (objeto, ["Ultra-Lube", "Very slippery."]), (mapinfos, ["Chloe's House"])):
            cola: list[str] = []
            self.inyector._extraer(datos, cola)
            self.assertEqual(cola, esperado)
            # La inyección consume el iterador igual y deja los nombres internos como estaban
            self.inyector._inyectar(datos, iter([f"ES:{t}" for t in esperado]))
        self.assertEqual(mapa["events"][1]["name"], "Chloe - AFTER")
        self.assertEqual(mapa["events"][1]["pages"][0]["list"][0]["parameters"][0], "ES:Hello there.")
        self.assertEqual(comunes[1]["name"], "SCN - Marina Brians Room")
        self.assertEqual(objeto[1]["name"], "ES:Ultra-Lube")

    def test_ignorar_comandos_voz_nlt(self):
        from traductor.motores.rpgmaker import es_traducible
        self.assertFalse(es_traducible("/worry"))
        self.assertFalse(es_traducible("/curse"))
        self.assertFalse(es_traducible("/finduseful"))
        self.assertTrue(es_traducible("Hello there!"))


if __name__ == "__main__":
    unittest.main()
