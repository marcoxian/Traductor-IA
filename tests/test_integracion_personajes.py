"""Integración de la ficha de personajes (personajes.json) en el perfil y en el traductor.

Ningún test llama a Ollama: ``_generar`` siempre está simulado. Los perfiles se construyen en
memoria o en un ``workspace`` temporal, y las cachés viven en carpetas temporales.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from traductor import config, prompts
from traductor.config import Perfil, huella_contexto
from traductor.ollama import OllamaTranslator
from traductor.personajes import FichaPersonajes, InfoLinea, Personaje
from traductor.texto import corregir_genero_hablante_v21, evaluar_traduccion

MODELO = "ModeloPrueba"

# Huellas del contexto en modo antiguo (sin personajes.json), calculadas ANTES de este cambio.
# Si cambias a propósito un contexto.txt, actualiza aquí su huella (esa caché se invalida igualmente).
HUELLAS_MODO_ANTIGUO = {
    None: "cdae65a393",  # el contexto global (glosarios/contexto.txt)
}


def _ficha(genero_prota: str = "mujer", prota: str = "Zoe") -> FichaPersonajes:
    return FichaPersonajes(personajes=[
        Personaje(prota, genero_prota, "protagonista", codigos=["Mc"], confirmado=True),
        Personaje("Ana", "mujer", "principal", codigos=["Al"], confianza=0.95),
        Personaje("Bob", "hombre", "secundario", codigos=["Bo"], confianza=0.9),
    ], titulo="Juego de prueba")


def _sha1(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def _analizador_falso(ficha: FichaPersonajes | None = None, error: Exception | None = None) -> types.ModuleType:
    """Módulo ``traductor.analizador`` de mentira (el real lo escribe otro paso)."""
    def analizar_y_guardar(juego, ruta_juego, *, usar_ia=False, modelo_ia=None, simular=False, motor=None):
        if error is not None:
            raise error
        ruta = config.carpeta_juego(juego, crear=True) / "personajes.json"
        ficha.guardar(ruta)
        return ruta, types.SimpleNamespace(ficha=ficha, avisos=["aviso de prueba"])

    modulo = types.ModuleType("traductor.analizador")
    modulo.analizar_y_guardar = mock.MagicMock(side_effect=analizar_y_guardar)
    return modulo


class _ConWorkspaceTemporal(unittest.TestCase):
    """Workspace y contexto global temporales: los tests no tocan workspace/ real."""

    contexto_global = "# cabecera\n@sin_ficha: REGLA MASCULINA.\nGLOBAL.\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.workspace = self.tmp / "workspace"
        self.carpeta = self.workspace / "juego_x"
        self.carpeta.mkdir(parents=True)
        (self.carpeta / "contexto.txt").write_text("# comentario\nJuego de prueba.\n", encoding="utf-8")
        self.global_ctx = self.tmp / "contexto_global.txt"
        self.global_ctx.write_text(self.contexto_global, encoding="utf-8")
        for parche in (mock.patch.object(config, "DIR_WORKSPACE", self.workspace),
                       mock.patch.object(config, "CONTEXTO_GLOBAL", self.global_ctx)):
            parche.start()
            self.addCleanup(parche.stop)

    def _juego_rpgmaker(self, actor: str = "Rina") -> Path:
        ruta = self.tmp / "MiJuego"
        (ruta / "www" / "data").mkdir(parents=True)
        (ruta / "www" / "data" / "System.json").write_text('{"gameTitle": "Mi Juego"}', encoding="utf-8")
        (ruta / "www" / "data" / "Actors.json").write_text(f'[null, {{"name": "{actor}"}}]', encoding="utf-8")
        return ruta


# --------------------------------------------------------------------------- Compatibilidad
class TestCompatibilidadModoAntiguo(unittest.TestCase):
    def test_huellas_modo_antiguo_de_los_perfiles_existentes(self):
        """Sin personajes.json el contexto es byte a byte el de antes: misma huella y misma caché."""
        for juego, esperada in HUELLAS_MODO_ANTIGUO.items():
            with self.subTest(juego=juego or "global"):
                if juego is not None and not (config.DIR_WORKSPACE / juego).is_dir():
                    self.skipTest(f"No existe workspace/{juego}")
                perfil = config.cargar_perfil(juego, auto_crear=False)
                self.assertEqual(perfil.huella_legacy, esperada)
                if perfil.personajes is None:
                    self.assertEqual(perfil.huella(), esperada)

    def test_contexto_global_real_marca_la_regla_masculina_como_sin_ficha(self):
        ruta = config.DIR_GLOSARIOS / "contexto.txt"
        antiguo = config.leer_contexto(ruta)
        con_ficha = config.leer_contexto(ruta, con_ficha=True)
        self.assertTrue(antiguo.startswith("El protagonista habla de sí mismo SIEMPRE en masculino"))
        self.assertNotIn("@sin_ficha", antiguo)
        self.assertNotIn("SIEMPRE en masculino", con_ficha)
        self.assertNotIn("@sin_ficha", con_ficha)
        self.assertIn("Español de España coloquial", con_ficha)

    def test_clave_sin_firma_es_la_de_siempre(self):
        t = OllamaTranslator(model_name=MODELO, perfil=Perfil(contexto="CTX"))
        huella = huella_contexto("CTX")
        esperada = _sha1(f"{MODELO}\x00{huella}\x00Door=Puerta\x00Open the door.")
        self.assertEqual(t._clave("Open the door.", [("Door", "Puerta")]), esperada)
        self.assertEqual(t._clave("Open the door.", [("Door", "Puerta")], "", None), esperada)
        self.assertNotEqual(t._clave("Open the door.", [("Door", "Puerta")], "h:Ana=mujer"), esperada)
        self.assertEqual(t._clave("Hi.", [], "", "0123456789"), _sha1(f"{MODELO}\x000123456789\x00\x00Hi."))

    def test_construir_instruccion_sin_personajes_no_cambia(self):
        base = prompts.construir_instruccion(prompts.INSTRUCCION, "CTX", [("a", "b")], ["[x -> y]"])
        self.assertEqual(base, prompts.construir_instruccion(prompts.INSTRUCCION, "CTX", [("a", "b")],
                                                             ["[x -> y]"], personajes=""))
        con = prompts.construir_instruccion(prompts.INSTRUCCION, "CTX", [("a", "b")], personajes="Habla Ana (mujer).")
        self.assertIn("CONTEXTO DEL JUEGO: CTX PERSONAJES: Habla Ana (mujer). GLOSARIO OBLIGATORIO", con)
        lote = prompts.construir_instruccion(prompts.INSTRUCCION_LOTE, "CTX",
                                             personajes_lote=[(1, "Habla Ana (mujer)."), (2, ""), (3, "Habla Bob (hombre).")])
        self.assertIn("PERSONAJES POR FRASE: 1) Habla Ana (mujer); 3) Habla Bob (hombre).", lote)
        self.assertNotIn("2)", lote)


# --------------------------------------------------------------------------- Perfil con ficha
class TestPerfilConFicha(_ConWorkspaceTemporal):
    def _guardar_ficha(self, genero_prota: str, prota: str = "Zoe") -> None:
        _ficha(genero_prota, prota).guardar(self.carpeta / "personajes.json")

    def test_sin_ficha_modo_antiguo(self):
        perfil = config.cargar_perfil("juego_x", auto_crear=False)
        self.assertIsNone(perfil.personajes)
        self.assertEqual(perfil.contexto, "REGLA MASCULINA. GLOBAL. Juego de prueba.")
        self.assertEqual(perfil.huella_legacy, perfil.huella())

    def test_con_ficha_mujer(self):
        self._guardar_ficha("mujer")
        perfil = config.cargar_perfil("juego_x", auto_crear=False)
        regla = perfil.personajes.regla_protagonista()
        self.assertTrue(regla.startswith("Protagonista: Zoe (mujer)."))
        self.assertEqual(perfil.contexto, f"{regla} GLOBAL. Juego de prueba.")
        self.assertNotIn("REGLA MASCULINA", perfil.contexto)
        self.assertEqual(perfil.huella_legacy, huella_contexto("REGLA MASCULINA. GLOBAL. Juego de prueba."))
        self.assertNotEqual(perfil.huella(), perfil.huella_legacy)
        self.assertIn("ficha de personajes", perfil.resumen())
        self.assertEqual(config.ruta_personajes("juego_x"), self.carpeta / "personajes.json")

    def test_con_ficha_hombre(self):
        self._guardar_ficha("hombre", prota="Carlos")
        perfil = config.cargar_perfil("juego_x", auto_crear=False)
        self.assertTrue(perfil.contexto.startswith("Protagonista: Carlos (hombre)."))
        self.assertTrue(perfil.contexto.endswith("GLOBAL. Juego de prueba."))
        self.assertNotIn("REGLA MASCULINA", perfil.contexto)

    def test_con_ficha_protagonista_desconocido_avisa_y_no_fuerza_genero(self):
        self._guardar_ficha("desconocido")
        with self.assertLogs("traductor.config", level="WARNING") as registro:
            perfil = config.cargar_perfil("juego_x", auto_crear=False)
        self.assertEqual(perfil.contexto, "GLOBAL. Juego de prueba.")
        self.assertTrue(any("Revisa workspace/juego_x/personajes.json: falta el género del protagonista" in m
                            for m in registro.output))

    def test_lineas_sin_ficha_tambien_en_el_contexto_del_juego(self):
        (self.carpeta / "contexto.txt").write_text("@sin_ficha: SOLO SIN FICHA.\nJuego.\n", encoding="utf-8")
        self.assertEqual(config.cargar_perfil("juego_x", auto_crear=False).contexto,
                         "REGLA MASCULINA. GLOBAL. SOLO SIN FICHA. Juego.")
        self._guardar_ficha("mujer")
        self.assertNotIn("SOLO SIN FICHA", config.cargar_perfil("juego_x", auto_crear=False).contexto)


class TestPerfilNuevo(_ConWorkspaceTemporal):
    def test_sin_ruta_crea_ficha_plantilla_con_protagonista_desconocido(self):
        perfil = config.cargar_perfil("Juego Nuevo", auto_crear=True)
        carpeta = self.workspace / "juego_nuevo"
        ficha = FichaPersonajes.cargar(carpeta / "personajes.json")
        self.assertIsNotNone(ficha)
        self.assertEqual(ficha.protagonista().nombre, "Protagonista")
        self.assertEqual(ficha.protagonista().genero, "desconocido")
        contexto_txt = (carpeta / "contexto.txt").read_text(encoding="utf-8")
        self.assertNotIn("Hombre por defecto", contexto_txt)
        self.assertNotIn("masculino", contexto_txt)
        self.assertNotIn("REGLA MASCULINA", perfil.contexto)

    def test_con_ruta_usa_el_analizador(self):
        falso = _analizador_falso(_ficha("mujer", prota="Rina"))
        ruta = self._juego_rpgmaker()
        with mock.patch.dict(sys.modules, {"traductor.analizador": falso}):
            perfil = config.cargar_perfil("Mi Juego", ruta_juego=ruta, auto_crear=True)
        falso.analizar_y_guardar.assert_called_once_with("mi_juego", ruta, usar_ia=False)
        self.assertEqual(perfil.personajes.protagonista().etiqueta(), "Rina (mujer)")
        self.assertTrue(perfil.contexto.startswith("Protagonista: Rina (mujer)."))
        self.assertIn("Título del juego: Mi Juego", perfil.contexto)

    def test_analizador_que_falla_deja_plantilla_con_el_actor_1(self):
        falso = _analizador_falso(error=RuntimeError("roto"))
        with mock.patch.dict(sys.modules, {"traductor.analizador": falso}), \
                self.assertLogs("traductor.config", level="WARNING"):
            perfil = config.cargar_perfil("Mi Juego", ruta_juego=self._juego_rpgmaker("Rina"), auto_crear=True)
        prota = perfil.personajes.protagonista()
        self.assertEqual((prota.nombre, prota.genero, prota.confirmado), ("Rina", "desconocido", False))

    def test_sin_analizador_instalado_deja_plantilla(self):
        with mock.patch.dict(sys.modules, {"traductor.analizador": None}):
            perfil = config.cargar_perfil("Mi Juego", ruta_juego=self._juego_rpgmaker(), auto_crear=True)
        self.assertEqual(perfil.personajes.protagonista().genero, "desconocido")

    def test_flags_analizar_y_usar_ia(self):
        falso = _analizador_falso(_ficha("hombre"))
        with mock.patch.dict(sys.modules, {"traductor.analizador": falso}):
            config.cargar_perfil("Juego A", ruta_juego=self._juego_rpgmaker(), analizar=False)
            falso.analizar_y_guardar.assert_not_called()
            config.cargar_perfil("Juego B", ruta_juego=self.tmp / "MiJuego", usar_ia=True)
        falso.analizar_y_guardar.assert_called_once_with("juego_b", self.tmp / "MiJuego", usar_ia=True)
        self.assertTrue((self.workspace / "juego_a" / "personajes.json").exists())

    def test_carpeta_existente_sin_ruta_no_cambia_de_modo(self):
        config.inicializar_perfil_nuevo("juego_x")
        self.assertFalse((self.carpeta / "personajes.json").exists())
        self.assertIsNone(config.cargar_perfil("juego_x", auto_crear=False).personajes)


# --------------------------------------------------------------------------- Traductor
class _BaseTraductor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _traductor(self, perfil: Perfil, **kw) -> OllamaTranslator:
        t = OllamaTranslator(model_name=MODELO, perfil=perfil, ruta_cache=self.tmp / "cache.json", **kw)
        self.addCleanup(t.cerrar)
        return t

    @staticmethod
    def _perfil(genero_prota: str = "mujer", prota: str = "Zoe", huella_legacy: str | None = None) -> Perfil:
        legacy = huella_contexto("ANTIGUO") if huella_legacy is None else huella_legacy
        return Perfil(juego="prueba", contexto="CTX", personajes=_ficha(genero_prota, prota), huella_legacy=legacy)

    @staticmethod
    def _prompt(t: OllamaTranslator, llamada: int = -1) -> str:
        return t._generar.call_args_list[llamada][0][0]


class TestTraductorConFicha(_BaseTraductor):
    def test_prompt_con_personajes_concordancia_y_clave_distinta(self):
        t = self._traductor(self._perfil())
        t._generar = mock.MagicMock(return_value="Estoy cansado.")
        info = InfoLinea(hablante="Ana")
        self.assertEqual(t.translate("I'm so tired.", info=info), "Estoy cansada.")
        prompt = self._prompt(t)
        self.assertIn("CONTEXTO DEL JUEGO: CTX PERSONAJES: Habla Ana (mujer).", prompt)
        clave_con, clave_sin = t._clave_de("I'm so tired.", info), t._clave_de("I'm so tired.")
        self.assertNotEqual(clave_con, clave_sin)
        self.assertEqual(clave_sin, t._clave("I'm so tired.", []))
        self.assertEqual(t.cache.get(clave_con), "Estoy cansada.")
        self.assertIsNone(t.cache.get(clave_sin))
        # La misma frase sin saber quién habla: otra clave y sin PERSONAJES en el prompt
        self.assertEqual(t.translate("I'm so tired."), "Estoy cansado.")
        self.assertNotIn("PERSONAJES", self._prompt(t))
        self.assertEqual(t._generar.call_count, 2)

    def test_concordancia_por_codigo_y_por_opcion(self):
        t = self._traductor(self._perfil("mujer"))
        t._generar = mock.MagicMock(return_value="Estoy cansada.")
        self.assertEqual(t.translate("I'm so tired.", info=InfoLinea(codigo="BoFrOp")), "Estoy cansado.")
        t._generar = mock.MagicMock(return_value="Estoy listo.")
        self.assertEqual(t.translate("I'm ready.", info=InfoLinea(es_opcion=True)), "Estoy lista.")
        self.assertIn("Habla el protagonista, Zoe (mujer).", self._prompt(t))

    def test_pensamiento_entre_parentesis_es_del_protagonista(self):
        t = self._traductor(self._perfil("mujer"))
        t._generar = mock.MagicMock(return_value="(¿Estoy equivocado?)")
        self.assertEqual(t.translate("(Am I wrong?)"), "(¿Estoy equivocada?)")
        self.assertIn("PERSONAJES: Es un pensamiento de Zoe (mujer).", self._prompt(t))

    def test_historial_lleva_quien_habla(self):
        t = self._traductor(self._perfil(), usar_historial=True)
        t._generar = mock.MagicMock(side_effect=["Hoy estoy muy cansado.", "Vámonos ya."])
        t.translate("I am really tired today.", info=InfoLinea(hablante="Ana"))
        self.assertEqual(list(t.historial), ["[Ana: I am really tired today. -> Hoy estoy muy cansada.]"])
        t.translate("Let's go now.")
        self.assertIn("CONVERSACIÓN PREVIA: [Ana: I am really tired today. -> Hoy estoy muy cansada.]",
                      self._prompt(t))

    def test_documento_multilinea_hereda_el_contexto(self):
        t = self._traductor(self._perfil())
        t._generar = mock.MagicMock(side_effect=lambda prompt, *a, **kw: (
            "Estoy cansado." if "tired" in prompt.split("### Input:")[1] else "Estoy listo."))
        res = t.translate("I'm so tired.\n────\nI'm ready.", info=InfoLinea(hablante="Ana"))
        self.assertEqual(res, "Estoy cansada.\n────\nEstoy lista.")
        self.assertEqual(t._generar.call_count, 2)
        for i in range(2):
            self.assertIn("PERSONAJES: Habla Ana (mujer).", self._prompt(t, i))

    def test_lote_turbo_con_hablantes(self):
        t = self._traductor(self._perfil(), tam_lote=20)
        # Respuesta con los géneros cambiados a propósito: la concordancia los arregla
        t._generar = mock.MagicMock(return_value="1. Estoy cansada.\n2. Estoy cansado.\n3. Hola.")
        textos = ["I'm so tired.", "I'm so tired.", "Hello there.", "I'm so tired."]
        infos = [InfoLinea(hablante="Bob"), InfoLinea(hablante="Ana"), None, InfoLinea(codigo="BoFrOp")]
        res = t.traducir_textos(textos, infos)
        self.assertEqual(res, ["Estoy cansado.", "Estoy cansada.", "Hola.", "Estoy cansado."])
        self.assertEqual(t._generar.call_count, 1)  # (texto, firma) deduplicado: 3 frases en el lote
        prompt = self._prompt(t)
        self.assertIn("1. I'm so tired.\n2. I'm so tired.\n3. Hello there.", prompt)
        self.assertIn("PERSONAJES POR FRASE: 1) Habla Bob (hombre).", prompt)
        self.assertIn("; 2) Habla Ana (mujer).", prompt)
        self.assertNotIn("3)", prompt)
        # Cada frase queda en caché con su propia firma
        self.assertEqual(t.cache.get(t._clave_de("I'm so tired.", InfoLinea(hablante="Ana"))), "Estoy cansada.")
        self.assertEqual(t.cache.get(t._clave_de("I'm so tired.", InfoLinea(hablante="Bob"))), "Estoy cansado.")

    def test_lote_retraduce_la_frase_que_pierde_un_nombre(self):
        t = self._traductor(self._perfil(), tam_lote=20)
        t._generar = mock.MagicMock(side_effect=["1. Gracias.\n2. Hola.", "Gracias, Ana."])
        res = t.traducir_textos(["Thanks, Ana.", "Hello there."], [None, None])
        self.assertEqual(res, ["Gracias, Ana.", "Hola."])
        self.assertEqual(t._generar.call_count, 2)   # el lote + la frase que perdió a Ana, sola

    def test_info_desalineada_se_ignora(self):
        t = self._traductor(self._perfil())
        t._generar = mock.MagicMock(return_value="Estoy cansado.")
        with self.assertLogs("traductor.ollama", level="WARNING"):
            res = t.traducir_textos(["I'm so tired."], [InfoLinea(hablante="Ana"), None])
        self.assertEqual(res, ["Estoy cansado."])
        self.assertNotIn("PERSONAJES", self._prompt(t))

    def test_traducir_validado_acepta_info(self):
        t = self._traductor(self._perfil())
        t._generar = mock.MagicMock(return_value="Estoy cansado.")
        self.assertEqual(t.traducir_validado("I'm so tired.", info=InfoLinea(hablante="Ana")), "Estoy cansada.")


class TestCacheAntigua(_BaseTraductor):
    def _sembrar(self, t: OllamaTranslator, texto: str, traduccion: str) -> None:
        t.cache.set(t._clave(texto, t.perfil.terminos_para(texto), "", t.perfil.huella_legacy), traduccion)

    def test_reutiliza_si_no_hay_marcas_de_genero(self):
        t = self._traductor(self._perfil())
        t._generar = mock.MagicMock()
        self._sembrar(t, "Let's go to the beach.", "Vamos a la playa.")
        self.assertEqual(t.translate("Let's go to the beach."), "Vamos a la playa.")
        t._generar.assert_not_called()
        self.assertEqual(t.cache.get(t._clave_de("Let's go to the beach.")), "Vamos a la playa.")
        self.assertEqual(t.estadisticas["cache_antigua"], 1)

    def test_reutiliza_corrigiendo_al_hablante_conocido(self):
        t = self._traductor(self._perfil())
        t._generar = mock.MagicMock()
        self._sembrar(t, "I'm so tired.", "Estoy cansado.")
        self.assertEqual(t.translate("I'm so tired.", info=InfoLinea(hablante="Ana")), "Estoy cansada.")
        t._generar.assert_not_called()

    def test_rechaza_masculino_si_la_protagonista_es_mujer(self):
        t = self._traductor(self._perfil("mujer"))
        t._generar = mock.MagicMock(return_value="¿O me equivoco?")
        self._sembrar(t, "Or am I wrong?", "¿O estoy equivocado?")
        self.assertEqual(t.translate("Or am I wrong?"), "¿O me equivoco?")
        t._generar.assert_called_once()
        self.assertEqual(t.estadisticas["cache_antigua_descartada"], 1)

    def test_rechaza_si_contradice_a_quien_se_habla(self):
        t = self._traductor(self._perfil("mujer"))
        t._generar = mock.MagicMock(return_value="¿Estás segura?")
        self._sembrar(t, "Are you sure?", "¿Estás seguro?")
        # Habla Ana (mujer) y probablemente se dirige a Zoe (mujer): "seguro" no vale
        self.assertEqual(t.translate("Are you sure?", info=InfoLinea(hablante="Ana")), "¿Estás segura?")
        t._generar.assert_called_once()

    def test_con_protagonista_hombre_se_reutiliza_el_masculino(self):
        t = self._traductor(self._perfil("hombre", prota="1Hero"))
        t._generar = mock.MagicMock()
        self._sembrar(t, "Or am I wrong?", "¿O estoy equivocado?")
        self.assertEqual(t.translate("Or am I wrong?"), "¿O estoy equivocado?")
        t._generar.assert_not_called()

    def test_sin_huella_legacy_no_se_busca_la_clave_antigua(self):
        t = self._traductor(self._perfil(huella_legacy=""))
        t._generar = mock.MagicMock(return_value="Vamos ya.")
        t.cache.set(t._clave("Let's go.", [], "", huella_contexto("ANTIGUO")), "Vámonos.")
        self.assertEqual(t.translate("Let's go."), "Vamos ya.")

    def test_lote_reutiliza_y_rechaza_cache_antigua(self):
        t = self._traductor(self._perfil("mujer"), tam_lote=20)
        self._sembrar(t, "Let's go to the beach.", "Vamos a la playa.")
        self._sembrar(t, "Or am I wrong?", "¿O estoy equivocado?")
        t._generar = mock.MagicMock(return_value="¿O me equivoco?")
        res = t.traducir_textos(["Let's go to the beach.", "Or am I wrong?"])
        self.assertEqual(res, ["Vamos a la playa.", "¿O me equivoco?"])
        self.assertEqual(t._generar.call_count, 1)


class TestSinFichaComoSiempre(_BaseTraductor):
    def test_translate_sin_ficha_ni_info_igual_que_antes(self):
        """Proxy de Unity: sin personajes.json no se resuelve nada y el prompt/clave son los de siempre."""
        t = self._traductor(Perfil(contexto="CTX"))
        t._generar = mock.MagicMock(return_value="Hola, amigo mío.")
        texto = "Hello there, my friend."
        with mock.patch("traductor.ollama.resolver_linea", side_effect=AssertionError("no debe llamarse")), \
                mock.patch("traductor.ollama.aplicar_concordancia", side_effect=AssertionError("no debe llamarse")):
            self.assertEqual(t.translate(texto), "Hola, amigo mío.")
            self.assertEqual(t.translate(texto, info=InfoLinea(hablante="Ana")), "Hola, amigo mío.")
        self.assertEqual(t._generar.call_count, 1)  # la segunda vez sale de la caché
        esperado = prompts.formatear(prompts.construir_instruccion(prompts.INSTRUCCION, "CTX", [], []), texto)
        self.assertEqual(self._prompt(t, 0), esperado)
        self.assertEqual(t.cache.get(_sha1(f"{MODELO}\x00{huella_contexto('CTX')}\x00\x00{texto}")),
                         "Hola, amigo mío.")

    def test_lote_sin_ficha_igual_que_antes(self):
        t = self._traductor(Perfil(contexto="CTX"), tam_lote=20)
        t._generar = mock.MagicMock(return_value="1. Uno.\n2. Dos.")
        self.assertEqual(t.batch_translate(["One thing.", "Two things.", "One thing."]), ["Uno.", "Dos.", "Uno."])
        self.assertNotIn("PERSONAJES", self._prompt(t))


# --------------------------------------------------------------------------- texto.py
class TestTextoConFicha(unittest.TestCase):
    def test_corregir_genero_v21_con_ficha(self):
        # Mi Juego: 'He' es el héroe (hombre), no Laura como en Otro Juego
        nora = FichaPersonajes(personajes=[Personaje("1Hero", "hombre", "protagonista", codigos=["He"]),
                                            Personaje("Ana", "mujer", "principal", codigos=["Al"]),
                                            Personaje("Rara", "desconocido", "secundario", codigos=["Ra"])])
        self.assertEqual(corregir_genero_hablante_v21("Estoy ocupada.", "HeFrOp.", ficha=nora), "Estoy ocupado.")
        self.assertEqual(corregir_genero_hablante_v21("Estoy cansado.", "Al,Fr,Op.", ficha=nora), "Estoy cansada.")
        # Código que no está en la ficha o de género desconocido: no se toca
        self.assertEqual(corregir_genero_hablante_v21("Estoy cansado.", "ChFrOp.", ficha=nora), "Estoy cansado.")
        self.assertEqual(corregir_genero_hablante_v21("Estoy cansado.", "RaFrOp.", ficha=nora), "Estoy cansado.")
        # Sin ficha: los códigos de las correcciones locales (aquí, las de prueba: 'He' es mujer)
        from traductor import texto as modulo_texto
        prueba = Path(__file__).parent / "datos" / "correcciones_locales.prueba.json"
        with mock.patch.object(modulo_texto, "ARCHIVO_CORRECCIONES_LOCALES", prueba):
            modulo_texto.correcciones_locales.cache_clear()
            try:
                self.assertEqual(corregir_genero_hablante_v21("Estoy ocupado.", "HeFrOp."), "Estoy ocupada.")
            finally:
                modulo_texto.correcciones_locales.cache_clear()

    def test_eco_de_la_ficha_en_la_respuesta(self):
        for eco in ("PERSONAJES: Habla Ana (mujer). Hola.", "Concuerda el género ('yo' = Ana). Hola.",
                    "Probablemente se dirige a Zoe (mujer). Hola.", "Es un pensamiento de Zoe (mujer). Hola.",
                    "PERSONAJES POR FRASE: 1) Habla Bob (hombre). Hola."):
            with self.subTest(eco=eco):
                self.assertIn("eco_prompt", evaluar_traduccion("Hello there, my friend.", eco))
        # Traducciones normales que se parecen: no son eco
        for normal, original in (("Personajes: 5", "Characters: 5"),
                                 ("Probablemente se dirige a la estación.", "He's probably heading to the station."),
                                 ("Es un pensamiento del pasado.", "It's a thought from the past.")):
            with self.subTest(normal=normal):
                self.assertNotIn("eco_prompt", evaluar_traduccion(original, normal))


# --------------------------------------------------------------------------- Herramientas
def _cargar_configurador():
    ruta = config.RAIZ / "herramientas_extra" / "configurar_perfil_juego.py"
    spec = importlib.util.spec_from_file_location("configurar_perfil_juego_prueba", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestConfigurarPerfilJuego(_ConWorkspaceTemporal):
    def setUp(self):
        super().setUp()
        self.cpj = _cargar_configurador()

    def test_actualizar_protagonista_crea_y_confirma(self):
        ficha = self.cpj.actualizar_protagonista(self.carpeta, "Zoe", "m")
        prota = ficha.protagonista()
        self.assertEqual((prota.nombre, prota.genero, prota.confirmado), ("Zoe", "mujer", True))
        self.assertEqual(FichaPersonajes.cargar(self.carpeta / "personajes.json").protagonista().genero, "mujer")
        self.assertIn("Protagonista: Zoe (mujer)", self.cpj.describir_ficha(self.carpeta))

    def test_actualizar_protagonista_renombra_y_cambia_de_protagonista(self):
        FichaPersonajes(personajes=[Personaje("1Hero", "desconocido", "protagonista"),
                                    Personaje("Ana", "mujer", "principal")]).guardar(self.carpeta / "personajes.json")
        # Solo el género: se actualiza el protagonista que ya había
        self.assertEqual(self.cpj.actualizar_protagonista(self.carpeta, None, "hombre").protagonista().etiqueta(),
                         "1Hero (hombre)")
        # Nombre nuevo: se renombra y el nombre anterior queda como alias
        prota = self.cpj.actualizar_protagonista(self.carpeta, "William", None).protagonista()
        self.assertEqual((prota.nombre, prota.alias, prota.genero), ("William", ["1Hero"], "hombre"))
        # Nombre de otro personaje: ese pasa a ser el protagonista
        ficha = self.cpj.actualizar_protagonista(self.carpeta, "Ana", None)
        self.assertEqual(ficha.protagonista().nombre, "Ana")
        self.assertEqual(ficha.buscar("William").rol, "principal")

    def test_sin_genero_no_se_confirma(self):
        prota = self.cpj.actualizar_protagonista(self.carpeta, "Zoe", None).protagonista()
        self.assertEqual((prota.genero, prota.confirmado), ("desconocido", False))

    def test_configurar_perfil_y_listar(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            self.cpj.configurar_perfil("juego_x", protagonista="Zoe", genero="mujer")
            self.cpj.listar_perfiles()
        self.assertIn("- Protagonista: Zoe (Género: Mujer)", (self.carpeta / "contexto.txt").read_text(encoding="utf-8"))
        self.assertTrue(config.cargar_perfil("juego_x", auto_crear=False).contexto.startswith("Protagonista: Zoe (mujer)."))
        self.assertIn("Protagonista: Zoe (mujer)", salida.getvalue())


class TestTraducirJuego(_ConWorkspaceTemporal):
    def setUp(self):
        super().setUp()
        self.mod = importlib.import_module("1_traducir_juego")

    def test_analizar_ficha_sin_analizador_avisa(self):
        with mock.patch.dict(sys.modules, {"traductor.analizador": None}), \
                self.assertLogs(self.mod.log, level="WARNING"):
            self.assertFalse(self.mod.analizar_ficha_personajes("juego_x", self.tmp))

    def test_analizar_ficha_con_analizador(self):
        falso = _analizador_falso(_ficha("mujer"))
        with mock.patch.dict(sys.modules, {"traductor.analizador": falso}), \
                self.assertLogs(self.mod.log, level="WARNING") as registro:
            self.assertTrue(self.mod.analizar_ficha_personajes("juego_x", self.tmp, usar_ia=True))
        falso.analizar_y_guardar.assert_called_once_with("juego_x", self.tmp, usar_ia=True)
        self.assertTrue(any("aviso de prueba" in m for m in registro.output))

    def test_mostrar_ficha_avisa_de_pendientes(self):
        ficha = FichaPersonajes(personajes=[Personaje("Rina", "desconocido", "protagonista")])
        with self.assertLogs(self.mod.log, level="WARNING") as registro:
            self.mod.mostrar_ficha_personajes(Perfil(juego="juego_x", personajes=ficha))
        self.assertTrue(any("Rina (desconocido)" in m for m in registro.output))

    def _injector(self, **kw):
        with mock.patch.object(self.mod, "EstadoProgreso"):
            injector = self.mod.GameEngineInjector(self.tmp / "MiJuego", modelo=MODELO, juego="juego_x",
                                                   abrir_monitor=False, **kw)
        self.addCleanup(injector.translator.cerrar)
        return injector

    def test_injector_analiza_si_falta_la_ficha(self):
        falso = _analizador_falso(_ficha("mujer"))
        with mock.patch.dict(sys.modules, {"traductor.analizador": falso}):
            injector = self._injector()
        falso.analizar_y_guardar.assert_called_once()
        self.assertIsNotNone(injector.perfil.personajes)
        self.assertIs(injector.translator.perfil, injector.perfil)
        self.assertTrue(injector.perfil.contexto.startswith("Protagonista: Zoe (mujer)."))

    def test_injector_sin_analisis(self):
        falso = _analizador_falso(_ficha("mujer"))
        with mock.patch.dict(sys.modules, {"traductor.analizador": falso}):
            injector = self._injector(analizar_personajes=False)
        falso.analizar_y_guardar.assert_not_called()
        self.assertIsNone(injector.perfil.personajes)

    def test_flags_de_linea_de_comandos(self):
        argv = ["1_traducir_juego.py", "--ruta", str(self.tmp), "--sin-analisis", "--analizar-ia"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(self.mod, "GameEngineInjector") as gei, \
                mock.patch.object(self.mod, "configurar_logging"):
            self.mod.main()
        kwargs = gei.call_args.kwargs
        self.assertFalse(kwargs["analizar_personajes"])
        self.assertTrue(kwargs["analizar_con_ia"])


if __name__ == "__main__":
    unittest.main()
