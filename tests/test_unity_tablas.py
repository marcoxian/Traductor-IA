"""Unity: tablas de texto del juego (CSV/TSV con columna inglesa) traducidas por adelantado.
Todo con datos inventados; ningún test abre un juego ni llama a Ollama."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from traductor import xunity
from traductor.motores.unity_tablas import (AjustesTablas, PistasTablas, elegir, genero_de_quien_escucha,
                                            genero_de_quien_habla, info_de_fila, leer_tabla, pretraducir_tablas)
from traductor.personajes import FichaPersonajes, InfoLinea, Personaje

CSV = ('ID,ZH,EN,JA,ua,ru\r\n'
       '1,測試,,,,\r\n'                                   # sin inglés: fuera
       '2,藍天,"The sky was blue, and I opened the window.",青い空,"Я відчинив вікно.","Я открыл окно."\r\n'
       '3,我,"I read the whole book, so don\'t lie.",本,"Я прочитала всю книгу.","Я прочитала всю книгу."\r\n'
       '4,咚,"Thud, thud.",ドン,"Бум.","Бам."\r\n'
       '5,中,兩者下面皆是同樣對話,,,\r\n'                  # la columna inglesa trae chino: fuera
       '6,咚,"Thud, thud.",ドン,"Бум.","Бам."\r\n')        # repetida: una sola vez

TSV = ('keys\ttw\ten\tko\r\n'
       'UI1\t成就\tAchievements\t실적\r\n'
       'UI2\t說明\t"Hm?" Start a new game?\\nThis will overwrite your save.\t설명\r \\n 끝\r\n')  # "\r" suelto


class TestLeerTabla(unittest.TestCase):
    def test_csv_con_columna_inglesa_y_pista_de_sexo(self):
        t = leer_tabla("TextData", CSV)
        self.assertEqual(t.entradas, [("The sky was blue, and I opened the window.", "hombre"),
                                      ("I read the whole book, so don't lie.", "mujer"),
                                      ("Thud, thud.", None)])

    def test_tsv_con_saltos_escritos_y_retorno_suelto(self):
        t = leer_tabla("testData", TSV)
        self.assertEqual([e for e, _ in t.entradas],
                         ["Achievements", '"Hm?" Start a new game?\nThis will overwrite your save.'])
        self.assertFalse(t.es_dialogo)  # frases cortas de menú: sin conversación previa

    def test_sin_columna_inglesa_o_binario(self):
        self.assertIsNone(leer_tabla("x", "ID,ZH,JA\n1,a,b\n"))
        self.assertIsNone(leer_tabla("x", "\x02\x00\x00\x00datos"))

    def test_pausa_en_mitad_de_frase_tambien_se_traduce_por_trozos(self):
        csv = ('ID,EN,ru\n1,"I was sure she would be angry,{wc} so I ran.","Я был уверен."\n'
               '2,"Training results: {0} Attack +{1}",\n')
        self.assertEqual(leer_tabla("t", csv).entradas,
                         [("I was sure she would be angry,{wc} so I ran.", "hombre"),
                          ("I was sure she would be angry,", "hombre"), ("so I ran.", "hombre"),
                          ("Training results: {0} Attack +{1}", None)])  # {0} es un número, no una pausa

    def test_misma_frase_dicha_por_los_dos_sexos_queda_sin_pista(self):
        csv = ('ID,EN,ru\n1,"I did it.","Я сделал это."\n2,"I did it.","Я сделала это."\n')
        self.assertEqual(leer_tabla("t", csv).entradas, [("I did it.", None)])


CSV_HABLANTE = (',,zh,en,ru\r\n'
                '1,莉莉,「我來了」,"I came back for you, Chef.","Я вернулась ради тебя."\r\n'
                '2,廚師,「好」,"Fine. I was waiting.","Ладно."\r\n'
                '3,無,{flag=Flag_Heroine}走了,"{flag=Flag_Heroine} leaves the room.","Лили уходит."\r\n'
                '4,莉莉,「他說」,"He said: I did it myself.","Он сказал: я сделал это сам."\r\n'
                '5,？？？,「誰」,"Who\'s there?","Кто там?"\r\n')
AJUSTES = AjustesTablas.desde_dict({
    "omitir": ["vieja*"],
    "columna_hablante": {"TextData*": 1},
    "hablantes": {"莉莉": "Lily", "廚師": "Protagonist", "無": "Protagonist", "？？？": ""},
    "variables": {"{flag=Flag_Heroine}": "Lily"},
})
FICHA = FichaPersonajes(personajes=[Personaje("Protagonist", "hombre", rol="protagonista"),
                                    Personaje("Lily", "mujer")])


class TestColumnaDeHablante(unittest.TestCase):
    def test_lee_quien_habla_y_sustituye_variables(self):
        t = leer_tabla("TextData_Extra", CSV_HABLANTE, AJUSTES)
        self.assertEqual(t.hablantes["I came back for you, Chef."], "莉莉")
        self.assertIn("Lily leaves the room.", t.hablantes)          # XUnity ve el nombre ya puesto
        self.assertEqual(t.hablantes["Lily leaves the room."], "無")
        # otra tabla sin columna configurada: no hay hablante
        self.assertEqual(leer_tabla("Otra", CSV_HABLANTE, AJUSTES).hablantes["Fine. I was waiting."], None)

    def test_omitir_por_patron(self):
        self.assertTrue(AJUSTES.se_omite("vieja_tabla"))
        self.assertFalse(AJUSTES.se_omite("TextData"))

    def test_info_de_fila(self):
        t = leer_tabla("TextData", CSV_HABLANTE, AJUSTES)
        info = {e: info_de_fila(t.hablantes[e], g, AJUSTES, FICHA, {}) for e, g in t.entradas}
        self.assertEqual(info["I came back for you, Chef."], InfoLinea(hablante="Lily", genero="mujer"))
        self.assertEqual(info["Fine. I was waiting."], InfoLinea(hablante="Protagonist", genero="hombre"))
        # la pista rusa de la línea (cita de un hombre) contradice a Lily: gana la pista, sin hablante
        self.assertEqual(info["He said: I did it myself."], InfoLinea(hablante=None, genero="hombre"))
        self.assertIsNone(info["Who's there?"])                       # "" = nadie de la ficha, sin pista

    def test_pretraducir_pasa_el_hablante(self):
        t = TraductorFalso({}, FICHA)
        with tempfile.TemporaryDirectory() as tmp:
            pretraducir_tablas(Path(tmp), t, Path(tmp) / "_AutoGeneratedTranslations.txt",
                               tablas=[leer_tabla("TextData", CSV_HABLANTE, AJUSTES)], ajustes=AJUSTES)
        pedidas = dict(t.pedidas)
        self.assertEqual(pedidas["I came back for you, Chef."], InfoLinea(hablante="Lily", genero="mujer"))
        self.assertEqual(pedidas["Lily leaves the room."], InfoLinea(hablante="Protagonist", genero="hombre"))

    def test_auditoria_usa_el_hablante(self):
        pistas = PistasTablas([leer_tabla("TextData", CSV_HABLANTE, AJUSTES)], FICHA, AJUSTES)
        self.assertEqual(pistas.info("Fine. I was waiting."), InfoLinea(hablante="Protagonist", genero="hombre"))


class TestPistaDeSexo(unittest.TestCase):
    def test_pasado_ruso_y_ucraniano(self):
        self.assertEqual(genero_de_quien_habla({"ru": "Я думал, что она злится."}), "hombre")
        self.assertEqual(genero_de_quien_habla({"ru": "Я слышала об этом."}), "mujer")
        self.assertEqual(genero_de_quien_habla({"ua": "Я відчинив вікно."}), "hombre")
        self.assertEqual(genero_de_quien_habla({"ru": "Я должна быть первой!"}), "mujer")
        self.assertIsNone(genero_de_quien_habla({"ru": "Голубое небо, белые облака."}))

    def test_si_se_contradicen_no_hay_pista(self):
        self.assertIsNone(genero_de_quien_habla({"ru": "Я сделала это.", "ua": "Я зробив це."}))

    def test_sexo_de_quien_escucha(self):
        """"Tú" en ruso/ucraniano: el pasado y el adjetivo corto dicen el sexo de quien escucha."""
        self.assertEqual(genero_de_quien_escucha({"ru": "Ты уверена, что уходишь?"}), "mujer")
        self.assertEqual(genero_de_quien_escucha({"ru": "Ты хорошо поработал!"}), "hombre")
        self.assertEqual(genero_de_quien_escucha({"ru": "Почему ты разделась?"}), "mujer")
        self.assertEqual(genero_de_quien_escucha({"ua": "Ти впевнена?"}), "mujer")
        self.assertEqual(genero_de_quien_escucha({"ua": "Ти не правий."}), None)   # "правий" no está: sin pista
        self.assertEqual(genero_de_quien_escucha({"ru": "Ты должен идти.", "ua": "Ти повинен іти."}), "hombre")
        self.assertIsNone(genero_de_quien_escucha({"ru": "Я устала."}))           # habla de sí: no es "tú"
        self.assertIsNone(genero_de_quien_escucha({"ru": "Ты сделала это.", "ua": "Ти зробив це."}))  # se contradicen
        # Quien habla y quien escucha a la vez
        celdas = {"ru": "Я рада, что ты пришёл."}
        self.assertEqual((genero_de_quien_habla(celdas), genero_de_quien_escucha(celdas)), ("mujer", "hombre"))


class TestPistasTablas(unittest.TestCase):
    def test_busca_por_frase_y_normalizada(self):
        csv = ('ID,EN,ru\n'
               '1,"Are you sure?","Ты уверена?"\n'
               '2,"<b>Why are you naked?</b>","Почему ты разделась?"\n'
               '3,"I did it.","Я сделала это."\n'
               '4,"You did it.","Ты сделал это."\n'
               '5,"You did it.","Ты сделала это."\n')     # misma frase a los dos sexos: sin pista
        pistas = PistasTablas([leer_tabla("t", csv)])
        self.assertEqual(pistas.genero_oyente("Are you sure?"), "mujer")
        self.assertEqual(pistas.genero_oyente("Why are you naked?"), "mujer")   # sin la etiqueta
        self.assertIsNone(pistas.genero_oyente("You did it."))
        self.assertEqual(pistas.info("I did it."), InfoLinea(hablante=None, genero="mujer"))
        self.assertIsNone(pistas.info("Are you sure?"))
        self.assertEqual(pistas.escena("Are you sure?"), ())


class TraductorFalso:
    def __init__(self, respuestas, ficha=None):
        self.respuestas = respuestas
        self.pedidas = []
        self.usar_historial = True
        self.historial = []
        self.perfil = type("P", (), {"personajes": ficha})()
        self.historiales = []

    def translate(self, texto, info=None, lanzar_error=False):
        self.pedidas.append((texto, info))
        self.historiales.append(self.usar_historial)
        return self.respuestas.get(texto, texto)


class TestPretraducir(unittest.TestCase):
    def test_escribe_las_tablas_y_retraduce_lo_suelto(self):
        ficha = FichaPersonajes(personajes=[Personaje("Protagonist", "hombre", rol="protagonista"),
                                            Personaje("Ana", "mujer")])
        tablas = [leer_tabla("TextData", CSV)]
        t = TraductorFalso({"The sky was blue, and I opened the window.": "El cielo era azul y abrí la ventana.",
                            "I read the whole book, so don't lie.": "Me leí el libro entero, así que no mientas.",
                            "Thud, thud.": "Pum, pum.",
                            "Settings": "Ajustes",
                            "Day 1": "Day 1"}, ficha)
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "_AutoGeneratedTranslations.txt"
            # lo que dejó otro traductor automático
            ruta.write_text("Thud, thud.=Ruido sordo, ruido sordo.\nSettings=Configuración\nDay 1=Día 1\n",
                            encoding="utf-8")
            stats = pretraducir_tablas(Path(tmp), t, ruta, tablas=tablas)
            final = xunity.leer_traducciones(ruta)
        self.assertEqual(final["Thud, thud."], "Pum, pum.")              # la nueva no es peor: entra
        self.assertEqual(final["Settings"], "Ajustes")                    # suelta del archivo: retraducida
        self.assertEqual(final["Day 1"], "Día 1")                         # la IA devolvió el inglés: se queda
        self.assertEqual(final["I read the whole book, so don't lie."], "Me leí el libro entero, así que no mientas.")
        # el único chico de la ficha es el protagonista: lo que dice "un chico" lo dice él
        self.assertEqual(t.pedidas[0][1], InfoLinea(hablante="Protagonist", genero="hombre"))
        self.assertEqual(t.pedidas[1][1], InfoLinea(hablante=None, genero="mujer"))
        self.assertIsNone(t.pedidas[2][1])
        self.assertEqual(stats["frases"], 5)
        self.assertTrue(t.usar_historial)  # se devuelve como estaba

    def test_elegir(self):
        self.assertEqual(elegir("Settings", "Configuración", "Ajustes"), "Ajustes")
        self.assertEqual(elegir("Open the door.", "Abre la puerta.", "Open the door."), "Abre la puerta.")
        self.assertEqual(elegir("Open the door.", "Abre la puerta.", None), "Abre la puerta.")
        self.assertEqual(elegir("Open the door.", None, "Abre la puerta."), "Abre la puerta.")


if __name__ == "__main__":
    unittest.main()
