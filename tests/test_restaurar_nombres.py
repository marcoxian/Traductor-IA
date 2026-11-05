"""Nombres protegidos: restaurar un nombre perdido sin pisar a otro personaje que está en el original.

Caso real: la regla de un nombre ("Lucinda") incluía otro personaje parecido ("Lucía") y "Lucía lo salvó" se
convertía en "Lucinda lo salvó" en decenas de frases."""
import unittest

from traductor.config import Perfil

REGLA = r"\b(?:Lucina|Luci|Lucy|Lucía)\b"


class TestRestaurarNombres(unittest.TestCase):
    def setUp(self):
        self.p = Perfil(nombres_protegidos={"Lucinda": REGLA})

    def test_no_pisa_a_otro_personaje(self):
        self.assertEqual(self.p.restaurar_nombres("Lucía saved him.", "Lucía lo salvó."), "Lucía lo salvó.")
        self.assertEqual(self.p.restaurar_nombres("Lucinda and Lucía.", "Lucy y Lucía."), "Lucinda y Lucía.")

    def test_sigue_restaurando(self):
        self.assertEqual(self.p.restaurar_nombres("Lucinda is here.", "Lucy está aquí."), "Lucinda está aquí.")
        self.assertEqual(self.p.restaurar_nombres("Lucinda is here.", "Lucinda está aquí."), "Lucinda está aquí.")


if __name__ == "__main__":
    unittest.main()
