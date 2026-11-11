"""Bloque AC: reglas nuevas de prevención y detección (gramática, modismos, "coger", oyente por turnos,
frases cortas inventadas, ecos de la autocorrección). Frases inventadas; ningún test llama a Ollama."""
from __future__ import annotations

import unittest

from traductor import ambiguas, modismos
from traductor.config import Perfil
from traductor.espana import a_espanol_de_espana, coger_a_follar
from traductor.gramatica import arreglar_determinantes, imperativo_negativo_mal, tartamudeo_como_yo
from traductor.motores.renpy import leer_cadenas, oyentes_del_archivo
from traductor.ollama import OllamaTranslator
from traductor.personajes import (FichaPersonajes, InfoLinea, Personaje, oyente_contradicho, oyentes_por_turnos,
                                  resolver_linea)
from traductor.texto import PROBLEMAS_LEVES_REINTENTO, evaluar_traduccion, limpiar_respuesta, postprocesar_traduccion


class TestDeterminantes(unittest.TestCase):
    def test_masculino_con_sustantivo_femenino(self):
        casos = {
            "Puedes ponerle muchos actualizaciones.": "Puedes ponerle muchas actualizaciones.",
            "Pasó un Navidad sola.": "Pasó una Navidad sola.",
            "Voy a llamar al recepción.": "Voy a llamar a la recepción.",
            "¿Este inversión es segura?": "¿Esta inversión es segura?",
            "Mucho diversión, ¿eh?": "Mucha diversión, ¿eh?",
            "el primer preocupación": "la primera preocupación",
            "Es el otro mitad.": "Es la otra mitad.",
            "TODOS LOS INVITACIONES": "TODAS LAS INVITACIONES",
            "Es un gran decisión.": "Es una gran decisión.",
        }
        for antes, despues in casos.items():
            with self.subTest(antes=antes):
                self.assertEqual(arreglar_determinantes(antes), despues)

    def test_no_toca_lo_que_esta_bien(self):
        for frase in ("la ciudad y el coche", "las canciones", "Mi dad dice que no.", "el hombre", "lo de la verdad",
                      "un camión", "El sol sale."):
            with self.subTest(frase=frase):
                self.assertEqual(arreglar_determinantes(frase), frase)

    def test_va_en_el_retoque_final(self):
        self.assertEqual(postprocesar_traduccion("Tengo muchos opciones.", "I have a lot of options."),
                         "Tengo muchas opciones.")
        # "dudas" no tiene una terminación que sea siempre femenina: no se toca (ante la duda, nada)
        self.assertEqual(arreglar_determinantes("muchos dudas"), "muchos dudas")


class TestImperativoNegativo(unittest.TestCase):
    def test_detecta_indicativo_y_usted(self):
        self.assertEqual(imperativo_negativo_mal("Don't pretend you missed it.", "No finge que no lo viste."), "finge")
        self.assertEqual(imperativo_negativo_mal("Don’t send that photo.", "No envía esa foto."), "envía")
        self.assertEqual(imperativo_negativo_mal("Don't bother calling.", "No te moleste en llamar."), "moleste")
        self.assertEqual(imperativo_negativo_mal("Don't mention it.", "No lo menciono."), "menciono")
        self.assertEqual(imperativo_negativo_mal("Don't ruin it.", "No lo arruinen."), "arruinen")  # vosotros

    def test_no_avisa_si_esta_bien(self):
        casos = [
            ("Don't pretend you missed it.", "No finjas que no lo viste."),
            ("Don't worry, I won't.", "No te preocupes. No lo haré."),
            ("Don't ruin it, guys.", "No lo arruinéis, chicos."),
            ("Don't look.", "No mirar."),                                  # opción de menú en infinitivo
            ("Don't know any guy called Tom.", "No conozco a ningún Tom."),  # "I don't know" sin el "I"
            ("Don't worry about it.", "No pasa nada."),
            ("Don't do it, sir.", "No lo haga, señor."),                     # trato de usted a propósito
            ("Don't you think so?", "¿No crees?"),
            ("I don't care.", "No me importa."),
        ]
        for en, es in casos:
            with self.subTest(en=en):
                self.assertIsNone(imperativo_negativo_mal(en, es))

    def test_puerta_de_calidad_reintenta(self):
        problemas = evaluar_traduccion("Don't pretend you missed it.", "No finge que no lo viste.")
        self.assertIn("imperativo_negativo", problemas)
        self.assertIn("imperativo_negativo", PROBLEMAS_LEVES_REINTENTO)


