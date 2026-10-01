import json
import random

# Nombres de los archivos extraídos
kde4_en = "KDE4.en-es.en"
kde4_es = "KDE4.en-es.es"
subs_en = "OpenSubtitles.en-es.en"
subs_es = "OpenSubtitles.en-es.es"
output_file = "dataset_entrenamiento.jsonl"

dataset = []

# 1. Cargar datos de interfaces (KDE4)
print("Procesando menús e interfaces (KDE4)...")
with open(kde4_en, "r", encoding="utf-8") as f_en, open(kde4_es, "r", encoding="utf-8") as f_es:
    for en, es in zip(f_en, f_es):
        # Ignoramos líneas vacías
        if not en.strip() or not es.strip(): continue
        dataset.append({
            "instruction": "Traduce este texto de interfaz y menús al español.",
            "input": en.strip(),
            "output": es.strip()
        })

# 2. Cargar diálogos (OpenSubtitles) - Limitado a 100,000 líneas
print("Procesando diálogos (OpenSubtitles)...")
subs_temp = []
with open(subs_en, "r", encoding="utf-8") as f_en, open(subs_es, "r", encoding="utf-8") as f_es:
    for en, es in zip(f_en, f_es):
        if not en.strip() or not es.strip(): continue
        subs_temp.append({
            "instruction": "Traduce este diálogo de videojuego al español manteniendo el tono conversacional.",
            "input": en.strip(),
            "output": es.strip()
        })
        if len(subs_temp) >= 100000:
            break

dataset.extend(subs_temp)

# 3. Mezclar para que la IA aprenda de ambos contextos a la vez
print("Mezclando el dataset...")
random.shuffle(dataset)

# 4. Guardar en formato JSONL
print(f"Guardando {len(dataset)} pares de frases en {output_file}...")
with open(output_file, "w", encoding="utf-8") as f_out:
    for item in dataset:
        f_out.write(json.dumps(item, ensure_ascii=False) + "\n")
        
print("¡Dataset listo para entrenar!")
