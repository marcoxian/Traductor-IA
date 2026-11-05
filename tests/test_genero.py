"""Pruebas de la concordancia de género (traductor/genero.py) y de la ficha de personajes
(traductor/personajes.py), incluidos falsos positivos reales encontrados en el corpus de Mi Juego."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from traductor.genero import (DESCONOCIDO, HOMBRE, MUJER, NEUTRO, corregir_primera_persona,
                              corregir_segunda_persona, corregir_tercera_persona, marcas_genero,
                              normalizar_genero, personas_con_genero_en)
from traductor.personajes import (FichaPersonajes, InfoLinea, Personaje, aplicar_concordancia,
                                  es_pensamiento, resolver_linea)


class TestInglesConGenero(unittest.TestCase):
    def test_palabras_de_persona(self):
        self.assertEqual(personas_con_genero_en("Thank you, sir."), {HOMBRE})
        self.assertEqual(personas_con_genero_en("You're such a good girl."), {MUJER})
        self.assertEqual(personas_con_genero_en("My boyfriend is waiting."), {HOMBRE})
        self.assertEqual(personas_con_genero_en("Ma’am, please."), {MUJER})
        self.assertEqual(personas_con_genero_en("You son of a bitch!"), {HOMBRE, MUJER})

    def test_sin_falsos_positivos(self):
        for texto in ("I'm ready.", "I miss you.", "That's pretty good.", "Oh my god!", "1Hero, are you sure?",
                      "What a human thing to do.", "We met in Manhattan.", "I'm studying for the class.",
                      "Hand me the switch, I'm glad you came.", "She was haunted by that moment."):
            self.assertEqual(personas_con_genero_en(texto), set(), texto)


class TestNormalizar(unittest.TestCase):
    def test_valores(self):
        for valor, esperado in (("Hombre", HOMBRE), ("masculino", HOMBRE), ("male", HOMBRE), ("h", HOMBRE),
                                ("Mujer (protagonista)", MUJER), ("F", MUJER), ("female", MUJER),
                                ("neutro", NEUTRO), ("?", DESCONOCIDO), (None, DESCONOCIDO), ("", DESCONOCIDO)):
            self.assertEqual(normalizar_genero(valor), esperado, valor)

    def test_m_es_ambigua(self):
        self.assertEqual(normalizar_genero("m"), DESCONOCIDO)
        self.assertEqual(normalizar_genero("m", "es"), MUJER)
        self.assertEqual(normalizar_genero("m", "en"), HOMBRE)
        f = FichaPersonajes.from_dict({"personajes": [{"nombre": "A", "genero": "m"}, {"nombre": "B", "genero": "f"}]})
        self.assertEqual(f.buscar("A").genero, HOMBRE)   # junto a 'f' -> convención inglesa
        f = FichaPersonajes.from_dict({"personajes": [{"nombre": "A", "genero": "m"}, {"nombre": "B", "genero": "h"}]})
        self.assertEqual(f.buscar("A").genero, MUJER)    # junto a 'h' -> convención española


class TestPrimeraPersona(unittest.TestCase):
    CASOS = [
        ("Estoy agotada.", HOMBRE, None, "Estoy agotado."),
        ("No estoy seguro de eso.", MUJER, None, "No estoy segura de eso."),
        ("Me quedé dormida en el sofá.", HOMBRE, None, "Me quedé dormido en el sofá."),
        ("Ahora estoy aún más confundida.", HOMBRE, None, "Ahora estoy aún más confundido."),
        ("Lo haré yo misma.", HOMBRE, None, "Lo haré yo mismo."),
        ("¿O estoy equivocado?", MUJER, None, "¿O estoy equivocada?"),
        ("ESTOY CANSADO", MUJER, None, "ESTOY CANSADA"),
        ("Estaba muy cansado ayer.", MUJER, "I was very tired yesterday.", "Estaba muy cansada ayer."),
        # Formas ambiguas sin "I" en inglés, o con otro sujeto: no se tocan
        ("Estaba muy cansado ayer.", MUJER, None, "Estaba muy cansado ayer."),
        ("Sabía que estaba cansada.", HOMBRE, "I knew she was tired.", "Sabía que estaba cansada."),
        ("Mi madre estaba cansada.", HOMBRE, "I think my mom was tired.", "Mi madre estaba cansada."),
        ("Puede que sea mala, pero mientras necesite su ayuda, no puedo actuar.", HOMBRE,
         "She may be evil, but as long as I need her help, I can't act.",
         "Puede que sea mala, pero mientras necesite su ayuda, no puedo actuar."),
        ("No pensé que sería tan serio.", MUJER, "I didn't think it would be that serious.",
         "No pensé que sería tan serio."),
        # Adjetivo de otro sustantivo, plurales, usos adverbiales y citas: no se tocan
        ("Soy buena persona.", HOMBRE, None, "Soy buena persona."),
        ("Estamos cansados.", MUJER, None, "Estamos cansados."),
        ("Estoy solo bromeando.", MUJER, None, "Estoy solo bromeando."),
        ("Estoy solo.", MUJER, None, "Estoy sola."),
        ('Ella me dijo: "Estoy cansada".', HOMBRE, None, 'Ella me dijo: "Estoy cansada".'),
        # Pausas y tartamudeos de diálogo (casos reales)
        ("(¡Kh-...! ¡Tengo que estar... tranquilo...!)", MUJER, None, "(¡Kh-...! ¡Tengo que estar... tranquila...!)"),
        ("Estoy... t-tan c-cansado...", MUJER, None, "Estoy... t-tan c-cansada..."),
        ("Estoy-... muy... cansada.", HOMBRE, None, "Estoy-... muy... cansado."),
        ("¡Estoy~ lista!", HOMBRE, None, "¡Estoy~ listo!"),
        # Tras la pausa empieza otra frase (mayúscula): no se toca
        ("No lo estoy... Tranquilo, Juan.", MUJER, None, "No lo estoy... Tranquilo, Juan."),
        ("Estoy. Cansado de todo.", MUJER, None, "Estoy. Cansado de todo."),
    ]

    def test_casos(self):
        for texto, genero, original, esperado in self.CASOS:
            self.assertEqual(corregir_primera_persona(texto, genero, original), esperado, texto)


class TestSegundaYTerceraPersona(unittest.TestCase):
    def test_segunda(self):
        for texto, genero, esperado in (("¿Estás lista?", HOMBRE, "¿Estás listo?"),
                                        ("¡Bienvenida, guapa!", HOMBRE, "¡Bienvenido, guapo!"),
                                        ("Te doy la bienvenida.", HOMBRE, "Te doy la bienvenida."),
                                        ("Eres buena persona.", HOMBRE, "Eres buena persona."),
                                        ("Querido, ven aquí.", MUJER, "Querida, ven aquí.")):
            self.assertEqual(corregir_segunda_persona(texto, genero), esperado, texto)

    def test_tercera_y_titulos(self):
        casos = [
            ("Ana está cansado.", "Ana", MUJER, "Ana está cansada."),
            ("Creo que Bradley está muy enfadada.", "Bradley", HOMBRE, "Creo que Bradley está muy enfadado."),
            ("Mi amigo Ana vendrá mañana.", "Ana", MUJER, "Mi amiga Ana vendrá mañana."),
            ("La jefa Bradley llegó tarde.", "Bradley", HOMBRE, "El jefe Bradley llegó tarde."),
            ("Vi al pequeño Ana en el parque.", "Ana", MUJER, "Vi a la pequeña Ana en el parque."),
            ("Señorita Bradley, pase.", "Bradley", HOMBRE, "Señor Bradley, pase."),
            # Falsos positivos reales (corpus de Mi Juego): no se tocan
            ("Espero que el padre de Ana no esté muy enojado con ella.", "Ana", MUJER,
             "Espero que el padre de Ana no esté muy enojado con ella."),
            ("Soy una mujer pequeña 1Hero.", "1Hero", HOMBRE, "Soy una mujer pequeña 1Hero."),
            ("¿Tienes una novia 1Hero?", "1Hero", HOMBRE, "¿Tienes una novia 1Hero?"),
            ("¿Es esta tu novia 1Hero?", "1Hero", HOMBRE, "¿Es esta tu novia 1Hero?"),
            ("Me alegra ser tu doctora 1Hero. Te cuidaré.", "1Hero", HOMBRE, "Me alegra ser tu doctora 1Hero. Te cuidaré."),
            ("Deberías encontrar un novio Kayla para que también puedas sentirlo.", "Kayla", MUJER,
             "Deberías encontrar un novio Kayla para que también puedas sentirlo."),
            ("Esta cosa en la que trabaja Emily es algo serio.", "Emily", MUJER,
             "Esta cosa en la que trabaja Emily es algo serio."),
        ]
        for texto, nombre, genero, esperado in casos:
            self.assertEqual(corregir_tercera_persona(texto, nombre, genero), esperado, texto)

    def test_marcas(self):
        self.assertEqual(marcas_genero("Estoy cansado."), {"1m"})
        self.assertEqual(marcas_genero("¿Estás lista?"), {"2f"})
        self.assertEqual(marcas_genero("Bienvenido a casa."), {"2m"})
        self.assertEqual(marcas_genero("Te doy la bienvenida"), set())
        self.assertEqual(marcas_genero("Lo hice yo mismo"), {"1m"})
        self.assertEqual(marcas_genero("¡Tengo que estar... tranquilo...!"), {"1m"})
        self.assertEqual(marcas_genero("¿Estás... s-segura?"), {"2f"})

    def test_tercera_con_pausa(self):
        self.assertEqual(corregir_tercera_persona("Ana está... muy c-cansado.", "Ana", MUJER),
                         "Ana está... muy c-cansada.")


class TestFicha(unittest.TestCase):
    def setUp(self):
        self.f = FichaPersonajes([
            Personaje("1Hero", "hombre", "protagonista", codigos=["Mc"], alias=["William"]),
            Personaje("Laura", "mujer", "principal", codigos=["He"]),
            Personaje("Chloe", "mujer", "principal", codigos=["Ch"]),
            Personaje("Bradley", "hombre", codigos=["Br"]),
        ])

    def test_nombres_en_texto(self):
        f = FichaPersonajes([*self.f.personajes, Personaje("Old Man", "hombre")])
        self.assertEqual(sorted(f.nombres_en("CHLOE! 1Hero and the Old Man are here, \\N[1].")), ["CHLOE", "Old Man"])
        self.assertEqual(f.nombres_en("William, wait."), ["William"])     # alias: sí; marcadores: no
        self.assertEqual(f.nombres_en(""), [])

    def test_resolver_linea(self):
        ctx = resolver_linea(self.f, "I'm so tired.", InfoLinea(codigo="HeFrOp"))
        self.assertEqual(ctx.hablante.nombre, "Laura")
        self.assertEqual(ctx.destinatario.nombre, "1Hero")   # probable: un NPC habla al protagonista
        self.assertFalse(ctx.destinatario_explicito)
        ctx = resolver_linea(self.f, "Chloe, are you ready?", InfoLinea(codigo="He"))
        self.assertEqual(ctx.destinatario.nombre, "Chloe")
        self.assertTrue(ctx.destinatario_explicito)
        ctx = resolver_linea(self.f, "(I wonder where Laura went.)", None)
        self.assertTrue(ctx.pensamiento)
        self.assertEqual(ctx.hablante.nombre, "1Hero")
        self.assertEqual([p.nombre for p in ctx.mencionados], ["Laura"])
        ctx = resolver_linea(self.f, "I'm ready!", InfoLinea(es_opcion=True))
        self.assertEqual(ctx.hablante.nombre, "1Hero")
        ctx = resolver_linea(self.f, "We are here!", InfoLinea(hablante="Chloe & Bradley"))
        self.assertIsNone(ctx.hablante)
        self.assertEqual(resolver_linea(self.f, "Just a normal line.", None).firma(), "")
        self.assertIn("Habla Laura (mujer)", resolver_linea(self.f, "Hi.", InfoLinea(codigo="He")).ficha())

    def test_aplicar_concordancia(self):
        ctx = resolver_linea(self.f, "Chloe, are you ready? Bradley is tired.", InfoLinea(codigo="He"))
        self.assertEqual(aplicar_concordancia("Chloe, ¿estás listo? Bradley está cansada.",
                                              "Chloe, are you ready? Bradley is tired.", ctx),
                         "Chloe, ¿estás lista? Bradley está cansado.")
        ctx = resolver_linea(self.f, "I'm ready!", InfoLinea(es_opcion=True))
        self.assertEqual(aplicar_concordancia("¡Estoy lista!", "I'm ready!", ctx), "¡Estoy listo!")

    def test_pensamiento(self):
        self.assertTrue(es_pensamiento("<i>(I'm sure it's a trap.)</i>"))
        self.assertTrue(es_pensamiento("(Hmm...)"))
        self.assertFalse(es_pensamiento("I said (quietly) hello."))

    def test_fusionar_respeta_confirmado_y_guardar(self):
        self.f.buscar("Laura").confirmado = True
        nueva = FichaPersonajes([Personaje("Laura", "hombre", confianza=0.99, apariciones=500),
                                 Personaje("Nueva", "mujer")])
        self.f.fusionar(nueva)
        self.assertEqual(self.f.buscar("Laura").genero, MUJER)
        self.assertEqual(self.f.buscar("Laura").apariciones, 500)
        self.assertIsNotNone(self.f.buscar("Nueva"))
        ruta = Path(tempfile.mkdtemp()) / "personajes.json"
        self.f.guardar(ruta)
        copia = FichaPersonajes.cargar(ruta)
        self.assertEqual(copia.huella(), self.f.huella())
        self.assertIs(copia.buscar("\\N[1]"), copia.protagonista())


if __name__ == "__main__":
    unittest.main()