class TestTartamudeo(unittest.TestCase):
    def test_tartamudeo_de_it_no_es_yo(self):
        self.assertEqual(tartamudeo_como_yo("The truck hit Ana. I-It threw her aside...",
                                            "El camión golpeó a Ana. Yo... La lanzó a un lado..."), "It")
        self.assertIsNone(tartamudeo_como_yo("I-It threw her aside...", "E-el camión la lanzó a un lado..."))
        self.assertIsNone(tartamudeo_como_yo("I-I'm sorry.", "Yo... lo siento."))
        self.assertIsNone(tartamudeo_como_yo("I-It was me. I did it.", "Fui yo. Lo hice yo."))
        self.assertIn("tartamudeo", evaluar_traduccion("I-It threw her aside...", "Yo... La lanzó a un lado..."))


class TestModismos(unittest.TestCase):
    def test_calcos_detectados(self):
        casos = [
            ("Same as always. Busting my ass.", "Como siempre. Dándome patadas en el culo.", "busting my ass"),
            ("He's a damn good cook.", "Es un maldito buen cocinero.", "damn good"),
            ("That was one hell of a game!", "¡Fue un partido de mierda!", "a hell of a"),
            ("Look at her perfect fucking smile.", "Mira su sonrisa de mierda perfecta.", "fucking (en positivo)"),
            ("No, not at all.", "En absoluto no.", "not at all"),
            ("I'd give every last drop of my sweat.", "Daría cada soltar de mi sudor.", "every last drop"),
            ("Tell him to go fuck himself.", "Dile que se vaya a follarse.", "go fuck yourself"),
            ("He's a pain in the ass.", "Es un dolor en el culo.", "pain in the ass"),
            ("My bad.", "Mi mal.", "my bad"),
        ]
        for en, es, clave in casos:
            with self.subTest(en=en):
                self.assertEqual([m.clave for m in modismos.calcos(en, es)][:1], [clave])
                self.assertIn("calco", evaluar_traduccion(en, es))

    def test_bien_traducidos_no_avisan(self):
        casos = [
            ("Same as always. Busting my ass.", "Lo de siempre. Matándome a trabajar."),
            ("He's a damn good cook.", "Es un cocinero buenísimo."),
            ("That was one hell of a game!", "¡Menudo partido!"),
            ("No, not at all.", "No, para nada."),
            ("I'd give every last drop of my sweat.", "Daría hasta la última gota de mi sudor."),
            ("He kicks ass at chess.", "Arrasa al ajedrez."),
        ]
        for en, es in casos:
            with self.subTest(en=en):
                self.assertEqual(modismos.calcos(en, es), [])

    def test_pista_solo_para_los_que_fallan_casi_siempre(self):
        self.assertEqual([c for c, _ in modismos.terminos("Same as always. Busting my ass.")], ["busting my ass"])
        self.assertEqual(modismos.terminos("No, not at all."), [])   # el modelo lo suele hacer bien: solo se comprueba
        self.assertEqual(modismos.terminos("Open the door."), [])

    def test_pista_en_el_glosario_del_perfil(self):
        p = Perfil(contexto="CTX")
        self.assertIn("busting my ass", [en for en, _ in p.terminos_para("Busting my ass all day.")])
        self.assertEqual(p.terminos_para("Busting my ass all day.", con_ambiguas=False), [])
        self.assertEqual(Perfil(contexto="CTX", palabras_ambiguas=False).terminos_para("Busting my ass all day."), [])


class TestCogerAFollar(unittest.TestCase):
    def test_con_sexo_en_ingles(self):
        casos = [
            ("Fuck me on the table!", "¡Cógeme en la mesa!", "¡Fóllame en la mesa!"),
            ("I'm going to fuck you.", "Voy a cogerte.", "Voy a follarte."),
            ("They banged all night.", "Cogieron toda la noche.", "Follaron toda la noche."),
            ("He banged my neighbor!", "¡Se cogió a mi vecina!", "¡Se folló a mi vecina!"),
            ("She was fucking him.", "Ella se lo estaba cogiendo.", "Ella se lo estaba follando."),
            ("FUCK 'EM ALL!", "¡CÓGELOS A TODOS!", "¡FÓLLALOS A TODOS!"),
            ("You'd be a good fuck.", "Serías una buena cogida.", "Serías un buen polvo."),
            ("I wanna get fucked.", "Quiero que me cojan.", "Quiero que me follen."),
        ]
        for en, es, esperado in casos:
            with self.subTest(en=en):
                self.assertEqual(coger_a_follar(es, en), esperado)
                self.assertEqual(a_espanol_de_espana(es, en), esperado)

    def test_sin_sexo_o_con_tomar_no_se_toca(self):
        self.assertEqual(coger_a_follar("Coge el autobús.", "Take the bus."), "Coge el autobús.")
        self.assertEqual(coger_a_follar("Coge el puto autobús.", "Take the fucking bus."), "Coge el puto autobús.")
        self.assertEqual(coger_a_follar("¡Joder, cojones!", "Fuck, fuck!"), "¡Joder, cojones!")
        self.assertEqual(coger_a_follar("Vamos a escoger.", "Let's fucking pick."), "Vamos a escoger.")


