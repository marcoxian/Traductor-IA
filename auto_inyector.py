import os
import re
import argparse
import logging
import configparser
import csv
import shutil
import requests
from collections import Counter
from pathlib import Path

# Configuración básica del logging para mostrar mensajes por consola (CMD)
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)

def sanitize_text(text):
    """Limpia saltos de línea artificiales que fragmentan oraciones.
    Los desarrolladores a veces parten frases largas con \n para que quepan
    en los bocadillos de diálogo. Esto confunde a la IA porque recibe
    fragmentos sin sentido. Esta función los fusiona en una sola oración."""
    # Reemplazar \r\n y \n sueltos por espacios
    cleaned = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    # Colapsar espacios múltiples en uno solo
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    return cleaned.strip()

# Nombres propios que la IA tiende a traducir literalmente -> formas incorrectas a deshacer
NOMBRES_PROTEGIDOS = {
    "Hills": r"\b(?:[Ll]as\s+)?[Cc]olinas\b",
}

def restore_names(source, translated):
    """Si el original contiene un nombre protegido y la traducción lo ha perdido, lo restaura."""
    for name, wrong in NOMBRES_PROTEGIDOS.items():
        if name in source and name not in translated:
            translated = re.sub(wrong, name, translated)
    return translated

def reinsert_breaks(translated, original_segments):
    """Recoloca los saltos '\\n' literales en la traducción, en los espacios más cercanos a la
    posición proporcional que tenían en el original (así el texto sigue cabiendo en la ventana)."""
    total = sum(len(s.strip()) for s in original_segments) or 1
    spaces = [i for i, c in enumerate(translated) if c == " "]
    chosen, acc = [], 0
    for seg in original_segments[:-1]:
        acc += len(seg.strip())
        target = acc / total * len(translated)
        candidates = [s for s in spaces if s not in chosen and (not chosen or s > chosen[-1])]
        if not candidates:
            break
        # Si en inglés el salto iba tras un final de frase, se prefiere un final de frase cercano
        ends_sentence = seg.rstrip()[-1:] in ".!?…)"
        bonus = 0.25 * len(translated) if ends_sentence else 0
        def score(s):
            return abs(s - target) - (bonus if translated[s - 1] in ".!?…)" else 0)
        chosen.append(min(candidates, key=score))
    out = list(translated)
    for pos in chosen:
        out[pos] = "\\n"
    return "".join(out)

# Códigos ANSI de colores para la consola
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RED    = "\033[91m"
RESET  = "\033[0m"

