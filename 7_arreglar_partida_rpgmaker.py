import os
import json
import lzstring
import csv
import shutil

save_dir = r'J:\SteamLibrary\steamapps\common\The Adventures of HILLS\www\save'
diccionario = 'correcciones_hills_menus.csv'

# Cargar correcciones
correcciones = {}
with open(diccionario, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
    for row in csv.reader(f, delimiter=';'):
        if len(row) >= 2 and row[0]:
            correcciones[row[0].strip()] = row[1].strip()

# Añadir también los textos literales malos si queremos reemplazarlos "a las bravas" en la partida
# por si el diccionario no caza algo concreto que está suelto.
reemplazos_brutos = {
    'tímida y tímida': 'tímida',
    'Desliza un elemento': 'Roba un objeto',
    'introducciones de caracteres': 'introducción de los personajes'
}

def reparar_cadenas(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                # 1. Reemplazos directos
                texto = v
                # Intentamos limpiar caracteres raros por si acaso
                for malo, bueno in reemplazos_brutos.items():
                    texto = texto.replace(malo, bueno)
                obj[k] = texto
            else:
                reparar_cadenas(v)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            if isinstance(obj[i], str):
                texto = obj[i]
                for malo, bueno in reemplazos_brutos.items():
                    texto = texto.replace(malo, bueno)
                obj[i] = texto
            else:
                reparar_cadenas(obj[i])

x = lzstring.LZString()

for f in os.listdir(save_dir):
    if f.endswith('.rpgsave'):
        path = os.path.join(save_dir, f)
        
        # Backup
        backup_path = path + '.bak'
        if not os.path.exists(backup_path):
            shutil.copy(path, backup_path)
            
        with open(path, 'r', encoding='utf8') as file:
            data = file.read()
            
        # Descomprimir
        dec = x.decompressFromBase64(data)
        if not dec:
            continue
            
        try:
            parsed = json.loads(dec)
            
            # Aplicamos nuestras correcciones
            reparar_cadenas(parsed)
            
            # Volvemos a comprimir
            new_json = json.dumps(parsed, separators=(',', ':'))
            enc = x.compressToBase64(new_json)
            
            with open(path, 'w', encoding='utf8') as file:
                file.write(enc)
            print(f'Partida guardada parcheada con éxito: {f}')
            
        except Exception as e:
            print(f'Error procesando {f}: {e}')
