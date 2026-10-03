import json
import requests
import re
from pathlib import Path

endpoint = "http://localhost:11434/api/generate"
model_name = "IA_Traductora"
cache = {}

def translate_text(text):
    if not text or not text.strip() or not any(c.isalpha() for c in text):
        return text
    if text in cache:
        return cache[text]
        
    print(f"Traduciendo UI: {text}")
    formatted_prompt = f"### Instruction:\nTraduce este texto de interfaz de usuario de videojuego al español de España de forma natural. Devuelve ÚNICAMENTE la traducción directa, sin comillas ni notas.\n\n### Input:\n{text}\n\n### Response:\n"
    
    payload = {
        "model": model_name,
        "prompt": formatted_prompt,
        "stream": False,
        "options": {"num_predict": 100, "temperature": 0.1}
    }
    
    try:
        response = requests.post(endpoint, json=payload, timeout=60)
        resp = response.json().get("response", "").strip()
        resp = resp.replace("Respuesta:", "").replace("### Response:", "").strip()
        if resp.startswith('"') and resp.endswith('"'): resp = resp[1:-1]
        
        final_resp = resp if resp else text
        cache[text] = final_resp
        return final_resp
    except Exception as e:
        print(f"Error: {e}")
        return text

def translate_node(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                node[k] = translate_text(v)
            elif isinstance(v, (dict, list)):
                translate_node(v)
    elif isinstance(node, list):
        for i in range(len(node)):
            if isinstance(node[i], str):
                node[i] = translate_text(node[i])
            elif isinstance(node[i], (dict, list)):
                translate_node(node[i])

def main():
    print("Traduciendo menús del sistema...")
    sys_path = Path(r"J:\SteamLibrary\steamapps\common\米可可大冒險\www\data\System.json")
    with open(sys_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Solo queremos traducir el apartado 'terms'
    if "terms" in data:
        translate_node(data["terms"])
        
    with open(sys_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
        
    print("Traduciendo plugin de RecollectionMode...")
    plugin_path = Path(r"J:\SteamLibrary\steamapps\common\米可可大冒險\www\js\plugins\RecollectionMode.js")
    with open(plugin_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # Reemplazamos los textos hardcodeados en el plugin
    content = content.replace('"Watch Events"', '"Ver Eventos"')
    content = content.replace('"Watch Cut Scenes"', '"Ver Cinemáticas"')
    content = content.replace('"Return to Title"', '"Volver al Título"')
    content = content.replace("'Watch Events'", "'Ver Eventos'")
    content = content.replace("'Watch Cut Scenes'", "'Ver Cinemáticas'")
    content = content.replace("'Return to Title'", "'Volver al Título'")
    
    with open(plugin_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print("¡TODO TRADUCIDO AL 100%!")

if __name__ == "__main__":
    main()
