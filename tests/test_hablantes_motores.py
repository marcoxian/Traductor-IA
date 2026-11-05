"""Pruebas: los motores (RPG Maker y CSV) saben QUIÉN dice cada línea (``InfoLinea``).

Fuentes de hablante en RPG Maker: cara y nombre de MZ del code 101, cajas de nombre
(\\N<..>, \\n<..>, \\nr<..>...), prefijos de hablante (V21) en 401 y en setValue(21), opciones 102/402.
Ningún test llama a Ollama: se usan traductores falsos con y sin el parámetro ``info``.
"""
from __future__ import annotations

import copy
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor.motores import rpgmaker as motor_rpg
from traductor.motores.csv_locales import InyectorCSV, ajustar_saltos, hablante_csv
from traductor.motores.rpgmaker import (INFO_OPCION, InyectorRPGMaker, codigo_v21, hablante_de_caja,
                                        traductor_acepta_info)
from traductor.personajes import FichaPersonajes, InfoLinea, Personaje, resolver_linea


# --------------------------------------------------------------------------- Utilidades
def _cmd(code: int, *params) -> dict:
    return {"code": code, "indent": 0, "parameters": list(params)}


def _evento(*cmds: dict) -> dict:
    """Mapa mínimo con un evento (sin nombre) cuya única página ejecuta ``cmds``."""
    return {"events": [None, {"id": 1, "pages": [{"list": [*cmds, _cmd(0)]}]}]}


def _pares(datos) -> list[tuple[str, InfoLinea | None]]:
    return InyectorRPGMaker(Path("."), None).extraer_con_info(datos)


def _infos(datos) -> list[InfoLinea | None]:
    return [info for _, info in _pares(datos)]


def _ficha() -> FichaPersonajes:
    return FichaPersonajes(personajes=[
        Personaje("1Hero", "hombre", "protagonista", alias=["\\N[1]"], codigos=["Mc"]),
        Personaje("Ana", "mujer", "principal", codigos=["Al", "face:Ana#0"]),
        Personaje("Kayla", "mujer", "principal"),
        Personaje("Bob", "hombre", "secundario", codigos=["He"]),  # como el héroe de Nora
        Personaje("Zed", "desconocido", "secundario"),
    ])


class PerfilFalso:
    """Lo mínimo del Perfil que usan los motores."""

    def __init__(self, personajes: FichaPersonajes | None = None):
        self.personajes = personajes
        self.glosario: dict[str, str] = {}

    def restaurar_nombres(self, origen: str, traducido: str) -> str:
        return traducido


class TraductorSinInfo:
    """Como los mocks antiguos: ``traducir_textos(textos)`` sin parámetro ``info``."""

    def __init__(self, perfil: PerfilFalso | None = None, respuestas: dict[str, str] | None = None):
        self.perfil = perfil or PerfilFalso()
        self.respuestas = respuestas or {}
        self.llamadas: list[list[str]] = []

    def traducir_textos(self, textos):
        self.llamadas.append(list(textos))
        return [self.respuestas.get(t, f"ES:{t}") for t in textos]