class OllamaTranslator:
    """Clase encargada de comunicarse con el modelo local de Ollama."""
    def __init__(self, model_name="IA_Traductora", endpoint="http://localhost:11434/api/generate"):
        self.model_name = model_name
        self.endpoint = "http://localhost:11434/api/generate"
        self.cache = {}

    def translate(self, text):
        if not text.strip():
            return text
            
        if text in self.cache:
            return self.cache[text]
            
        formatted_prompt = f"### Instruction:\nTraduce este texto al español de España de forma natural. Devuelve ÚNICAMENTE la traducción directa, sin números de lista, sin comillas y sin notas.\n\n### Input:\n{text}\n\n### Response:\n"
        
        payload = {
            "model": self.model_name,
            "prompt": formatted_prompt,
            "stream": False,
            "options": {
                "num_predict": 250,
                "temperature": 0.1
            }
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(self.endpoint, json=payload, timeout=60)
                response.raise_for_status()
                data = response.json()
                resp = data.get("response", "").strip()
                
                # Limpieza de alucinaciones
                resp = resp.replace("Respuesta:", "").replace("### Response:", "").strip()
                if resp.startswith("1. "): resp = resp[3:]
                if resp.startswith("- "): resp = resp[2:]
                if resp.startswith('"') and resp.endswith('"'): resp = resp[1:-1]
                if resp.startswith("'") and resp.endswith("'"): resp = resp[1:-1]
                
                # Filtro agresivo para alucinaciones con el prompt
                if "Texto de videojuego" in resp and ":" in resp:
                    resp = resp.split(":", 1)[-1].strip()
                if "Texto original:" in resp and "Tu traducción:" in resp:
                    resp = resp.split("Tu traducción:", 1)[-1].strip()
                
                # Si se coló alguna etiqueta residual
                if "<|im_start|>" in resp: resp = resp.split("<|im_start|>")[0].strip()
                
                final_resp = resp if resp else text
                self.cache[text] = final_resp
                return final_resp
            except requests.exceptions.RequestException as e:
                logging.warning(f"{YELLOW}Error de red (Intento {attempt + 1}/{max_retries}): {e}{RESET}")
                if attempt == max_retries - 1:
                    logging.error(f"{RED}Saltando texto tras {max_retries} intentos fallidos.{RESET}")
                    return text

    def extract_format_tags(self, text):
        """Extrae todas las variables y etiquetas de formato de un texto."""
        # Captura %s, %d, %f, %1, {0}, {name}, \n, BBCode [tag], [/tag], RPGMaker \C[3], \F[name], etc.
        pattern = r'(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\])'
        return re.findall(pattern, text)

    def validate_format_tags(self, original, translated):
        """Comprueba que la traducción conserva las mismas etiquetas de formato."""
        orig_tags = sorted(self.extract_format_tags(original))
        trans_tags = sorted(self.extract_format_tags(translated))
        return orig_tags == trans_tags, orig_tags, trans_tags

    def autocorrect(self, original, bad_translation, reason, max_attempts=3):
        """Reenvía a Ollama con el motivo del fallo para autocorregir."""
        last_corrected = bad_translation
        for attempt in range(max_attempts):
            correction_prompt = (
                f"Texto original: {original}\n"
                f"Tu traducción: {last_corrected}\n"
                f"Has fallado por este motivo: {reason}\n"
                f"Vuelve a traducirlo corrigiendo este error específico. "
                f"Devuelve únicamente el texto final, sin explicaciones ni comillas extra."
            )
            corrected = self.translate(correction_prompt)
            if correction_prompt in self.cache:
                del self.cache[correction_prompt]

            is_valid, _, _ = self.validate_format_tags(original, corrected)
            if is_valid:
                logging.info(f"{BLUE}  ✔ Autocorregido (intento {attempt + 1}): {corrected[:40]}...{RESET}")
                return corrected
            else:
                logging.warning(f"{YELLOW}  ✗ Intento {attempt + 1}/{max_attempts} sigue fallando{RESET}")
                last_corrected = corrected
        
        # Fallback de emergencia: Añadir las etiquetas faltantes a la fuerza
        logging.warning(f"{RED}  ✖ Irrecuperable. Aplicando Fallback de emergencia usando la primera traducción.{RESET}")
        orig_tags_list = self.extract_format_tags(original)
        trans_tags_list = self.extract_format_tags(bad_translation)
        
        missing = []
        for tag in orig_tags_list:
            if tag in trans_tags_list:
                trans_tags_list.remove(tag)
            else:
                missing.append(tag)
                
        if missing:
            fallback = "".join(missing) + " " + bad_translation
            logging.info(f"{BLUE}  ✔ Fallback inyectado: {fallback[:40]}...{RESET}")
            return fallback
            
        return bad_translation

class GameEngineInjector:
    """Gestor universal de detección de motores gráficos y estrategias de inyección."""
    def __init__(self, game_path, target_file=None, model_name="IA_Traductora"):
        self.game_path = Path(game_path)
        self.target_file = target_file
        self.translator = OllamaTranslator(model_name=model_name)

    def detect_engine(self):
        """Fase 1: Detección del Motor (Engine Scanner)"""
        logging.info(f"Analizando ruta: {self.game_path}...")
        
        if not self.game_path.exists():
            logging.error("La ruta especificada no existe.")
            return "Unknown"

        # 1. Detección Unity
        # Verifica el dll principal o la carpeta _Data
        if (self.game_path / "UnityPlayer.dll").exists() or any(self.game_path.glob("*_Data")):
            logging.info("Motor Unity detectado (Ideal para XUnity.AutoTranslator).")
            return "Unity"
            
        # 2. Detección Godot
        # Verifica archivos de paquete .pck o de traducción local .csv
        if any(self.game_path.glob("*.pck")) or any(self.game_path.glob("**/*.csv")):
            logging.info("Motor Godot detectado (Ideal para parcheo nativo de .csv).")
            return "Godot"
            
        # 3. Detección Unreal Engine
        # Verifica la estructura de carpetas clásica de Unreal
        if (self.game_path / "Engine" / "Binaries").exists():
            logging.info("Motor Unreal Engine detectado.")
            return "Unreal"
            
        # 4. Detección RPG Maker
        # Verifica librerías rgss o la carpeta www de las versiones MV/MZ
        if any(self.game_path.glob("*.rgss*")) or (self.game_path / "www").exists():
            logging.info("Motor RPG Maker detectado.")
            return "RPGMaker"
            
        logging.warning("No se detectó un patrón de motor reconocible.")
        return "Unknown"

    def inject_unity(self):
        """Fase 2: Estrategia para Unity"""
        logging.info("Inyectando framework BepInEx y XUnity.AutoTranslator...")
        
        auto_translator_dir = self.game_path / "BepInEx" / "config"
        auto_translator_dir.mkdir(parents=True, exist_ok=True)
        config_path = auto_translator_dir / "AutoTranslatorConfig.ini"
        
        logging.info("Configurando IA local (Ollama)...")
        config = configparser.ConfigParser()
        config.optionxform = str  # Mantiene las mayúsculas/minúsculas de las claves
        
        config["Service"] = {
            "Endpoint": "CustomHTTP"
        }
        # Configuración para que AutoTranslator ataque localmente a nuestra IA
        config["CustomHTTP"] = {
            "Url": "http://localhost:11434/api/generate",
            "Method": "POST",
            "RequestTemplate": '{"model": "IA_Traductora", "prompt": "{0}", "stream": false}',
            "ResponsePath": "response"
        }
        config["General"] = {
            "Language": "es",
            "FromLanguage": "en"
        }
        
        # Guardar la configuración ini
        with open(config_path, "w", encoding="utf-8") as f:
            config.write(f)
            
        logging.info(f"¡Éxito! Archivo de AutoTranslator generado en: {config_path}")

    @staticmethod
    def _read_lines(path):
        """Lee un CSV como texto plano. Devuelve (bom, líneas).
        Se parte por '\\n' igual que hace el plugin DKTools_Localization (sin interpretar comillas)."""
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig" if bom else "utf-8")
        return bom, text.split("\n")

    @staticmethod
    def _write_lines(path, bom, lines):
        """Escribe el CSV de forma atómica respetando BOM y saltos de línea originales."""
        temp_file = path.with_name(path.name + ".tmp")
        data = "\n".join(lines).encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        temp_file.write_bytes(data)
        os.replace(temp_file, path)

    @staticmethod
    def _detect_delimiter(header_line):
        counts = {d: header_line.count(d) for d in (";", ",", "\t")}
        return max(counts, key=counts.get)

    def inject_godot(self):
        """Fase 2: Estrategia para CSV de localización (Godot o plugins de idiomas de RPG Maker,
        p. ej. DKTools_Localization). Solo traduce la columna de inglés ('en') y la sustituye
        por español, manteniendo el formato exacto que espera el juego.
        Se guarda una copia '<archivo>.original' para poder reanudar y restaurar."""
        logging.info("Buscando archivos .csv de localización...")
        csv_files = [f for f in self.game_path.glob("**/*.csv")]
        
        if not csv_files:
            logging.warning("No se encontraron archivos .csv para parchear.")
            return

        BATCH_SIZE = 30
        tag_strip = re.compile(r'(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}<>|.!^$]|<[^>]*>)')
        # Prefijo de códigos de control al inicio del diálogo (caja de nombre \N<...>, caras, animaciones...).
        # Se aparta y se vuelve a pegar intacto; a la IA solo le llega la frase.
        prefix_re = re.compile(r'^(?:\\N<[^>]*>|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}|.!^$<>](?![A-Za-z])|\s)+')

        for csv_file in csv_files:
            logging.info(f"Parcheando archivo: {csv_file.name}...")

            # Copia de seguridad del original (solo la primera vez)
            backup = csv_file.with_name(csv_file.name + ".original")
            if not backup.exists():
                shutil.copy2(csv_file, backup)
                logging.info(f"Copia de seguridad creada: {backup.name}")

            bom, orig_lines = self._read_lines(backup)
            if not orig_lines or not orig_lines[0].strip():
                continue

            header_line = orig_lines[0].rstrip("\r")
            delim = self._detect_delimiter(header_line)
            header = [h.strip().lower() for h in header_line.split(delim)]

            # Localizar la columna de inglés
            col = None
            for name in ("en", "english", "en_us", "en-us"):
                if name in header:
                    col = header.index(name)
                    break
            if col is None:
                logging.warning(f"No se encontró columna de inglés en {csv_file.name} (cabecera: {header[:6]}). Se omite.")
                continue
            logging.info(f"Separador '{delim}' | Columna de inglés: '{header[col]}' (índice {col})")

            # Progreso previo: si el archivo actual tiene las mismas líneas, reutilizamos lo ya traducido
            _, cur_lines = self._read_lines(csv_file)
            if len(cur_lines) != len(orig_lines):
                logging.warning("El archivo actual no coincide con el original; se empieza desde el original.")
                cur_lines = list(orig_lines)

            total = len(orig_lines) - 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
            for batch_idx in range(total_batches):
                start = 1 + batch_idx * BATCH_SIZE
                end = min(start + BATCH_SIZE, len(orig_lines))
                logging.info(f"--- Bloque {batch_idx + 1}/{total_batches} (líneas {start}-{end - 1}) ---")
                changed = False

                for i in range(start, end):
                    o_line = orig_lines[i]
                    cr = "\r" if o_line.endswith("\r") else ""
                    o_parts = o_line[:-1].split(delim) if cr else o_line.split(delim)
                    if len(o_parts) <= col:
                        continue
                    original_text = o_parts[col]

                    # Ya traducido en una ejecución anterior
                    c_line = cur_lines[i]
                    c_parts = (c_line[:-1] if c_line.endswith("\r") else c_line).split(delim)
                    if len(c_parts) == len(o_parts) and c_parts[col] != original_text:
                        continue

                    sanitized = sanitize_text(original_text)
                    m = prefix_re.match(sanitized)
                    prefix = m.group(0) if m else ""
                    body = sanitized[len(prefix):]
                    if not any(c.isalpha() for c in tag_strip.sub("", body)):
                        continue

                    logging.info(f"-> Traduciendo: {body[:50]}...")
                    # Los '\n' literales se quitan para que la IA vea la frase completa
                    # y se recolocan después (la IA los perdía constantemente).
                    segments = re.split(r"\\n", body)
                    to_translate = re.sub(r" {2,}", " ", " ".join(s.strip() for s in segments)).strip()
                    translated_text = self.translator.translate(to_translate)

                    # Auditoría RegEx de etiquetas (con conteo, no solo conjuntos)
                    is_valid, orig_tags, trans_tags = self.translator.validate_format_tags(to_translate, translated_text)
                    if is_valid:
                        logging.info(f"{GREEN}  ✔ OK: {translated_text[:40]}...{RESET}")
                        final_text = translated_text
                    else:
                        missing = list((Counter(orig_tags) - Counter(trans_tags)).elements())
                        extra = list((Counter(trans_tags) - Counter(orig_tags)).elements())
                        reason = f"Faltan etiquetas: {missing}" if missing else f"Etiquetas sobrantes: {extra}"
                        logging.warning(f"{YELLOW}  ⚠ Etiquetas rotas en: {translated_text[:30]}... -> {reason}{RESET}")
                        final_text = self.translator.autocorrect(to_translate, translated_text, reason)

                    # El plugin parte por el separador y por saltos de línea sin entender comillas:
                    # la traducción no puede contener ninguno de los dos.
                    final_text = final_text.replace("\r", " ").replace("\n", " ")
                    final_text = final_text.replace(delim, "," if delim != "," else ";").strip()
                    if not final_text:
                        continue
                    final_text = restore_names(to_translate, final_text)
                    if len(segments) > 1:
                        final_text = reinsert_breaks(final_text, segments)
                    final_text = prefix + final_text
                    if final_text == original_text:
                        continue

                    o_parts[col] = final_text
                    cur_lines[i] = delim.join(o_parts) + cr
                    changed = True

                # Guardar tras cada bloque por seguridad
                if changed:
                    self._write_lines(csv_file, bom, cur_lines)

            logging.info(f"Archivo parcheado y guardado al completo: {csv_file.name}")

    def inject_unreal(self):
        """Fase 2: Estrategia para Unreal Engine"""
        logging.info("Módulo de inyección para Unreal Engine iniciado.")
        pass # Por implementar

    def inject_rpgmaker(self):
        logging.info("Módulo de inyección nativo para RPG Maker iniciado.")
        import json
        import shutil
        
        # Buscar carpeta de datos
        data_dir = self.game_path / "www" / "data"
        if not data_dir.exists():
            data_dir = self.game_path / "data"
            
        if not data_dir.exists():
            logging.error("No se encontró la carpeta 'data' de RPG Maker.")
            return
            
        json_files = list(data_dir.glob("*.json"))
        if self.target_file:
            json_files = [f for f in json_files if f.name.lower() == self.target_file.lower()]
            if not json_files:
                logging.error(f"No se encontró el archivo {self.target_file} en {data_dir}")
                return
        
        def process_json_data(data):
            if isinstance(data, dict):
                # Evitar traducir nombres de archivos de audio (tienen volume y pitch)
                if not ("name" in data and "volume" in data and "pitch" in data):
                    # Traducir campos comunes de base de datos
                    for key in ["name", "description", "message1", "message2", "message3", "nickname", "gameTitle"]:
                        if key in data and isinstance(data[key], str) and data[key].strip():
                            original = data[key]
                            if not any(c.isalpha() for c in original):
                                continue
                            sanitized = sanitize_text(original)
                            logging.info(f"-> Traduciendo ({key}): {sanitized[:30]}...")
                            translated = self.translator.translate(sanitized)
                            
                            is_valid, orig_tags, trans_tags = self.translator.validate_format_tags(sanitized, translated)
                            if not is_valid:
                                reason = f"Faltan etiquetas: {set(orig_tags)-set(trans_tags)}" if set(orig_tags)-set(trans_tags) else f"Sobrantes: {set(trans_tags)-set(orig_tags)}"
                                logging.warning(f"{YELLOW}  ⚠ Etiquetas rotas: {reason}{RESET}")
                                translated = self.translator.autocorrect(sanitized, translated, reason)
                                
                            # Aplicar saltos de línea automáticos a descripciones largas
                            if key == "description" and len(translated) > 48:
                                words = translated.split()
                                lines = []
                                current_line = []
                                current_length = 0
                                for word in words:
                                    if current_length + len(word) + 1 > 48 and current_line:
                                        lines.append(" ".join(current_line))
                                        current_line = [word]
                                        current_length = len(word)
                                    else:
                                        current_line.append(word)
                                        current_length += len(word) + 1
                                if current_line:
                                    lines.append(" ".join(current_line))
                                translated = "\n".join(lines)
                                
                            data[key] = translated

                # Traducir los términos del sistema (System.json) como New Game, Continue, HP, MP, etc.
                if "terms" in data and isinstance(data["terms"], dict):
                    terms = data["terms"]
                    # Los terms tienen arrays (commands, basic, params) y dicts (messages)
                    for term_category in ["commands", "basic", "params"]:
                        if term_category in terms and isinstance(terms[term_category], list):
                            for idx, term_str in enumerate(terms[term_category]):
                                if isinstance(term_str, str) and term_str.strip() and any(c.isalpha() for c in term_str):
                                    logging.info(f"-> Traduciendo menú ({term_category}): {term_str[:30]}...")
                                    terms[term_category][idx] = self.translator.translate(term_str)
                                    
                    if "messages" in terms and isinstance(terms["messages"], dict):
                        for msg_key, msg_str in terms["messages"].items():
                            if isinstance(msg_str, str) and msg_str.strip() and any(c.isalpha() for c in msg_str):
                                logging.info(f"-> Traduciendo mensaje del sistema: {msg_str[:30]}...")
                                terms["messages"][msg_key] = self.translator.translate(msg_str)
                                
                # Traducir los tipos de equipamiento, armas, armaduras, elementos y habilidades (System.json)
                for array_key in ["equipTypes", "weaponTypes", "armorTypes", "elements", "skillTypes"]:
                    if array_key in data and isinstance(data[array_key], list):
                        for idx, item in enumerate(data[array_key]):
                            if isinstance(item, str) and item.strip() and any(c.isalpha() for c in item):
                                logging.info(f"-> Traduciendo tipo ({array_key}): {item[:30]}...")
                                data[array_key][idx] = self.translator.translate(item)
                
                # Traducir opciones de diálogo (code 402)
                if "code" in data and "parameters" in data:
                    if data["code"] == 402 and len(data["parameters"]) > 1 and isinstance(data["parameters"][1], str):
                        original = data["parameters"][1]
                        if original.strip() and any(c.isalpha() for c in original):
                            logging.info(f"-> Traduciendo (Opción): {original[:30]}...")
                            translated = self.translator.translate(original)
                            is_valid, orig_tags, trans_tags = self.translator.validate_format_tags(original, translated)
                            if not is_valid:
                                reason = f"Faltan etiquetas: {set(orig_tags)-set(trans_tags)}" if set(orig_tags)-set(trans_tags) else f"Sobrantes: {set(trans_tags)-set(orig_tags)}"
                                translated = self.translator.autocorrect(original, translated, reason)
                            data["parameters"][1] = translated

                # Recursión para bucear en el JSON
                for k, v in data.items():
                    data[k] = process_json_data(v)
                    
            elif isinstance(data, list):
                # Agrupar diálogos consecutivos (code 401) antes de traducir
                data = group_and_translate_dialogues(data)
                for i in range(len(data)):
                    data[i] = process_json_data(data[i])
                    
            return data
        
        def group_and_translate_dialogues(commands):
            """Agrupa líneas de diálogo consecutivas (code 401) en un solo bloque,
            las envía como una sola oración a la IA para obtener contexto completo,
            y luego reparte la traducción de vuelta en las líneas originales."""
            i = 0
            while i < len(commands):
                # Detectar si el elemento actual es un comando de diálogo (code 401)
                if (isinstance(commands[i], dict) and 
                    commands[i].get("code") == 401 and
                    len(commands[i].get("parameters", [])) > 0 and
                    isinstance(commands[i]["parameters"][0], str)):
                    
                    # Recopilar todas las líneas 401 consecutivas
                    group_start = i
                    fragments = []
                    while (i < len(commands) and 
                           isinstance(commands[i], dict) and
                           commands[i].get("code") == 401 and
                           len(commands[i].get("parameters", [])) > 0 and
                           isinstance(commands[i]["parameters"][0], str)):
                        fragments.append(commands[i]["parameters"][0])
                        i += 1
                    
                    # Si no hay texto útil, saltar el grupo
                    full_text = " ".join(fragments)
                    if not any(c.isalpha() for c in full_text):
                        continue
                    
                    # Limpiar y fusionar los fragmentos en una sola oración
                    merged = sanitize_text(full_text)
                    logging.info(f"-> Agrupando texto ({len(fragments)} líneas): {merged[:50]}...")
                    
                    # Traducir la oración completa de una sola vez
                    translated = self.translator.translate(merged)
                    
                    is_valid, orig_tags, trans_tags = self.translator.validate_format_tags(merged, translated)
                    if not is_valid:
                        reason = f"Faltan etiquetas: {set(orig_tags)-set(trans_tags)}" if set(orig_tags)-set(trans_tags) else f"Sobrantes: {set(trans_tags)-set(orig_tags)}"
                        logging.warning(f"{YELLOW}  ⚠ Etiquetas rotas en diálogo: {reason}{RESET}")
                        translated = self.translator.autocorrect(merged, translated, reason)
                    
                    # Repartir la traducción inteligente: llenar líneas hasta ~45 caracteres
                    words = translated.split()
                    current_line = []
                    current_length = 0
                    lines = []
                    
                    for word in words:
                        # 45 caracteres es un buen límite seguro para RPG Maker
                        if current_length + len(word) + 1 > 45 and current_line:
                            lines.append(" ".join(current_line))
                            current_line = [word]
                            current_length = len(word)
                        else:
                            current_line.append(word)
                            current_length += len(word) + 1
                            
                    if current_line:
                        lines.append(" ".join(current_line))
                        
                    import copy
                    new_commands = []
                    for line_text in lines:
                        new_cmd = copy.deepcopy(commands[group_start])
                        new_cmd["parameters"][0] = line_text
                        new_commands.append(new_cmd)
                        
                    # Reemplazar los comandos originales por los nuevos divididos
                    commands[group_start:i] = new_commands
                    i = group_start + len(new_commands)
                else:
                    i += 1
            return commands

        for json_file in json_files:
            logging.info(f"Parcheando archivo nativo: {json_file.name}...")
            
            # Crear backup de seguridad la primera vez
            backup_file = json_file.with_suffix(".json.bak")
            if not backup_file.exists():
                shutil.copy2(json_file, backup_file)
                
            source_file = backup_file if backup_file.exists() else json_file
            with open(source_file, 'r', encoding='utf-8-sig') as f:
                try:
                    file_data = json.load(f)
                except Exception as e:
                    logging.error(f"Error al leer JSON {json_file.name}: {e}")
                    continue
                    
            translated_data = process_json_data(file_data)
            
            temp_file = json_file.with_suffix(".json.tmp")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(translated_data, f, ensure_ascii=False)
                
            os.replace(temp_file, json_file)
            logging.info(f"Archivo JSON de RPG Maker guardado al 100%: {json_file.name}")

    def run(self):
        engine = self.detect_engine()
        
        if engine == "Unity":
            self.inject_unity()
        elif engine == "Godot":
            self.inject_godot()
        elif engine == "Unreal":
            self.inject_unreal()
        elif engine == "RPGMaker":
            self.inject_rpgmaker()
        else:
            logging.error("Finalizando inyector sin hacer cambios.")

def main():
    parser = argparse.ArgumentParser(description="Auto-Inyector de IA Traductora Local en Videojuegos.")
    parser.add_argument("--ruta", type=str, required=True, help="Ruta absoluta de la carpeta del juego.")
    parser.add_argument("--archivo", type=str, required=False, help="Traducir solo un archivo específico (ej. System.json)")
    parser.add_argument("--modelo", type=str, default="IA_Traductora", help="Modelo de Ollama a usar (por defecto IA_Traductora)")
    
    args = parser.parse_args()

    logging.info("--- INICIANDO GESTOR UNIVERSAL DE TRADUCCIÓN ---")
    logging.info(f"Modelo: {args.modelo}")
    injector = GameEngineInjector(args.ruta, args.archivo, args.modelo)
    injector.run()
    logging.info("--- PROCESO FINALIZADO ---")

if __name__ == "__main__":
    main()
