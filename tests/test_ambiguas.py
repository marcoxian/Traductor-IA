"""Palabras con dos sentidos (W1-W3): "chest" (cofre / pecho / frase hecha) y "safe" (caja fuerte).

Las frases son reales (Otro Juego y Juego CSV), con la traducción que tenían."""
import unittest

from traductor import ambiguas


def sentido(texto: str, palabra: str = "chest") -> str | None:
    d = [x for x in ambiguas.decidir(texto) if x.palabra.startswith(palabra)]
    return d[0].sentido if d else None


class TestDecidirChest(unittest.TestCase):
    def test_cuerpo(self):
        for frase in ("Just looking at that manly chest has my heart thumping.",
                      "Want me to stab you in the chest again, miracle boy?",
                      "Alice reaches out and gives Hilda's chest a thorough grope.",
                      "Though...with your chest, it might feel a little tight. Bear with it, okay?",
                      "Boss, um, isn't this outfit a little...revealing? Especially around the chest...",
                      "Maybe they'll come because you're famous, but your big chest will draw their attention",
                      "(Whew... My heart's about to jump out of my chest! It's lucky that I got out safe...)",
                      "Lily's movements are hesitant, but Mai gently caresses the man's chest with one hand.",
                      "The guest buries his face in Julie's chest.",
                      "One of the men slips his hand inside Hilda's clothes, groping her chest.",
                      "Her huge breasts press against his chest."):
            self.assertEqual(sentido(frase), "pecho", frase)

    def test_cofre(self):
        for frase in ("Back half of a chest key that can be attached to the front half of a chest key.",
                      "A key to an antique chest.", "Bring the chest to Tanya.",
                      "Use a lock pick on the locked chest in the mansion.",
                      "Did you unlock the chest outside the farm?",
                      "There’s a chest to open under the mansion, near where the rift is open.",
                      "Craft a Hell Key to open the scary chests in the master bedroom.",
                      "Is it true there are treasure chests in the forest?",
                      "Every time I see a storage chest inside someone’s house, I open it.",
                      "What’s in the chest?", "The chests contained the amulets.",
                      "It wasn’t easy, but Lydia had them locked away in magic chests.",
                      "All you had to do was unlock a chest.", "An empty chest.", "\\c[17]Treasure Chest"):
            self.assertEqual(sentido(frase), "cofre", frase)

    def test_frases_hechas(self):
        for frase in ("What about you, 1Hero? Anything to get off your chest?",
                      "And, 1Hero, we’ll keep our little secret close to the chest.",
                      "Hell no… Just… Let’s keep this new development close to the chest.",
                      "He plays his cards close to his chest."):
            self.assertEqual(sentido(frase), "frase_hecha", frase)

    def test_dudosas_no_se_deciden(self):
        """Sin pistas claras no se fuerza nada: el modelo decide (y la clave de caché no cambia)."""
        for frase in ("Not a lot of women your age can boast about a chest like this.",
                      "You have the chest?", "I'm sure I'd remember that chest...",
                      "There’s a chest in the XXX Shop. Have you seen it?", "Chest",
                      "Open your chest.",                      # posesivo (cuerpo) + abrir (cofre): conflicto
                      "I put my heart into finding that chest."):
            self.assertIsNone(sentido(frase), frase)

    def test_comoda_y_sin_palabra(self):
        self.assertEqual(sentido("Check the chest of drawers in her room."), "comoda")
        self.assertEqual(ambiguas.decidir("Nothing to see here."), [])
        self.assertEqual(ambiguas.decidir(""), [])


