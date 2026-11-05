"""Pruebas del analizador de personajes (Paso 0) con juegos sintéticos en carpetas temporales."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor import analizador, config
from traductor.genero import DESCONOCIDO, HOMBRE, MUJER
from traductor.personajes import FichaPersonajes, Personaje


def _cmd(code: int, params: list, indent: int = 0) -> dict:
    return {"code": code, "indent": indent, "parameters": params}


def _mensaje(lineas: list[str], cara: str = "", indice: int = 0, nombre_mz: str | None = None) -> list[dict]:
    params = [cara, indice, 0, 2] + ([nombre_mz] if nombre_mz is not None else [])
    return [_cmd(101, params)] + [_cmd(401, [t]) for t in lineas]


def _escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _mapa(comandos: list[dict]) -> dict:
    return {"events": [None, {"pages": [{"list": comandos + [_cmd(0, [])]}]}]}


def _evento_mensaje_nlt() -> list:
    """CommonEvents con el evento 'MESSAGE' de los juegos con códigos de hablante: códigos -> variable 27 -> 'VOICE <Nombre>'."""
    lista = []
    for codigo, valor in (("Mc", 1), ("Al", 2), ("Br", 3)):
        lista.append(_cmd(355, [f'if ($gameVariables.value(26).includes("{codigo}")) {{']))
        lista.append(_cmd(655, [f"$gameVariables.setValue(27, {valor})"]))
        lista.append(_cmd(655, ["}"]))
    # 'Vo' es una bandera de voz (otra variable): NO es un personaje
    lista.append(_cmd(355, ['if ($gameVariables.value(26).includes("Vo")) {']))
    lista.append(_cmd(655, ["$gameVariables.setValue(49, 1)"]))
    for valor, ce in ((1, 3), (2, 4), (3, 5)):
        lista.append(_cmd(111, [1, 27, 0, valor, 0]))
        lista.append(_cmd(117, [ce], indent=1))
        lista.append(_cmd(0, [], indent=1))
        lista.append(_cmd(412, []))
    lista.append(_cmd(111, [1, 49, 0, 1, 0]))
    lista.append(_cmd(117, [3], indent=1))
    return [None,
            {"id": 1, "name": "MESSAGE", "list": lista},
            {"id": 2, "name": "Otro", "list": []},
            {"id": 3, "name": "VOICE MC", "list": []},
            {"id": 4, "name": "VOICE Ana", "list": []},
            {"id": 5, "name": "DISPLAY Brian", "list": []}]


class _ConCarpeta(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRPGMaker(_ConCarpeta):
    def _juego_nlt(self) -> Path:
        datos = self.tmp / "Juego Codigos" / "www" / "data"
        _escribir(datos / "System.json", {"gameTitle": "Juego de Prueba"})
        _escribir(datos / "Actors.json", [None, {"id": 1, "name": "William", "faceName": "", "faceIndex": 0},
                                          {"id": 2, "name": "0"}, {"id": 3, "name": "HERO STANDIN"}])
        _escribir(datos / "CommonEvents.json", _evento_mensaje_nlt())
        lineas = [
            "AlFrOp.Hi 1Hero! I'm so happy to see you.",
            "AlFrOp.I'm tired. Let's go home.",
            "McFrOp.Ana is my best friend. She is always there for me.",
            "McFrOp.Brian? He went to the church.",
            "BrFrOp.Bless you, my child.",
            "NPC.Who are you?",
        ]
        comandos = []
        for t in lineas:
            comandos += _mensaje([t])
        comandos += _mensaje(["1Hero is late again. He never comes on time."])
        comandos += _mensaje(["Miss Ana, welcome back. Father Brian is waiting."])
        comandos += _mensaje(["Ana said she would come. Ana? I haven't seen her."])
        comandos += _mensaje(["Do it 1Hero. She is ready for you."])  # vocativo sin coma: 'She' NO es 1Hero
        comandos += _mensaje(["Thanks, Sister. Brian said he would help."])  # 'Sister. Brian' no es tratamiento
        comandos.append(_cmd(102, [["I'm ready", "Not now"]]))
        _escribir(datos / "Map001.json", _mapa(comandos))
        return self.tmp / "Juego Codigos"

    def test_mapa_codigos_del_evento_mensaje(self):
        mapa = analizador._mapa_codigos(_evento_mensaje_nlt())
        self.assertEqual(mapa, {"Mc": "MC", "Al": "Ana", "Br": "Brian"})  # sin 'Vo'

    def test_analisis_completo_nlt(self):
        inf = analizador.analizar_juego(self._juego_nlt())
        f = inf.ficha
        self.assertEqual(inf.motor, "RPGMaker")
        self.assertEqual(inf.titulo, "Juego de Prueba")
        prota = f.protagonista()
        self.assertIsNotNone(prota)
        self.assertEqual(prota.nombre, "1Hero")          # el marcador del texto manda
        self.assertIn("William", prota.alias)              # el actor 1 queda como alias
        self.assertIn("\\N[1]", prota.alias)
        self.assertIn("Mc", prota.codigos)
        self.assertEqual(prota.genero, HOMBRE)
        ana = f.buscar("Ana")
        self.assertEqual(ana.genero, MUJER)
        self.assertIn("Al", ana.codigos)
        self.assertGreaterEqual(ana.apariciones, 2)
        brian = f.buscar("Brian")
        self.assertEqual(brian.genero, HOMBRE)
        self.assertIsNone(f.por_codigo("Vo"))
        self.assertIsNone(f.buscar("HERO STANDIN"))
        self.assertIsNone(f.buscar("0"))
        # La ficha resuelve los códigos tal y como los entrega el motor
        self.assertIs(f.por_codigo("AlFrOp"), ana)

    def test_mz_nombre_de_hablante(self):
        datos = self.tmp / "Juego MZ" / "data"
        _escribir(datos / "System.json", {"gameTitle": "MZ"})
        _escribir(datos / "Actors.json", [None, {"id": 1, "name": "Reid", "faceName": "Actor1", "faceIndex": 0}])
        comandos = []
        for _ in range(3):
            comandos += _mensaje(["I'm so happy today."], nombre_mz="Priscilla")
        comandos += _mensaje(["Priscilla is my girlfriend. She is great."], cara="Actor1", indice=0)
        _escribir(datos / "Map001.json", _mapa(comandos))
        inf = analizador.analizar_juego(self.tmp / "Juego MZ")
        pri = inf.ficha.buscar("Priscilla")
        self.assertEqual(pri.genero, MUJER)
        self.assertEqual(pri.apariciones, 3)
        prota = inf.ficha.protagonista()
        self.assertEqual(prota.nombre, "Reid")
        self.assertIn("face:Actor1#0", prota.codigos)

    def test_solo_copias_bak(self):
        datos = self.tmp / "Solo bak" / "www" / "data"
        _escribir(datos / "System.json.bak", {"gameTitle": "Con bak"})
        _escribir(datos / "Map001.json.bak", _mapa(_mensaje(["Hello Kayla. She looks happy."])))
        inf = analizador.analizar_juego(self.tmp / "Solo bak")
        self.assertEqual(inf.titulo, "Con bak")
        self.assertGreater(inf.lineas_analizadas, 0)


class TestOtrosMotores(_ConCarpeta):
    def test_renpy(self):
        juego = self.tmp / "VN" / "game"
        juego.mkdir(parents=True)
        (juego / "script.rpy").write_text(
            'define e = Character("Eileen")\n'
            'define mc = Character("[mcname]")\n'
            'label start:\n'
            '    e "I\'m Eileen. Nice to meet you."\n'
            '    mc "Hi Eileen."\n'
            '    "Eileen smiles. She looks happy."\n'
            '    e "Eileen is a girl who loves books."\n', encoding="utf-8")
        inf = analizador.analizar_juego(self.tmp / "VN")
        self.assertEqual(inf.motor, "RenPy")
        eileen = inf.ficha.buscar("Eileen")
        self.assertEqual(eileen.genero, MUJER)
        self.assertIn("renpy:e", eileen.codigos)
        prota = inf.ficha.protagonista()
        self.assertIsNotNone(prota)
        self.assertIn("renpy:mc", prota.codigos)

    def test_csv_con_caja_de_nombre(self):
        carpeta = self.tmp / "CSVJuego" / "locales"
        carpeta.mkdir(parents=True)
        filas = ["Key;English;Spanish"]
        for i in range(4):
            filas.append(f"k{i};\\N<\\C[2]Miya\\C[0]>I'm so hungry.;")
        filas.append("k9;Miya is my sister. She eats a lot.;")
        (carpeta / "main.csv").write_text("\n".join(filas) + "\n", encoding="utf-8")
        inf = analizador.analizar_juego(self.tmp / "CSVJuego", motor="CSV")
        miya = inf.ficha.buscar("Miya")
        self.assertIsNotNone(miya)
        self.assertEqual(miya.genero, MUJER)
        self.assertEqual(miya.apariciones, 4)

    def test_xunity_protagonista_por_vocativos(self):
        carpeta = self.tmp / "UnityJuego" / "BepInEx" / "Translation" / "es" / "Text"
        carpeta.mkdir(parents=True)
        lineas = []
        for i in range(8):
            lineas.append(f"Zoe, look at this number {i}!=Zoe, mira esto {i}!")
            lineas.append(f"Thanks, Zoe. That was {i} times great.=Gracias, Zoe.")
            lineas.append(f"I met Sarah at the bar {i}.=x")
        lineas += ["Zoe is late. She always is.=x", "Sarah is my best friend. She loves cats.=x",
                   "Did you see Sarah? I saw her yesterday.=x", "Zoe said she would come.=x"]
        (carpeta / "_AutoGeneratedTranslations.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        inf = analizador.analizar_juego(self.tmp / "UnityJuego", motor="Unity")
        prota = inf.ficha.protagonista()
        self.assertIsNotNone(prota)
        self.assertEqual(prota.nombre, "Zoe")
        self.assertEqual(prota.genero, MUJER)
        self.assertEqual(inf.ficha.buscar("Sarah").genero, MUJER)

    def test_xunity_nombres_fuera_del_lexico(self):
        """Caso real: 'Lio' no está en el léxico de nombres, pero los pronombres dicen
        que es un hombre. Los lugares ('the Glowing Hole', 'Nail Salon') no deben salir como personajes."""
        carpeta = self.tmp / "UnityJuego2" / "BepInEx" / "Translation" / "es" / "Text"
        carpeta.mkdir(parents=True)
        lineas = []
        for i in range(8):
            lineas.append(f"Zoe, look at this number {i}!=x")
            lineas.append(f"Thanks, Zoe. That was {i} times great.=x")
        for i in range(3):
            lineas.append(f"I should call my tech guy, Lio. He'll know what to do {i}.=x")
            lineas.append(f"We went to the Glowing Hole. She was there {i} times.=x")
            lineas.append(f"Visit the Nail Salon after helping Lio {i}.=x")
            lineas.append(f"Ask about Peitho at the desk {i}.=x")
        lineas.append("Ask about Peitho now.=x")
        (carpeta / "_AutoGeneratedTranslations.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        inf = analizador.analizar_juego(self.tmp / "UnityJuego2", motor="Unity")
        lio = inf.ficha.buscar("Lio")
        self.assertIsNotNone(lio)
        self.assertEqual(lio.genero, HOMBRE)
        for lugar in ("Glowing", "Hole", "Nail", "Salon", "Peitho"):
            self.assertIsNone(inf.ficha.buscar(lugar), lugar)
        self.assertEqual(inf.ficha.protagonista().nombre, "Zoe")

    def test_narracion_en_segunda_persona_no_elige_protagonista(self):
        juego = self.tmp / "VN2" / "game" / "tl" / "spanish"
        juego.mkdir(parents=True)
        lineas = []
        for i in range(30):
            lineas.append(f'    # "You walk to the kitchen {i} times."')
            lineas.append(f'    # "Mia, wait for me {i}!"')
        (juego / "s.rpy").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        inf = analizador.analizar_juego(self.tmp / "VN2", motor="RenPy")
        self.assertIsNone(inf.ficha.protagonista())
        self.assertTrue(any("2.ª persona" in a for a in inf.avisos))


class TestInferencia(unittest.TestCase):
    def test_decidir_genero(self):
        c = analizador._Candidato(nombre="X")
        self.assertEqual(analizador._decidir_genero(c), (DESCONOCIDO, 0.0))
        c.votar(MUJER, 1.0, "she")
        self.assertEqual(analizador._decidir_genero(c)[0], DESCONOCIDO)  # un solo voto no basta
        c.votar(MUJER, 2.0, "léxico")
        self.assertEqual(analizador._decidir_genero(c)[0], MUJER)
        c.votar(HOMBRE, 3.0, "he")
        self.assertEqual(analizador._decidir_genero(c)[0], DESCONOCIDO)  # evidencia contradictoria

    def test_lexico_y_roles(self):
        for nombre, esperado in (("Laura", MUJER), ("Bradley", HOMBRE), ("Henchwoman", MUJER),
                                 ("Old Man", HOMBRE), ("Wilson", DESCONOCIDO), ("Sam", DESCONOCIDO),
                                 ("Jaime", DESCONOCIDO), ("Mujer", MUJER)):
            c = analizador._Candidato(nombre=nombre)
            analizador._votar_lexico(c)
            self.assertEqual(analizador._decidir_genero(c)[0], esperado, nombre)

    def test_pronombre_objeto_en_la_misma_oracion_no_cuenta(self):
        c = analizador._Candidato(nombre="1Hero")
        analizador._votar_pronombre(c, " kissed her softly.", {"1Hero": c})
        self.assertEqual((c.m, c.f), (0.0, 0.0))
        k = analizador._Candidato(nombre="Kayla")
        analizador._votar_pronombre(k, "? I haven't seen her.", {"Kayla": k})
        self.assertGreater(k.f, 0)

    def test_posesivo_no_cuenta(self):
        c = analizador._Candidato(nombre="1Hero")
        analizador._votar_pronombre(c, "'s mom said she would call.", {"1Hero": c})
        self.assertEqual((c.m, c.f), (0.0, 0.0))

    def test_regex_literal(self):
        import re
        patron = re.compile(analizador._regex_literal("Ámbar"))
        for texto in ("Ámbar", "ámbar", "Ambar", "ambar"):
            self.assertTrue(patron.search(f"Hola, {texto}."), texto)
        self.assertIsNone(patron.search("Hola, Amber."))


class TestGuardado(_ConCarpeta):
    def setUp(self):
        super().setUp()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.parche = mock.patch.object(config, "DIR_WORKSPACE", self.ws)
        self.parche.start()
        datos = self.tmp / "Juego Amber" / "www" / "data"
        _escribir(datos / "System.json", {"gameTitle": "Amber"})
        _escribir(datos / "Actors.json", [None, {"id": 1, "name": "Max", "faceName": "", "faceIndex": 0}])
        comandos = []
        for _ in range(4):
            comandos += _mensaje(["\\n<Amber>I'm so happy, Max."])
        comandos += _mensaje(["Amber is my girlfriend. She is cute. Max is my brother. He is tall."])
        _escribir(datos / "Map001.json", _mapa(comandos))
        self.ruta_juego = self.tmp / "Juego Amber"

    def tearDown(self):
        self.parche.stop()
        super().tearDown()

    def test_simular_no_escribe(self):
        destino, inf = analizador.analizar_y_guardar("juego_amber", self.ruta_juego, simular=True)
        self.assertIsNone(destino)
        self.assertFalse((self.ws / "juego_amber").exists())
        self.assertEqual(inf.ficha.buscar("Amber").genero, MUJER)

    def test_guarda_fusiona_y_protege_nombres(self):
        carpeta = self.ws / "juego_amber"
        carpeta.mkdir()
        # El usuario ya confirmó que Max es mujer (aunque el texto diga 'he'): no se debe pisar
        FichaPersonajes([Personaje("Max", "mujer", "protagonista", confirmado=True)]).guardar(carpeta / "personajes.json")
        (carpeta / "nombres_propios.txt").write_text("Max\n", encoding="utf-8")
        destino, inf = analizador.analizar_y_guardar("juego_amber", self.ruta_juego)
        self.assertEqual(destino, carpeta / "personajes.json")
        ficha = FichaPersonajes.cargar(destino)
        self.assertEqual(ficha.buscar("Max").genero, MUJER)
        self.assertTrue(ficha.buscar("Max").confirmado)
        self.assertEqual(ficha.buscar("Amber").genero, MUJER)
        propios = (carpeta / "nombres_propios.txt").read_text(encoding="utf-8").split()
        self.assertEqual(propios.count("Max"), 1)
        self.assertIn("Amber", propios)
        protegidos = json.loads((carpeta / "nombres_protegidos.json").read_text(encoding="utf-8"))
        self.assertIn("Amber", protegidos)
        self.assertIn("mbar", protegidos["Amber"])

    def test_ia_mockeada(self):
        respuesta_tags = mock.Mock()
        respuesta_tags.json.return_value = {"models": [{"name": "IA_Traductora_v2:latest"}, {"name": "llama3.1:latest"}]}
        respuesta_tags.raise_for_status.return_value = None
        respuesta_gen = mock.Mock()
        respuesta_gen.json.return_value = {"response": '{"genero": "hombre", "motivo": "le llaman sir"}'}
        respuesta_gen.raise_for_status.return_value = None
        with mock.patch("requests.get", return_value=respuesta_tags) as get, \
                mock.patch("requests.post", return_value=respuesta_gen) as post:
            inf = analizador.analizar_juego(self.ruta_juego, usar_ia=True)
        self.assertTrue(get.called)
        modelos = {llamada.kwargs["json"]["model"] for llamada in post.call_args_list}
        self.assertTrue(modelos <= {"llama3.1:latest"})  # nunca el modelo traductor afinado
        self.assertIsNotNone(inf.ficha.protagonista())


if __name__ == "__main__":
    unittest.main()
