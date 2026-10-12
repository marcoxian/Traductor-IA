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

    def test_forzar_etiquetas(self):
        orig = r"\C[1]\C[2]Texto"
        trad = "Texto"
        forzado = forzar_etiquetas(orig, trad)
        self.assertTrue(forzado.startswith(r"\C[1]\C[2]") or forzado.startswith(r"\C[2]\C[1]"))

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
        # Prefijo de sprite en RPG Maker se preserva sin espacio extra
        self.assertEqual(corregir_puntuacion_pegada("HeFrOp.Siento energía.Ahora voy."), "HeFrOp.Siento energía. Ahora voy.")
        # Código Javascript intacto
        self.assertEqual(corregir_puntuacion_pegada("Galv.CACHE.load('img')"), "Galv.CACHE.load('img')")


if __name__ == "__main__":
    unittest.main()
