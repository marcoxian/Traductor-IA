import os
import re
import argparse
import logging
import configparser
import csv
import requests
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
        for attempt in range(max_attempts):
            correction_prompt = (
                f"Texto original: {original}\n"
                f"Tu traducción: {bad_translation}\n"
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
        
        logging.error(f"{RED}  ✖ Irrecuperable tras {max_attempts} intentos. Se deja en inglés.{RESET}")
        return original

class GameEngineInjector:
    """Gestor universal de detección de motores gráficos y estrategias de inyección."""
    def __init__(self, game_path):
        self.game_path = Path(game_path)
        self.translator = OllamaTranslator()

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

    def inject_godot(self):
        """Fase 2: Estrategia para Godot con auditoría RegEx y autocorrección."""
        logging.info("Buscando archivos .csv de localización en el directorio Godot...")
        csv_files = list(self.game_path.glob("**/*.csv"))
        
        if not csv_files:
            logging.warning("No se encontraron archivos .csv para parchear.")
            return

        BATCH_SIZE = 30

        for csv_file in csv_files:
            logging.info(f"Parcheando archivo: {csv_file.name}...")
            
            # Leer todas las filas del CSV
            with open(csv_file, "r", encoding="utf-8", newline='') as infile:
                reader = csv.reader(infile)
                header = next(reader, None)
                rows = list(reader)
            
            if not header:
                continue

            # Procesar en bloques de BATCH_SIZE
            total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
            for batch_idx in range(total_batches):
                start = batch_idx * BATCH_SIZE
                end = min(start + BATCH_SIZE, len(rows))
                batch = rows[start:end]
                logging.info(f"--- Bloque {batch_idx + 1}/{total_batches} (líneas {start+1}-{end}) ---")

                # Fase 1: Traducción del bloque
                for row in batch:
                    if len(row) <= 1:
                        continue
                    original_text = row[1]
                    
                    if len(row) > 2 and row[2].strip() and row[2] != original_text:
                        logging.info(f"-> Omitiendo (Ya traducido): {original_text[:20]}...")
                        continue

                    sanitized = sanitize_text(original_text)
                    if not sanitized.strip() or not any(c.isalpha() for c in sanitized):
                        continue

                    logging.info(f"-> Traduciendo: {sanitized[:30]}...")
                    translated_text = self.translator.translate(sanitized)

                    # Fase 2: Auditoría RegEx
                    is_valid, orig_tags, trans_tags = self.translator.validate_format_tags(sanitized, translated_text)
                    
                    if is_valid:
                        logging.info(f"{GREEN}  ✔ OK: {translated_text[:40]}...{RESET}")
                        final_text = translated_text
                    else:
                        missing = set(orig_tags) - set(trans_tags)
                        extra = set(trans_tags) - set(orig_tags)
                        reason = f"Faltan etiquetas: {missing}" if missing else f"Etiquetas sobrantes: {extra}"
                        logging.warning(f"{YELLOW}  ⚠ Etiquetas rotas en: {translated_text[:30]}... -> {reason}{RESET}")
                        
                        # Fase 3: Autocorrección
                        final_text = self.translator.autocorrect(sanitized, translated_text, reason)

                    if len(row) > 2:
                        row[2] = final_text
                    else:
                        row.append(final_text)

            # Guardar el CSV completo parcheado
            temp_file = csv_file.with_suffix(".csv.tmp")
            with open(temp_file, "w", encoding="utf-8", newline='') as outfile:
                writer = csv.writer(outfile)
                writer.writerow(header)
                writer.writerows(rows)
            
            os.replace(temp_file, csv_file)
            logging.info(f"Archivo de Godot parcheado y guardado: {csv_file.name}")

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
                    
                    # Repartir la traducción inteligente: llenar líneas hasta ~50 caracteres
                    # para evitar que queden líneas con 2 palabras
                    num_lines = len(fragments)
                    if num_lines == 1:
                        commands[group_start]["parameters"][0] = translated
                    else:
                        words = translated.split()
                        current_line = []
                        current_length = 0
                        lines = []
                        
                        for word in words:
                            # 50 caracteres es un buen límite seguro para RPG Maker
                            if current_length + len(word) + 1 > 50 and current_line:
                                lines.append(" ".join(current_line))
                                current_line = [word]
                                current_length = len(word)
                            else:
                                current_line.append(word)
                                current_length += len(word) + 1
                                
                        if current_line:
                            lines.append(" ".join(current_line))
                            
                        # Si ocupamos más líneas que las originales, embutir las sobrantes en la última
                        while len(lines) > num_lines:
                            lines[-2] = lines[-2] + " " + lines[-1]
                            lines.pop()
                            
                        # Rellenar con cadenas vacías si usamos menos líneas
                        while len(lines) < num_lines:
                            lines.append("")
                            
                        for j in range(num_lines):
                            commands[group_start + j]["parameters"][0] = lines[j]
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
    
    args = parser.parse_args()

    logging.info("--- INICIANDO GESTOR UNIVERSAL DE TRADUCCIÓN ---")
    injector = GameEngineInjector(args.ruta)
    injector.run()
    logging.info("--- PROCESO FINALIZADO ---")

if __name__ == "__main__":
    main()
