"""Glosario de la base de datos de RPG Maker (P2) y nombre visible de los mapas (P5).

Ningún test llama a Ollama (``_generar`` está simulado) ni toca workspace/ real.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor import config
from traductor.config import Perfil
from traductor.motores.rpgmaker import InyectorRPGMaker
from traductor.ollama import OllamaTranslator
from traductor.personajes import FichaPersonajes, Personaje


def _perfil_bd(**kw) -> Perfil:
    return Perfil(glosario_bd={"Rough Diamond": "Diamante en bruto", "Stick": "Palo", "Album": "Álbum"},
                  glosario_bd_frases=frozenset({"Rough Diamond"}), **kw)


def _entrada(prompt: str) -> str:
    return prompt.split("### Input:\n", 1)[1].split("\n\n### Response:", 1)[0]


# Lo que "contesta el modelo" en las pruebas
TRADUCCIONES = {
    "Rough Diamond": "Diamante en bruto", "Stick": "Palo", "Album": "Álbum", "Fire": "Fuego",
    "Ariel": "Ariel", "A shiny rock.": "Una roca brillante.", "A wooden stick.": "Un palo de madera.",
    "Photos.": "Fotos.", "I found a Rough Diamond and a Stick.": "Encontré un diamante en bruto y un palo.",
}


def _modelo_falso(prompt: str, *a, **kw) -> str:
    entrada = _entrada(prompt)
    return TRADUCCIONES.get(entrada, f"ES {entrada}")


class TestPerfilGlosarioBD(unittest.TestCase):
    def test_texto_entero_copia_la_traduccion_con_sus_codigos(self):
        p = _perfil_bd()
        self.assertEqual(p.traduccion_exacta("Rough Diamond"), "Diamante en bruto")
        self.assertEqual(p.traduccion_exacta("\\c[23]Album\\c[0]"), "\\c[23]Álbum\\c[0]")
        self.assertEqual(p.traduccion_exacta("  Stick "), "  Palo ")
        for otro in ("Stick with me.", "stick", "STICK", "Rough Diamond!", "I found a Rough Diamond.", ""):
            self.assertIsNone(p.traduccion_exacta(otro), otro)
        self.assertIsNone(Perfil().traduccion_exacta("Rough Diamond"))

    def test_dentro_de_frases_solo_los_seguros_y_con_sus_mayusculas(self):
        p = _perfil_bd()
        self.assertEqual(p.terminos_para("I found two Rough Diamonds!"), [("Rough Diamond", "Diamante en bruto")])
        self.assertEqual(p.terminos_para("It's just a rough diamond."), [])  # en minúscula no es el objeto
        self.assertEqual(p.terminos_para("Stick with me, Sister."), [])     # "Stick" solo como texto entero

    def test_sin_nombres_de_la_bd_los_terminos_son_los_de_siempre(self):
        glosario = {"Lovense Remote": "Control Lovense", "Remote": "Mando"}
        base = Perfil(glosario=glosario)
        con_bd = Perfil(glosario=glosario, glosario_bd={"Rough Diamond": "Diamante en bruto"},
                        glosario_bd_frases=frozenset({"Rough Diamond"}))
        texto = "Use the Lovense Remote now."
        self.assertEqual(con_bd.terminos_para(texto), base.terminos_para(texto))  # misma clave de caché
        self.assertEqual(con_bd.terminos_para("A Rough Diamond and the Lovense Remote."),
                         [("Lovense Remote", "Control Lovense"), ("Rough Diamond", "Diamante en bruto"),
                          ("Remote", "Mando")])

    def test_el_glosario_del_usuario_manda(self):
        p = Perfil(glosario={"rough diamond": "Diamante tosco (contexto: objeto)"},
                   glosario_bd={"Rough Diamond": "Diamante en bruto"}, glosario_bd_frases=frozenset({"Rough Diamond"}))
        self.assertEqual(p.terminos_para("A Rough Diamond."), [("rough diamond", "Diamante tosco")])
        self.assertEqual(p.valor_glosario("Rough Diamond"), "Diamante tosco")
        self.assertIsNone(p.valor_glosario("Stick"))

    def test_guardar_leer_y_cargar_perfil(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            ruta = workspace / "juego_x" / config.ARCHIVO_GLOSARIO_BD
            config.guardar_glosario_bd(ruta, {"Stick": "Palo", "Rough Diamond": "Diamante en bruto"}, {"Rough Diamond"})
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            self.assertEqual(datos[config.SECCION_BD_FRASES], {"Rough Diamond": "Diamante en bruto"})
            self.assertEqual(datos[config.SECCION_BD_EXACTOS], {"Stick": "Palo"})
            self.assertIn("_info", datos)
            self.assertEqual(config.leer_glosario_bd(ruta),
                             ({"Rough Diamond": "Diamante en bruto", "Stick": "Palo"}, {"Rough Diamond"}))
            self.assertEqual(config.leer_glosario_bd(workspace / "no_existe.json"), ({}, set()))
            with mock.patch.object(config, "DIR_WORKSPACE", workspace):
                perfil = config.cargar_perfil("juego_x", auto_crear=False)
            self.assertEqual(perfil.traduccion_exacta("Stick"), "Palo")
            self.assertEqual(perfil.glosario_bd_frases, frozenset({"Rough Diamond"}))
            self.assertIn("2 nombres de la base de datos", perfil.resumen())


class TestTraductorGlosarioBD(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _traductor(self, **kw) -> OllamaTranslator:
        t = OllamaTranslator(model_name="modelo_prueba", perfil=_perfil_bd(), ruta_cache=self.tmp / "cache.json", **kw)
        self.addCleanup(t.cerrar)
        t._generar = mock.MagicMock(side_effect=_modelo_falso)
        return t

    def test_el_nombre_entero_no_pasa_por_el_modelo(self):
        for tam_lote in (1, 20):
            t = self._traductor(tam_lote=tam_lote)
            self.assertEqual(t.traducir_textos(["\\c[23]Album\\c[0]", "Rough Diamond", "Stick"]),
                             ["\\c[23]Álbum\\c[0]", "Diamante en bruto", "Palo"])
            t._generar.assert_not_called()
            self.assertEqual(t.estadisticas["glosario_bd"], 3)

    def test_en_una_frase_se_pide_el_nombre_fijado(self):
        t = self._traductor()
        t.translate("I found a Rough Diamond and a Stick.")
        prompt = t._generar.call_args[0][0]
        self.assertIn("'Rough Diamond' = 'Diamante en bruto'", prompt)
        self.assertNotIn("'Stick'", prompt)


class TestPasadaBaseDeDatos(unittest.TestCase):
    """InyectorRPGMaker.procesar(): primero fija los nombres y luego traduce con ellos."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.workspace = self.tmp / "workspace"
        parche = mock.patch.object(config, "DIR_WORKSPACE", self.workspace)
        parche.start()
        self.addCleanup(parche.stop)
        (self.workspace / "juego_x").mkdir(parents=True)  # el perfil del juego ya existe (lo crea el Paso 1)
        self.data = self.tmp / "Juego" / "www" / "data"
        self.data.mkdir(parents=True)
        objetos = [None,
                   {"id": 1, "name": "Rough Diamond", "description": "A shiny rock.", "price": 10},
                   {"id": 2, "name": "Stick", "description": "A wooden stick.", "price": 1},
                   {"id": 3, "name": "\\c[23]Album", "description": "Photos.", "price": 0},
                   {"id": 4, "name": "Ariel", "description": "", "price": 0},
                   {"id": 5, "name": "Fire", "description": "", "price": 0}]
        lista = [{"code": 401, "parameters": ["I found a Rough Diamond and a Stick."], "indent": 0},
                 {"code": 102, "parameters": [["Rough Diamond", "Stick"]], "indent": 0},
                 {"code": 0, "parameters": []}]
        mapa = {"displayName": "", "events": [None, {"id": 1, "name": "EV001", "x": 1, "y": 1, "note": "",
                                                     "pages": [{"list": lista}]}]}
        self._escribir("Items.json", objetos)
        self._escribir("Map001.json", mapa)
        self.ficha = FichaPersonajes(personajes=[Personaje(nombre="Ariel", genero="mujer", rol="principal")])

    def _escribir(self, nombre: str, datos) -> None:
        (self.data / nombre).write_text(json.dumps(datos), encoding="utf-8")

    def _leer(self, nombre: str):
        return json.loads((self.data / nombre).read_text(encoding="utf-8"))

    def _traductor(self, perfil: Perfil) -> OllamaTranslator:
        t = OllamaTranslator(model_name="modelo_prueba", perfil=perfil, ruta_cache=self.tmp / "cache.json")
        self.addCleanup(t.cerrar)
        t._generar = mock.MagicMock(side_effect=_modelo_falso)
        return t

    def test_fija_los_nombres_y_los_usa_en_todo_el_juego(self):
        t = self._traductor(Perfil(juego="juego_x", personajes=self.ficha))
        InyectorRPGMaker(self.data.parent.parent, t).procesar()

        guardado = json.loads((self.workspace / "juego_x" / config.ARCHIVO_GLOSARIO_BD).read_text(encoding="utf-8"))
        # "Stick" sale en minúscula ("A wooden stick.") y "Fire" es una palabra corriente: solo texto entero.
        # "Ariel" es un personaje: no se fija.
        self.assertEqual(guardado[config.SECCION_BD_FRASES], {"Album": "Álbum", "Rough Diamond": "Diamante en bruto"})
        self.assertEqual(guardado[config.SECCION_BD_EXACTOS], {"Fire": "Fuego", "Stick": "Palo"})

        objetos = self._leer("Items.json")
        self.assertEqual([o["name"] for o in objetos[1:4]], ["Diamante en bruto", "Palo", "\\c[23]Álbum"])
        lista = self._leer("Map001.json")["events"][1]["pages"][0]["list"]
        self.assertEqual(lista[1]["parameters"][0], ["Diamante en bruto", "Palo"])  # opciones = inventario
        prompt = next(c[0][0] for c in t._generar.call_args_list
                      if _entrada(c[0][0]) == "I found a Rough Diamond and a Stick.")
        self.assertIn("'Rough Diamond' = 'Diamante en bruto'", prompt)
        self.assertNotIn("'Stick'", prompt)

    def test_respeta_lo_que_corrige_el_usuario(self):
        ruta = self.workspace / "juego_x" / config.ARCHIVO_GLOSARIO_BD
        config.guardar_glosario_bd(ruta, {"Rough Diamond": "Diamante tosco", "Stick": "Rama", "Album": "Álbum",
                                          "Fire": "Fuego"}, {"Rough Diamond"})
        nombres, frases = config.leer_glosario_bd(ruta)
        t = self._traductor(Perfil(juego="juego_x", personajes=self.ficha, glosario_bd=nombres,
                                   glosario_bd_frases=frozenset(frases)))
        InyectorRPGMaker(self.data.parent.parent, t).procesar()
        entradas = [_entrada(c[0][0]) for c in t._generar.call_args_list]
        self.assertNotIn("Rough Diamond", entradas)  # nada que fijar: no se pregunta al modelo
        self.assertEqual([o["name"] for o in self._leer("Items.json")[1:3]], ["Diamante tosco", "Rama"])
        self.assertEqual(config.leer_glosario_bd(ruta)[0]["Stick"], "Rama")

    def test_solo_genero_conserva_el_inventario_ya_traducido(self):
        original = json.loads((self.data / "Items.json").read_text(encoding="utf-8"))
        (self.data / "Items.json.bak").write_text(json.dumps(original), encoding="utf-8")
        traducido = json.loads(json.dumps(original))
        traducido[1]["name"] = "Diamante bruto"  # lo que ya ponía el juego
        traducido[2]["name"] = "Rama"
        self._escribir("Items.json", traducido)
        t = self._traductor(Perfil(juego="juego_x", personajes=self.ficha))
        InyectorRPGMaker(self.data.parent.parent, t, reaprovechar_traduccion=True).procesar()
        entradas = [_entrada(c[0][0]) for c in t._generar.call_args_list]
        self.assertNotIn("Rough Diamond", entradas)
        self.assertNotIn("Stick", entradas)
        lista = self._leer("Map001.json")["events"][1]["pages"][0]["list"]
        self.assertEqual(lista[1]["parameters"][0], ["Diamante bruto", "Rama"])  # opciones = inventario actual

    def test_sin_carpeta_de_perfil_no_crea_nada(self):
        t = self._traductor(Perfil(juego="sin_carpeta", personajes=self.ficha))
        InyectorRPGMaker(self.data.parent.parent, t).procesar()
        self.assertFalse((self.workspace / "sin_carpeta").exists())
        self.assertEqual(self._leer("Items.json")[1]["name"], "Diamante en bruto")  # pero se usa en esta pasada

    def test_se_puede_desactivar(self):
        t = self._traductor(Perfil(juego="juego_x"))
        InyectorRPGMaker(self.data.parent.parent, t, glosario_bd=False).procesar()
        self.assertFalse((self.workspace / "juego_x" / config.ARCHIVO_GLOSARIO_BD).exists())
        self.assertEqual(t.estadisticas["glosario_bd"], 0)


class TestNombreVisibleMapa(unittest.TestCase):
    def test_se_traduce_el_nombre_visible_pero_no_los_marcadores(self):
        iny = InyectorRPGMaker(Path("."), mock.MagicMock(perfil=Perfil()))
        mapa = {"displayName": "Old Mine", "events": [], "data": []}
        hilda = {"displayName": "{map_name_0033}", "events": [], "data": []}
        cola: list[str] = []
        iny._extraer(mapa, cola)
        iny._extraer(hilda, cola)
        self.assertEqual(cola, ["Old Mine"])
        iny._inyectar(mapa, iter(["Mina abandonada"]))
        iny._inyectar(hilda, iter([]))
        self.assertEqual(mapa["displayName"], "Mina abandonada")
        self.assertEqual(hilda["displayName"], "{map_name_0033}")


if __name__ == "__main__":
    unittest.main()
