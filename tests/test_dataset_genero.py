"""Pruebas de herramientas_extra/dataset_genero.py (reparar corpus y generar ejemplos con pistas)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas_extra"))

import dataset_genero  # noqa: E402
from traductor.genero import marcas_genero  # noqa: E402
from traductor.personajes import FichaPersonajes, Personaje  # noqa: E402


def _ficha() -> FichaPersonajes:
    return FichaPersonajes([
        Personaje("1Hero", "hombre", "protagonista", codigos=["He"]),
        Personaje("Ana", "mujer", "principal", codigos=["Al"]),
        Personaje("Bradley", "hombre", "principal", codigos=["Br"]),
    ])


class TestDatasetGenero(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.corpus = self.tmp / "corpus.jsonl"
        registros = [
            {"input": "Al,Sa,Op.What? I'm confused.", "output": "Al,Sa,Op.¿Qué? Estoy confundido."},   # Ana en masculino
            {"input": "HeFrOp.I'm ready for more.", "output": "HeFrOp.Estoy listo para más."},
            {"input": "BrFrOp.I'm sure.", "output": "BrFrOp.Estoy seguro."},
            {"input": "AlFrOp.The weather is nice today.", "output": "AlFrOp.Hace buen tiempo hoy."},
            {"input": "BrFrOp.Let's go to the beach.", "output": "BrFrOp.Vamos a la playa."},
            {"input": "AlFrOp.Where is the key?", "output": "AlFrOp.¿Dónde está la llave?"},
            {"input": "Sin hablante conocido.", "output": "Sin hablante conocido."},
        ]
        self.corpus.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reparar_con_copia(self):
        stats = dataset_genero.procesar(self.corpus, _ficha(), reparar=True)
        self.assertEqual(stats["corregidas"], 1)
        lineas = [json.loads(l) for l in self.corpus.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lineas[0]["output"], "Al,Sa,Op.¿Qué? Estoy confundida.")  # se conserva el prefijo de hablante
        self.assertEqual(lineas[1]["output"], "HeFrOp.Estoy listo para más.")
        self.assertTrue(self.corpus.with_name("corpus.jsonl.bak").exists())

    def test_generar_con_espejo_y_neutros_limitados(self):
        salida = self.tmp / "dataset_genero_prueba.jsonl"
        stats = dataset_genero.procesar(self.corpus, _ficha(), generar=salida, proporcion_neutros=1.0,
                                        espejo_protagonista=False)
        ejemplos = [json.loads(l) for l in salida.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(stats["ejemplos_con_genero"], 3)
        self.assertEqual(stats["ejemplos_espejo"], 3)
        self.assertEqual(stats["ejemplos_neutros"], 3)   # 1 neutro por cada ejemplo con marca (hay 3 disponibles)
        self.assertEqual(len(ejemplos), 9)
        por_salida = {(e["output"], e["contexto"]): e for e in ejemplos}
        # Original corregido: Ana (mujer)
        self.assertIn(("¿Qué? Estoy confundida.", "genero_hablante"), por_salida)
        # Espejo: misma frase, pista "Ana (hombre)" y salida en masculino
        espejo = por_salida[("¿Qué? Estoy confundido.", "genero_hablante_espejo")]
        self.assertIn("Habla Ana (hombre)", espejo["instruccion_completa"])
        # Espejo del protagonista: cambia también la regla del CONTEXTO
        prota = por_salida[("Estoy lista para más.", "genero_hablante_espejo")]
        self.assertIn("Protagonista: 1Hero (mujer)", prota["instruccion_completa"])
        self.assertNotIn("(hombre). Cuando él", prota["instruccion_completa"])
        for e in ejemplos:
            if e["contexto"] == "genero_hablante_espejo":
                self.assertTrue(marcas_genero(e["output"]))

    def test_sin_espejo_y_sin_neutros(self):
        salida = self.tmp / "dataset_genero_prueba.jsonl"
        stats = dataset_genero.procesar(self.corpus, _ficha(), generar=salida, proporcion_neutros=0, espejo=False,
                                        espejo_protagonista=False)
        self.assertEqual(stats["ejemplos"], 3)
        self.assertEqual(stats["ejemplos_espejo"], 0)
        self.assertEqual(stats["ejemplos_espejo_protagonista"], 0)

    def test_neutros_deterministas(self):
        a = self.tmp / "a.jsonl"
        b = self.tmp / "b.jsonl"
        dataset_genero.procesar(self.corpus, _ficha(), generar=a, proporcion_neutros=0.5)
        dataset_genero.procesar(self.corpus, _ficha(), generar=b, proporcion_neutros=0.5)
        self.assertEqual(a.read_bytes(), b.read_bytes())


def _ficha_henry() -> FichaPersonajes:
    return FichaPersonajes([
        Personaje("1Hero", "hombre", "protagonista", alias=["Henry"], codigos=["He"]),
        Personaje("Ana", "mujer", "principal", codigos=["Al"]),
        Personaje("Bradley", "hombre", "principal", codigos=["Br"]),
    ])


class TestEspejoProtagonista(unittest.TestCase):
    """La familia con la protagonista MUJER: lo que el corpus de Nora (protagonista hombre) no tiene."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.corpus = self.tmp / "corpus.jsonl"
        registros = [
            {"input": "BrFrOp.I'm sure.", "output": "BrFrOp.Estoy seguro."},                       # hombre -> prota
            {"input": "AlFrOp.What? I'm confused.", "output": "AlFrOp.¿Qué? Estoy confundida."},   # mujer -> prota
            {"input": "AlFrOp.Are you ready, 1Hero?", "output": "AlFrOp.¿Estás listo, 1Hero?"},    # 2.ª persona
            {"input": "HeFrOp.I'm ready for more.", "output": "HeFrOp.Estoy listo para más."},     # habla la prota
            {"input": "AlFrOp.Are you sure, sir?", "output": "AlFrOp.¿Estás seguro, señor?"},      # "sir": no
            {"input": "AlFrOp.Henry, I'm ready.", "output": "AlFrOp.Henry, estoy lista."},         # alias con género
            {"input": "AlFrOp.1Hero is so tired.", "output": "AlFrOp.1Hero está tan cansado."},    # 3.ª persona
            {"input": "AlFrOp.I'm a good girl. I'm ready.", "output": "AlFrOp.Soy una buena chica. Estoy lista."},
            {"input": "BrFrOp.Let's go to the beach.", "output": "BrFrOp.Vamos a la playa."},      # neutra
        ]
        self.corpus.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros), encoding="utf-8")
        self.salida = self.tmp / "dataset_genero_prueba.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _generar(self, **kw):
        stats = dataset_genero.procesar(self.corpus, _ficha_henry(), generar=self.salida, **kw)
        ejemplos = [json.loads(l) for l in self.salida.read_text(encoding="utf-8").splitlines()]
        return stats, ejemplos

    def test_hombre_y_mujer_hablan_a_una_protagonista_mujer(self):
        _, ejemplos = self._generar(proporcion_neutros=0, espejo=False)
        inv = [e for e in ejemplos if e["contexto"] in ("genero_protagonista_espejo", "genero_doble_espejo")]
        por_salida = {(e["output"], e["contexto"]): e["instruccion_completa"] for e in inv}
        # Un hombre le habla a la protagonista mujer: su 1.ª persona sigue en masculino
        bradley = por_salida[("Estoy seguro.", "genero_protagonista_espejo")]
        self.assertIn("Habla Bradley (hombre)", bradley)
        self.assertIn("se dirige a 1Hero (mujer)", bradley)
        self.assertIn("Protagonista: 1Hero (mujer)", bradley)
        # Una mujer le habla a otra mujer
        ana = por_salida[("¿Qué? Estoy confundida.", "genero_protagonista_espejo")]
        self.assertIn("Habla Ana (mujer)", ana)
        self.assertIn("se dirige a 1Hero (mujer)", ana)
        # Doble espejo: hombre (Ana invertida) que habla a la protagonista mujer
        doble = por_salida[("¿Qué? Estoy confundido.", "genero_doble_espejo")]
        self.assertIn("Habla Ana (hombre)", doble)
        self.assertIn("1Hero (mujer)", doble)
        # 2.ª persona invertida con vocativo explícito
        self.assertIn(("¿Estás lista, 1Hero?", "genero_protagonista_espejo"), por_salida)
        self.assertIn("Se dirige a 1Hero (mujer)", por_salida[("¿Estás lista, 1Hero?", "genero_protagonista_espejo")])
        # Habla la protagonista (sin el espejo del hablante sale de aquí)
        self.assertIn(("Estoy lista para más.", "genero_protagonista_espejo"), por_salida)

    def test_no_inventa_ejemplos_que_el_ingles_contradice(self):
        _, ejemplos = self._generar(proporcion_neutros=1.0)
        inv = [e for e in ejemplos if e["contexto"] != "genero_hablante"]
        prota_mujer = [e for e in inv if e["contexto"] in ("genero_protagonista_espejo", "genero_doble_espejo")]
        salidas = {e["output"] for e in inv}
        self.assertNotIn("¿Estás segura, señor?", salidas)
        # "Henry" (alias con género del protagonista): vale si sigue siendo hombre, no si pasa a mujer
        self.assertFalse(any(e["input"].startswith("Henry") for e in prota_mujer))
        self.assertFalse(any("1Hero is so tired" in e["input"] for e in prota_mujer))  # 3.ª persona
        # "good girl": ni espejo del hablante (un hombre no lo diría) ni doble espejo
        self.assertFalse(any("good girl" in e["input"] and "(hombre)" in e["instruccion_completa"].split("PERSONAJES")[-1]
                             for e in inv))
        self.assertTrue(prota_mujer)
        for e in prota_mujer:
            self.assertNotIn("(hombre). Cuando él", e["instruccion_completa"])
            self.assertIn("Protagonista: 1Hero (mujer)", e["instruccion_completa"])

    def test_sin_duplicados_y_neutros_limitados(self):
        stats, ejemplos = self._generar(proporcion_neutros=1.0)
        claves = [(e["input"], e["output"], e["instruccion_completa"]) for e in ejemplos]
        self.assertEqual(len(claves), len(set(claves)))
        self.assertLessEqual(stats["ejemplos_neutros_protagonista"], stats["ejemplos_espejo_protagonista"])
        self.assertEqual(stats["ejemplos"], len(ejemplos))
        neutra = [e for e in ejemplos if e["output"] == "Vamos a la playa." and "1Hero (mujer)" in e["instruccion_completa"]]
        self.assertEqual(len(neutra), 1)

    def test_sin_espejo_si_el_contenido_fija_el_sexo(self):
        registros = [
            {"input": "AlFrOp.Oh! I'm so wet!", "output": "AlFrOp.¡Oh! ¡Estoy tan mojada!"},           # anatomía
            {"input": "HeFrOp.I'm ready. Look at my dick!", "output": "HeFrOp.Estoy listo. ¡Mira mi polla!"},
            {"input": "AlFrOp.I'm sure you're a brave sailor.",
             "output": "AlFrOp.Estoy segura de que eres un marinero valiente."},                    # sustantivo
            {"input": "AlFrOp.I am a maid. I'm ready.", "output": "AlFrOp.Soy una criada. Estoy lista."},
            {"input": "AlFrOp.I'm ready.", "output": "AlFrOp.Estoy lista."},                         # control
        ]
        self.corpus.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros), encoding="utf-8")
        _, ejemplos = self._generar(proporcion_neutros=0)
        espejos = [e for e in ejemplos if e["contexto"] != "genero_hablante"]
        entradas = {e["input"] for e in espejos}
        self.assertNotIn("Oh! I'm so wet!", entradas)
        self.assertNotIn("I'm ready. Look at my dick!", entradas)
        # "soy una criada" dicho por un hombre: ni espejo del hablante ni doble; a la protagonista mujer, sí
        criada = {e["contexto"] for e in espejos if "maid" in e["input"]}
        self.assertEqual(criada, {"genero_protagonista_espejo"})
        # "eres un marinero": no a la protagonista mujer, pero sí el espejo de quien habla (Ana hombre)
        marinero = [e for e in espejos if "sailor" in e["input"]]
        self.assertEqual([e["contexto"] for e in marinero], ["genero_hablante_espejo"])
        self.assertEqual(marinero[0]["output"], "Estoy seguro de que eres un marinero valiente.")
        self.assertIn("I'm ready.", entradas)
        # Los originales se quedan
        self.assertIn("¡Oh! ¡Estoy tan mojada!", {e["output"] for e in ejemplos})

    def test_desactivable(self):
        stats, ejemplos = self._generar(proporcion_neutros=1.0, espejo_protagonista=False)
        self.assertFalse(any("1Hero (mujer)" in e["instruccion_completa"] and e["contexto"] != "genero_hablante_espejo"
                             for e in ejemplos))
        self.assertEqual(stats["ejemplos_doble_espejo"], 0)


if __name__ == "__main__":
    unittest.main()
