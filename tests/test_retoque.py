"""Retoque de las traducciones (``postprocesar_traduccion``): etiquetas espaciadas, fugas de idioma, falsos
amigos, sincronización de líneas de control y las correcciones locales de cada usuario (con un archivo de prueba
de nombres inventados: las de verdad son privadas)."""
import shutil
import unittest
from pathlib import Path
from unittest import mock

from traductor import config, texto
from traductor.motores.rpgmaker import InyectorRPGMaker, _separar_envoltorios_dialogo
from traductor.texto import corregir_genero_hablante_v21, limpiar_respuesta, postprocesar_traduccion

PRUEBA = Path(__file__).parent / "datos" / "correcciones_locales.prueba.json"


def con_correcciones_de_prueba(test: unittest.TestCase, ruta: Path = PRUEBA) -> None:
    parche = mock.patch.object(texto, "ARCHIVO_CORRECCIONES_LOCALES", ruta)
    parche.start()
    texto.correcciones_locales.cache_clear()
    test.addCleanup(texto.correcciones_locales.cache_clear)
    test.addCleanup(parche.stop)


class TestRetoqueGenerico(unittest.TestCase):

    def test_colapso_etiquetas_html_espaciadas(self):
        entrada = "< center > < br > < br > ¿Quieres personalizar el nombre de tu personaje?"
        esperado = "<center><br><br>¿Quieres personalizar el nombre de tu personaje?"
        self.assertEqual(postprocesar_traduccion(entrada), esperado)

    def test_colapso_etiquetas_cierre_y_wordwrap(self):
        entrada = "< wordwrap > < / center > Texto con formato < / br >"
        esperado = "<wordwrap></center>Texto con formato</br>"
        self.assertEqual(postprocesar_traduccion(entrada), esperado)

    def test_reparacion_carets_y_codigos_espera(self):
        self.assertEqual(postprocesar_traduccion("Llega tarde, Sr. García. \\w[170]^\\"),
                         "Llega tarde, Sr. García. \\w[170]\\^")
        orig = "<center><br><br>Too late, Mr. Garcia.\\^"
        trad = "<center><br><br>Llega tarde, Sr. García. ^"
        self.assertEqual(postprocesar_traduccion(trad, orig), "<center><br><br>Llega tarde, Sr. García.\\^")

    def test_fuga_idioma_aleman_nein(self):
        self.assertEqual(postprocesar_traduccion("Nein", "No"), "No")
        self.assertEqual(postprocesar_traduccion("nein", "no"), "no")

    def test_opciones_interfaz_criticas(self):
        self.assertEqual(postprocesar_traduccion("Siempre Dasher", "Always Dash"), "Correr siempre")
        self.assertEqual(postprocesar_traduccion("Orden Recuerda", "Command Remember"), "Recordar comandos")
        self.assertEqual(postprocesar_traduccion("Pantalla completa", "Fullscreen"), "Pantalla completa")

    def test_corregir_miss_como_fallo(self):
        self.assertEqual(postprocesar_traduccion("Será mejor hablar con la fallo Pérez."), "Será mejor hablar con la señorita Pérez.")
        self.assertEqual(postprocesar_traduccion("Lo siento fallo Pérez."), "Lo siento señorita Pérez.")
        self.assertEqual(postprocesar_traduccion("Fallo López, buenas tardes."), "Señorita López, buenas tardes.")
        self.assertEqual(postprocesar_traduccion("Gracias, fallo."), "Gracias, señorita.")

    def test_limpiar_ecos_prompt_y_metadatos(self):
        self.assertEqual(limpiar_respuesta("Original (inglés): You are late.\nTraducción: Llegas tarde."), "Llegas tarde.")
        self.assertEqual(limpiar_respuesta("Origen (anglés): Parar ara!\nTraducción: ¡Para ahora!"), "¡Para ahora!")
        self.assertEqual(limpiar_respuesta("Traducción directa: Hola mundo"), "Hola mundo")
        self.assertEqual(limpiar_respuesta("Texto original: Test\nRespuesta: Prueba"), "Prueba")

    def test_separacion_envoltorios_dialogo_cutscene(self):
        prefijo, cuerpo, sufijo, envolver = _separar_envoltorios_dialogo("<center><br><br>You’re too late, Mr. Garcia.\\w[170]\\^")
        self.assertEqual(prefijo, "<center><br><br>")
        self.assertEqual(cuerpo, "You’re too late, Mr. Garcia.")
        self.assertEqual(sufijo, "\\w[170]\\^")
        self.assertFalse(envolver)

    def test_preservacion_lineas_control_401(self):
        # Cinemática de RPG Maker con línea de diálogo y línea de espera separadas
        event_list = [
            {"code": 401, "parameters": ["<center><br><br>You’re too late, Mr. Garcia."]},
            {"code": 401, "parameters": ["\\w[170]\\^"]},
            {"code": 401, "parameters": ["<center><br><br>Let her go!"]},
            {"code": 401, "parameters": ["\\w[240]\\^"]},
        ]
        inyector = InyectorRPGMaker(Path("."), None)
        cola = []
        inyector._extraer(event_list, cola)
        self.assertEqual(cola, ["You’re too late, Mr. Garcia.", "Let her go!"])  # solo las de texto visible

        class FakePerfil:
            def restaurar_nombres(self, orig, trad): return trad

        class FakeTranslator:
            perfil = FakePerfil()

        inyector.translator = FakeTranslator()
        inyector._inyectar(event_list, iter(["Llega demasiado tarde, Sr. García.", "¡Suéltala!"]))
        self.assertEqual(event_list[0]["parameters"][0], "<center><br><br>Llega demasiado tarde, Sr. García.")
        self.assertEqual(event_list[1]["parameters"][0], "\\w[170]\\^")
        self.assertEqual(event_list[2]["parameters"][0], "<center><br><br>¡Suéltala!")
        self.assertEqual(event_list[3]["parameters"][0], "\\w[240]\\^")

    def test_reparacion_etiquetas_fuente_yanfly(self):
        res1 = postprocesar_traduccion("\\c[27]\\ow[0]\\fs[24] <Arial> Llamar a una cita de soltero")
        self.assertIn("\\fn<Arial>", res1)
        self.assertIn("Cita íntima", res1)
        res2 = postprocesar_traduccion("\\c[23] \\fn\\Cinzel-Black\\fs[70]<br><center>Objeto")
        self.assertIn("\\fn<Cinzel-Black>", res2)

    def test_booty_call_y_noise_complaint(self):
        self.assertEqual(postprocesar_traduccion("Llamar a una cita de soltero", "Booty Call"), "Cita íntima")
        self.assertEqual(postprocesar_traduccion("Cita de soltero", "Booty Call"), "Cita íntima")
        self.assertIn("denuncia por ruido", postprocesar_traduccion("Investigar el quejoso.", "Investigate the noise complaint."))
        self.assertIn("queja por ruido", postprocesar_traduccion("Si estás aquí por el ruido de la queja",
                                                                 "If you are here about the noise complaint"))

    def test_autogeneracion_perfil_nuevo_juego(self):
        nombre_test = "juego_prueba_autogenerado_xyz"
        carpeta_test = config.DIR_WORKSPACE / nombre_test
        if carpeta_test.exists():
            shutil.rmtree(carpeta_test)
        try:
            with self.assertLogs("traductor.config", level="WARNING") as registro:
                perfil = config.cargar_perfil(nombre_test, auto_crear=True)
            self.assertTrue(carpeta_test.is_dir())
            for archivo in ("contexto.txt", "glosario.json", "ajustes.json", "personajes.json"):
                self.assertTrue((carpeta_test / archivo).exists(), archivo)
            # La ficha se crea con el protagonista de género DESCONOCIDO (no se adivina)
            prota = perfil.personajes.protagonista()
            self.assertEqual(prota.genero, "desconocido")
            self.assertTrue(any("falta el género del protagonista" in m for m in registro.output))
            self.assertIn("Español de España coloquial", perfil.contexto)  # hereda el contexto global
            self.assertNotIn("SIEMPRE en masculino", perfil.contexto)     # ...sin forzar el masculino
            self.assertNotIn("Protagonista:", perfil.contexto)
        finally:
            if carpeta_test.exists():
                shutil.rmtree(carpeta_test)

    def test_apelativos_sugar_y_stud(self):
        self.assertEqual(postprocesar_traduccion("¡Oye, azúcar!", "Hey, sugar!"), "¡Oye, cielo!")
        self.assertEqual(postprocesar_traduccion("¿Qué pasa, panecillo de azúcar?", "What's the matter, sugarplum?"),
                         "¿Qué pasa, bombón?")
        self.assertEqual(postprocesar_traduccion("Hola, estudiante.", "Hey, stud."), "Hola, guapetón.")
        self.assertEqual(postprocesar_traduccion("Ahí estás, estudiante.", "There you are, studmuffin."), "Ahí estás, macizo.")

    def test_modismos_naturales(self):
        self.assertEqual(postprocesar_traduccion("Me he hecho una tontería en el gimnasio. Nunca volveré...",
                                                 "I made a fool of myself at the gym. I'm never going back..."),
                         "He hecho el ridículo en el gimnasio. Nunca volveré...")
        self.assertEqual(postprocesar_traduccion("Bueno, Pablo. ¿Vas a invitarnos chicas a tu nueva casa?",
                                                 "So, Pablo. Are you going to invite us girls over to your new home?"),
                         "Bueno, Pablo. ¿Vas a invitarnos a las chicas a tu nueva casa?")

    def test_easy_there_etiquetas_vacias_y_modismos(self):
        self.assertEqual(postprocesar_traduccion("Fácil allí, cariño. Necesitamos una licencia para cosechar esas viejas juguetas.",
                                                 "Easy there, honey. We need a license to harvest those old toys."),
                         "Tranquila, cariño. Necesitamos una licencia para cosechar esos juguetes viejos.")
        self.assertEqual(postprocesar_traduccion("<> \\i[229] \\c[17]Envoltura de goma\\c[0]<br>Se puede usar como laparte superior.",
                                                 "<center>\\i[229] \\c[17]Rubber Wrap\\c[0]<br>Can be used as the top portion."),
                         "<center>\\i[229] \\c[17]Envoltura de goma\\c[0]<br>Se puede usar como la parte superior.")
        self.assertEqual(postprocesar_traduccion("Un buen tracto nuevo.", "A good new tractor."), "Un buen tractor nuevo.")


