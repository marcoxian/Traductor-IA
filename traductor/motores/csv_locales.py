"""Inyector de traducciones para archivos CSV de localización (Godot y DKTools_Localization)."""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from ..csv_locales import analizar_cabecera, escribir_lineas, leer_lineas, limpiar_celda, partir, unir
from ..ollama import OllamaTranslator
from ..texto import (PATRON_CODIGOS, PATRON_NOMBRE_HABLANTE, PATRON_PREFIJO, reinsertar_saltos,
                    sanitizar, tiene_texto_visible)

log = logging.getLogger(__name__)


class InyectorCSV:
    """Traduce archivos CSV de localización celda por celda o en lotes."""

    def __init__(self, ruta_juego: Path, translator: OllamaTranslator, tam_bloque: int = 30):
        self.ruta_juego = ruta_juego
        self.translator = translator
        self.tam_bloque = tam_bloque

    def procesar(self) -> None:
        todos_csv = list(self.ruta_juego.glob("**/*.csv"))
        csv_files = [
            f for f in todos_csv
            if not f.name.endswith(".original") and not f.name.endswith(".tmp") and not f.name.endswith(".bak")
        ]

        if not csv_files:
            log.warning("No se encontraron archivos .csv de localización para traducir.")
            return

        for csv_file in csv_files:
            log.info("Procesando archivo CSV: %s...", csv_file.name)
            backup = csv_file.with_name(csv_file.name + ".original")
            if not backup.exists():
                shutil.copy2(csv_file, backup)
                log.info("Copia de seguridad creada: %s", backup.name)

            bom, orig_lines = leer_lineas(backup)
            if not orig_lines or not orig_lines[0].strip():
                continue

            delim, header, col = analizar_cabecera(orig_lines)
            if col is None:
                log.warning("No se encontró columna de inglés en %s (cabecera: %s). Se omite.",
                            csv_file.name, header[:6])
                continue

            log.info("Delimitador '%s' | Columna inglesa: '%s' (índice %d)", delim, header[col], col)

            _, cur_lines = leer_lineas(csv_file)
            if len(cur_lines) != len(orig_lines):
                log.warning("El archivo actual no tiene las mismas líneas que el original; se resetea.")
                cur_lines = list(orig_lines)

            total = len(orig_lines) - 1
            total_bloques = (total + self.tam_bloque - 1) // self.tam_bloque

            for num_bloque in range(total_bloques):
                inicio = 1 + num_bloque * self.tam_bloque
                fin = min(inicio + self.tam_bloque, len(orig_lines))
                cambiado = False

                indices: list[int] = []
                textos_a_traducir: list[str] = []
                prefijos: list[str] = []
                segmentos_lista: list[list[str]] = []

                for i in range(inicio, fin):
                    o_parts, _ = partir(orig_lines[i], delim)
                    if len(o_parts) <= col:
                        continue
                    orig_text = o_parts[col]

                    c_parts, _ = partir(cur_lines[i], delim)
                    if len(c_parts) == len(o_parts) and c_parts[col] != orig_text:
                        # Ya traducido previamente
                        continue

                    m_pre = PATRON_PREFIJO.match(orig_text)
                    prefix = m_pre.group(0) if m_pre else ""

                    # Traducir nombre de personaje en el prefijo si coincide con el glosario
                    if prefix:
                        def _traducir_nombre(m):
                            c_in = m.group(1) or ""
                            nombre = m.group(2)
                            c_out = m.group(3) or ""
                            for en, es in self.translator.perfil.glosario.items():
                                if nombre.lower() == en.lower():
                                    return f"\\N<{c_in}{es}{c_out}>"
                            return m.group(0)
                        prefix = PATRON_NOMBRE_HABLANTE.sub(_traducir_nombre, prefix)

                    cuerpo = orig_text[len(m_pre.group(0)) if m_pre else 0:]
                    sanitizado = sanitizar(cuerpo)
                    if not tiene_texto_visible(sanitizado):
                        continue

                    segments = re.split(r"\\n", sanitizado)
                    frase = re.sub(r" {2,}", " ", " ".join(s.strip() for s in segments)).strip()

                    indices.append(i)
                    textos_a_traducir.append(frase)
                    prefijos.append(prefix)
                    segmentos_lista.append(segments)

                if not textos_a_traducir:
                    continue

                traducciones = self.translator.traducir_textos(textos_a_traducir)

                for idx_cola, trad in enumerate(traducciones):
                    line_idx = indices[idx_cola]
                    frase_orig = textos_a_traducir[idx_cola]
                    prefix = prefijos[idx_cola]
                    segments = segmentos_lista[idx_cola]

                    trad_limpia = limpiar_celda(trad, delim, quitar_comillas=False).strip()
                    if not trad_limpia:
                        continue

                    trad_limpia = self.translator.perfil.restaurar_nombres(frase_orig, trad_limpia)
                    if len(segments) > 1:
                        trad_limpia = reinsertar_saltos(trad_limpia, segments)

                    final_text = prefix + trad_limpia
                    o_parts, cr = partir(orig_lines[line_idx], delim)
                    if final_text == o_parts[col]:
                        continue

                    o_parts[col] = final_text
                    cur_lines[line_idx] = unir(o_parts, delim, cr)
                    cambiado = True

                if cambiado:
                    escribir_lineas(csv_file, bom, cur_lines)

            log.info("Archivo CSV guardado al 100%%: %s", csv_file.name)
