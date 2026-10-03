import csv
import json
import requests
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

def extract_format_tags(text):
    pattern = r'(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}<>|.!^$]|<[^>]*>)'
    return re.findall(pattern, text)

def validate_format_tags(original, translated):
    orig_tags = sorted(extract_format_tags(original))
    trans_tags = sorted(extract_format_tags(translated))
    return orig_tags == trans_tags

def fix_with_llama(ingles, traduccion_mala):
    prompt = f"""You are a precise technical translator for an RPG game.
Your task is to fix a Spanish translation that has broken or missing formatting tags.

Original English text (contains correct tags):
{ingles}

Bad Spanish translation (tags are broken/missing):
{traduccion_mala}

Instructions:
1. Keep the Spanish translation natural.
2. You MUST include ALL the tags from the English text (like \\C[4], \\n, \\N<...>, \\SK[...], etc.) in their exact corresponding positions in the Spanish text.
3. DO NOT add any extra text, quotes, or explanations. Just output the corrected Spanish text.
"""
    try:
        response = requests.post("http://localhost:11434/api/generate", json={
            "model": "llama3.1:latest",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 500}
        }, timeout=60)
        response.raise_for_status()
        resp = response.json().get("response", "").strip()
        
        # Cleanup
        if resp.startswith('"') and resp.endswith('"'): resp = resp[1:-1]
        return resp
    except Exception as e:
        print(f"Error calling llama3.1: {e}")
        return traduccion_mala

def main():
    archivo = "revision_The_Adventures_of_HILLS.csv"
    filas = []
    
    with open(archivo, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            filas.append(row)
            
    print(f"Procesando {len(filas)} filas con llama3.1...")
    
    corregidas = 0
    for i, row in enumerate(filas):
        if row["correccion"].strip():
            continue
            
        ingles = row["ingles"]
        mala = row["traduccion_ia"]
        
        # If it's a long text truncation issue
        if "LONGITUD" in row["problema"]:
            print(f"[{i+1}/{len(filas)}] Refaciendo longitud truncada...")
            mejorada = fix_with_llama(ingles, "")
        else:
            print(f"[{i+1}/{len(filas)}] Arreglando etiquetas/orden...")
            mejorada = fix_with_llama(ingles, mala)
            
        # Verify
        if validate_format_tags(ingles, mejorada) or "LONGITUD" in row["problema"]:
            row["correccion"] = mejorada
            corregidas += 1
            print(f"  -> OK: {mejorada[:50]}...")
        else:
            print(f"  -> FALLO: Las etiquetas siguen sin coincidir. Usando fallback básico.")
            # Basic fallback: prepend missing tags
            orig_tags = extract_format_tags(ingles)
            trans_tags = extract_format_tags(mejorada)
            missing = [t for t in orig_tags if t not in trans_tags]
            if missing:
                row["correccion"] = "".join(missing) + " " + mejorada
            else:
                row["correccion"] = mejorada
            corregidas += 1
            
        # Save incrementally
        if i % 10 == 0:
            with open(archivo, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=filas[0].keys(), delimiter=";")
                writer.writeheader()
                writer.writerows(filas)
                
    # Final save
    with open(archivo, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=filas[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(filas)
        
    print(f"¡Proceso completado! {corregidas} líneas corregidas automáticamente.")

if __name__ == "__main__":
    main()
