"""Pruebas del sistema de diagnóstico y depuración (herramientas_extra/diagnostico.py)."""
import unittest
from pathlib import Path

from herramientas_extra.diagnostico import (
    diagnosticar_gpu,
    diagnosticar_paquetes,
    generar_reporte_completo,
    copiar_al_portapapeles,
    guardar_reporte,
    RAIZ,
)


class TestDiagnostico(unittest.TestCase):
    def test_diagnosticar_gpu_estructura(self):
        gpu = diagnosticar_gpu()
        self.assertIn("disponible", gpu)
        self.assertIn("nombre", gpu)
        self.assertIn("vram_total", gpu)
        self.assertIn("vram_libre", gpu)

    def test_diagnosticar_paquetes_estructura(self):
        paquetes = diagnosticar_paquetes()
        self.assertIn("tkinter", paquetes)
        self.assertIn("Pillow (PIL)", paquetes)

    def test_generar_reporte_contiene_secciones_clave(self):
        reporte = generar_reporte_completo()
        self.assertIn("REPORTE DE DIAGNÓSTICO", reporte)
        self.assertIn("[1] SISTEMA OPERATIVO Y ENTORNO PYTHON", reporte)
        self.assertIn("[2] HARDWARE Y GPU", reporte)
        self.assertIn("[3] SERVICIO DE IA (OLLAMA)", reporte)
        self.assertIn("[7] REGISTRO DE ERRORES RECIENTES", reporte)

    def test_copiar_al_portapapeles_no_lanza_excepcion(self):
        # Debe ejecutarse de forma segura sin excepciones no controladas
        resultado = copiar_al_portapapeles("Prueba unitaria Traductor IA")
        self.assertIsInstance(resultado, bool)

    def test_guardar_reporte_crea_archivos(self):
        texto_prueba = "REPORTE TEST UNITARIO"
        p_root, p_ws = guardar_reporte(texto_prueba)
        self.assertTrue(p_root.exists())
        self.assertTrue(p_ws.exists())
        self.assertEqual(p_root.read_text(encoding="utf-8"), texto_prueba)

    def test_archivos_bat_existen(self):
        self.assertTrue((RAIZ / "diagnostico.bat").exists())
        self.assertTrue((RAIZ / "iniciar_modo_depuracion.bat").exists())
        self.assertTrue((RAIZ / "consola_cmd.bat").exists())
