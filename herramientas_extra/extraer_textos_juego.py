import os
import csv
import json

def extraer_textos(ruta_langs, ruta_salida):
    if not os.path.exists(ruta_langs):
        print(f"Error: No se encuentra la carpeta {ruta_langs}")
        return

    archivos = [f for f in os.listdir(ruta_langs) if f.endswith('.csv')]
    if not archivos:
        print("No se encontraron archivos CSV en la carpeta.")
        return

    pares_extraidos = 0
    datos = []

    for archivo in archivos:
        ruta_completa = os.path.join(ruta_langs, archivo)
        try:
            with open(ruta_completa, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Verify columns exist
                if not reader.fieldnames or 'ENGLISH' not in reader.fieldnames or 'SPANISH' not in reader.fieldnames:
                    print(f"Saltando {archivo}: No tiene columnas ENGLISH y SPANISH")
                    continue
                    
                for row in reader:
                    ingles = row.get('ENGLISH', '').strip()
                    espanol = row.get('SPANISH', '').strip()
                    
                    # Filtros básicos:
                    # - Que no estén vacíos
                    # - Que no sean idénticos (suele pasar en nombres propios sin traducir)
                    # - Que no sean solo un espacio
                    if ingles and espanol and ingles != espanol:
                        datos.append({
                            "ingles": ingles,
                            "espanol": espanol,
                            "contexto": "oficial_my_summer"
                        })
                        pares_extraidos += 1
        except Exception as e:
            print(f"Error procesando {archivo}: {e}")

    # Escribir el resultado
    with open(ruta_salida, 'w', encoding='utf-8') as f_out:
        for item in datos:
            f_out.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"\n¡Éxito! Se han extraído {pares_extraidos} frases bilingües.")
    print(f"Guardado en: {ruta_salida}")

if __name__ == '__main__':
    ruta = r"J:\SteamLibrary\steamapps\common\My Summer Makeup Romance\Langs"
    salida = "dataset_extra_mysummer.jsonl"
    print(f"Analizando {ruta}...")
    extraer_textos(ruta, salida)