class TestChestDePersona(unittest.TestCase):
    def test_alguien_tiene_pecho(self):
        for en in ("Admit it, she had a chest worth staring at, mate!", "She's got such a nice chest.",
                   "You have a nice chest."):
            with self.subTest(en=en):
                self.assertEqual([d.sentido for d in ambiguas.decidir(en)], ["pecho"])

    def test_cofre_de_alguien(self):
        self.assertEqual([d.sentido for d in ambiguas.decidir("He had a chest full of gold coins.")], ["cofre"])
        self.assertEqual(ambiguas.decidir("You have a chest in the attic?"), [])
        self.assertEqual(ambiguas.decidir("You have the chest?"), [])


class TestFrasesCortasInventadas(unittest.TestCase):
    def test_frase_inventada(self):
        self.assertIn("longitud_larga", evaluar_traduccion("*coughs*", "¡Vaya! Creo que me he resfriado otra vez esta mañana."))
        self.assertIn("longitud_larga", evaluar_traduccion("OH, DAMN!", "¡Oh, maldita sea! ¡No me puedo creer que hayas vuelto tan pronto!"))

    def test_lo_normal_no_avisa(self):
        for en, es in (("Better hurry.", "Será mejor que te des prisa."), ("No, thanks.", "No, gracias, de verdad."),
                       ("Always. Forever. Together.", "Siempre. Para siempre. Juntos."),
                       ("Support her.", "Apóyala.")):
            with self.subTest(en=en):
                self.assertNotIn("longitud_larga", evaluar_traduccion(en, es))


class TestEcoAutocorreccion(unittest.TestCase):
    def test_quita_el_motivo_y_lo_detecta(self):
        resp = "¿Eh?{w=0.5} {nw}. Motivo: faltan ['']. Devuelve ÚNICAMENTE la traducción final en español."
        self.assertEqual(limpiar_respuesta(resp, "Hm-{w=0.5}{nw}"), "¿Eh?{w=0.5} {nw}")
        self.assertIn("eco_prompt", evaluar_traduccion("Yes. Same as before.",
                                                       ". Motivo: faltan . Devuelve ÚNICAMENTE la traducción final."))


# --------------------------------------------------------------------------- Oyente por turnos
def _ficha() -> FichaPersonajes:
    return FichaPersonajes([
        Personaje("Dario", "hombre", rol="protagonista", codigos=["renpy:d"]),
        Personaje("Irene", "mujer", rol="principal", codigos=["renpy:i"]),
        Personaje("Paula", "mujer", rol="principal", codigos=["renpy:p"]),
        Personaje("Tomás", "hombre", rol="principal", codigos=["renpy:t"]),
    ])