class TestDecidirSafe(unittest.TestCase):
    def test_caja_fuerte(self):
        for frase in ("There’s a metal safe near a lake that you should open.",
                      "Use the electromagnet to open Ella’s safe.",
                      "Can clocks help you break into Andrea’s office safe?",
                      "Safes can hold valuable stuff.", "Safe Key", "It was in the safe.",
                      "It’s a combination safe… The code probably died with Zachary.",
                      "The safe is locked. I’ll need to find a code if I’m going to open it up.",
                      "The code for Andrea’s kitchen safe is written in her home.",
                      "I left my safe outside and it got so rusty I couldn’t open it…"):
            self.assertEqual(sentido(frase, "safe"), "caja_fuerte", frase)

    def test_adjetivo_no_se_toca(self):
        for frase in ("Don’t worry, 1Hero. I’ll keep her safe.", "Is that safe?", "Ella's safe now.",
                      "The secret is safe with me.", "It’s better to be safe than sorry.",
                      "I didn’t see any of Duncan’s henchmen inside the rift… But it’s safe to assume they left.",
                      "Let's find a safe place to rest.", "Better to be on the safe side.",
                      "Come back safe and sound.", "I’ll keep them safe.", "Is the office safe?"):
            self.assertIsNone(sentido(frase, "safe"), frase)


class TestTerminosYComprobacion(unittest.TestCase):
    def test_terminos(self):
        self.assertEqual(ambiguas.terminos("Groping her chest."), [("chest", "pecho")])
        self.assertEqual(ambiguas.terminos("Open the treasure chest."), [("chest", "cofre")])
        self.assertEqual(ambiguas.terminos("Anything to get off your chest?"), [])  # frase hecha: no se fuerza
        # "Chest Key" ya está en el glosario del usuario: no se repite la palabra
        self.assertEqual(ambiguas.terminos("Buy the Chest Key.", [("Chest Key", "Llave de cofre")]), [])
        self.assertEqual(ambiguas.terminos("Open Ella's safe."), [("safe", "caja fuerte")])

    def test_sentido_equivocado(self):
        f = ambiguas.sentido_equivocado
        self.assertTrue(f("Want me to stab you in the chest again?", "¿Quieres que te apuñale de nuevo en el cofre?"))
        self.assertFalse(f("Want me to stab you in the chest again?", "¿Quieres que te apuñale otra vez en el pecho?"))
        self.assertTrue(f("Bring the chest to Tanya.", "Lleva el pecho a Tanya."))
        self.assertFalse(f("Bring the chest to Tanya.", "Lleva el cofre a Tanya."))
        self.assertTrue(f("Anything to get off your chest?", "¿Algo que sacar de tu cofre?"))
        self.assertFalse(f("Anything to get off your chest?", "¿Algo que quieras contarme?"))
        self.assertTrue(f("Use the electromagnet to open Ella’s safe.", "Usa el imán para abrir el cofre de Ella."))
        self.assertTrue(f("Safe Key", "Llave de seguridad"))
        self.assertFalse(f("Safe Key", "Llave de la caja fuerte"))
        self.assertFalse(f("I'll keep her safe.", "La mantendré a salvo."))   # adjetivo: nada que comprobar
        # "tetas" para un "chest" neutro es otro registro; si el inglés ya es vulgar, vale
        self.assertTrue(f("Groping her chest.", "Tocándole las tetas."))
        self.assertFalse(f("Groping her chest and squeezing her boobs.", "Tocándole las tetas y apretándoselas."))
        # con "pechos" por "breasts", el cofre sigue sobrando
        self.assertTrue(f("Her huge breasts press against his chest.", "Sus enormes pechos presionan su cofre."))
        self.assertEqual(ambiguas.forzar_sentido("Her huge breasts press against his chest.",
                                                 "Sus enormes pechos presionan su cofre."),
                         "Sus enormes pechos presionan su pecho.")
        # un cofre de verdad junto a un pecho de verdad: si el sentido es cofre, el pecho no es un fallo
        self.assertFalse(f("She hugged the treasure chest to her breast.", "Abrazó el cofre del tesoro contra su pecho."))

    def test_nota_reintento(self):
        fallos = ambiguas.sentido_equivocado("Groping her chest.", "Tocándole el cofre.")
        self.assertIn("'chest' significa 'pecho'", ambiguas.nota_reintento(fallos))
        self.assertEqual(ambiguas.nota_reintento([]), "")

    def test_forzar_sentido(self):
        self.assertEqual(ambiguas.forzar_sentido("Groping her chest.", "Tocándole el cofre."), "Tocándole el pecho.")
        self.assertEqual(ambiguas.forzar_sentido("Just looking at that manly chest has my heart thumping.",
                                                 "Solo con mirar ese cofre tan viril me late el corazón."),
                         "Solo con mirar ese pecho tan viril me late el corazón.")
        self.assertEqual(ambiguas.forzar_sentido("It’s a combination safe…", "Es un cofre fuerte con combinación…"),
                         "Es una caja fuerte con combinación…")
        self.assertEqual(ambiguas.forzar_sentido("There’s a metal safe near a lake that you should open.",
                                                 "Hay un cofre fuerte cerca del lago que deberías abrir."),
                         "Hay una caja fuerte cerca del lago que deberías abrir.")
        self.assertEqual(ambiguas.forzar_sentido("Safes can hold valuable stuff.", "Los cofres fuertes guardan cosas."),
                         "Las cajas fuertes guardan cosas.")
        # lo que no es seguro de cambiar se deja ("el cofre de Ella" -> "la caja fuerte" cambia el artículo)
        self.assertEqual(ambiguas.forzar_sentido("Use the electromagnet to open Ella’s safe.", "Abre el cofre de Ella."),
                         "Abre el cofre de Ella.")
        self.assertEqual(ambiguas.forzar_sentido("Bring the chest to Tanya.", "Lleva el cofre a Tanya."),
                         "Lleva el cofre a Tanya.")


