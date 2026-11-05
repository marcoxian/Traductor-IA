"""Tests de la puerta de calidad y gestión avanzada de etiquetas (traductor/texto.py)."""
import unittest

from unittest.mock import MagicMock

from traductor import config
from traductor.personajes import FichaPersonajes, Personaje
from traductor.texto import (
    comparar_etiquetas,
    evaluar_traduccion,
    extraer_etiquetas,
    forzar_etiquetas,
    gravedad,
    limpiar_respuesta,
    nombres_perdidos,
    nota_reintento,
    quitar_etiquetas_inventadas,
    separar_envoltorio,
    tiene_fallo_grave,
)


class TestNombresPerdidos(unittest.TestCase):
    def test_detecta_nombre_que_desaparece(self):
        # Caso real de v3 en Otro Juego
        self.assertEqual(nombres_perdidos("Sala de la Escuela Secundaria del Condado", ["Marina"]), ["Marina"])
        self.assertEqual(nombres_perdidos("Gracias.", ["Ana"]), ["Ana"])

    def test_acepta_tildes_adaptaciones_y_nombres_genericos(self):
        self.assertEqual(nombres_perdidos("SCN - Habitación de Marina Brians", ["Marina"]), [])
        self.assertEqual(nombres_perdidos("Gracias, Sofía.", ["Sofia"]), [])
        self.assertEqual(nombres_perdidos("Es el Oráculo.", ["Oracle"]), [])          # misma raíz
        self.assertEqual(nombres_perdidos("El padre Brian lo sabe.", ["Father Brian"]), [])
        self.assertEqual(nombres_perdidos("Tío, estoy cansado.", ["Man", "Old Man"]), [])  # se traducen
        self.assertEqual(nombres_perdidos("¡Guardia!", ["Guard"]), [])
        self.assertEqual(nombres_perdidos("\\C[2]ANA\\C[0]: hola", ["ANA"]), [])

    def _traductor(self):
        from traductor.ollama import OllamaTranslator
        ficha = FichaPersonajes([Personaje("1Hero", "hombre", "protagonista"),
                                 Personaje("Marina", "mujer", "principal")])
        return OllamaTranslator(reintentos_calidad=3, perfil=config.Perfil(personajes=ficha, contexto="x"),
                                ruta_cache=None)

    def test_reintenta_pidiendo_el_nombre(self):
        t = self._traductor()
        t._generar = MagicMock(side_effect=["Sala de la escuela", "Habitación de Marina"])
        self.assertEqual(t.translate("Marina's Room"), "Habitación de Marina")
        self.assertEqual(t._generar.call_count, 2)
        nota = t._generar.call_args_list[1][0][0].split("IMPORTANTE:")[-1]
        self.assertIn("Marina", nota.split("### Input")[0])

    def test_acepta_la_mejor_si_nunca_conserva_el_nombre(self):
        t = self._traductor()
        t._generar = MagicMock(return_value="Sala de la escuela")
        self.assertEqual(t.translate("Marina's Room"), "Sala de la escuela")
        self.assertEqual(t._generar.call_count, 3)
        self.assertEqual(len(t.cache), 1)                       # no es grave: se guarda
        self.assertEqual(t.estadisticas["rechazadas_calidad"], 0)

    def test_sin_ficha_no_cambia_nada(self):
        from traductor.ollama import OllamaTranslator
        t = OllamaTranslator(reintentos_calidad=3, ruta_cache=None)
        t._generar = MagicMock(return_value="Sala de la escuela")
        self.assertEqual(t.translate("Marina's Room"), "Sala de la escuela")
        self.assertEqual(t._generar.call_count, 1)