class TestOyentesPorTurnos(unittest.TestCase):
    def test_a_b_a(self):
        self.assertEqual(oyentes_por_turnos(["i", "p", "i", None, "p"]), [None, "i", "p", None, None])
        self.assertEqual(oyentes_por_turnos(["i", "i", "p", "i"]), [None, None, "i", None])  # nadie habló antes
        self.assertEqual(oyentes_por_turnos(["i", "p", "t"]), [None, None, None])     # tres personas: no se sabe
        self.assertEqual(oyentes_por_turnos(["i", None, None, None, None, "p", "i"], ventana=3)[5], None)

    def test_resolver_usa_el_oyente_sin_corregir_solo(self):
        ficha = _ficha()
        ctx = resolver_linea(ficha, "Are you sure?", InfoLinea(codigo="renpy:t", oyente="renpy:p"))
        self.assertEqual(ctx.destinatario.nombre, "Paula")
        self.assertFalse(ctx.destinatario_explicito)
        self.assertTrue(ctx.destinatario_por_turnos)
        self.assertIn("Probablemente se dirige a Paula (mujer)", ctx.ficha())
        # el protagonista también tiene ahora a quién habla
        ctx = resolver_linea(ficha, "Are you sure?", InfoLinea(codigo="renpy:d", oyente="renpy:i"))
        self.assertEqual(ctx.destinatario.nombre, "Irene")
        # un nombre en la frase manda
        ctx = resolver_linea(ficha, "Are you sure, Irene?", InfoLinea(codigo="renpy:t", oyente="renpy:p"))
        self.assertEqual(ctx.destinatario.nombre, "Irene")
        self.assertTrue(ctx.destinatario_explicito)

    def test_oyente_contradicho(self):
        ficha = _ficha()
        ctx = resolver_linea(ficha, "Are you sure?", InfoLinea(codigo="renpy:t", oyente="renpy:p"))
        self.assertTrue(oyente_contradicho(ctx, "Are you sure?", "¿Estás seguro?"))
        self.assertFalse(oyente_contradicho(ctx, "Are you sure?", "¿Estás segura?"))
        self.assertFalse(oyente_contradicho(ctx, "Are you sure, mister?", "¿Estás seguro, señor?"))  # el inglés lo dice
        sin_turnos = resolver_linea(ficha, "Are you sure?", InfoLinea(codigo="renpy:i"))   # prota probable de siempre
        self.assertFalse(oyente_contradicho(sin_turnos, "Are you sure?", "¿Estás segura?"))

    def test_renpy_saca_los_oyentes_del_archivo(self):
        tl = (
            'translate Spanish s1:\n\n    # t "Hi, Paula."\n    t "Hola, Paula."\n\n'
            'translate Spanish s2:\n\n    # p "Hi. Are you ready?"\n    p "Hi. Are you ready?"\n\n'
            'translate Spanish s3:\n\n    # t "Sure."\n    t "Sure."\n'
        )
        lineas = tl.splitlines(keepends=True)
        oyentes = oyentes_del_archivo(lineas)
        pend = {p.original: p for p in leer_cadenas(lineas)}
        self.assertEqual(oyentes.get(pend["Hi. Are you ready?"].linea), "renpy:t")
        info = pend["Hi. Are you ready?"].info(oyentes.get(pend["Hi. Are you ready?"].linea))
        self.assertEqual((info.codigo, info.oyente), ("renpy:p", "renpy:t"))


class TestTraductorReintenta(unittest.TestCase):
    def _traductor(self, respuestas, perfil: Perfil | None = None) -> OllamaTranslator:
        t = OllamaTranslator(model_name="prueba", perfil=perfil or Perfil(contexto="CTX"), ruta_cache=None)
        self.addCleanup(t.cerrar)
        self.prompts: list[str] = []
        cola = list(respuestas)

        def generar(prompt, num_predict, temperature=0.1):
            self.prompts.append(prompt)
            return cola.pop(0) if len(cola) > 1 else cola[0]

        t._generar = generar
        return t

    def test_reintenta_el_calco_con_su_significado(self):
        t = self._traductor(["Es un maldito buen cocinero.", "Es un cocinero buenísimo."])
        self.assertEqual(t.translate("He's a damn good cook."), "Es un cocinero buenísimo.")
        self.assertIn("'damn good'", self.prompts[0])                     # pista en el glosario
        self.assertIn("'damn good' significa", self.prompts[1])           # nota del reintento

    def test_reintenta_el_imperativo(self):
        t = self._traductor(["No finge que no lo viste.", "No finjas que no lo viste."])
        self.assertEqual(t.translate("Don't pretend you missed it."), "No finjas que no lo viste.")
        self.assertIn("No finjas", self.prompts[1])

    def test_si_no_se_arregla_acepta_la_mejor(self):
        t = self._traductor(["No finge que no lo viste."])
        self.assertEqual(t.translate("Don't pretend you missed it."), "No finge que no lo viste.")

    def test_reintenta_el_genero_del_oyente(self):
        perfil = Perfil(contexto="CTX", personajes=_ficha())
        t = self._traductor(["¿Estás seguro?", "¿Estás segura?"], perfil)
        info = InfoLinea(codigo="renpy:t", oyente="renpy:p")
        self.assertEqual(t.translate("Are you sure?", info=info), "¿Estás segura?")
        self.assertIn("Se habla a Paula (mujer)", self.prompts[1])


if __name__ == "__main__":
    unittest.main()
