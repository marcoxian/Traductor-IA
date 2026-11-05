"""Inyector de traducciones para archivos CSV de localización (Godot y DKTools_Localization)."""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from ..csv_locales import analizar_cabecera, escribir_lineas, leer_lineas, limpiar_celda, partir, unir
from ..nombres_hablantes import tabla_del_juego, traducir_nombre
from ..ollama import OllamaTranslator
from ..personajes import InfoLinea, limpiar_nombre
from ..texto import (PATRON_CODIGOS, PATRON_NOMBRE_HABLANTE, PATRON_PREFIJO, reinsertar_saltos,
                    sanitizar, tiene_texto_visible)
from .rpgmaker import hablante_de_caja, traductor_acepta_info

log = logging.getLogger(__name__)


def hablante_csv(celda: str) -> str | None:
    """Quién habla en una celda inglesa con caja de nombre al principio.

    '\\N<\\C[3]Ana\\C[0]>Hola' -> 'Ana'; '\\n<\\C[9]\\N[1]\\C[0]>Hola' -> '\\N[1]' (protagonista).
    None si no hay caja de nombre antes del texto visible.
    """
    if not celda or "<" not in celda:
        return None
    m = PATRON_NOMBRE_HABLANTE.search(celda)
    if m and not tiene_texto_visible(celda[:m.start()]):
        nombre = limpiar_nombre(m.group(2))
        if nombre:
            return nombre
    return hablante_de_caja(celda, solo_al_inicio=True)


def quitar_comillas_csv(celda: str) -> tuple[str, bool]:
    """'"\\N<Ana>Say ""hi""."' -> ('\\N<Ana>Say "hi".', True). Hay juegos que entrecomillan celdas como en un
    CSV normal, pero su lector no entiende comillas: con ellas delante no se reconoce la caja de nombre y el
    modelo la pierde. La traducción se escribe sin ellas (es lo que el jugador debe ver)."""
    if len(celda) >= 2 and celda[0] == '"' and celda[-1] == '"':
        return celda[1:-1].replace('""', '"'), True
    return celda, False


class InyectorCSV:
    """Traduce archivos CSV de localización celda por celda o en lotes."""

    def __init__(self, ruta_juego: Path, translator: OllamaTranslator, tam_bloque: int = 30,
                 reaprovechar_traduccion: bool = False):
        self.ruta_juego = ruta_juego
        self.translator = translator
        self.tam_bloque = tam_bloque
        # --solo-genero: las celdas ya traducidas se conservan salvo las que tienen marcas de género, un
        # sentido equivocado ("cofre" por pecho) o un fallo grave; esas se vuelven a pedir al modelo
        self.reaprovechar_traduccion = reaprovechar_traduccion
        self.conservadas = 0
        self.retraducidas = 0

    def _tabla_hablantes(self) -> tuple[dict[str, str], frozenset[str]]:
        return tabla_del_juego(getattr(getattr(self.translator, "perfil", None), "juego", None))

    @staticmethod
    def _frase_de_celda(celda: str) -> tuple[str, str, list[str]]:
        """(prefijo de códigos, frase en una línea, segmentos separados por "\\n" literal) de una celda."""
        m_pre = PATRON_PREFIJO.match(celda)
        prefijo = m_pre.group(0) if m_pre else ""
        sanitizado = sanitizar(celda[len(prefijo):])
        segmentos = re.split(r"\\n", sanitizado)
        frase = re.sub(r" {2,}", " ", " ".join(s.strip() for s in segmentos)).strip()
        return prefijo, frase, segmentos

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
                infos: list[InfoLinea | None] = []
                actuales: list[str | None] = []  # traducción que ya tenía la celda (--solo-genero)

                for i in range(inicio, fin):
                    o_parts, _ = partir(orig_lines[i], delim)
                    if len(o_parts) <= col:
                        continue
                    c_parts, _ = partir(cur_lines[i], delim)
                    actual = None
                    if len(c_parts) == len(o_parts) and c_parts[col] != o_parts[col]:
                        # Ya traducido previamente
                        if not self.reaprovechar_traduccion:
                            continue
                        celda_actual = c_parts[col]
                        if o_parts[col].startswith('"'):
                            celda_actual = quitar_comillas_csv(celda_actual)[0].replace('""', '"')
                        actual = self._frase_de_celda(celda_actual)[1]

                    orig_text = quitar_comillas_csv(o_parts[col])[0]

                    m_pre = PATRON_PREFIJO.match(orig_text)
                    prefix = m_pre.group(0) if m_pre else ""

                    # Traducir nombre de personaje en el prefijo: la tabla de hablantes del juego (la del Paso 5:
                    # "Man" -> "Hombre", "Guard A" -> "Guardia A", nombres propios tal cual) y, si no está, el glosario
                    if prefix:
                        def _traducir_nombre(m):
                            c_in = m.group(1) or ""
                            nombre = m.group(2)
                            c_out = m.group(3) or ""
                            es = traducir_nombre(nombre, *self._tabla_hablantes())
                            if es:
                                return f"\\N<{c_in}{limpiar_celda(es, delim)}{c_out}>"
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

                    hablante = hablante_csv(orig_text)
                    info = InfoLinea(hablante=hablante) if hablante else None
                    if actual is not None:
                        sembrar = getattr(self.translator, "sembrar_traduccion", None)
                        if actual and sembrar is not None:
                            sembrar(frase, actual, info)
                    indices.append(i)
                    textos_a_traducir.append(frase)
                    prefijos.append(prefix)
                    segmentos_lista.append(segments)
                    infos.append(info)
                    actuales.append(actual)

                if not textos_a_traducir:
                    continue

                if traductor_acepta_info(self.translator):
                    traducciones = self.translator.traducir_textos(textos_a_traducir, info=infos)
                else:
                    traducciones = self.translator.traducir_textos(textos_a_traducir)

                for idx_cola, trad in enumerate(traducciones):
                    line_idx = indices[idx_cola]
                    frase_orig = textos_a_traducir[idx_cola]
                    prefix = prefijos[idx_cola]
                    segments = segmentos_lista[idx_cola]

                    trad_limpia = limpiar_celda(trad, delim, quitar_comillas=False).strip()
                    if not trad_limpia:
                        continue
                    if actuales[idx_cola] is not None:
                        if trad_limpia == actuales[idx_cola]:
                            self.conservadas += 1  # igual que antes: la celda se queda tal cual
                            continue
                        self.retraducidas += 1

                    trad_limpia = self.translator.perfil.restaurar_nombres(frase_orig, trad_limpia)
                    if len(segments) > 1:
                        trad_limpia = reinsertar_saltos(trad_limpia, segments)

                    final_text = prefix + trad_limpia
                    o_parts, cr = partir(orig_lines[line_idx], delim)
                    if final_text in (o_parts[col], quitar_comillas_csv(o_parts[col])[0]):
                        continue

                    o_parts[col] = final_text
                    cur_lines[line_idx] = unir(o_parts, delim, cr)
                    cambiado = True

                if cambiado:
                    escribir_lineas(csv_file, bom, cur_lines)

            log.info("Archivo CSV guardado al 100%%: %s", csv_file.name)
            if self.reaprovechar_traduccion:
                log.info("  ♻ %d celda(s) ya traducidas se conservan; %d cambian.",
                         self.conservadas, self.retraducidas)