class TraductorConInfo(TraductorSinInfo):
    """Traductor nuevo: acepta ``info`` en paralelo a ``textos``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.infos_recibidas: list[list[InfoLinea | None] | None] = []

    def traducir_textos(self, textos, info=None):
        self.infos_recibidas.append(None if info is None else list(info))
        return super().traducir_textos(textos)


def _json_grande(n: int = 120) -> list:
    """CommonEvents sintético con todos los tipos de comando que extrae el motor."""
    eventos: list = [None]
    for k in range(n):
        lista = [
            _cmd(101, "Ana" if k % 2 else "", k % 8, 0, 2, *(["Kayla"] if k % 3 == 0 else [])),
            _cmd(401, f"<wordwrap>McBaOp.Line {k} from the hero,"),
            _cmd(401, f"AlFrOp.and another speaker {k}."),
            _cmd(401, "\\w[30]\\^"),
            _cmd(401, f"\\n<\\C[2]Kayla\\C[0]>Box line {k}."),
            _cmd(101, "", 0, 0, 2),
            _cmd(401, f"(Just thinking {k}...)"),
            _cmd(102, [f"Option A{k}", "/worry", f"I'm ready {k}"], 1, 0, 2, 0),
            _cmd(402, 0, f"Option A{k}"),
            _cmd(401, f"Nested {k}."),
            _cmd(0),
            _cmd(402, 2, f"I'm ready {k}"),
            _cmd(0),
            _cmd(404),
            _cmd(355, f'$gameVariables.setValue(21, "HeFrOp.Script line {k}.");'),
            _cmd(655, f'$gameVariables.setValue(21, "NPC.Generic {k}.");'),
            _cmd(355, f'$gameVariables.setValue(107, "Item {k}");'),
            _cmd(355, "var res = $gameVariables.value(25).replace(/1Hero/gi, 'x');"),
            _cmd(250, {"name": "Cursor1", "volume": 90, "pitch": 100, "pan": 0}),
        ]
        eventos.append({"id": k + 1, "name": f"Common {k}", "list": [*lista, _cmd(0)]})
    return eventos


# --------------------------------------------------------------------------- RPG Maker: extracción
class TestHablantesRPGMaker(unittest.TestCase):

    def test_mv_cara_del_101(self):
        datos = _evento(_cmd(101, "Ana", 0, 0, 2), _cmd(401, "Hello there,"), _cmd(401, "how are you?"))
        self.assertEqual(_pares(datos), [("Hello there, how are you?", InfoLinea(codigo="face:Ana#0"))])

    def test_mv_sin_cara_ni_nombre_no_hay_info(self):
        datos = _evento(_cmd(101, "", 0, 0, 2), _cmd(401, "Nice weather today."))
        self.assertEqual(_pares(datos), [("Nice weather today.", None)])

    def test_mz_hablante_en_parameters_4(self):
        datos = _evento(_cmd(101, "Actor1", 2, 0, 2, "\\C[2]Kayla\\C[0]"), _cmd(401, "I'm so tired."))
        self.assertEqual(_infos(datos), [InfoLinea(hablante="Kayla", codigo="face:Actor1#2")])
        sin_cara = _evento(_cmd(101, "", 0, 0, 2, "Ana"), _cmd(401, "Hi!"))
        self.assertEqual(_infos(sin_cara), [InfoLinea(hablante="Ana")])
        vacio = _evento(_cmd(101, "", 0, 0, 2, ""), _cmd(401, "Hi!"))
        self.assertEqual(_infos(vacio), [None])

    def test_cajas_de_nombre_con_codigos_de_color(self):
        casos = {
            "\\N<\\C[3]Ana\\C[0]>Hello!": "Ana",
            "\\n<\\C[9]Kayla\\C[0]>Hi there.": "Kayla",
            "\\nr<Bob>Yo.": "Bob",
            "\\nc<Ana>Look!": "Ana",
            "\\nl<\\c[4]Zed\\c[0]>Wait.": "Zed",
            "\\c[3]\\n<Ana>Over here!": "Ana",
        }
        for linea, hablante in casos.items():
            with self.subTest(linea=linea):
                datos = _evento(_cmd(101, "", 0, 0, 2), _cmd(401, linea))
                self.assertEqual(_infos(datos), [InfoLinea(hablante=hablante)])
        # \N<..> se aparta del texto que se traduce (como antes)
        datos = _evento(_cmd(101, "", 0, 0, 2), _cmd(401, "\\N<\\C[3]Ana\\C[0]>Hello!"))
        self.assertEqual(_pares(datos)[0][0], "Hello!")

    def test_no_confunde_codigos_de_fuente_ni_etiquetas(self):
        self.assertIsNone(hablante_de_caja("\\fn<Cinzel-Black>\\fb\\c[19]Chapter 1"))
        self.assertIsNone(hablante_de_caja("Hello\\n<br>"))
        self.assertIsNone(hablante_de_caja("\\n<>Empty"))
        self.assertIsNone(hablante_de_caja("Hello there"))
        self.assertEqual(hablante_de_caja("\\n<\\c[2]\\fb Kayla\\fb\\c[0]>Hey"), "Kayla")
        self.assertIsNone(hablante_de_caja("Hey \\n<Ana> you", solo_al_inicio=True))

    def test_caja_de_nombre_tiene_prioridad_sobre_hablante_mz(self):
        datos = _evento(_cmd(101, "Actor1", 0, 0, 2, "Ana"), _cmd(401, "\\n<Kayla>Hey!"))
        self.assertEqual(_infos(datos), [InfoLinea(hablante="Kayla", codigo="face:Actor1#0")])

    def test_caja_con_actor_1_es_el_protagonista(self):
        for linea in ("\\n<\\C[9]\\N[1]\\C[0]>Hmm, I think so.", "\\n<\\n[1]>Hmm, I think so.",
                      "\\N<\\N[1]>Hmm, I think so."):
            with self.subTest(linea=linea):
                texto, info = _pares(_evento(_cmd(101, "MC", 0, 0, 2), _cmd(401, linea)))[0]
                self.assertEqual(info, InfoLinea(hablante="\\N[1]", codigo="face:MC#0"))
                ctx = resolver_linea(_ficha(), texto, info)
                self.assertEqual(ctx.hablante.nombre, "1Hero")

    def test_caja_de_nombre_vale_para_todo_el_mensaje(self):
        datos = _evento(
            _cmd(101, "", 0, 0, 2),
            _cmd(401, "\\n<Ana>Hello!"),
            _cmd(401, "\\w[30]"),            # sin texto visible: parte el grupo
            _cmd(401, "Are you there?"),
            _cmd(101, "", 0, 0, 2),          # mensaje nuevo: ya no hay caja
            _cmd(401, "Who's that?"),
        )
        self.assertEqual(_infos(datos), [InfoLinea(hablante="Ana"), InfoLinea(hablante="Ana"), None])

    def test_pensamiento_con_caja_de_nombre(self):
        datos = _evento(_cmd(101, "Ruth", 3, 0, 2), _cmd(401, "\\n<\\C[20]Ruth\\C[0]>(It's so close!"),
                        _cmd(401, "I can't believe it.)"))
        self.assertEqual(_infos(datos), [InfoLinea(hablante="Ruth", codigo="face:Ruth#3", es_pensamiento=True)])

    def test_prefijo_v21_en_401(self):
        datos = _evento(
            _cmd(101, "", 0, 0, 2), _cmd(401, "<wordwrap>MiHaEx^.Don't leave me here!"),
            _cmd(101, "", 0, 0, 2), _cmd(401, "D1FlOp#.Look, ladies."),
            _cmd(101, "Actor1", 0, 0, 2), _cmd(401, "HeFrOp.Hi."),             # V21 antes que la cara
            _cmd(101, "Actor1", 0, 0, 2), _cmd(401, "NPC.Do you believe in the virus?"),
            _cmd(101, "", 0, 0, 2), _cmd(401, "McBaOp.First line"), _cmd(401, "AlFrOp.Second line"),
        )
        self.assertEqual(_pares(datos), [
            ("Don't leave me here!", InfoLinea(codigo="Mi")),
            ("Look, ladies.", InfoLinea(codigo="D1")),
            ("Hi.", InfoLinea(codigo="He")),
            ("Do you believe in the virus?", None),  # NPC genérico: ni código ni cara
            ("First line", InfoLinea(codigo="Mc")),
            ("Second line", InfoLinea(codigo="Al")),
        ])

    def test_codigo_v21(self):
        casos = {"HeFrOp": "He", "D1FlOp#": "D1", "@McVo>": "Mc", "Br,fr,op": "Br", "MiHaEx^": "Mi",
                 "NPC": None, "NPCFrOp": None, "1A": None, "": None, None: None}
        for prefijo, esperado in casos.items():
            with self.subTest(prefijo=prefijo):
                self.assertEqual(codigo_v21(prefijo), esperado)

    def test_set_value_con_y_sin_prefijo_v21(self):
        datos = _evento(
            _cmd(355, '$gameVariables.setValue(21, "HeFrOp.I am so tired.");'),
            _cmd(655, '$gameVariables.setValue(21, "MiHaEx^.Wait for me!");'),
            _cmd(355, '$gameVariables.setValue(21, "Br,fr,op.Smells like rain.");'),
            _cmd(355, '$gameVariables.setValue(21, "NPC.Do you believe in the sex virus?");'),
            _cmd(355, '$gameVariables.setValue(21, "Failed the exam. Please study more.");'),
            _cmd(355, '$gameVariables.setValue(25, "Incoming call from office phone.");'),
            _cmd(355, '$gameVariables.setValue(107, "Oracle of the Seraph");'),
            _cmd(355, '$gameVariables.setValue(21, "@McVo>./worry");'),  # comando de voz: no se traduce
        )
        self.assertEqual(_pares(datos), [
            ("I am so tired.", InfoLinea(codigo="He")),
            ("Wait for me!", InfoLinea(codigo="Mi")),
            ("Smells like rain.", InfoLinea(codigo="Br")),
            ("Do you believe in the sex virus?", None),
            ("Failed the exam. Please study more.", None),
            ("Incoming call from office phone.", None),
            ("Oracle of the Seraph", None),
        ])

    def test_opciones_102_y_etiquetas_402(self):
        datos = _evento(
            _cmd(102, ["I'm ready", "Not yet"], 1, 0, 2, 0),
            _cmd(402, 0, "I'm ready"),
            _cmd(0),
            _cmd(402, 1, "Not yet"),
            _cmd(0),
            _cmd(404),
        )
        self.assertEqual(_pares(datos), [("I'm ready", INFO_OPCION), ("Not yet", INFO_OPCION),
                                         ("I'm ready", INFO_OPCION), ("Not yet", INFO_OPCION)])
        self.assertTrue(INFO_OPCION.es_opcion)

    def test_base_de_datos_terminos_y_tipos_sin_info(self):
        items = [None, {"id": 1, "name": "Potion", "description": "Restores 50 HP.", "note": ""},
                 {"id": 2, "name": "Ether", "description": "Restores MP."}]
        sistema = {"gameTitle": "My Game", "elements": ["", "Fire"], "skillTypes": ["", "Magic"],
                   "terms": {"basic": ["Level"], "commands": ["Fight"], "params": ["Max HP"],
                             "messages": {"actionFailure": "There was no effect on %1!"}},
                   "titleBgm": {"name": "Theme1", "volume": 90, "pitch": 100}}
        for datos in (items, sistema):
            with self.subTest(datos=str(datos)[:30]):
                pares = _pares(datos)
                self.assertTrue(pares)
                self.assertTrue(all(info is None for _, info in pares))

    def test_infos_alineadas_con_la_cola_en_json_grande(self):
        datos = _json_grande()
        intacto = copy.deepcopy(datos)
        iny = InyectorRPGMaker(Path("."), None)

        cola_simple: list[str] = []
        iny._extraer(copy.deepcopy(datos), cola_simple)
        cola: list[str] = []
        infos: list[InfoLinea | None] = []
        iny._extraer(copy.deepcopy(datos), cola, infos)
        self.assertGreater(len(cola), 1000)
        self.assertEqual(len(infos), len(cola))
        self.assertEqual(cola, cola_simple)  # mismo QUÉ y mismo ORDEN que antes

        pares = iny.extraer_con_info(datos)
        self.assertEqual([t for t, _ in pares], cola_simple)
        self.assertEqual(datos, intacto)  # extraer_con_info no toca los datos (ni el script .replace(/1Hero)

        por_texto = dict(pares)
        # k=9: cara Ana#1 y hablante MZ Kayla; k=8: sin cara ni hablante; k=7: cara Ana#7
        self.assertEqual(por_texto["Line 9 from the hero,"], InfoLinea(hablante="Kayla", codigo="Mc"))
        self.assertEqual(por_texto["and another speaker 9."], InfoLinea(hablante="Kayla", codigo="Al"))
        self.assertEqual(por_texto["\\n<\\C[2]Kayla\\C[0]>Box line 9."],
                         InfoLinea(hablante="Kayla", codigo="face:Ana#1"))
        self.assertEqual(por_texto["Line 8 from the hero,"], InfoLinea(codigo="Mc"))
        self.assertEqual(por_texto["and another speaker 8."], InfoLinea(codigo="Al"))
        self.assertEqual(por_texto["\\n<\\C[2]Kayla\\C[0]>Box line 8."], InfoLinea(hablante="Kayla"))
        self.assertEqual(por_texto["Line 7 from the hero,"], InfoLinea(codigo="Mc"))
        self.assertEqual(por_texto["\\n<\\C[2]Kayla\\C[0]>Box line 7."],
                         InfoLinea(hablante="Kayla", codigo="face:Ana#7"))
        self.assertIsNone(por_texto["(Just thinking 7...)"])
        self.assertIsNone(por_texto["Nested 7."])  # 401 suelto tras un 402: sin cabecera 101
        self.assertEqual(por_texto["Option A7"], INFO_OPCION)
        self.assertEqual(por_texto["Script line 7."], InfoLinea(codigo="He"))
        self.assertIsNone(por_texto["Generic 7."])
        self.assertIsNone(por_texto["Item 7"])
        self.assertIsNone(por_texto["Common 7"])  # nombre del evento común (base de datos)

    def test_infos_se_alinean_aunque_la_cola_no_empiece_vacia(self):
        cola = ["ya estaba"]
        infos: list[InfoLinea | None] = []
        InyectorRPGMaker(Path("."), None)._extraer(_evento(_cmd(101, "Ana", 0, 0, 2), _cmd(401, "Hi.")),
                                                   cola, infos)
        self.assertEqual(len(infos), len(cola))
        self.assertEqual(infos, [None, InfoLinea(codigo="face:Ana#0")])


# --------------------------------------------------------------------------- RPG Maker: traductor
class TestTraductorConYSinInfo(unittest.TestCase):

    def _juego(self, tmp: str) -> Path:
        carpeta = Path(tmp) / "www" / "data"
        carpeta.mkdir(parents=True)
        datos = _evento(
            _cmd(101, "", 0, 0, 2, "Ana"), _cmd(401, "I'm so tired."),
            _cmd(102, ["Me too"], 0, 0, 2, 0),
            _cmd(355, '$gameVariables.setValue(21, "McBaOp.Let us go.");'),
        )
        (carpeta / "Map001.json").write_text(json.dumps(datos), encoding="utf-8")
        return carpeta / "Map001.json"

    def test_traductor_sin_parametro_info_sigue_funcionando(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._juego(tmp)
            traductor = TraductorSinInfo()
            InyectorRPGMaker(Path(tmp), traductor).procesar()
            self.assertEqual(traductor.llamadas, [["I'm so tired.", "Me too", "Let us go."]])
            resultado = json.loads(ruta.read_text(encoding="utf-8"))
            cmds = resultado["events"][1]["pages"][0]["list"]
            self.assertEqual(cmds[1]["parameters"][0], "ES:I'm so tired.")
            self.assertIn('"McBaOp.ES:Let us go."', cmds[3]["parameters"][0])
            self.assertTrue(ruta.with_suffix(".json.bak").exists())

    def test_traductor_con_parametro_info_recibe_las_infos(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._juego(tmp)
            traductor = TraductorConInfo()
            InyectorRPGMaker(Path(tmp), traductor).procesar()
            self.assertEqual(traductor.llamadas, [["I'm so tired.", "Me too", "Let us go."]])
            self.assertEqual(traductor.infos_recibidas,
                             [[InfoLinea(hablante="Ana"), INFO_OPCION, InfoLinea(codigo="Mc")]])

    def test_deteccion_del_parametro_info_cacheada(self):
        motor_rpg._FIRMAS.clear()
        with mock.patch.object(motor_rpg.inspect, "signature", wraps=inspect.signature) as firma:
            for _ in range(3):
                self.assertTrue(traductor_acepta_info(TraductorConInfo()))
                self.assertFalse(traductor_acepta_info(TraductorSinInfo()))
        self.assertEqual(firma.call_count, 2)
        self.assertFalse(traductor_acepta_info(object()))       # sin traducir_textos
        self.assertFalse(traductor_acepta_info(mock.Mock()))    # (*args, **kwargs): no se le pasa info


# --------------------------------------------------------------------------- RPG Maker: concordancia al inyectar
class TestConcordanciaAlInyectar(unittest.TestCase):

    def _inyectar(self, datos, traducciones, ficha: FichaPersonajes | None = None):
        iny = InyectorRPGMaker(Path("."), TraductorSinInfo(PerfilFalso(ficha)))
        iterador = iter(traducciones)
        iny._inyectar(datos, iterador)
        with self.assertRaises(StopIteration):
            next(iterador)
        return datos

    def test_hablante_mujer_estoy_cansada(self):
        datos = [_cmd(101, "", 0, 0, 2, "Ana"), _cmd(401, "I'm so tired."), _cmd(0)]
        self._inyectar(datos, ["Estoy muy cansado."], _ficha())
        self.assertEqual(datos[1]["parameters"][0], "Estoy muy cansada.")

    def test_caja_de_nombre_y_cara(self):
        datos = [_cmd(101, "", 0, 0, 2), _cmd(401, "\\N<\\C[3]Ana\\C[0]>I'm ready."), _cmd(0),
                 _cmd(101, "Ana", 0, 0, 2), _cmd(401, "I'm sure."), _cmd(0)]
        self._inyectar(datos, ["Estoy listo.", "Estoy seguro."], _ficha())
        self.assertEqual(datos[1]["parameters"][0], "\\N<\\C[3]Ana\\C[0]>Estoy lista.")
        self.assertEqual(datos[4]["parameters"][0], "Estoy segura.")  # cara face:Ana#0 en la ficha

    def test_sin_ficha_o_sin_genero_no_se_toca(self):
        for ficha, hablante in ((None, "Ana"), (_ficha(), "Zed"), (_ficha(), "Desconocida")):
            with self.subTest(ficha=ficha is not None, hablante=hablante):
                datos = [_cmd(101, "", 0, 0, 2, hablante), _cmd(401, "I'm so tired."), _cmd(0)]
                self._inyectar(datos, ["Estoy muy cansado."], ficha)
                self.assertEqual(datos[1]["parameters"][0], "Estoy muy cansado.")

    def test_opciones_las_dice_el_protagonista(self):
        datos = [_cmd(102, ["I'm ready!"], 0, 0, 2, 0), _cmd(402, 0, "I'm ready!"), _cmd(0), _cmd(404)]
        self._inyectar(datos, ["¡Estoy lista!", "¡Estoy lista!"], _ficha())
        self.assertEqual(datos[0]["parameters"][0], ["¡Estoy listo!"])
        self.assertEqual(datos[1]["parameters"][1], "¡Estoy listo!")

    def test_set_value_v21_usa_la_ficha_del_juego(self):
        # En esta ficha 'He' es un hombre (como el héroe de Mi Juego), no Laura.
        datos = [_cmd(355, '$gameVariables.setValue(21, "HeFrOp.I\'m so tired.");'),
                 _cmd(355, '$gameVariables.setValue(21, "AlFrOp.I\'m so tired.");')]
        self._inyectar(datos, ["Estoy cansada.", "Estoy cansado."], _ficha())
        self.assertEqual(datos[0]["parameters"][0], '$gameVariables.setValue(21, "HeFrOp.Estoy cansado.");')
        self.assertEqual(datos[1]["parameters"][0], '$gameVariables.setValue(21, "AlFrOp.Estoy cansada.");')

    def test_set_value_v21_sin_ficha_usa_los_codigos_locales(self):
        # Sin ficha, los géneros de los códigos salen de las correcciones locales (aquí, las de prueba)
        from traductor import texto as modulo_texto
        prueba = Path(__file__).parent / "datos" / "correcciones_locales.prueba.json"
        parche = mock.patch.object(modulo_texto, "ARCHIVO_CORRECCIONES_LOCALES", prueba)
        parche.start()
        modulo_texto.correcciones_locales.cache_clear()
        self.addCleanup(modulo_texto.correcciones_locales.cache_clear)
        self.addCleanup(parche.stop)
        datos = [_cmd(355, '$gameVariables.setValue(21, "McNoOp.I fell asleep on the couch.");')]
        self._inyectar(datos, ["Me quedé dormida en el sofá."])
        self.assertEqual(datos[0]["parameters"][0],
                         '$gameVariables.setValue(21, "McNoOp.Me quedé dormido en el sofá.");')

    def test_correccion_v21_recibe_la_ficha_solo_si_la_acepta(self):
        ficha = _ficha()
        iny = InyectorRPGMaker(Path("."), TraductorSinInfo(PerfilFalso(ficha)))
        llamadas: list[tuple] = []

        def con_ficha(texto, prefijo_v21, ficha=None):
            llamadas.append(("con", prefijo_v21, ficha))
            return texto

        def sin_ficha(texto, prefijo_v21):
            llamadas.append(("sin", prefijo_v21))
            return texto

        for falsa in (con_ficha, sin_ficha):
            with mock.patch.object(motor_rpg, "corregir_genero_hablante_v21", falsa):
                iny._corregir_genero_v21("Hola.", "HeFrOp.")
        self.assertEqual(llamadas, [("con", "HeFrOp.", ficha), ("sin", "HeFrOp.")])


# --------------------------------------------------------------------------- CSV
class TestHablantesCSV(unittest.TestCase):

    def test_hablante_desde_la_caja_de_la_celda_inglesa(self):
        self.assertEqual(hablante_csv("\\N<\\C[3]Ana\\C[0]>Hello"), "Ana")
        self.assertEqual(hablante_csv("\\N<Bob>Hi"), "Bob")
        self.assertEqual(hablante_csv("\\C[2]\\N<Ana>Hello"), "Ana")
        self.assertEqual(hablante_csv("\\n<\\C[9]\\N[1]\\C[0]>Oh shit, gold coins!"), "\\N[1]")
        self.assertIsNone(hablante_csv("Hello \\N<Ana> there"))  # no es el prefijo
        self.assertIsNone(hablante_csv("Just narration."))
        self.assertIsNone(hablante_csv(""))

    def _csv(self, tmp: str) -> Path:
        ruta = Path(tmp) / "locales" / "main.csv"
        ruta.parent.mkdir(parents=True)
        ruta.write_text("tag;en;jp\n"
                        "l1;\\N<\\C[3]Ana\\C[0]>I'm so tired.;x\n"
                        "l2;Just narration.;y\n"
                        "l3;\\N<Bob>Hi there!;z\n", encoding="utf-8")
        return ruta

    def test_procesar_pasa_el_hablante_al_traductor(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._csv(tmp)
            traductor = TraductorConInfo()
            InyectorCSV(Path(tmp), traductor).procesar()
            self.assertEqual(traductor.llamadas, [["I'm so tired.", "Just narration.", "Hi there!"]])
            self.assertEqual(traductor.infos_recibidas,
                             [[InfoLinea(hablante="Ana"), None, InfoLinea(hablante="Bob")]])
            resultado = ruta.read_text(encoding="utf-8")
            self.assertIn("l1;\\N<\\C[3]Ana\\C[0]>ES:I'm so tired.;x", resultado)
            self.assertIn("l3;\\N<Bob>ES:Hi there!;z", resultado)

    def test_procesar_con_traductor_sin_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._csv(tmp)
            traductor = TraductorSinInfo()
            InyectorCSV(Path(tmp), traductor).procesar()
            self.assertEqual(traductor.llamadas, [["I'm so tired.", "Just narration.", "Hi there!"]])
            self.assertIn("l2;ES:Just narration.;y", ruta.read_text(encoding="utf-8"))

    def test_caja_de_nombre_usa_la_tabla_de_hablantes(self):
        """'Man' no está en el glosario, pero sí en la tabla del Paso 5 del juego."""
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "locales" / "main.csv"
            ruta.parent.mkdir(parents=True)
            ruta.write_text("tag;en\nl1;\\N<\\C[5]Man\\C[0]>Hi.\nl2;\\N<\\C[5]Guard B\\C[0]>Stop.\n"
                            "l3;\\N<\\C[5]Zed\\C[0]>Yo.\n", encoding="utf-8")
            tabla = ({"Man": "Hombre", "Guard": "Guardia"}, frozenset())
            with mock.patch("traductor.motores.csv_locales.tabla_del_juego", return_value=tabla):
                InyectorCSV(Path(tmp), TraductorConInfo()).procesar()
            resultado = ruta.read_text(encoding="utf-8")
            self.assertIn("l1;\\N<\\C[5]Hombre\\C[0]>ES:Hi.", resultado)
            self.assertIn("l2;\\N<\\C[5]Guardia B\\C[0]>ES:Stop.", resultado)
            self.assertIn("l3;\\N<\\C[5]Zed\\C[0]>ES:Yo.", resultado)  # no se sabe: tal cual

    def test_celda_entre_comillas_conserva_la_caja_de_nombre(self):
        """El lector del juego no entiende comillas: se quitan para que la caja de nombre siga delante."""
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "locales" / "main.csv"
            ruta.parent.mkdir(parents=True)
            ruta.write_text('tag;en;jp\nl1;"\\N<\\C[5]Bob\\C[0]>Call it ""Home."" OK?";x\n', encoding="utf-8")
            traductor = TraductorConInfo()
            InyectorCSV(Path(tmp), traductor).procesar()
            self.assertEqual(traductor.llamadas, [['Call it "Home." OK?']])
            self.assertEqual(traductor.infos_recibidas, [[InfoLinea(hablante="Bob")]])
            self.assertIn('l1;\\N<\\C[5]Bob\\C[0]>ES:Call it "Home." OK?;x', ruta.read_text(encoding="utf-8"))

    def test_solo_genero_conserva_lo_ya_traducido_y_retraduce_el_resto(self):
        """--solo-genero: lo que el traductor acepta de la traducción actual queda igual, salto incluido."""

        class TraductorQueSiembra(TraductorConInfo):
            def __init__(self):
                super().__init__()
                self.sembradas: dict[str, str] = {}

            def sembrar_traduccion(self, original, traduccion, info=None):
                if "cansado" in traduccion:  # marca de género: que la traduzca el modelo
                    return False
                self.sembradas[original] = traduccion
                return True

            def traducir_textos(self, textos, info=None):
                super().traducir_textos(textos, info)
                return [self.sembradas.get(t, "ES:" + t) for t in textos]

        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._csv(tmp)
            ruta.with_name("main.csv.original").write_text(ruta.read_text(encoding="utf-8"), encoding="utf-8")
            ruta.write_text("tag;en;jp\n"
                            "l1;\\N<\\C[3]Ana\\C[0]>Estoy muy cansado.;x\n"
                            "l2;Solo\\nnarración.;y\n"
                            "l3;\\N<Bob>Hi there!;z\n", encoding="utf-8")
            traductor = TraductorQueSiembra()
            inyector = InyectorCSV(Path(tmp), traductor, reaprovechar_traduccion=True)
            inyector.procesar()
            self.assertEqual(traductor.sembradas, {"Just narration.": "Solo narración."})
            resultado = ruta.read_text(encoding="utf-8")
            self.assertIn("l1;\\N<\\C[3]Ana\\C[0]>ES:I'm so tired.;x", resultado)
            self.assertIn("l2;Solo\\nnarración.;y", resultado)  # intacta, con su salto de línea
            self.assertIn("l3;\\N<Bob>ES:Hi there!;z", resultado)  # seguía en inglés
            self.assertEqual((inyector.conservadas, inyector.retraducidas), (1, 1))


class TestSaltosDeCeldaCSV(unittest.TestCase):
    B = chr(92)  # barra invertida: las celdas llevan "\n" y "\CL" escritos

    def test_salto_obligatorio_antes_de_codigo_y_sangria(self):
        b = self.B
        original = "            Accepted mission" + b + "n" + b + "CL Get rid of sewer rats"
        segmentos = original.split(b + "n")
        # la IA junta las dos líneas: sin el salto, el juego pinta una encima de otra
        self.assertEqual(ajustar_saltos("Misión aceptada " + b + "CL Eliminar ratas", segmentos),
                         "            Misión aceptada" + b + "n" + b + "CL Eliminar ratas")
        self.assertEqual(ajustar_saltos("Misión aceptada" + b + "n" + b + "CL Eliminar ratas", segmentos),
                         "            Misión aceptada" + b + "n" + b + "CL Eliminar ratas")

    def test_sin_codigos_se_reparte_por_longitud(self):
        b = self.B
        segmentos = ("Hello there" + b + "nmy friend, how are you today").split(b + "n")
        self.assertEqual(ajustar_saltos("Hola, amigo mío, ¿cómo estás hoy?", segmentos).count(b + "n"), 1)
        self.assertEqual(ajustar_saltos("Hola", ["Hello"]), "Hola")


if __name__ == "__main__":
    unittest.main()
