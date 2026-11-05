"""U2: cola en inglés pegada sin espacio al final de la traducción ("POZOConstellation name (optional)").

Casos como los del corpus de KDE y los que repiten los modelos en rótulos en mayúsculas."""
import unittest

from traductor.texto import quitar_cola_pegada


class TestColaPegada(unittest.TestCase):
    def test_se_quita(self):
        casos = {
            ("MAP ROLL", "ROLLO DE MAPAConstellation name (optional)"): "ROLLO DE MAPA",
            ("STAR SKINS", "PIEL DE ESTRELLASConstellation name"): "PIEL DE ESTRELLAS",
            ("LEFT TREE", "ÁRBOL IZQUIERDOConstellation name (optional)"): "ÁRBOL IZQUIERDO",
            ("SPIDER", "ARAÑAConstellation name (optional)"): "ARAÑA",
            ("Export highlighted document to HTML", "Exportar documento resaltado a HTMLName"):
                "Exportar documento resaltado a HTML",
            ("Geolocation IP", "Geolocalización mediante IPComment"): "Geolocalización mediante IP",
            ("Unable to get statement type", "No se ha podido obtener el tipo de sentenciaQOCIResult"):
                "No se ha podido obtener el tipo de sentencia",
            ("Circuit - NPN Transistor", "Circuito - Transmisor NPNStencils"): "Circuito - Transmisor NPN",
            ("SQL", "SQLLanguage"): "SQL",
            ("BeOS", "BeOSComment"): "BeOS",
            ("Lisu", "LisuKCharselect unicode block name"): "Lisu",
            ("Malayalam", "Malayalam (malabar)KCharselect unicode block name"): "Malayalam (malabar)",
            ("Audex", "AudexGenericName"): "Audex",
            ("internal general entity reference not allowed in DTD", "no permitida en la DTDQXml"):
                "no permitida en la DTD",
            ("PgDown", "AvPágQShortcut"): "AvPág",
            ("zeptopascal; zeptopascals; zPa", "zeptopascal; zeptopascales; zPaamount in units (real)"):
                "zeptopascal; zeptopascales; zPa",
        }
        for (en, es), esperado in casos.items():
            self.assertEqual(quitar_cola_pegada(en, es), esperado, es)

    def test_no_se_toca(self):
        for en, es in (("Buy a PlayStation", "Compra una PlayStation"),
                       ("I want an iPhone", "Quiero un iPhone"),
                       ("Let's go to McDonald", "Vamos a McDonald"),
                       ("Call the UN Tomorrow", "Llama a la ONU Mañana"),          # con espacio: es otra palabra
                       ("Welcome to MasterChef!", "¡Bienvenido a MasterChef!"),
                       ("Open the door.", "Abre la puerta."),
                       ("Name", "Name"),                                         # nada que quitar: quedaría vacío
                       ("", ""), ("DeShawn said", "dijo DeShawn"),
                       # palabras pegadas a propósito (logros, etiquetas) y saltos de línea escritos
                       ("LuciaObsessed", "LuciaObsesionada"), ("HomeSweetHome", "#HogarDulceHogar"),
                       ("depthVariance", "varianzaProfundidad"), ("BestieBenefits", "BestieBeneficios"),
                       ("Mouse Wheel Up\\nClick Rollback Side", "Rueda del ratón hacia arriba\\nRetroceso"),
                       ("File\\nName", "Archivo\\nName"), ("General Store", "ALMACÉNGeneral")):
            self.assertEqual(quitar_cola_pegada(en, es), es, es)


if __name__ == "__main__":
    unittest.main()
