"""Reglas del bloque AD: tratamiento en vocativo sin artículo, inglés corto con signos de español y palabrotas
traducidas como palabras de sexo."""
from __future__ import annotations

import unittest

from traductor import modismos
from traductor.gramatica import arreglar_tratamiento_vocativo
from traductor.texto import evaluar_traduccion, postprocesar_traduccion


class TestTratamientoVocativo(unittest.TestCase):
    def test_quita_el_articulo(self):
        self.assertEqual(
            arreglar_tratamiento_vocativo("Mr. Lopez, we have a problem.", "El Sr. Lopez, tenemos un problema."),
            "Sr. Lopez, tenemos un problema.")

    def test_femenino_y_doctor(self):
        self.assertEqual(
            arreglar_tratamiento_vocativo("Ms. Lopez, I assure you.", "La Sra. Lopez, se lo aseguro."),
            "Sra. Lopez, se lo aseguro.")
        self.assertEqual(
            arreglar_tratamiento_vocativo("Dr. Vega, come in!", "¡El Dr. Vega, pase!"), "¡Dr. Vega, pase!")

    def test_no_toca_si_no_es_vocativo(self):
        # El original habla DE él, no A él: el artículo es correcto.
        self.assertEqual(
            arreglar_tratamiento_vocativo("I saw Mr. Lopez yesterday.", "Vi ayer al Sr. Lopez."),
            "Vi ayer al Sr. Lopez.")
        self.assertEqual(
            arreglar_tratamiento_vocativo("Mr. Lopez is late.", "El Sr. Lopez llega tarde."),
            "El Sr. Lopez llega tarde.")

    def test_en_el_flujo_completo(self):
        r = postprocesar_traduccion("El Sr. Lopez, necesito hablar con usted.",
                                    "Mr. Lopez, I need a word with you.")
        self.assertTrue(r.startswith("Sr. Lopez,"), r)


class TestInglesEnMayusculas(unittest.TestCase):
    def test_detecta_ingles_con_signos_espanoles(self):
        self.assertIn("ingles_residual",
                      evaluar_traduccion("That fucking door is stuck!", "¡DAMN THAT DOOR IS STUCK!"))

    def test_palabras_inglesas_con_silabas_espanolas(self):
        # "la" dentro de "PLEASE" o "es" dentro de "THESE" no son señal de español
        self.assertIn("ingles_residual",
                      evaluar_traduccion("Please, take these away!", "¡PLEASE TAKE THESE AWAY!"))

    def test_no_marca_espanol_normal(self):
        self.assertEqual(evaluar_traduccion("That fucking door is stuck!", "¡Joder, la puerta se ha atascado!"), [])


def _claves(original: str, traduccion: str) -> set[str]:
    return {m.clave for m in modismos.calcos(original, traduccion)}