class TestEtiquetasYEnvoltorio(unittest.TestCase):
    def test_llaves_con_espacios_no_son_etiquetas(self):
        # Caso real: encabezados entre llaves que antes se pegaban al principio
        orig = "WELCOME!\n{Lesson 1: Home Row}\nPlace your fingers."
        self.assertEqual(extraer_etiquetas(orig), [])
        # Pero {name} y [pic=2] sin espacios sí son etiquetas
        self.assertEqual(extraer_etiquetas("Hi {name} [pic=2]"), ["{name}", "[pic=2]"])

    def test_separar_envoltorio(self):
        pref, nuc, suf = separar_envoltorio("<i>She watches me with fascination.</i> [picc=16]")
        self.assertEqual(pref, "<i>")
        self.assertEqual(nuc, "She watches me with fascination.")
        self.assertEqual(suf, "</i> [picc=16]")

        # Si solo hay etiquetas sin letras visibles no se parte
        self.assertEqual(separar_envoltorio("... [pic=41]"), ("", "... [pic=41]", ""))

    def test_quitar_etiquetas_inventadas_y_sustituir_corruptas(self):
        # Caso real: el modelo añade [pic=n] al final además del [pic=9] real
        orig = "Are you really in a position to be correcting me? [pic=9]"
        trad = "[pic=9] ¿Realmente estás en posición de corregirme? [pic=n]"
        limpio = quitar_etiquetas_inventadas(orig, trad)
        self.assertTrue(comparar_etiquetas(orig, limpio)[0])
        self.assertNotIn("[pic=n]", limpio)

        # Si corrompió [pic=9] -> [pic=n], lo reemplaza por [pic=9]
        trad2 = "¿Realmente estás en posición de corregirme? [pic=n]"
        limpio2 = quitar_etiquetas_inventadas(orig, trad2)
        self.assertEqual(limpio2, "¿Realmente estás en posición de corregirme? [pic=9]")

    def test_forzar_etiquetas_respeta_posicion_final(self):
        orig = "<i>What have I gotten myself into?!</i> [picc=11]"
        trad = "¡¿En qué me he metido?! [picc=11]"
        res = forzar_etiquetas(orig, trad)
        self.assertEqual(res, "<i>¡¿En qué me he metido?!</i> [picc=11]")
        self.assertTrue(comparar_etiquetas(orig, res)[0])


class TestPuertaCalidad(unittest.TestCase):
    def test_traduccion_correcta_sin_problemas(self):
        orig = "Good evening, sir. The pool area is currently closed. [pic=9]"
        trad = "Buenas noches, señor. La zona de la piscina está cerrada ahora mismo. [pic=9]"
        self.assertEqual(evaluar_traduccion(orig, trad), [])
        self.assertFalse(tiene_fallo_grave([]))
        self.assertEqual(gravedad([]), 0)

    def test_detecta_sin_traducir(self):
        self.assertIn("sin_traducir", evaluar_traduccion("Cute Songbird", "Cute Songbird"))
        self.assertIn("sin_traducir", evaluar_traduccion("<i>Giggle</i> [pic=2]", "<i>Giggle</i> [pic=2]"))
        self.assertIn("sin_traducir", evaluar_traduccion("I'll be quick, I promise.", "I'll be quick, I promise."))

    def test_acepta_onomatopeyas_e_identificadores_identicos(self):
        for s in ("No", "Mmmhh...", "O..kay... [picc=11]", "... [pic=41]", "ViliCatchQuest", "Oh no..."):
            self.assertEqual(evaluar_traduccion(s, s), [], f"Falso positivo en {s!r}")

    def test_detecta_ingles_residual(self):
        orig = "H-how are you so strong?! I can't move!!!"
        trad = "¿¡H-how are you so strong?! I can't move!!!"
        probs = evaluar_traduccion(orig, trad)
        self.assertIn("ingles_residual", probs)
        self.assertTrue(tiene_fallo_grave(probs))

    def test_detecta_ingles_sin_senales_de_espanol(self):
        """Pocas palabras de la lista inglesa, pero ni una señal de español: es inglés."""
        orig = r"In just a few moments, he'd managed to strip completely naked. \!His rod juts forward."
        trad = r"In just a few moments, he managed to strip completely naked. \!His rod juts forward."
        self.assertIn("ingles_residual", evaluar_traduccion(orig, trad))
        bien = r"En pocos momentos, se había desnudado por completo. \!Su miembro se alza hacia delante."
        self.assertEqual(evaluar_traduccion(orig, bien), [])
        sin_tildes = "Bien, vamos a ver si sirve para algo, Tanya."  # español sin tildes: no salta
        self.assertNotIn("ingles_residual", evaluar_traduccion("Okay, let's see if it helps at all, Tanya.", sin_tildes))

    def test_detecta_frase_recortada(self):
        orig = "Did your keen detective instincts lead you here? Or is this just a fortunate mistake? [pic=8]"
        trad = "¿O es solo un error afortunado? [pic=8]"
        self.assertIn("longitud_corta", evaluar_traduccion(orig, trad))

    def test_detecta_alucinacion_larga(self):
        orig = "Blocking your mind?! [pic=41]"
        trad = ("¿¡Espera! Esto no está bien! Tu mente no es la de un ser humano normal, "
                "también es antigua. Es como si hubiera algo más ahí dentro bloqueándolo todo. [pic=41]")
        self.assertIn("longitud_larga", evaluar_traduccion(orig, trad))

    def test_detecta_vacia_cuando_solo_quedan_simbolos(self):
        orig = "♪♪♪♪♪♪♪♪♪♪Hello, room service at your service! [pic=41]"
        trad = "♪♪♪♪♪♪♪♪♪♪ [pic=41]"
        self.assertIn("vacia", evaluar_traduccion(orig, trad))

    def test_limpia_y_detecta_repeticion(self):
        orig = "<i>!!!...Why did she stop I was so close...hah!!!</i>"
        bruto = "<i>¡¿¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡... Por qué se detuvo... ¡¿hah?!</i>"
        limpio = limpiar_respuesta(bruto, orig)
        self.assertNotIn("¡¡¡¡¡¡", limpio)

        # Bucle de palabras
        probs = evaluar_traduccion("Wait for me there.", "Espérame allí allí allí allí allí.")
        self.assertIn("repeticion", probs)
        self.assertTrue(nota_reintento(probs))


