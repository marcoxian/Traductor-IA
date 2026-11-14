"""Bloque C de calcos: frases de conversación traducidas palabra por palabra (frases inventadas)."""
from __future__ import annotations

import unittest

from traductor import modismos
from traductor.espana import a_espanol_de_espana
from traductor.gramatica import tiempo_verbal_imposible
from traductor.texto import evaluar_traduccion


class ArreglosSeguros(unittest.TestCase):
    def comprobar(self, casos):
        for original, mala, buena in casos:
            with self.subTest(original=original, mala=mala):
                self.assertEqual(modismos.arreglar(original, mala), buena)

    def test_palabrotas(self):
        self.comprobar([
            ("Fuck yes!", "¡Sí mierda!", "¡Joder, sí!"),
            ("Oh fuck yes, Lucas...", "¡Oh mierda sí, Lucas...", "¡Oh joder, sí, Lucas..."),
            ("FUCK YES!", "¡SÍ MIERDA!", "¡JODER, SÍ!"),
            ("Fuck. My. Life.", "¡Mierda mi vida!", "¡Qué asco de vida!"),
            ("Well, fuck you too!", "¡Pues joder a ti también!", "¡Pues que te jodan también!"),
        ])

    def test_conversacion(self):
        self.comprobar([
            ("I really appreciate it.", "Realmente lo aprecio.", "Realmente lo agradezco."),
            ("I appreciate that you came.", "Aprecio que hayas venido.", "Agradezco que hayas venido."),
            ("Yeah, I hear you.", "Sí, te escucho.", "Sí, te entiendo."),
            ("You never know.", "Nunca sabes.", "Nunca se sabe."),
            ("You make a good point, Rita.", "Haces un buen punto, Rita.", "Tienes razón, Rita."),
            ("That's a good point.", "Es un buen punto.", "Es una buena observación."),
            ("My pleasure.", "Mi placer.", "Un placer."),
            ("Medium rare, please.", "Medio raro, por favor.", "Poco hecho, por favor."),
            ("I can't wait to see the beach!", "¡No puedo esperar por ver la playa!", "¡Estoy deseando ver la playa!"),
            ("I can tell.", "Puedo verlo.", "Se nota."),
            ("Thanks, I owe you for this.", "Gracias, te debo por esto.", "Gracias, te debo una."),
            ("I'll see you tomorrow, Rita.", "Te veré mañana, Rita.", "Nos vemos mañana, Rita."),
            ("Fine, I'll see you there.", "Vale, te veré allí.", "Vale, nos vemos allí."),
            ("Good girl.", "Bueno chica.", "Buena chica."),
            ("Don't worry, my lips are sealed.", "No te preocupes, mis labios están sellados.",
             "No te preocupes, seré una tumba."),
            ("Our lips are sealed.", "Nuestros labios están sellados.", "Seremos una tumba."),
        ])

    def test_frases_enteras(self):
        self.comprobar([
            ("Got it.", "Lo tengo.", "Entendido."),
            ("{i}Nope.", "{i}Paso.", "{i}No."),
            ("You think so?", "¿Crees que sí?", "¿Tú crees?"),
            ("Well?", "¿Bien?", "¿Y bien?"),
            ("Deal!", "¡Trato!", "¡Trato hecho!"),
            ("Sort of.", "Así es.", "Más o menos."),
            ("Good point.", "Buena idea.", "Bien visto."),
            ("Uh-huh.", "Mm-mm.", "Ajá."),
            ("Mm-hmm...", "Mmm-huh...", "Ajá..."),
        ])

    def test_no_toca_lo_que_esta_bien(self):
        self.comprobar([
            ("Got it!", "¡Lo tengo!", "¡Lo tengo!"),                       # atrapar algo
            ("I've got it under control.", "Lo tengo bajo control.", "Lo tengo bajo control."),
            ("If I hear you are late again...", "Si escucho que llegas tarde otra vez...",
             "Si escucho que llegas tarde otra vez..."),
            ("I want to see you dance.", "Quiero verte bailar.", "Quiero verte bailar."),
            ("I'll see you dance.", "Te veré bailar.", "Te veré bailar."),
            ("Touch yourself for my pleasure.", "Tócate para mi placer.", "Tócate para mi placer."),
            ("Uh-huh.", "Sí.", "Sí."),
            ("MMMmmm Hmmmmm!", "¡MMMMMM Hmmmmmm!", "¡MMMMMM Hmmmmmm!"),   # gemido, no "sí"
            ("Mhmmmm!", "¡Mmmm!", "¡Mmmm!"),
            ("You never know your luck.", "Nunca sabes tu suerte.", "Nunca sabes tu suerte."),
            ("Fuck me, yes!", "¡Fóllame, sí!", "¡Fóllame, sí!"),
        ])

    def test_deteccion(self):
        casos = [
            ("I appreciate that.", "Lo aprecio.", "I appreciate it"),
            ("I hear you, man.", "Te escucho, tío.", "I hear you"),
            ("Good point.", "Buen punto.", "good point"),
            ("Can't wait to try it.", "No puedo esperar para probarlo.", "can't wait to"),
            ("Don't worry, my lips are sealed.", "Tranquila, mis labios están sellados.", "my lips are sealed"),
            ("What a spoilsport.", "Qué deportista.", "spoilsport"),
        ]
        for original, mala, clave in casos:
            with self.subTest(original=original):
                self.assertIn(clave, [m.clave for m in modismos.calcos(original, mala)])
                self.assertIn("calco", evaluar_traduccion(original, mala))
        self.assertEqual(modismos.calcos("What a spoilsport.", "Qué aguafiestas."), [])
        self.assertEqual(modismos.calcos("I can tell you that it works.", "Puedo decirte que funciona."), [])


