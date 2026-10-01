import json
import os
from pathlib import Path

def restore_audio(original_node, translated_node):
    if isinstance(original_node, dict) and isinstance(translated_node, dict):
        # Is this an audio object? Check for signature keys
        if "name" in original_node and "volume" in original_node and "pitch" in original_node:
            if translated_node.get("name") != original_node["name"]:
                print(f"Restaurando audio: {translated_node['name']} -> {original_node['name']}")
                translated_node["name"] = original_node["name"]
        
        for k in original_node:
            if k in translated_node:
                restore_audio(original_node[k], translated_node[k])
                
    elif isinstance(original_node, list) and isinstance(translated_node, list):
        # Solamente comparamos listas de la misma longitud por seguridad
        if len(original_node) == len(translated_node):
            for o, t in zip(original_node, translated_node):
                restore_audio(o, t)

def main():
    data_dir = Path(r"J:\SteamLibrary\steamapps\common\米可可大冒險\www\data")
    json_files = list(data_dir.glob("*.json"))
    
    for json_file in json_files:
        bak_file = json_file.with_suffix(".json.bak")
        if not bak_file.exists():
            continue
            
        with open(bak_file, 'r', encoding='utf-8-sig') as f:
            orig_data = json.load(f)
            
        with open(json_file, 'r', encoding='utf-8') as f:
            trans_data = json.load(f)
            
        restore_audio(orig_data, trans_data)
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(trans_data, f, ensure_ascii=False)
            
    print("¡Restauración de audios completada!")

if __name__ == "__main__":
    main()