class TestOllamaQualityGate(unittest.TestCase):
    def test_reintenta_cuando_primera_respuesta_queda_en_ingles(self):
        from unittest.mock import MagicMock
        from traductor.ollama import OllamaTranslator

        t = OllamaTranslator(reintentos_calidad=3)
        respuestas = ["<i>Giggle</i>", "Risita"]
        t._generar = MagicMock(side_effect=respuestas)

        res = t.translate("<i>Giggle</i> [pic=2]")
        self.assertEqual(res, "<i>Risita</i> [pic=2]")
        self.assertEqual(t._generar.call_count, 2)
        self.assertEqual(t.estadisticas["reintentadas_calidad"], 1)

    def test_guarda_caso_dificil_solo_si_se_activa(self):
        import json
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from traductor.ollama import OllamaTranslator

        tmp = Path(tempfile.mkdtemp())
        try:
            # Sin activar: no se escribe nada (las pruebas nunca tocan workspace/)
            t = OllamaTranslator(reintentos_calidad=3)
            t._generar = MagicMock(side_effect=["Giggle", "Risita"])
            t.translate("Giggle")
            self.assertIsNone(t.ruta_casos_dificiles)
            # Activado: el primer intento (sin traducir) se rechaza y el reintento se guarda como ejemplo
            ruta = tmp / "casos_dificiles.jsonl"
            t = OllamaTranslator(reintentos_calidad=3)
            t.activar_casos_dificiles(ruta)
            t._generar = MagicMock(side_effect=["Giggle", "Risita"])
            self.assertEqual(t.translate("Giggle"), "Risita")
            t._generar = MagicMock(return_value="Hola.")
            t.translate("Hello.")  # bien a la primera: no es un caso difícil
            registros = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(registros), 1)
            r = registros[0]
            self.assertEqual((r["input"], r["output"], r["rechazada"]), ("Giggle", "Risita", "Giggle"))
            self.assertIn("sin_traducir", r["problemas"])
            self.assertIn("Traduce este texto", r["instruccion_completa"])
            self.assertNotIn("IMPORTANTE", r["instruccion_completa"])  # sin la nota del reintento
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_cachea_fallo_y_lanza_error_si_se_pide(self):
        from unittest.mock import MagicMock
        from traductor.ollama import OllamaTranslator, TraduccionFallida

        t = OllamaTranslator(reintentos_calidad=2)
        t._generar = MagicMock(return_value="Cute Songbird")

        with self.assertRaises(TraduccionFallida):
            t.translate("Cute Songbird", lanzar_error=True)
        self.assertEqual(len(t.cache), 0)

    def test_preserva_saltos_en_documentos_multilinea(self):
        from unittest.mock import MagicMock
        from traductor.ollama import OllamaTranslator

        t = OllamaTranslator(reintentos_calidad=1)
        mapa = {
            "First sentence.": "Primera frase.",
            "Second sentence.": "Segunda frase.",
        }
        t._generar = MagicMock(side_effect=lambda prompt, *a, **kw: (
            "Primera frase." if "First sentence." in prompt else "Segunda frase."
        ))
        res = t.translate("First sentence.\n────\nSecond sentence.")
        self.assertEqual(res, "Primera frase.\n────\nSegunda frase.")

    def test_migracion_cache_descarta_rotas_y_conserva_buenas(self):
        from traductor.ollama import OllamaTranslator

        t = OllamaTranslator()
        aceptadas, rechazadas = t.importar_pares_externos({
            "Red Potion": "Poción Roja",
            "Cute Songbird": "Cute Songbird",  # sin traducir -> rechazada
            "<i>She watches me.</i>": "<i>Me observa.",  # falta </i> -> se repara y acepta
        }, guardar=False)
        self.assertEqual(aceptadas, 2)
        self.assertEqual(rechazadas, 1)

    def test_resolver_perfil_con_sufijo_demo(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from traductor import config
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "juego_unity").mkdir()
            with mock.patch.object(config, "DIR_WORKSPACE", Path(tmp)):
                self.assertEqual(config.resolver_perfil_existente("juego_unity_demo"), "juego_unity")


if __name__ == "__main__":
    unittest.main()