class TestPalabrotasNoSonSexo(unittest.TestCase):
    """"Fuck" de palabrota traducido "follar"/"follón"/"mamada"; "asshole" traducido "hijo de puta"."""

    def test_fuck_palabrota_traducido_follar(self):
        malas = [
            ("I was fucking right about the engine!", "¡Yo estaba follando razón con el motor!"),
            ("Fucking do it already!", "¡Fóllalo ya!"),
            ("You fucking cheated in that race!", "¡Te follaste la carrera!"),
            ("We had a dry spell longer than the fucking desert!", "¡Una sequía más larga que el follón del desierto!"),
            ("Quit fucking around and help me.", "Deja de follar por ahí y ayúdame."),
        ]
        for en, es in malas:
            with self.subTest(en=en):
                self.assertIn("fuck (palabrota, no sexo)", _claves(en, es))
                self.assertIn("calco", evaluar_traduccion(en, es))

    def test_fuck_de_sexo_no_se_toca(self):
        buenas = [
            ("Keep fucking me, harder…", "Sigue follándome, más fuerte…"),
            ("Keep… fucking… me…", "Sigue… follándome…"),
            ("We were fucking in the garage when he came in.", "Estábamos follando en el garaje cuando entró."),
            ("Tell me about all the women he fucked.", "Háblame de todas las mujeres que se folló."),
            ("I want to fuck you right now.", "Quiero follarte ahora mismo."),
            ("You two fucked like crazy that night.", "Esa noche follasteis como locos."),
            ("I haven't had sex in months. You don't see me fucking around!", "No me ves follando por ahí."),
            ("What a fucking mess!", "¡Menudo puto follón!"),
        ]
        for en, es in buenas:
            with self.subTest(en=en):
                self.assertNotIn("fuck (palabrota, no sexo)", _claves(en, es))

    def test_frases_hechas(self):
        casos = [
            ("I really fucked this whole thing up.", "La he follado entera.", "fuck up"),
            ("He was eye-fucking her all night.", "Él la estaba follando con los ojos.", "eye-fucking"),
            ("FUCK YES! WE WON!", "¡FOLLÓN SÍ! ¡GANAMOS!", "fuck yes"),
            ("FUUUCK!", "¡MAMADA DE MIERDA!", "fuck! (exclamación)"),
            ("FUCKING FUCK!", "¡MAMADA DE PUTA!", "fuck! (exclamación)"),
            ("Holy shit, look at that!", "¡Santa mierda, mira eso!", "holy fuck"),
            ("She told me to fuck off.", "Me dijo que me follaran.", "go fuck yourself"),
            ("I'll fucking kill him.", "Le mato de puta madre.", "fucking + verbo"),
            ("Your cousin is such an asshole.", "Tu primo es un hijo de puta.", "asshole"),
            ("Asshole.", "Putas.", "asshole"),
        ]
        for en, es, clave in casos:
            with self.subTest(en=en):
                self.assertIn(clave, _claves(en, es))

    def test_traducciones_buenas_sin_aviso(self):
        buenas = [
            ("I really fucked this whole thing up.", "La he cagado del todo."),
            ("Shut the fuck up and kiss me.", "Cállate de una puta vez y bésame."),
            ("FUCK YES! WE WON!", "¡JODER, SÍ! ¡HEMOS GANADO!"),
            ("FUUUCK!", "¡JODEEER!"),
            ("Holy shit!", "¡Santo cielo!"),
            ("Your cousin is such an asshole.", "Tu primo es un gilipollas."),
            ("That son of a bitch is an asshole.", "Ese hijo de puta es un capullo."),
            ("She is damn good at it.", "Se le da de puta madre."),
        ]
        for en, es in buenas:
            with self.subTest(en=en):
                self.assertEqual(modismos.calcos(en, es), [])

    def test_exclamacion_sin_palabrota_es_fallo(self):
        self.assertIn("fuck! (exclamación)", _claves("FUUUCK!", "¡FUEEERROOOO!"))
        self.assertEqual(modismos.calcos("Fuck!", "¡Mierda!"), [])
        self.assertEqual(modismos.calcos("Fuck...", "Joder..."), [])

    def test_arreglo_de_la_exclamacion_sola(self):
        casos = [
            ("FUUUCK!", "¡FUEEERROOOO!", "¡JODEEER!"),
            ("FUUUCK!", "¡MAMADA DE MIERDA!", "¡JODEEER!"),
            ("{b}FUCK!", "{b}¡MAMAD!", "{b}¡JODER!"),
            ("FUCK!{fast}", "¡MAMÁ!{fast}", "¡JODER!{fast}"),
            ("{i}FUCK!", "¡{i}MAMADA!{/i}", "{i}¡JODER!{/i}"),
            ("Fuck...", "Follón...", "Joder..."),
            ("fuck?!", "¿¡mamada?!", "¡¿joder?!"),
        ]
        for en, es, esperado in casos:
            with self.subTest(en=en, es=es):
                self.assertEqual(modismos.arreglar(en, es), esperado)

    def test_arreglo_no_toca_lo_bueno_ni_otras_frases(self):
        intactas = [
            ("FUCK!", "¡Mierda!"),
            ("FUUUCK!", "¡JODEEER!"),
            ("FUUUUCK!", "¡Mierdaaaaa!"),             # palabrota alargada: está bien
            ("Oh, fuck!", "¡Oh, mamada!"),          # con "oh" no se arregla solo: va al reintento
            ("Fuck you!", "¡Que te follen!"),
            ("FUCKING HELL!", "¡MAMADA!"),
            ("Fuck, yes!", "¡Joder, sí!"),
        ]
        for en, es in intactas:
            with self.subTest(en=en):
                self.assertEqual(modismos.arreglar(en, es), es)

    def test_arreglo_dentro_del_postproceso(self):
        self.assertEqual(postprocesar_traduccion("¡FUEEERROOOO!", "FUUUCK!"), "¡JODEEER!")

    def test_pista_en_el_glosario(self):
        self.assertIn("eye-fucking", [c for c, _ in modismos.terminos("He was eye-fucking her.")])
        self.assertIn("asshole", [c for c, _ in modismos.terminos("You're an asshole.")])
        # La regla general no va al glosario: confundiría al modelo en las frases de sexo
        self.assertNotIn("fuck (palabrota, no sexo)", [c for c, _ in modismos.terminos("I was fucking right.")])


if __name__ == "__main__":
    unittest.main()