class EspanaDeEspana(unittest.TestCase):
    def test_viejo_a_tio(self):
        casos = [
            ("It's true, bro!", "¡Es verdad, viejo!", "¡Es verdad, tío!"),
            ("I know, buddy.", "Lo sé viejo amigo.", "Lo sé, tío."),
            ("Dude... seriously?", "Viejo... ¿en serio?", "Tío... ¿en serio?"),
            ("Bro, calm down.", "Hermano, cálmate.", "Tío, cálmate."),
        ]
        for original, mala, buena in casos:
            with self.subTest(mala=mala):
                self.assertEqual(a_espanol_de_espana(mala, original), buena)

    def test_viejo_que_no_se_toca(self):
        casos = [
            ("He's my old buddy, man.", "Es mi viejo amigo, viejo."),   # "old" en el inglés
            ("My brother, bro.", "Mi hermano, viejo."),                  # "brother" en el inglés
            ("He's my buddy.", "Es mi viejo amigo."),                    # detrás de un posesivo
            ("Help a bro out.", "Ayuda a un hermano."),
            ("The car is old.", "El coche es viejo."),                   # sin "bro" en el inglés
        ]
        for original, frase in casos:
            with self.subTest(frase=frase):
                self.assertEqual(a_espanol_de_espana(frase, original), frase)

    def test_te_amo_y_amo_infinitivo(self):
        casos = [
            ("Love you.", "Te amo.", "Te quiero."),
            ("I LOVE YOU!", "¡TE AMO!", "¡TE QUIERO!"),
            ("Love you all!", "¡Os amo a todos!", "¡Os quiero a todos!"),
            ("I love dancing here.", "Amo bailar aquí.", "Me encanta bailar aquí."),
            ("I love seeing you.", "Y amo verte.", "Y me encanta verte."),
            ("You love cooking.", "Tú amas cocinar.", "A ti te encanta cocinar."),
            ("Yes, master, as you wish.", "Sí, amo, como desees.", "Sí, amo, como desees."),
            ("Someone you love when you are away.", "Alguien que amas cuando estás lejos.",
             "Alguien que amas cuando estás lejos."),
            ("The master arrives when he wants.", "El amo cuando quiere llega.", "El amo cuando quiere llega."),
        ]
        for original, mala, buena in casos:
            with self.subTest(mala=mala):
                self.assertEqual(a_espanol_de_espana(mala, original), buena)

    def test_buen_dia(self):
        self.assertEqual(a_espanol_de_espana("Señora Ruiz... buen día.", "Mrs. Ruiz... good day."),
                         "Señora Ruiz... buenos días.")
        self.assertEqual(a_espanol_de_espana("Que tengas un buen día.", "Have a good day."), "Que tengas un buen día.")


class TiempoVerbal(unittest.TestCase):
    def test_detecta(self):
        for frase in ("Quiero mirarte mientras me follarás.", "Sigue ahí mientras te follar.",
                      "¿Quieres que te besaré?", "Lo vi mientras se reirá."):
            with self.subTest(frase=frase):
                self.assertIsNotNone(tiempo_verbal_imposible(frase))

    def test_no_avisa(self):
        for frase in ("Quiero mirarte mientras me follas.", "Mientras la mujer cantaba, salimos.",
                      "Te esperaré mientras te duchas.", "Quiero que me beses.", "Mientras tanto, cenaré."):
            with self.subTest(frase=frase):
                self.assertIsNone(tiempo_verbal_imposible(frase))

    def test_puerta_de_calidad(self):
        self.assertIn("tiempo_verbal", evaluar_traduccion("Look at me while you kiss me.",
                                                          "Mírame mientras me besarás."))


if __name__ == "__main__":
    unittest.main()
