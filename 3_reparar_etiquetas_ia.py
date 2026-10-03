import csv
import json
import requests
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

def extraer_etiquetas(texto):
    pattern = r'(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}<>|.!^$]|<[^>]*>)'
    return re.findall(pattern, texto)

def etiquetas_coinciden(original, traducido):
    etiquetas_orig = sorted(extraer_etiquetas(original))
    etiquetas_trad = sorted(extraer_etiquetas(traducido))
    return etiquetas_orig == etiquetas_trad

def corregir_con_ia(texto_ingles, traduccion_con_errores):
    prompt = f"""You are a precise technical translator for an RPG game.
Your task is to fix a Spanish translation that has broken or missing formatting tags.

Original English text (contains correct tags):
{texto_ingles}

Bad Spanish translation (tags are broken/missing):
{traduccion_con_errores}

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
        return traduccion_con_errores

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
            
        texto_ingles = row["ingles"]
        texto_traduccion_mala = row["traduccion_ia"]
        
        # If it's a long text truncation issue
        if "LONGITUD" in row["problema"]:
            print(f"[{i+1}/{len(filas)}] Refaciendo longitud truncada...")
            traduccion_reparada = corregir_con_ia(texto_ingles, "")
        else:
            print(f"[{i+1}/{len(filas)}] Arreglando etiquetas/orden...")
            traduccion_reparada = corregir_con_ia(texto_ingles, texto_traduccion_mala)
            
        # Verify
        if etiquetas_coinciden(texto_ingles, traduccion_reparada) or "LONGITUD" in row["problema"]:
            row["correccion"] = traduccion_reparada
            corregidas += 1
            print(f"  -> OK: {traduccion_reparada[:50]}...")
        else:
            print(f"  -> FALLO: Las etiquetas siguen sin coincidir. Usando fallback básico.")
            # Basic fallback: prepend missing tags
            etiquetas_orig = extraer_etiquetas(texto_ingles)
            etiquetas_trad = extraer_etiquetas(traduccion_reparada)
            etiquetas_faltantes = [t for t in etiquetas_orig if t not in etiquetas_trad]
            if etiquetas_faltantes:
                row["correccion"] = "".join(etiquetas_faltantes) + " " + traduccion_reparada
            else:
                row["correccion"] = traduccion_reparada
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
