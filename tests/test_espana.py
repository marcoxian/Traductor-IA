"""Vocabulario de Latinoamérica -> España (traductor/espana.py) y su uso en el retoque final."""
from __future__ import annotations

import unittest

from traductor.espana import a_espanol_de_espana as espana
from traductor.texto import postprocesar_traduccion


class TestEnfadar(unittest.TestCase):
    def test_todas_las_formas(self):
        self.assertEqual(espana("No te enojes."), "No te enfades.")
        self.assertEqual(espana("¡Estoy enojada!"), "¡Estoy enfadada!")
        self.assertEqual(espana("¡Enójate conmigo!"), "¡Enfádate conmigo!")
        self.assertEqual(espana("Se enojó mucho."), "Se enfadó mucho.")
        self.assertEqual(espana("ENOJADO"), "ENFADADO")

    def test_enojoso_se_queda(self):
        self.assertEqual(espana("Qué cosa tan enojosa."), "Qué cosa tan enojosa.")


class TestBonito(unittest.TestCase):
    def test_lindo(self):
        self.assertEqual(espana("¡Qué lindo!"), "¡Qué bonito!")
        self.assertEqual(espana("¡Hola, linda!"), "¡Hola, bonita!")
        self.assertEqual(espana("Mis lindas flores."), "Mis bonitas flores.")

    def test_si_alguien_se_llama_linda_no_se_toca(self):
        self.assertEqual(espana("Linda está aquí, qué linda.", "Linda is here, so cute."),
                         "Linda está aquí, qué linda.")


class TestDarsePrisa(unittest.TestCase):
    def test_con_hurry(self):
        self.assertEqual(espana("¡Apúrate!", "Hurry up!"), "¡Date prisa!")
        self.assertEqual(espana("Si no te apuras...", "If you don't hurry..."), "Si no te das prisa...")
        self.assertEqual(espana("¡Apúrense!", "Hurry up, everyone!"), "¡Daos prisa!")
        self.assertEqual(espana("Tenemos que apurarnos.", "We must hurry."), "Tenemos que darnos prisa.")

    def test_sin_hurry_no_se_toca(self):
        self.assertEqual(espana("No te apures.", "Don't worry."), "No te apures.")


class TestEcharDeMenos(unittest.TestCase):
    def test_con_miss(self):
        self.assertEqual(espana("Te extraño mucho.", "I miss you so much."), "Te echo mucho de menos.")
        self.assertEqual(espana("Pero extraño a mis padres.", "I miss my parents."),
                         "Pero echo de menos a mis padres.")
        self.assertEqual(espana("Voy a extrañarte.", "I'll miss you."), "Voy a echarte de menos.")
        self.assertEqual(espana("La he extrañado.", "I've missed her."), "La he echado de menos.")
        self.assertEqual(espana("Señorita Ana, te extraño.", "Miss Ana, I miss you."),
                         "Señorita Ana, te echo de menos.")

    def test_el_adjetivo_no_se_toca(self):
        self.assertEqual(espana("Una extraña esfera.", "I miss it. A strange orb."), "Una extraña esfera.")
        self.assertEqual(espana("La extraña esfera.", "I missed the strange orb."), "La extraña esfera.")
        self.assertEqual(espana("Una sensación extraña.", "A strange feeling."), "Una sensación extraña.")

    def test_sorpresa_o_traduccion_ya_rara_no_se_toca(self):
        # "me extraña" = me sorprende; "extrañarse de" = sorprenderse: el cambio lo empeoraría
        self.assertEqual(espana("De hecho me extraña un poco.", "I kind of miss it."), "De hecho me extraña un poco.")
        self.assertEqual(espana("¿Te extrañas tanto de tu madre?", "Do you miss your mom that much?"),
                         "¿Te extrañas tanto de tu madre?")

    def test_sin_miss_no_se_toca(self):
        self.assertEqual(espana("Te extraño.", "You're weird to me."), "Te extraño.")


class TestEnElRetoque(unittest.TestCase):
    def test_postprocesar_lo_aplica(self):
        self.assertEqual(postprocesar_traduccion("¡Apúrate, no te enojes!", "Hurry, don't be mad!"),
                         "¡Date prisa, no te enfades!")


if __name__ == "__main__":
    unittest.main()
