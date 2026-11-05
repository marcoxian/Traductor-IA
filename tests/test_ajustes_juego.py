"""Modelo por juego (Q2): workspace/<juego>/ajustes.json decide el modelo si no se pide otro."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from traductor import config


class TestModeloPorJuego(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        parche = mock.patch.object(config, "DIR_WORKSPACE", self.workspace)
        parche.start()
        self.addCleanup(parche.stop)
        (self.workspace / "juego_x").mkdir()

    def test_orden_pedido_ajustes_automatico(self):
        # sin nada guardado: automático (juego_x no tiene ficha de personajes -> el modelo para juegos sin ficha)
        self.assertEqual(config.modelo_para_juego("juego_x"), config.MODELO_SIN_FICHA)
        config.guardar_ajustes_juego("juego_x", modelo="IA_Traductora_v3")
        self.assertEqual(config.modelo_para_juego("juego_x"), "IA_Traductora_v3")       # elegido a mano
        self.assertEqual(config.modelo_para_juego("juego_x", "IA_Traductora"), "IA_Traductora")  # --modelo
        self.assertEqual(config.modelo_para_juego(None), config.MODELO_SIN_FICHA)

    def test_automatico(self):
        """V2: con ficha de personajes, v4; sin ficha, v1. "auto" (o la etiqueta del Centro de Control) en
        ajustes.json o en --modelo vuelve a la elección automática."""
        self.assertEqual(config.modelo_automatico("juego_x")[0], config.MODELO_SIN_FICHA)
        (self.workspace / "juego_x" / "personajes.json").write_text("{}", encoding="utf-8")
        modelo, motivo = config.modelo_automatico("juego_x")
        self.assertEqual(modelo, config.MODELO_CON_FICHA)
        self.assertIn("ficha", motivo)
        config.guardar_ajustes_juego("juego_x", modelo="IA_Traductora_v2")
        self.assertEqual(config.modelo_para_juego("juego_x"), "IA_Traductora_v2")
        for auto in ("auto", config.ETIQUETA_AUTOMATICO, "Automático"):
            self.assertEqual(config.modelo_para_juego("juego_x", auto), config.MODELO_CON_FICHA, auto)
        config.guardar_ajustes_juego("juego_x", modelo=config.MODELO_AUTOMATICO)
        self.assertEqual(config.modelo_para_juego("juego_x"), config.MODELO_CON_FICHA)
        self.assertTrue(config.es_automatico(None) and config.es_automatico(""))
        self.assertFalse(config.es_automatico("IA_Traductora"))

    def test_guardar_conserva_lo_demas_y_no_crea_perfiles(self):
        ruta = self.workspace / "juego_x" / "ajustes.json"
        ruta.write_text(json.dumps({"modelo": "IA_Traductora_v2", "otro": 1}), encoding="utf-8")
        self.assertEqual(config.guardar_ajustes_juego("juego_x", modelo="IA_Traductora_v3"), ruta)
        self.assertEqual(json.loads(ruta.read_text(encoding="utf-8")), {"modelo": "IA_Traductora_v3", "otro": 1})
        self.assertIsNone(config.guardar_ajustes_juego("juego_que_no_existe", modelo="IA_Traductora_v3"))
        self.assertIsNone(config.guardar_ajustes_juego(None, modelo="IA_Traductora_v3"))
        self.assertFalse((self.workspace / "juego_que_no_existe").exists())
        self.assertFalse((self.workspace / "_comun").exists())


if __name__ == "__main__":
    unittest.main()
