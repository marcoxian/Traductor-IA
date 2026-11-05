"""Q3: al cambiar de modelo se reaprovechan las traducciones del anterior SIN marcas de género.

Ningún test llama a Ollama (``_generar`` está simulado).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor.config import Perfil, huella_contexto
from traductor.ollama import OllamaTranslator
from traductor.personajes import FichaPersonajes, InfoLinea, Personaje


class TestCacheDeOtroModelo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cache"
        self.cache.mkdir()

    def _traductor(self, modelo: str, perfil: Perfil) -> OllamaTranslator:
        t = OllamaTranslator(model_name=modelo, perfil=perfil, ruta_cache=self.cache / f"cache_{modelo}.json")
        self.addCleanup(t.cerrar)
        t._generar = mock.MagicMock(return_value="Traducción nueva.")
        return t

    def _cache_antigua(self, perfil: Perfil, pares: dict[str, str], modelo: str = "IA_Traductora",
                       con_ficha_antigua: bool = False) -> Path:
        """Escribe la caché que habría dejado ``modelo`` (claves calculadas como las calcula él)."""
        viejo = OllamaTranslator(model_name=modelo, perfil=perfil, ruta_cache=None)
        datos = {}
        for en, es in pares.items():
            terminos = perfil.terminos_para(en)
            clave = (viejo._clave(en, terminos, "", perfil.huella_legacy) if con_ficha_antigua
                     else viejo._clave(en, terminos))
            datos[clave] = es
        ruta = self.cache / f"cache_{modelo}.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return ruta

    def test_reutiliza_lo_que_no_tiene_genero_y_retraduce_lo_demas(self):
        perfil = Perfil(contexto="CTX")
        ruta = self._cache_antigua(perfil, {"Open the door.": "Abre la puerta.", "I'm tired.": "Estoy cansado."})
        antes = ruta.read_text(encoding="utf-8")
        t = self._traductor("IA_Traductora_v4", perfil)
        self.assertEqual(t.reaprovechar_cache_de(), "IA_Traductora")  # la encuentra sola
        self.assertEqual(t.translate("Open the door."), "Abre la puerta.")
        t._generar.assert_not_called()
        self.assertEqual(t.translate("I'm tired."), "Traducción nueva.")
        self.assertEqual(t._generar.call_count, 1)
        self.assertEqual(t.estadisticas["cache_otro_modelo"], 1)
        self.assertEqual(t.estadisticas["otro_modelo_con_genero"], 1)
        t.cerrar()
        self.assertEqual(ruta.read_text(encoding="utf-8"), antes)  # la caché del otro modelo no se toca
        nueva = json.loads((self.cache / "cache_IA_Traductora_v4.json").read_text(encoding="utf-8"))
        self.assertIn("Abre la puerta.", nueva.values())  # queda guardada con la clave del modelo nuevo

    def test_lotes_tambien(self):
        perfil = Perfil(contexto="CTX")
        self._cache_antigua(perfil, {"Open the door.": "Abre la puerta."})
        t = self._traductor("IA_Traductora_v4", perfil)
        t.tam_lote = 20
        t.reaprovechar_cache_de("IA_Traductora")
        self.assertEqual(t.traducir_textos(["Open the door."]), ["Abre la puerta."])
        t._generar.assert_not_called()

    def test_elige_la_cache_mas_completa_y_nunca_la_propia(self):
        perfil = Perfil(contexto="CTX")
        self._cache_antigua(perfil, {"A.": "A.", "B.": "B.", "C.": "C."}, modelo="IA_Traductora")
        self._cache_antigua(perfil, {"A.": "A."}, modelo="IA_Traductora_v2")
        t = self._traductor("IA_Traductora_v4", perfil)
        self.assertEqual(t.reaprovechar_cache_de(), "IA_Traductora")
        solo = self._traductor("IA_Traductora", perfil)
        self.assertEqual(solo.reaprovechar_cache_de(), "IA_Traductora_v2")
        self.assertIsNone(solo.reaprovechar_cache_de("IA_Traductora"))  # la suya no es "otro modelo"
        self.assertIsNone(self._traductor("IA_Traductora_v4", perfil).reaprovechar_cache_de("no_existe"))

    def test_sin_reaprovechar_no_cambia_nada(self):
        perfil = Perfil(contexto="CTX")
        self._cache_antigua(perfil, {"Open the door.": "Abre la puerta."})
        t = self._traductor("IA_Traductora_v4", perfil)
        self.assertEqual(t.translate("Open the door."), "Traducción nueva.")

    def test_con_ficha_sirve_la_cache_de_antes_de_la_ficha(self):
        ficha = FichaPersonajes(personajes=[Personaje(nombre="Zoe", genero="mujer", rol="protagonista"),
                                            Personaje(nombre="Ana", genero="mujer", rol="principal")])
        perfil = Perfil(juego="prueba", contexto="CTX", personajes=ficha, huella_legacy=huella_contexto("ANTIGUO"))
        self._cache_antigua(perfil, {"Open the door.": "Abre la puerta.", "I'm tired.": "Estoy cansado."},
                            con_ficha_antigua=True)
        t = self._traductor("IA_Traductora_v4", perfil)
        t.reaprovechar_cache_de("IA_Traductora")
        info = InfoLinea(hablante="Ana")
        self.assertEqual(t.translate("Open the door.", info=info), "Abre la puerta.")
        t._generar.assert_not_called()
        t.translate("I'm tired.", info=info)  # "cansado" con hablante mujer: lo traduce el modelo nuevo
        self.assertEqual(t._generar.call_count, 1)


def _mapa(*lineas: str) -> dict:
    """Mapa con un evento por línea (cada línea es su propio mensaje)."""
    eventos: list = [None]
    for i, linea in enumerate(lineas, 1):
        eventos.append({"id": i, "name": f"EV{i}", "x": i, "y": 1, "note": "", "pages": [{"list": [
            {"code": 401, "parameters": [linea], "indent": 0}, {"code": 0, "parameters": []}]}]})
    return {"displayName": "", "events": eventos}


class TestSoloGenero(unittest.TestCase):
    """--solo-genero: el juego ya traducido conserva lo que no tiene género; el resto lo traduce el modelo."""

    RESPUESTAS = {"I'm tired.": "Estoy cansada.", "Hello there.": "Hola.", "Open the door.": "Abre esa puerta."}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data = self.tmp / "Juego" / "www" / "data"
        self.data.mkdir(parents=True)
        (self.data / "Map001.json.bak").write_text(
            json.dumps(_mapa("Open the door.", "I'm tired.", "Hello there.")), encoding="utf-8")
        self._traduccion_actual(_mapa("Abre la puerta.", "Estoy cansado.", "Hello there."))

    def _traduccion_actual(self, mapa: dict) -> None:
        (self.data / "Map001.json").write_text(json.dumps(mapa, ensure_ascii=False), encoding="utf-8")

    def _procesar(self, reaprovechar: bool) -> tuple[list[str], list[str]]:
        from traductor.motores.rpgmaker import InyectorRPGMaker
        t = OllamaTranslator(model_name="IA_Traductora_v4", perfil=Perfil(contexto="CTX"),
                             ruta_cache=self.tmp / "cache.json")
        self.addCleanup(t.cerrar)
        t._generar = mock.MagicMock(side_effect=lambda prompt, *a, **kw: self.RESPUESTAS.get(
            prompt.split("### Input:\n", 1)[1].split("\n\n### Response:", 1)[0], "Texto nuevo."))
        InyectorRPGMaker(self.data.parent.parent, t, reaprovechar_traduccion=reaprovechar).procesar()
        pedidas = [c[0][0].split("### Input:\n", 1)[1].split("\n\n### Response:", 1)[0]
                   for c in t._generar.call_args_list]
        mapa = json.loads((self.data / "Map001.json").read_text(encoding="utf-8"))
        return pedidas, [ev["pages"][0]["list"][0]["parameters"][0] for ev in mapa["events"][1:]]

    def test_solo_se_retraduce_lo_que_tiene_genero_o_sigue_en_ingles(self):
        pedidas, final = self._procesar(reaprovechar=True)
        self.assertEqual(sorted(pedidas), ["Hello there.", "I'm tired."])
        self.assertEqual(final, ["Abre la puerta.", "Estoy cansada.", "Hola."])

    def test_sin_la_opcion_se_traduce_todo(self):
        pedidas, final = self._procesar(reaprovechar=False)
        self.assertEqual(sorted(pedidas), ["Hello there.", "I'm tired.", "Open the door."])
        self.assertEqual(final, ["Abre esa puerta.", "Estoy cansada.", "Hola."])

    def test_si_no_se_puede_emparejar_se_traduce_entero(self):
        self._traduccion_actual(_mapa("Abre la puerta.", "Estoy cansado."))  # falta una frase
        pedidas, _ = self._procesar(reaprovechar=True)
        self.assertEqual(sorted(pedidas), ["Hello there.", "I'm tired.", "Open the door."])


if __name__ == "__main__":
    unittest.main()
