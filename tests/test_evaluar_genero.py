"""Pruebas de 9_evaluar_genero.py (banco de pruebas de género del modelo), con Ollama simulado."""
from __future__ import annotations

import importlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor import config
from traductor.genero import HOMBRE, MUJER
from traductor.ollama import OllamaTranslator
from traductor.personajes import FichaPersonajes, Personaje

evaluar = importlib.import_module("9_evaluar_genero")


def _ficha() -> FichaPersonajes:
    return FichaPersonajes([
        Personaje("1Hero", "hombre", "protagonista", codigos=["Mc"]),
        Personaje("Laura", "mujer", "principal", codigos=["He"]),
    ])


def _cmd(code, params):
    return {"code": code, "indent": 0, "parameters": params}


class TestFrasesYNotas(unittest.TestCase):
    def test_es_frase_de_prueba(self):
        self.assertTrue(evaluar.es_frase_de_prueba("I'm so tired."))
        self.assertTrue(evaluar.es_frase_de_prueba("I’m not sure what you mean."))   # apóstrofo tipográfico
        self.assertTrue(evaluar.es_frase_de_prueba("I was really worried about you!"))
        self.assertFalse(evaluar.es_frase_de_prueba("You're tired."))                # 2.ª persona
        self.assertFalse(evaluar.es_frase_de_prueba("I'm happy."))                   # "feliz" no marca género
        self.assertFalse(evaluar.es_frase_de_prueba("I'm tired. " * 30))             # demasiado larga

    def test_puntuar(self):
        self.assertEqual(evaluar.puntuar("Estoy tan cansada.", MUJER), "correcto")
        self.assertEqual(evaluar.puntuar("Estoy tan cansado.", MUJER), "contrario")
        self.assertEqual(evaluar.puntuar("Me alegro.", MUJER), "neutra")
        self.assertEqual(evaluar.puntuar("No estoy seguro.", HOMBRE), "correcto")