class TestCorreccionesLocales(unittest.TestCase):
    """glosarios/correcciones_locales.json (privado): aquí, con un archivo de prueba de nombres inventados."""

    def setUp(self):
        con_correcciones_de_prueba(self)

    def test_sin_archivo_solo_el_retoque_generico(self):
        con_correcciones_de_prueba(self, Path(__file__).parent / "datos" / "no_existe.json")
        self.assertEqual(postprocesar_traduccion("Suave, 1Héroe.", "Smooth, 1Hero."), "Suave, 1Héroe.")
        self.assertEqual(corregir_genero_hablante_v21("Estoy agotada.", "McSaOp."), "Estoy agotada.")  # sin códigos

    def test_comodin_del_protagonista(self):
        orig = "Smooth, 1Hero. Real smooth."
        for t in ("Suave, 1Héroe. Muy suave.", "Suave, 1héroe. Muy suave.", "Suave, Héroe. Muy suave."):
            self.assertEqual(postprocesar_traduccion(t, orig), "Suave, 1Hero. Muy suave.")
        self.assertEqual(postprocesar_traduccion("Líbrate de tus pensamientos, 1Hero 1.", "Free your mind, 1Hero."),
                         "Líbrate de tus pensamientos, 1Hero.")
        self.assertEqual(postprocesar_traduccion("Hola, 1 1Hero.", "Hello, 1Hero."), "Hola, 1Hero.")
        self.assertEqual(postprocesar_traduccion("Vi al 1Hero ayer.", "I saw 1Hero yesterday."), "Vi a 1Hero ayer.")

    def test_lugares_y_nombres_propios(self):
        self.assertEqual(postprocesar_traduccion("No me interesa ir al Chiringuito de Joe.", "I'm not interested in going to Joe's."),
                         "No me interesa ir a Joe's Diner.")
        self.assertEqual(postprocesar_traduccion("El padre Salomón dijo eso.", "Father Solomon said that."),
                         "El padre Solomon dijo eso.")
        self.assertEqual(postprocesar_traduccion("Viven en Puerto Brisa.", "They live in Breeze Harbor."), "Viven en Breeze Harbor.")
        # "si_original": sin el nombre en el original no se toca
        self.assertEqual(postprocesar_traduccion("El rey Salomón.", "King Solomonoff."), "El rey Salomón.")
        self.assertEqual(postprocesar_traduccion("Hola, Lcuía.", ""), "Hola, Lucía.")

    def test_tranquila_con_nombre(self):
        self.assertEqual(postprocesar_traduccion("Fácil allí, Lucía.", "Easy there, Lucia."), "Tranquila, Lucía.")

    def test_codigos_de_hablante_sin_ficha(self):
        self.assertEqual(corregir_genero_hablante_v21("Me quedé dormida en el sofá.", "McNoOp."), "Me quedé dormido en el sofá.")
        self.assertEqual(corregir_genero_hablante_v21("Ahora estoy aún más confundida.", "McThOp."),
                         "Ahora estoy aún más confundido.")
        self.assertEqual(corregir_genero_hablante_v21("Lo haré yo misma.", "McSmOp."), "Lo haré yo mismo.")
        self.assertEqual(corregir_genero_hablante_v21("Estaba muy cansado ayer.", "ChSmOp."), "Estaba muy cansada ayer.")
        self.assertEqual(corregir_genero_hablante_v21("Estoy ocupado.", "ZzFrOp."), "Estoy ocupado.")  # desconocido


if __name__ == "__main__":
    unittest.main()
