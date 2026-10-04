import csv
import re
import sys
import os
import argparse

csv.field_size_limit(2147483647)

parser = argparse.ArgumentParser(description="Auditoría semántica de traducciones RPG Maker / CSV.")
parser.add_argument("--original", default=r'J:\SteamLibrary\steamapps\common\The Adventures of HILLS\www\locales_backup\main.csv.original', help="Ruta al CSV original en inglés")
parser.add_argument("--traducido", default=r'J:\SteamLibrary\steamapps\common\The Adventures of HILLS\www\locales\main.csv', help="Ruta al CSV traducido")
parser.add_argument("--diccionario", default='glosarios/glosario_interfaz_rpgmaker.csv', help="Ruta al archivo CSV de diccionario / glosario")
args = parser.parse_args()

path_orig = args.original
path_trans = args.traducido
path_dic = args.diccionario

if not os.path.exists(path_orig):
    print(f"Aviso: Archivo original no encontrado en: {path_orig}")
    print("Especifica la ruta correcta usando: python 6_auditoria_semantica.py --original <ruta> --traducido <ruta>")
    sys.exit(0)

if not os.path.exists(path_trans):
    print(f"Aviso: Archivo traducido no encontrado en: {path_trans}")
    print("Especifica la ruta correcta usando: python 6_auditoria_semantica.py --original <ruta> --traducido <ruta>")
    sys.exit(0)

# Reglas de sustitución: (palabra_ingles, regex_espanol_malo, reemplazo_espanol_bueno)
reglas = [
    ('item', r'\belemento\b', 'objeto'),
    ('items', r'\belementos\b', 'objetos'),
    ('item', r'\bartículo\b', 'objeto'),
    ('item', r'\barticulo\b', 'objeto'),
    ('items', r'\bartículos\b', 'objetos'),
    ('items', r'\barticulos\b', 'objetos'),
    ('party', r'\bfiesta\b', 'grupo'),
    ('character', r'\bcarácter\b', 'personaje'),
    ('characters', r'\bcaracteres\b', 'personajes'),
    ('save', r'\bahorrar\b', 'guardar'),
    ('save file', r'\barchivo de ahorro\b', 'archivo de guardado'),
    ('swipe', r'\bdesliza\b', 'roba'),
    ('swipe', r'\bdeslizar\b', 'robar'),
    ('swipe', r'\bdeslizado\b', 'robado'),
    ('miss', r'\bseñorita\b', 'fallo'),
    ('cast', r'\belenco\b', 'lanzar'),
    ('chest', r'\bpecho\b', 'cofre'), # 'chest' as box translated as body part
    ('drop', r'\bgota\b', 'soltar'), # drop item translated as water drop
]

orig_dict = {}
with open(path_orig, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
    for row in csv.reader(f, delimiter=';'):
        orig_dict[row[0]] = row[1]

nuevas_correcciones = []
# Leemos las ya existentes para no duplicar
existentes = set()
if os.path.exists(path_dic):
    with open(path_dic, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
        for row in csv.reader(f, delimiter=';'):
            if row:
                existentes.add(row[0])

count = 0
with open(path_trans, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
    for row in csv.reader(f, delimiter=';'):
        if not row: continue
        tag = row[0]
        es = row[1]
        en = orig_dict.get(tag, '')
        
        if not en or en in existentes:
            continue
            
        es_modificado = es
        en_lower = en.lower()
        
        # Aplicamos las reglas
        for en_word, bad_regex, good_word in reglas:
            if re.search(r'\b' + en_word + r'\b', en_lower):
                # Validar mayúsculas iniciales
                def repl(match):
                    word = match.group(0)
                    if word.istitle():
                        return good_word.capitalize()
                    elif word.isupper():
                        return good_word.upper()
                    return good_word
                es_modificado = re.sub(bad_regex, repl, es_modificado, flags=re.IGNORECASE)
                
        # Correcciones especiales
        if 'tímida y tímida' in es_modificado:
            es_modificado = es_modificado.replace('tímida y tímida', 'tímida')
            
        if es_modificado != es:
            nuevas_correcciones.append((en, es_modificado))
            count += 1

if nuevas_correcciones:
    with open(path_dic, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerows(nuevas_correcciones)
    print(f"Se encontraron y corrigieron automáticamente {count} traducciones literales malas.")
else:
    print("No se encontraron traducciones para arreglar con las reglas actuales.")
