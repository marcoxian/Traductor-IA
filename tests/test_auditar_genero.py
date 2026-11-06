"""Pruebas de 8_auditar_genero.py (auditoría de género de juegos ya traducidos)."""
from __future__ import annotations

import importlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from traductor.personajes import FichaPersonajes, Personaje

auditoria = importlib.import_module("8_auditar_genero")


def _ficha() -> FichaPersonajes:
    return FichaPersonajes([
        Personaje("1Hero", "mujer", "protagonista", codigos=["Mc"]),
        Personaje("Laura", "mujer", "principal", codigos=["He"]),
        Personaje("Bradley", "hombre", "principal", codigos=["Br"]),
    ])


def _cmd(code, params):
    return {"code": code, "indent": 0, "parameters": params}


def _mapa(comandos):
    return {"events": [None, {"pages": [{"list": comandos + [_cmd(0, [])]}]}]}


class TestAuditoriaRPGMaker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.datos = self.tmp / "www" / "data"
        self.datos.mkdir(parents=True)
        original = _mapa([
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["HeFrOp.I'm so tired. I worked all day long"]),
            _cmd(401, ["at the hospital today."]),
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["BrFrOp.I'm ready."]),
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["Hello there."]),
        ])
        traducido = _mapa([
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["HeFrOp.Estoy tan cansado. He trabajado todo el"]),
            _cmd(401, ["día en el hospital."]),
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["BrFrOp.Estoy listo."]),
            _cmd(101, ["", 0, 0, 2]), _cmd(401, ["Hola."]),
        ])
        (self.datos / "Map001.json.bak").write_text(json.dumps(original), encoding="utf-8")
        self.json = self.datos / "Map001.json"
        self.json.write_text(json.dumps(traducido, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _textos(self) -> list[str]:
        datos = json.loads(self.json.read_text(encoding="utf-8"))
        return [c["parameters"][0] for c in datos["events"][1]["pages"][0]["list"] if c["code"] == 401]

    def test_informe_sin_corregir_no_modifica(self):
        antes = self.json.read_text(encoding="utf-8")
        hallazgos, avisos = auditoria.auditar_rpgmaker(self.tmp, _ficha(), corregir=False)
        self.assertEqual(avisos, [])
        self.assertEqual(len(hallazgos), 1)
        h = hallazgos[0]
        self.assertEqual(h.tipo, auditoria.CORREGIBLE)
        self.assertEqual(h.hablante, "Laura")
        self.assertIn("Estoy tan cansada.", h.propuesta)
        self.assertTrue(h.contexto.startswith("(inicio) ‖ « I'm ready. »"), h.contexto)
        self.assertEqual(self.json.read_text(encoding="utf-8"), antes)

    def test_corregir_aplica_y_hace_copia(self):
        auditoria.auditar_rpgmaker(self.tmp, _ficha(), corregir=True)
        textos = " ".join(self._textos())
        self.assertIn("HeFrOp.Estoy tan cansada.", textos)
        self.assertIn("día en el hospital.", textos)
        self.assertIn("BrFrOp.Estoy listo.", textos)   # el de Bradley (hombre) no se toca
        self.assertTrue(self.json.with_name("Map001.json.auditoria.bak").exists())
        # Una segunda pasada ya no encuentra nada
        hallazgos, _ = auditoria.auditar_rpgmaker(self.tmp, _ficha(), corregir=False)
        self.assertEqual(hallazgos, [])


class TestSegundaPersonaSinNombrar(unittest.TestCase):
    """X3: la frase no nombra a quien escucha; se mira quién más está en la escena."""

    @staticmethod
    def _ficha() -> FichaPersonajes:
        return FichaPersonajes([
            Personaje("1Hero", "hombre", "protagonista", codigos=["Mc"]),
            Personaje("Laura", "mujer", "principal", codigos=["He"]),
            Personaje("Chloe", "mujer", "principal", codigos=["Ch"]),
        ])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        datos = self.tmp / "www" / "data"
        datos.mkdir(parents=True)
        pausa = [("The wind blows.", "Sopla el viento.")] * 4   # separa las escenas (nadie habla)
        frases = [
            # Escena 1: Laura a solas con el protagonista (hombre)
            ("HeFrOp.Are you sure?", "HeFrOp.¿Estás segura?"),
            ("McFrOp.You're crazy.", "McFrOp.Estás loco."),                       # él le habla a ella
            ("HeFrOp.Don't be silly, girl.", "HeFrOp.No seas tonta, chica."),      # el inglés ya dice 'girl'
            ("HeFrOp.Don't be so hard on yourself.", "HeFrOp.No seas tan dura contigo misma."),
            *pausa,
            # Escena 2: también está Chloe; "¿Estás loca?" puede ir para ella
            ("HeFrOp.Are you crazy?", "HeFrOp.¿Estás loca?"),
            ("ChFrOp.Me?", "ChFrOp.¿Yo?"),
            ("McFrOp.Hi.", "McFrOp.Hola."),
            *pausa,
            # Escena 3: habla alguien que no está en la ficha, a solas con el protagonista
            ("NpFrOp.I'm on break. Cook it yourself.", "NpFrOp.Estoy de descanso. Cocínala tú misma."),
            ("McFrOp.Fine.", "McFrOp.Vale."),
        ]
        comandos_o, comandos_t = [], []
        for o, t in frases:
            comandos_o += [_cmd(101, ["", 0, 0, 2]), _cmd(401, [o])]
            comandos_t += [_cmd(101, ["", 0, 0, 2]), _cmd(401, [t])]
        (datos / "Map001.json.bak").write_text(json.dumps(_mapa(comandos_o)), encoding="utf-8")
        self.json = datos / "Map001.json"
        self.json.write_text(json.dumps(_mapa(comandos_t), ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _textos(self) -> list[str]:
        datos = json.loads(self.json.read_text(encoding="utf-8"))
        return [c["parameters"][0] for c in datos["events"][1]["pages"][0]["list"] if c["code"] == 401]

    def test_informe(self):
        hallazgos, _ = auditoria.auditar_rpgmaker(self.tmp, self._ficha())
        propuestas = {h.original: (h.tipo, h.propuesta) for h in hallazgos}
        self.assertEqual(propuestas["Are you sure?"], (auditoria.PROBABLE, "¿Estás seguro?"))
        self.assertEqual(propuestas["You're crazy."], (auditoria.PROBABLE, "Estás loca."))
        self.assertEqual(propuestas["Don't be so hard on yourself."],
                         (auditoria.PROBABLE, "No seas tan duro contigo mismo."))
        self.assertNotIn("Don't be silly, girl.", propuestas)   # 'girl': va para una chica
        self.assertNotIn("Are you crazy?", propuestas)          # Chloe también está en la escena
        self.assertEqual(propuestas["I'm on break. Cook it yourself."],
                         (auditoria.PROBABLE, "Estoy de descanso. Cocínala tú mismo."))
        self.assertIn("en la escena: 1Hero (hombre)", hallazgos[0].motivo)

    def test_dudosas_senala_la_escena_con_otra_mujer(self):
        hallazgos, _ = auditoria.auditar_rpgmaker(self.tmp, self._ficha(), dudosas=True)
        h = next(h for h in hallazgos if h.original == "Are you crazy?")
        self.assertEqual((h.tipo, h.propuesta), (auditoria.REVISAR, ""))
        self.assertIn("Chloe (mujer)", h.motivo)

    def test_solo_se_aplica_con_segunda(self):
        antes = self._textos()
        auditoria.auditar_rpgmaker(self.tmp, self._ficha(), corregir=True)
        self.assertEqual(self._textos(), antes)
        auditoria.auditar_rpgmaker(self.tmp, self._ficha(), corregir=True, segunda=True)
        textos = self._textos()
        self.assertIn("HeFrOp.¿Estás seguro?", textos)
        self.assertIn("McFrOp.Estás loca.", textos)
        self.assertIn("HeFrOp.No seas tonta, chica.", textos)
        self.assertIn("HeFrOp.¿Estás loca?", textos)
        self.assertIn("NpFrOp.Estoy de descanso. Cocínala tú mismo.", textos)
        self.assertEqual(auditoria.auditar_rpgmaker(self.tmp, self._ficha())[0], [])

    def test_plural_segun_la_escena(self):
        """S2: el protagonista (hombre) habla a Laura y Chloe: "vosotros dos" va en femenino."""
        ficha = self._ficha()
        ctx = auditoria.resolver_linea(ficha, "You two are fucked up.", auditoria.InfoLinea(codigo="Mc"))
        oyentes = [ficha.buscar("Laura"), ficha.buscar("Chloe")]
        h = auditoria.revisar_par(ficha, "You two are fucked up.", "Vosotros dos estáis jodidos.", None, "x",
                                  ctx=ctx, oyentes=oyentes)
        self.assertEqual((h.tipo, h.propuesta), (auditoria.PROBABLE, "Vosotras dos estáis jodidas."))
        self.assertIn("el plural va en femenino", h.motivo)
        # Propuesta a medias ("creativo" no está en la lista): solo para revisar
        h = auditoria.revisar_par(ficha, "You two are creative.", "Vosotros dos sois muy creativos.", None, "x",
                                  ctx=ctx, oyentes=oyentes)
        self.assertEqual(h.tipo, auditoria.REVISAR)
        # Si en la escena también hay un hombre, no se sabe a quiénes habla: no se toca
        ficha.personajes.append(Personaje("Bradley", "hombre", codigos=["Br"]))
        ficha.reindexar()
        h = auditoria.revisar_par(ficha, "You two are fucked up.", "Vosotros dos estáis jodidos.", None, "x",
                                  ctx=ctx, oyentes=oyentes + [ficha.buscar("Bradley")])
        self.assertIsNone(h)
        # "you boys": el inglés da la razón a la traducción (habla a otros que no están en la escena)
        ctx = auditoria.resolver_linea(ficha, "You boys are crazy.", auditoria.InfoLinea(codigo="Mc"))
        self.assertIsNone(auditoria.revisar_par(ficha, "You boys are crazy.", "Vosotros estáis locos.", None,
                                                "x", ctx=ctx, oyentes=oyentes))

    def test_genero_desconocido_en_la_escena_no_es_probable(self):
        ficha = self._ficha()
        ficha.personajes.append(Personaje("Guard", "desconocido", codigos=["Gu"]))
        ficha.reindexar()
        ctx = auditoria.resolver_linea(ficha, "Are you sure?", auditoria.InfoLinea(codigo="He"))
        oyentes = [ficha.buscar("Guard")]
        h = auditoria.revisar_par(ficha, "Are you sure?", "¿Estás segura?", None, "x", ctx=ctx, oyentes=oyentes)
        self.assertEqual(h.tipo, auditoria.REVISAR)
        self.assertEqual(h.propuesta, "¿Estás seguro?")
        self.assertIn("género desconocido", h.motivo)


class TestAuditoriaCSVyXUnity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_csv(self):
        carpeta = self.tmp / "locales"
        carpeta.mkdir()
        (carpeta / "main.csv.original").write_text(
            "Key;English\nk1;\\N<\\C[2]Laura\\C[0]>I'm so tired.\nk2;Hello.\n", encoding="utf-8")
        actual = carpeta / "main.csv"
        actual.write_text("Key;English\nk1;\\N<\\C[2]Laura\\C[0]>Estoy tan cansado.\nk2;Hola.\n", encoding="utf-8")
        hallazgos, _ = auditoria.auditar_csv(self.tmp, _ficha(), corregir=False)
        self.assertEqual(len(hallazgos), 1)
        self.assertIn("cansado", actual.read_text(encoding="utf-8"))
        auditoria.auditar_csv(self.tmp, _ficha(), corregir=True)
        texto = actual.read_text(encoding="utf-8")
        self.assertIn("\\N<\\C[2]Laura\\C[0]>Estoy tan cansada.", texto)
        self.assertIn("k2;Hola.", texto)

    def test_xunity_pensamiento_de_la_protagonista(self):
        txt = self.tmp / "_AutoGeneratedTranslations.txt"
        txt.write_text("(I'm sure it's a trap.)=(Estoy seguro de que es una trampa.)\n"
                       "Bradley is tired.=Bradley está cansada.\n"
                       "I'm sure.=Estoy seguro.\n", encoding="utf-8-sig")
        hallazgos, _ = auditoria.auditar_xunity(txt, _ficha(), corregir=True)
        self.assertEqual(len(hallazgos), 2)  # 'Estoy seguro.' sin hablante conocido no se toca
        from traductor import xunity
        pares = xunity.leer_traducciones(txt)
        self.assertEqual(pares["(I'm sure it's a trap.)"], "(Estoy segura de que es una trampa.)")
        self.assertEqual(pares["Bradley is tired."], "Bradley está cansado.")
        self.assertEqual(pares["I'm sure."], "Estoy seguro.")

    def test_xunity_solo_reescribe_las_lineas_corregidas(self):
        """Archivo real de XUnity: sin BOM, CRLF, líneas en blanco, claves repetidas, URL con \\/\\/,
        líneas que XUnity ignora y un byte no UTF-8. Solo deben cambiar las líneas corregidas."""
        txt = self.tmp / "_AutoGeneratedTranslations.txt"
        lineas = [
            b"Glowing Hole \\/\\/ Staff Login=Hoyo luminoso \\/\\/ Acceso del personal",
            b"",
            b"(I'm sure it's a trap.)=(Estoy seguro de que es una trampa.)",
            b"<color=#EB83FF>roto</color>=<color=#EB83FF>roto</color>",  # 2 '=' sin escapar: XUnity la ignora
            b"https:\\/\\/x.com/brothbowl=https:\\/\\/x.com/brothbowl",
            b"(I'm sure it's a trap.)=(Estoy seguro de que es una trampa.)",  # clave repetida
            "Café=Café".encode("utf-8") + b"\xe9",  # byte suelto no UTF-8
            b"Glowing Hole \\/\\/ Staff Login=Hoyo Resplandeciente \\/\\/ Acceso del personal",
        ]
        original = b"\r\n".join(lineas) + b"\r\n"
        txt.write_bytes(original)

        hallazgos, _ = auditoria.auditar_xunity(txt, _ficha(), corregir=False)
        self.assertEqual(len(hallazgos), 1)  # la línea repetida se informa una sola vez
        self.assertEqual(txt.read_bytes(), original)  # sin --corregir no se toca

        auditoria.auditar_xunity(txt, _ficha(), corregir=True)
        corregida = b"(I'm sure it's a trap.)=(Estoy segura de que es una trampa.)"
        esperado = list(lineas)
        esperado[2] = esperado[5] = corregida
        self.assertEqual(txt.read_bytes(), b"\r\n".join(esperado) + b"\r\n")
        self.assertEqual(txt.with_name(txt.name + ".auditoria.bak").read_bytes(), original)

    def test_xunity_nombres_protegidos_y_contexto(self):
        from traductor import config
        txt = self.tmp / "_AutoGeneratedTranslations.txt"
        txt.write_text("Hello.=Hola.\n"
                       "My Jasmine! Did you see her?=¡Mi jazmín! ¿La viste?\n"
                       "(I'm sure it's Jasmine.)=(Estoy seguro de que es Jazmín.)\n"
                       "Goodbye.=Adiós.\n", encoding="utf-8")
        perfil = config.Perfil(nombres_protegidos={"Jasmine": r"\b[jJ]azmín\b"}, personajes=_ficha())
        # Sin perfil de nombres: solo el género del pensamiento
        hallazgos, _ = auditoria.auditar_xunity(txt, _ficha())
        self.assertEqual([h.propuesta for h in hallazgos], ["(Estoy segura de que es Jazmín.)"])
        self.assertIn("« My Jasmine! Did you see her? »", hallazgos[0].contexto)   # frase anterior
        self.assertIn("« Goodbye. »", hallazgos[0].contexto)                        # frase siguiente
        # Con nombres: se restaura "Jasmine" y se combina con la corrección de género
        hallazgos, _ = auditoria.auditar_xunity(txt, _ficha(), corregir=True, perfil_nombres=perfil)
        self.assertEqual(len(hallazgos), 2)
        from traductor import xunity
        pares = xunity.leer_traducciones(txt)
        self.assertEqual(pares["My Jasmine! Did you see her?"], "¡Mi Jasmine! ¿La viste?")
        self.assertEqual(pares["(I'm sure it's Jasmine.)"], "(Estoy segura de que es Jasmine.)")
        self.assertEqual(pares["Hello."], "Hola.")

    def test_csv_segunda_persona_sin_nombrar(self):
        """Los CSV con caja de nombre también miran quién está en la escena."""
        ficha = TestSegundaPersonaSinNombrar._ficha()
        carpeta = self.tmp / "locales"
        carpeta.mkdir()
        (carpeta / "main.csv.original").write_text(
            "Key;English\nk1;\\N<Laura>Are you ready?\nk2;\\N<1Hero>Yes.\n", encoding="utf-8")
        actual = carpeta / "main.csv"
        actual.write_text("Key;English\nk1;\\N<Laura>¿Estás lista?\nk2;\\N<1Hero>Sí.\n", encoding="utf-8")
        hallazgos, _ = auditoria.auditar_csv(self.tmp, ficha, corregir=True, segunda=True)
        self.assertEqual([(h.tipo, h.propuesta) for h in hallazgos], [(auditoria.PROBABLE, "¿Estás listo?")])
        self.assertIn("k1;\\N<Laura>¿Estás listo?", actual.read_text(encoding="utf-8"))

    def test_xunity_con_tabla_de_hablantes(self):
        """Unity: con la tabla de quién habla y la escena, se revisa la 2.ª persona y el plural."""
        from traductor.unity_dialogos import Hablante, TablaHablantes
        ficha = TestSegundaPersonaSinNombrar._ficha()     # 1Hero (hombre, protagonista), Laura y Chloe (mujeres)
        laura, chloe, hero = Hablante("Laura", "mujer"), Hablante("Chloe", "mujer"), Hablante("1Hero", "hombre")
        txt = self.tmp / "_AutoGeneratedTranslations.txt"
        lineas = [
            "Are you sure?=¿Estás segura?",                                       # Laura a 1Hero: "seguro"
            "Are you sure about that?=¿Estás segura de eso?",                     # Laura con Chloe delante: no se sabe
            "Wait, that was you two?=Espera, ¿eran vosotros?",                    # 1Hero ante Laura y Chloe
            "We are ready, Chloe.=Estamos listos, Chloe.",                        # Laura y Chloe: "we" a secas -> a mano
            "We are ready.=Estamos listos.",                                      # con 1Hero cerca: puede ser mixto
            "We both know it, Chloe.=Ambos lo sabemos, Chloe.",                   # solo Laura y Chloe, "both"
        ]
        txt.write_bytes(("\r\n".join(lineas) + "\r\n").encode("utf-8"))
        tabla = TablaHablantes(
            {"Are you sure?": laura, "Are you sure about that?": laura, "Wait, that was you two?": hero,
             "We are ready, Chloe.": laura, "We are ready.": laura, "We both know it, Chloe.": laura},
            {"Are you sure?": (laura, hero), "Are you sure about that?": (laura, chloe, hero),
             "Wait, that was you two?": (hero, laura, chloe), "We are ready, Chloe.": (laura, chloe),
             "We are ready.": (laura, chloe), "We both know it, Chloe.": (laura, chloe)})
        hallazgos, _ = auditoria.auditar_xunity(txt, ficha, hablantes=tabla)
        resultado = {h.original: (h.tipo, h.propuesta) for h in hallazgos}
        self.assertEqual(resultado["Are you sure?"], (auditoria.PROBABLE, "¿Estás seguro?"))
        self.assertNotIn("Are you sure about that?", resultado)
        self.assertEqual(resultado["Wait, that was you two?"], (auditoria.PROBABLE, "Espera, ¿eran vosotras?"))
        self.assertEqual(resultado["We are ready, Chloe."][0], auditoria.REVISAR)   # "we" a secas: solo revisar
        self.assertNotIn("We are ready.", resultado)                                # 1Hero escucha: no se sabe
        self.assertEqual(resultado["We both know it, Chloe."][0], auditoria.CORREGIBLE)
        # Sin --segunda solo se aplican las correcciones seguras
        original = txt.read_bytes()
        auditoria.auditar_xunity(txt, ficha, corregir=True, hablantes=tabla)
        self.assertEqual(txt.read_bytes().decode("utf-8").splitlines()[0], "Are you sure?=¿Estás segura?")
        self.assertIn("Ambas lo sabemos, Chloe.", txt.read_text(encoding="utf-8"))
        txt.write_bytes(original)
        auditoria.auditar_xunity(txt, ficha, corregir=True, segunda=True, hablantes=tabla)
        resultado = txt.read_bytes().decode("utf-8")
        self.assertIn("Are you sure?=¿Estás seguro?\r\n", resultado)
        self.assertIn("¿eran vosotras?", resultado)
        self.assertIn("We are ready, Chloe.=Estamos listos, Chloe.\r\n", resultado)  # lo dudoso no se toca

    def test_xunity_con_pistas_del_ruso(self):
        """Juego de Unity sin objetos Dialogue: el ruso de sus tablas dice el sexo de quien escucha."""
        from traductor.motores.unity_tablas import PistasTablas, leer_tabla
        csv = ('ID,EN,ru\n1,"Are you sure?","Ты уверена?"\n2,"You did well!","Ты хорошо поработал!"\n'
               '3,"Are you ready?","Ты готова?"\n')
        pistas = PistasTablas([leer_tabla("t", csv)], _ficha())
        txt = self.tmp / "_AutoGeneratedTranslations.txt"
        txt.write_text("Are you sure?=¿Estás seguro?\nYou did well!=¡Lo has hecho bien!\n"
                       "Are you ready?=¿Estás lista?\n", encoding="utf-8")
        hallazgos, _ = auditoria.auditar_xunity(txt, _ficha(), hablantes=pistas)
        self.assertEqual([(h.original, h.tipo, h.propuesta) for h in hallazgos],
                         [("Are you sure?", auditoria.PROBABLE, "¿Estás segura?")])
        self.assertIn("rusa/ucraniana", hallazgos[0].motivo)
        auditoria.auditar_xunity(txt, _ficha(), corregir=True, hablantes=pistas)           # sin --segunda
        self.assertIn("¿Estás seguro?", txt.read_text(encoding="utf-8"))
        auditoria.auditar_xunity(txt, _ficha(), corregir=True, segunda=True, hablantes=pistas)
        self.assertIn("Are you sure?=¿Estás segura?", txt.read_text(encoding="utf-8"))

    def test_dudosas_segunda_persona_sin_destinatario(self):
        """Protagonista mujer (1Hero en la ficha de prueba) y nadie nombrado: '¿Eres nuevo?' se señala
        para revisar (probablemente se lo dicen a ella), pero no se corrige solo."""
        txt = self.tmp / "_AutoGeneratedTranslations.txt"
        txt.write_text("You new here?=¿Eres nuevo?\nAre you ready, Bradley?=¿Estás listo, Bradley?\n", encoding="utf-8")
        hallazgos, _ = auditoria.auditar_xunity(txt, _ficha(), dudosas=True)
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].tipo, auditoria.REVISAR)
        self.assertIn("2.ª persona va en femenino", hallazgos[0].motivo)
        self.assertEqual(auditoria.auditar_xunity(txt, _ficha(), dudosas=False)[0], [])

    def test_informe_csv(self):
        h = auditoria.Hallazgo("Map001.json", auditoria.CORREGIBLE, "Laura", "I'm tired", "Estoy cansado",
                               "Estoy cansada", "habla Laura (mujer)")
        ruta = auditoria.guardar_informe([h], self.tmp / "informe.csv")
        contenido = ruta.read_text(encoding="utf-8-sig")
        self.assertIn("archivo;tipo;hablante", contenido)
        self.assertIn("Estoy cansada", contenido)


if __name__ == "__main__":
    unittest.main()
