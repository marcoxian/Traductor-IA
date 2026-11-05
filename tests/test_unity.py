"""Tests para inyección de motor Unity y servidor proxy de traducción."""
import configparser
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from traductor.motores.unity import inyectar_unity
import ollama_proxy


class TestUnityMotor(unittest.TestCase):
    def test_inyectar_unity_configuracion_limpia(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ruta_juego = Path(tmpdir)
            config_path = inyectar_unity(ruta_juego, modelo="IA_Traductora", puerto_proxy=11435)

            self.assertTrue(config_path.exists())
            cfg = configparser.ConfigParser(strict=True)
            cfg.read(config_path, encoding="utf-8")

            # Comprobar secciones y valores clave
            self.assertEqual(cfg.get("Service", "Endpoint"), "CustomTranslate")
            self.assertEqual(cfg.get("Custom", "Url"), "http://127.0.0.1:11435/translate")
            self.assertEqual(cfg.get("Custom", "DisableSpamChecks"), "True")
            self.assertEqual(cfg.get("General", "Language"), "es")
            self.assertEqual(cfg.get("General", "FromLanguage"), "en")
            self.assertEqual(cfg.get("Behaviour", "MinDialogueChars"), "1")
            self.assertEqual(cfg.get("Behaviour", "EnableBatching"), "False")
            self.assertFalse(cfg.has_section("CustomHTTP"))

    def test_proxy_endpoints(self):
        import json
        import threading
        import time
        import urllib.request

        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Nueva Partida"

        servidor = ollama_proxy.iniciar_servidor_proxy(mock_translator, puerto=11442)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        time.sleep(0.3)

        try:
            with urllib.request.urlopen("http://127.0.0.1:11442/health", timeout=3) as resp_health:
                self.assertEqual(resp_health.status, 200)
                datos_health = json.loads(resp_health.read().decode("utf-8"))
                self.assertEqual(datos_health.get("status"), "ok")

            with urllib.request.urlopen(
                "http://127.0.0.1:11442/translate?from=en&to=es&text=New%20Game", timeout=3
            ) as resp_trans:
                self.assertEqual(resp_trans.status, 200)
                self.assertEqual(resp_trans.read().decode("utf-8"), "Nueva Partida")
            mock_translator.translate.assert_called_once_with("New Game", info=None)

            # Si el modelo devuelve el texto en inglés sin traducir, el proxy responde 503 (no 200)
            import urllib.error
            mock_translator.translate.return_value = "Cute Songbird"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(
                    "http://127.0.0.1:11442/translate?from=en&to=es&text=Cute%20Songbird", timeout=3
                )
            self.assertEqual(ctx.exception.code, 503)
        finally:
            servidor.shutdown()
            servidor.server_close()


if __name__ == "__main__":
    unittest.main()
