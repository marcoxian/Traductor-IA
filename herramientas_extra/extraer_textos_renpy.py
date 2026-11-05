import sys
import os
import re
import json

def parsear_rpy(ruta_archivo):
    pares = []
    with open(ruta_archivo, 'r', encoding='utf-8-sig', errors='ignore') as f:
        lineas = f.readlines()

    ingles_dialogo = None
    ingles_old = None

    for i in range(len(lineas)):
        linea = lineas[i].strip()
        if not linea:
            continue
            
        # Detectar diálogo original (comentado)
        # Ejemplo: # char "Texto en inglés"
        match_dialogo_en = re.match(r'^#\s*([\w\s]*?)\s*"(.*)"$', linea)
        if match_dialogo_en:
            ingles_dialogo = match_dialogo_en.group(2)
            continue
            
        # Detectar diálogo traducido (sin comentar)
        # Ejemplo: char "Texto en español"
        if ingles_dialogo:
            match_dialogo_es = re.match(r'^([\w\s]*?)\s*"(.*)"$', linea)
            if match_dialogo_es:
                espanol_dialogo = match_dialogo_es.group(2)
                if ingles_dialogo != espanol_dialogo:
                    pares.append({
                        "ingles": ingles_dialogo.strip(),
                        "espanol": espanol_dialogo.strip(),
                        "contexto": "oficial_renpy"
                    })
            ingles_dialogo = None # Reiniciar siempre después de intentar emparejar
            
        # Detectar strings (menús, interfaz)
        match_old = re.match(r'^old\s+"(.*)"$', linea)
        if match_old:
            ingles_old = match_old.group(1)
            continue
            
        match_new = re.match(r'^new\s+"(.*)"$', linea)
        if match_new and ingles_old:
            espanol_new = match_new.group(1)
            if ingles_old != espanol_new:
                pares.append({
                    "ingles": ingles_old.strip(),
                    "espanol": espanol_new.strip(),
                    "contexto": "oficial_renpy_ui"
                })
            ingles_old = None

    return pares

def extraer_textos_renpy(ruta_tl, ruta_salida):
    if not os.path.exists(ruta_tl):
        print(f"Error: No se encuentra la carpeta {ruta_tl}")
        return

    archivos_rpy = []
    for root, dirs, files in os.walk(ruta_tl):
        for f in files:
            if f.endswith('.rpy'):
                archivos_rpy.append(os.path.join(root, f))

    if not archivos_rpy:
        print("No se encontraron archivos .rpy en la carpeta.")
        return

    datos = []
    for archivo in archivos_rpy:
        datos.extend(parsear_rpy(archivo))

    # Eliminar duplicados exactos
    vistos = set()
    datos_unicos = []
    for item in datos:
        tupla = (item['ingles'], item['espanol'])
        if tupla not in vistos:
            vistos.add(tupla)
            datos_unicos.append(item)

    with open(ruta_salida, 'w', encoding='utf-8') as f_out:
        for item in datos_unicos:
            f_out.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"\n¡Éxito! Se han extraído {len(datos_unicos)} frases bilingües únicas.")
    print(f"Guardado en: {ruta_salida}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Uso: python extraer_textos_renpy.py <ruta_game_tl_spanish> <archivo_salida.jsonl>")
        sys.exit(1)
        
    ruta = sys.argv[1]
    salida = sys.argv[2]
    print(f"Analizando {ruta}...")
    extraer_textos_renpy(ruta, salida)