class TestVulgares(unittest.TestCase):
    """W7: palabras vulgares (frases reales de Otro Juego con la traducción que tenían)."""

    def vulgares(self, texto):
        return {d.palabra: d.termino for d in ambiguas.decidir(texto) if d.sentido == "vulgar"}

    def test_se_piden(self):
        self.assertEqual(self.vulgares("Eat that pussy, Kim."), {"pussy": "coño"})
        self.assertEqual(self.vulgares("Maybe if you’d stop riding my cock for a moment…"), {"cock": "polla"})
        self.assertEqual(self.vulgares("I can’t wait to hop on that dick again."), {"dick": "polla"})
        self.assertEqual(self.vulgares("Suck them tits!"), {"tits": "tetas"})
        self.assertEqual(self.vulgares("You took my dildo?"), {"dildo": "consolador"})
        self.assertEqual(self.vulgares("Make me cum, baby!"), {"cum": ""})             # solo se comprueba
        self.assertIn(("pussy", "coño"), ambiguas.terminos("Fuck my pussy!"))
        self.assertNotIn(("cum", ""), ambiguas.terminos("Make me cum, baby!"))

    def test_excepciones(self):
        for frase in ("Yes! What a pussy!", "Ugh. You’re a pussy.", "Don't be a pussy.", "He pussied out.",
                      "The cock crowed at dawn.", "Don't be a dick.", "You're such a dick.", "What a dick move.",
                      "Ella is waiting for you at Dick’s Diner.", "Dick’s Diner?", "Dick Grayson is here.",
                      "It was tit for tat.", "She graduated summa cum laude."):
            self.assertEqual(self.vulgares(frase), {}, frase)
        # el nombre no tapa la palabra si también sale en minúscula
        self.assertEqual(self.vulgares("At Dick’s, he showed me his dick."), {"dick": "polla"})

    def test_comprobacion(self):
        f = ambiguas.sentido_equivocado
        self.assertTrue(f("Eat that pussy, Kim.", "Llévate esa pija, Kim."))
        self.assertTrue(f("Ah! Yes! Fuck my pussy!", "¡Ah! ¡Sí! ¡Fóllame con tu polla!"))   # otro órgano
        self.assertFalse(f("Eat that pussy, Kim.", "Cómete ese coño, Kim."))
        self.assertFalse(f("Fuck my pussy with your cock!", "¡Fóllame el coño con tu polla!"))
        self.assertTrue(f("You took my dildo?", "¿Me robaste mi polla?"))
        self.assertFalse(f("Cum for me, Irene!", "¡Córrete para mí, Irene!"))
        self.assertTrue(f("God! Make me cum, baby!", "¡Dios mío... fóllame ya, cariño!"))
        self.assertFalse(f("Good boy. Suckle at my tit.", "Buen chico. Chupa mi pezón."))
        self.assertFalse(f("Yes! What a pussy!", "¡Sí! ¡Qué cobarde!"))                    # insulto: nada
        nota = ambiguas.nota_reintento(f("Eat that pussy, Kim.", "Llévate esa pija, Kim."))
        self.assertIn("'pussy' es 'coño'", nota)

    def test_insultos(self):
        """Los insultos se traducen con un insulto igual de vulgar ("nenaza", "capullo"), no con el órgano."""
        insultos = lambda t: {d.palabra: d.termino for d in ambiguas.decidir(t) if d.sentido == "insulto"}
        self.assertEqual(insultos("Yes! What a pussy!"), {"pussy": "nenaza"})
        self.assertEqual(insultos("Don't be a dick."), {"dick": "capullo"})
        self.assertEqual(insultos("Eat that pussy."), {})
        f = ambiguas.sentido_equivocado
        self.assertTrue(f("Yes! What a pussy!", "¡Sí! Qué coño de pija más grande..."))   # caso real
        self.assertFalse(f("Ugh. You’re a pussy.", "¡Vaya... qué gallina eres!"))
        self.assertFalse(f("Don't be a dick.", "No seas capullo."))
        self.assertIn(("pussy", "nenaza"), ambiguas.terminos("Yes! What a pussy!"))
        self.assertIn("insulto", ambiguas.nota_reintento(f("Yes! What a pussy!", "¡Qué coño!")))

    def test_glosario_del_usuario(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "glosario_adulto.json"
            ruta.write_text(json.dumps({"pussy": "chocho", "cock": ""}), encoding="utf-8")
            with mock.patch.object(ambiguas, "ARCHIVO_ADULTO", ruta):
                ambiguas.terminos_adultos.cache_clear()
                ambiguas._decidir.cache_clear()
                try:
                    self.assertEqual(self.vulgares("Eat that pussy."), {"pussy": "chocho"})
                    self.assertEqual(self.vulgares("Suck my cock."), {})                    # desactivada
                    self.assertFalse(ambiguas.sentido_equivocado("Eat that pussy.", "Cómete ese chocho."))
                finally:
                    ambiguas.terminos_adultos.cache_clear()
                    ambiguas._decidir.cache_clear()


class TestArticulos(unittest.TestCase):
    def test_arreglar_articulos(self):
        a = ambiguas.arreglar_articulos
        self.assertEqual(a("Usa la piqueta inquebrantable en la cofre bajo la iglesia."),
                         "Usa la piqueta inquebrantable en el cofre bajo la iglesia.")
        self.assertEqual(a("Hay una cofre en el gimnasio."), "Hay un cofre en el gimnasio.")
        self.assertEqual(a("Abre las cofres terroríficos."), "Abre los cofres terroríficos.")
        self.assertEqual(a("Todo lo que tenías que hacer era abrir una cofre."),
                         "Todo lo que tenías que hacer era abrir un cofre.")
        self.assertEqual(a("La llave de la cofre."), "La llave del cofre.")
        self.assertEqual(a("Ve a la cofre."), "Ve al cofre.")
        self.assertEqual(a("La cofre está aquí."), "El cofre está aquí.")
        self.assertEqual(a("Una gran cofre."), "Un gran cofre.")
        # lo que ya está bien no cambia (ni palabras parecidas: "la pechuga")
        for bien in ("El cofre del tesoro.", "Los cofres mágicos.", "Me duele el pecho.", "Come la pechuga.",
                     "La caja fuerte.", "Nada que ver."):
            self.assertEqual(a(bien), bien)


if __name__ == "__main__":
    unittest.main()