class TestRecogidaYEvaluacion(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        datos = self.tmp / "www" / "data"
        datos.mkdir(parents=True)
        mapa = {"events": [None, {"pages": [{"list": [
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["HeFrOp.I'm so tired. I worked all day."]),
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["McFrOp.I’m not sure about this."]),
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["HeFrOp.Hello there."]),          # no marca género
            _cmd(0, []),
        ]}]}]}
        (datos / "Map001.json.bak").write_text(json.dumps(mapa), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_casos_rpgmaker(self):
        casos = evaluar.casos_rpgmaker("prueba", self.tmp, _ficha())
        por_hablante = {c.hablante: c for c in casos}
        self.assertEqual(set(por_hablante), {"Laura", "1Hero"})
        self.assertEqual(por_hablante["Laura"].genero, MUJER)
        self.assertEqual(por_hablante["1Hero"].genero, HOMBRE)
        elegidos = evaluar.recoger_casos("prueba", self.tmp, _ficha(), por_genero=1)
        self.assertEqual(len(elegidos), 2)

    def test_evaluador_con_ollama_simulado(self):
        casos = evaluar.casos_rpgmaker("prueba", self.tmp, _ficha())
        laura = next(c for c in casos if c.hablante == "Laura")
        perfil = config.Perfil(personajes=_ficha(), contexto="Protagonista: 1Hero (hombre).",
                               contexto_legacy="El protagonista habla SIEMPRE en masculino.")
        prompts_vistos = []

        def generar(self, prompt, num_predict, temperature=0.1):
            prompts_vistos.append(prompt)
            return "Estoy tan cansado. He trabajado todo el día."

        with mock.patch.object(OllamaTranslator, "_generar", generar):
            ev = evaluar.Evaluador("modelo_prueba", perfil)
            res = ev.evaluar(laura)
            ev.cerrar()
        self.assertEqual(res["A_antes"]["nota"], "contrario")
        self.assertEqual(res["B_con_pista"]["nota"], "contrario")
        self.assertEqual(res["C_pipeline"]["nota"], "correcto")          # la concordancia lo arregla
        self.assertIn("cansada", res["C_pipeline"]["traduccion"])
        # A usa el contexto antiguo y ninguna pista; B el de la ficha y "PERSONAJES: Habla Laura (mujer)"
        self.assertIn("SIEMPRE en masculino", prompts_vistos[0])
        self.assertNotIn("PERSONAJES", prompts_vistos[0])
        self.assertIn("Habla Laura (mujer)", prompts_vistos[1])
        resumen = evaluar.resumir([laura])
        self.assertEqual(resumen["C_pipeline"]["correcto"], 1)
        self.assertEqual(resumen["A_antes"]["por_genero"][MUJER]["contrario"], 1)
        self.assertIn("C. pipeline completo", evaluar.tabla(resumen))

    def test_juego_que_no_es_rpgmaker_sin_avisos_falsos(self):
        vacio = Path(tempfile.mkdtemp())
        try:
            with self.assertNoLogs(level="ERROR"):
                self.assertEqual(evaluar.casos_rpgmaker("x", vacio, _ficha()), [])
                self.assertEqual(evaluar.textos_juego(vacio), [])
        finally:
            shutil.rmtree(vacio, ignore_errors=True)

    def test_invertir_protagonista(self):
        perfil = config.Perfil(personajes=_ficha(), contexto="Protagonista: 1Hero (hombre). Protagonista masculino.")
        inv = evaluar.invertir_protagonista(perfil)
        self.assertEqual(inv.personajes.protagonista().genero, MUJER)
        self.assertTrue(inv.contexto.startswith("Protagonista: 1Hero (mujer)"))
        self.assertNotIn("Protagonista masculino", inv.contexto)          # el contexto del juego se quita
        self.assertEqual(perfil.personajes.protagonista().genero, HOMBRE)  # el perfil original no cambia
        casos = {c.hablante: c for c in evaluar.casos_rpgmaker("prueba", self.tmp, inv.personajes)}
        self.assertEqual(casos["1Hero"].genero, MUJER)
        self.assertTrue(casos["1Hero"].es_protagonista)
        self.assertFalse(casos["Laura"].es_protagonista)
        sin_genero = FichaPersonajes([Personaje("Prota", "desconocido", "protagonista")])
        self.assertIsNone(evaluar.invertir_protagonista(config.Perfil(personajes=sin_genero)))

    def test_prueba_espejo_sin_condicion_a(self):
        perfil = evaluar.invertir_protagonista(config.Perfil(personajes=_ficha(), contexto="x"))
        casos = evaluar.casos_rpgmaker("prueba", self.tmp, perfil.personajes)
        prompts_vistos = []

        def generar(self, prompt, num_predict, temperature=0.1):
            prompts_vistos.append(prompt)
            return "No estoy segura de esto."

        with mock.patch.object(OllamaTranslator, "_generar", generar):
            ev = evaluar.Evaluador("modelo_prueba", perfil, con_antes=False)
            for c in casos:
                ev.evaluar(c)
            ev.cerrar()
        self.assertEqual(len(prompts_vistos), len(casos))                 # una llamada por frase (sin A)
        self.assertTrue(all(set(c.resultados) == {"B_con_pista", "C_pipeline"} for c in casos))
        self.assertTrue(all("Protagonista: 1Hero (mujer)" in p for p in prompts_vistos))
        texto = evaluar.tabla(evaluar.resumir(casos))
        self.assertNotIn("A. antes", texto)
        self.assertIn("habla la protagonista", texto)
        self.assertIn("habla otro personaje", texto)

    def test_condicion_d_sin_hablante(self):
        """D (Unity): la ficha está en el contexto, pero el prompt no dice quién habla y la concordancia
        no puede arreglar la 1.ª persona de Laura."""
        casos = evaluar.casos_rpgmaker("prueba", self.tmp, _ficha())
        laura = next(c for c in casos if c.hablante == "Laura")
        perfil = config.Perfil(personajes=_ficha(), contexto="Protagonista: 1Hero (hombre).")
        prompts_vistos = []

        def generar(self, prompt, num_predict, temperature=0.1):
            prompts_vistos.append(prompt)
            return "Estoy tan cansado. He trabajado todo el día."

        with mock.patch.object(OllamaTranslator, "_generar", generar):
            ev = evaluar.Evaluador("modelo_prueba", perfil, sin_hablante=True)
            res = ev.evaluar(laura)
            ev.cerrar()
        self.assertEqual(set(res), {"A_antes", "B_con_pista", "C_pipeline", "D_sin_hablante"})
        self.assertEqual(res["C_pipeline"]["nota"], "correcto")
        self.assertEqual(res["D_sin_hablante"]["nota"], "contrario")      # nadie sabe que habla Laura
        self.assertNotIn("Habla Laura", prompts_vistos[-1])
        self.assertIn("Protagonista: 1Hero (hombre)", prompts_vistos[-1])
        self.assertIn("D. sin hablante (Unity)", evaluar.tabla(evaluar.resumir([laura])))

    def test_calidad_general(self):
        muestra = evaluar.muestra_general(self.tmp, 10)
        self.assertEqual([t for t, _ in muestra].count("Hello there."), 0)   # < 12 caracteres: fuera
        self.assertEqual(len(muestra), 2)
        perfil = config.Perfil(personajes=_ficha(), contexto="x")
        respuestas = iter(["Estoy tan cansada. He trabajado todo el día.", "I'm not sure about this."])
        with mock.patch.object(OllamaTranslator, "_generar", lambda self, *a, **k: next(respuestas)):
            ev = evaluar.Evaluador("modelo_prueba", perfil)
            resultados = [ev.calidad(t, i) for t, i in muestra]
            ev.cerrar()
        r = evaluar.resumir_calidad(resultados)
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["con_fallo_grave"], 1)                 # la que quedó en inglés
        self.assertTrue({"sin_traducir", "ingles_residual"} & set(r["problemas"]), r["problemas"])
        self.assertIn("1 ( 50.0 %) con fallos graves", evaluar.tabla_calidad(r))


if __name__ == "__main__":
    unittest.main()
