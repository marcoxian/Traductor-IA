"""Pruebas unitarias para utilidades de texto y códigos de formato."""
from __future__ import annotations

import unittest
from traductor.texto import (
    ajustar_lineas,
    comparar_etiquetas,
    extraer_etiquetas,
    forzar_etiquetas,
    limpiar_respuesta,
    longitud_visible,
    reinsertar_saltos,
    sanitizar,
    separar_prefijo,
)


class TestTexto(unittest.TestCase):
    def test_etiquetas_desordenadas(self):
        from traductor.texto import etiquetas_desordenadas, evaluar_traduccion
        # El modelo copia el nombre de quien habla dentro de una llave: el conteo de {i} cuadra, pero Ren'Py falla
        self.assertTrue(etiquetas_desordenadas("{i}I better find her.", "{Pedro: {i}}Será mejor que la encuentre."))
        self.assertTrue(etiquetas_desordenadas("{i}Fuck it.", "{i} {¡i! A la mierda."))
        # Cierre antes de abrir
        self.assertTrue(etiquetas_desordenadas("I {i}just{/i} told you.", "{/i} Acabo de {i}decírtelo."))
        self.assertIn("etiquetas", evaluar_traduccion("I {i}just{/i} told you.", "{/i} Acabo de {i}decírtelo."))
        # Bien: mismas etiquetas en orden, llaves escritas ({{) o llaves que ya estaban en el original
        self.assertFalse(etiquetas_desordenadas("I {i}just{/i} told you.", "{i}Acabo{/i} de decírtelo."))
        self.assertFalse(etiquetas_desordenadas("{size=16}Oh{/size} yes!", "{size=16}Oh{/size} ¡sí!"))
        self.assertFalse(etiquetas_desordenadas("Use {{braces}}.", "Usa {{llaves}}."))
        self.assertFalse(etiquetas_desordenadas("{Lesson 1: Home Row}", "{Lección 1: fila central}"))

    def test_extraer_etiquetas(self):
        txt = r"Hola \C[4]mundo\C[0] %1 {name} \I[123] \n salto"
        etiquetas = extraer_etiquetas(txt)
        self.assertIn(r"\C[4]", etiquetas)
        self.assertIn(r"\C[0]", etiquetas)
        self.assertIn("%1", etiquetas)
        self.assertIn("{name}", etiquetas)
        self.assertIn(r"\I[123]", etiquetas)
        self.assertIn(r"\n", etiquetas)

    def test_comparar_etiquetas(self):
        orig = r"\C[2]A\C[0] %1"
        bien = r"%1 \C[2]A\C[0]"
        mal = r"\C[2]A %1"

        ok, faltan, sobran = comparar_etiquetas(orig, bien)
        self.assertTrue(ok)
        self.assertEqual(faltan, [])
        self.assertEqual(sobran, [])

        ok2, faltan2, sobran2 = comparar_etiquetas(orig, mal)
        self.assertFalse(ok2)
        self.assertIn(r"\C[0]", faltan2)

    def test_ajustar_lineas_longitud_visible(self):
        # Códigos de color no deben contar en la anchura visible
        texto_con_color = r"\C[4]Texto\C[0] corto"
        visible = longitud_visible(texto_con_color)
        self.assertEqual(visible, len("Texto corto"))

        # Líneas largas se reparten sin romper códigos
        texto_largo = "Esta es una oración que debería ser dividida en líneas de longitud controlada."
        lineas = ajustar_lineas(texto_largo, ancho=25)
        for l in lineas:
            self.assertLessEqual(len(l), 30)

    def test_sanitizar(self):
        sucio = "Frase con saltos\r\nde línea\n  y   espacios múltiples.\r"
        limpio = sanitizar(sucio)
        self.assertEqual(limpio, "Frase con saltos de línea y espacios múltiples.")

    def test_limpiar_respuesta(self):
        # Quita numeraciones y ecos del prompt
        resp1 = '1. "Hola mundo"'
        self.assertEqual(limpiar_respuesta(resp1), "Hola mundo")

        resp2 = 'Traducción de videojuego RPG del español de España: ¡Vamos allá!'
        self.assertEqual(limpiar_respuesta(resp2), "¡Vamos allá!")

        resp3 = 'Texto RPG del videojuego: "Aventura"'
        self.assertEqual(limpiar_respuesta(resp3), "Aventura")

        # NUNCA recortar frases con comas ni truncar cláusulas legítimas
        resp4 = "Vamos ahora, no nos emocionemos demasiado, ¿eh? Quién sabe qué pasa realmente."
        self.assertEqual(limpiar_respuesta(resp4, "Now now, let's not get too excited, hmm? Who knows."), resp4)

        resp5 = "Mierda, lo siento, Zoe."
        self.assertEqual(limpiar_respuesta(resp5, "Shit, I'm sorry, Zoe."), resp5)

        resp6 = "Lo sé, pero no tengo dinero para un conejito."
        self.assertEqual(limpiar_respuesta(resp6, "I know, but I don't have the money for a bunny."), resp6)

    def test_forzar_etiquetas(self):
        orig = r"\C[1]\C[2]Texto"
        trad = "Texto"
        forzado = forzar_etiquetas(orig, trad)
        self.assertTrue(forzado.startswith(r"\C[1]\C[2]") or forzado.startswith(r"\C[2]\C[1]"))

    def test_limpiar_respuesta_quita_el_eco_de_la_correccion(self):
        """El modelo devuelve la frase corregida y después repite la entrada de la corrección."""
        resp = r"Lo siento. \!Me voy. Borrador a corregir: ¡Lo siento! Me voy."
        self.assertEqual(limpiar_respuesta(resp, r"Sorry. \!I'm leaving."), r"Lo siento. \!Me voy.")
        self.assertEqual(limpiar_respuesta("Borrador a corregir: Me voy.", "I'm leaving."), "Me voy.")

    def test_limpiar_respuesta_quita_los_ecos_con_la_etiqueta_reescrita(self):
        """El modelo cambia la etiqueta ("Borrado a corrigir", "Corrección sugerida"...) y a veces la pone
        en otra línea; lo de detrás es la frase vieja."""
        casos = [
            ("{i}Seguirá...{/i}\nBorrado a corregir: Seguira...", "{i}Seguirá...{/i}"),
            ("{i}Ajustes{/i}\nBorrado a corrigir: Ajustes", "{i}Ajustes{/i}"),
            ("Me voy ya.\nCorrección sugerida: Me voy.", "Me voy ya."),
            ("Me voy ya.\nCorrección: Me voy.", "Me voy ya."),
            ("{i}¡No, no!\nVersión del usuario para corregir: {no no... ¡No!", "{i}¡No, no!"),
            ("¡Qué frío!\nTexto del borrador que necesita corrección: ¡Qué frio!", "¡Qué frío!"),
            ("¡Bien! Corrección para el borrado: ¡Bien hecho!", "¡Bien!"),
            ("El texto original es: Lo haría igual. El borrador que se debe corregir dice: Lo hacía igual.",
             "Lo haría igual."),
        ]
        for respuesta, esperado in casos:
            with self.subTest(respuesta=respuesta):
                self.assertEqual(limpiar_respuesta(respuesta, "I'd do the same."), esperado)

    def test_forzar_etiquetas_pone_las_pausas_entre_las_mismas_frases(self):
        """Una pausa de mitad de frase al principio haría pulsar una tecla antes de ver el texto."""
        self.assertEqual(forzar_etiquetas(r"Yeah... \!Becoming one seems nice...", "Sí... ¡Serlo parece genial..."),
                         r"Sí... \!¡Serlo parece genial...")
        self.assertEqual(forzar_etiquetas(r"Fine. \!Seen my sword? \|The silver one.",
                                          "¡Bien! ¿Has visto mi espada? ¡La de plata!"),
                         r"¡Bien! \!¿Has visto mi espada? \|¡La de plata!")
        self.assertEqual(forzar_etiquetas(r"Same. \|None of us.", "Igual. |Ninguno."), r"Igual. \|Ninguno.")
        # Sin hueco entre frases, o al principio: como siempre
        self.assertEqual(forzar_etiquetas(r"One. Two. \!Three.", "Uno, dos y tres."), r"Uno, dos y tres. \!")
        self.assertEqual(forzar_etiquetas(r"\!Wait here.", "Espera aquí."), r"\! Espera aquí.")

    def test_separar_prefijo(self):
        txt = r"\N<\C[5]Brad\C[0]>Hola a todos"
        prefijo, cuerpo = separar_prefijo(txt)
        self.assertEqual(prefijo, r"\N<\C[5]Brad\C[0]>")
        self.assertEqual(cuerpo, "Hola a todos")

    def test_corregir_puntuacion_pegada(self):
        from traductor.texto import corregir_puntuacion_pegada
        # Palabras pegadas tras punto
        self.assertEqual(corregir_puntuacion_pegada("examen.Si"), "examen. Si")
        self.assertEqual(corregir_puntuacion_pegada("Diana.Ella te dará dinero."), "Diana. Ella te dará dinero.")
        # Signos pegados
        self.assertEqual(corregir_puntuacion_pegada("progreso.¿Te gusta?"), "progreso. ¿Te gusta?")
        self.assertEqual(corregir_puntuacion_pegada("¡Hola!¿Cómo estás?"), "¡Hola! ¿Cómo estás?")
        # Prefijo de sprite en RPG Maker se preserva sin espacio extra (incluso con ^)
        self.assertEqual(corregir_puntuacion_pegada("HeFrOp.Siento energía.Ahora voy."), "HeFrOp.Siento energía. Ahora voy.")
        self.assertEqual(corregir_puntuacion_pegada("MiHaEx^.¡No!...Ahora voy."), "MiHaEx^.¡No!... Ahora voy.")
        # Código Javascript intacto
        self.assertEqual(corregir_puntuacion_pegada("Galv.CACHE.load('img')"), "Galv.CACHE.load('img')")
        # Nombres de archivos o etiquetas con signo al inicio no deben separarse
        self.assertEqual(corregir_puntuacion_pegada("!Strip"), "!Strip")
        self.assertEqual(corregir_puntuacion_pegada("!Door"), "!Door")
        self.assertEqual(corregir_puntuacion_pegada("?Help"), "?Help")

    def test_postprocesar_traduccion_errores_frecuentes(self):
        from traductor.texto import postprocesar_traduccion

        # 1. Alucinaciones fonéticas y errores léxicos
        self.assertEqual(postprocesar_traduccion("¡Fúmeme!", "Fuck me!"), "¡Fóllame!")
        self.assertEqual(postprocesar_traduccion("Vamos a vestamos bien.", "Let's dress up."), "Vamos a vistamos bien.")
        self.assertEqual(postprocesar_traduccion("Hola Va1erie.", "Hello Valerie."), "Hola Valerie.")
        self.assertEqual(postprocesar_traduccion("¡Mierda santa!", "Holy shit!"), "¡No me jodas!")
        self.assertEqual(postprocesar_traduccion("¡Oh, mi!", "Oh my!"), "¡Madre mía!")

        # 2. Tartamudeos a medio traducir
        self.assertEqual(postprocesar_traduccion("R- correcto.", "R-right."), "C-correcto.")
        self.assertEqual(postprocesar_traduccion("¿Y-yah...?", "Y-yeah...?"), "¿S-sí...?")
        self.assertEqual(postprocesar_traduccion("S-siento mucho eso.", "S-sorry about that."), "L-lo siento mucho eso.")

        # 3. Bucles degenerativos del LLM ("correr el riesgo de..." ante "cum")
        bucle = "C-correr el riesgo de correr el riesgo de correr el riesgo de correr el riesgo"
        self.assertEqual(postprocesar_traduccion(bucle, "C-cum!"), "¡C-córrete!")

        # 4. Calcos estructurales y falsos amigos con contexto inglés
        self.assertEqual(postprocesar_traduccion("Eso no hace sentido.", "That doesn't make sense."), "Eso no tiene sentido.")
        self.assertEqual(postprocesar_traduccion("La vi más temprano hoy.", "I saw her earlier today."), "La vi hace un rato.")
        self.assertEqual(postprocesar_traduccion("Obtuviste un elemento.", "You got an item."), "Obtuviste un objeto.")
        self.assertEqual(postprocesar_traduccion("¡Sácame el pene!", "Take my cock!"), "¡Trágate mi polla!")

        # 5. Contenido adulto y desambiguaciones
        self.assertEqual(postprocesar_traduccion("R-derecha...", "R-right..."), "C-correcto...")
        self.assertEqual(postprocesar_traduccion("Es mi vecino Jaime.", "It's my neighbor Jaime."), "Es mi vecina Jaime.")
        self.assertEqual(postprocesar_traduccion("Bajar de la caravana.", "Leave the train."), "Bajar del tren.")
        self.assertEqual(postprocesar_traduccion("Vendedor de bolsillo coño", "Pocket pussy vendor"), "Vendedor de masturbador de bolsillo")

        # 6. Signos dobles desbalanceados
        self.assertEqual(postprocesar_traduccion("¡¿Qué estás haciendo!"), "¡¿Qué estás haciendo?!")

        # 7. Modismos y concordancias frecuentes (Oh dear, la Oráculo, Tantas músculos)
        self.assertEqual(postprocesar_traduccion("¡Ay, querido!", "Oh, dear!"), "¡Vaya por Dios!")
        self.assertEqual(postprocesar_traduccion("Salir de la Oráculo.", "Leave the Oracle."), "Salir del Oráculo.")
        self.assertEqual(postprocesar_traduccion("¡Oh! ¡Tantas músculos!", "Oh! So many muscles!"), "¡Oh! ¡Cuántos músculos!")

    def test_fuga_idioma_y_genero_v21(self):
        from pathlib import Path
        from unittest import mock

        from traductor import texto as modulo_texto
        prueba = Path(__file__).parent / "datos" / "correcciones_locales.prueba.json"
        parche = mock.patch.object(modulo_texto, "ARCHIVO_CORRECCIONES_LOCALES", prueba)
        parche.start()
        modulo_texto.correcciones_locales.cache_clear()
        self.addCleanup(modulo_texto.correcciones_locales.cache_clear)
        self.addCleanup(parche.stop)
        from traductor.texto import corregir_genero_hablante_v21, evaluar_traduccion, tiene_fallo_grave
        # Detección de fugas de otros idiomas (chino, ruso, italiano, polaco)
        self.assertIn("fuga_idioma", evaluar_traduccion("Chloe is upset.", "克洛伊很生气。"))
        self.assertIn("fuga_idioma", evaluar_traduccion("Beautiful as always.", "Bella come sempre."))
        self.assertIn("fuga_idioma", evaluar_traduccion("Show it to me.", "Mój się."))
        # Checo sin háček: ninguna letra rara, solo las palabras lo delatan
        self.assertIn("fuga_idioma", evaluar_traduccion("Only one way to find out.", "Slo jedna cesta, jak se to zjistí."))
        self.assertIn("fuga_idioma", evaluar_traduccion("I don't know.", "Nie wiem, to jest dziwne."))
        self.assertNotIn("fuga_idioma", evaluar_traduccion("Grab the basket.", "Coge la cesta, que no hay tiempo."))
        self.assertTrue(tiene_fallo_grave(evaluar_traduccion("Chloe is upset.", "克洛伊很生气。")))

        # Corrección de género de hablante según prefijo V21 de 2 letras
        self.assertEqual(corregir_genero_hablante_v21("Estoy agotada.", "McSaOp."), "Estoy agotado.")
        self.assertEqual(corregir_genero_hablante_v21("Estoy ocupado.", "HeFrOp."), "Estoy ocupada.")
        self.assertEqual(corregir_genero_hablante_v21("No estoy seguro de eso.", "ArWoOp."), "No estoy segura de eso.")


if __name__ == "__main__":
    unittest.main()
