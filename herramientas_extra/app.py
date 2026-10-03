import time
import threading
import pyperclip
import requests
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Estado global y memoria
historial_contexto = []
ultima_traduccion = {"original": "", "traduccion": ""}
texto_anterior = ""

# Configuración de Ollama
OLLAMA_URL = "http://localhost:11434/api/generate"
MODELO = "IA_Traductora"
GLOSARIO = {
    "Beatrix LeBeau": "Beatrix LeBeau",
    "Plort": "Plort",
    "Tarr": "Alquitrán"
}

def construir_prompt(texto_nuevo):
    contexto = "\n".join(historial_contexto)
    instruccion_glosario = "Respeta estos términos exactos: " + ", ".join([f"{k}={v}" for k, v in GLOSARIO.items()])
    
    return f"""A continuación hay una instrucción que describe una tarea, emparejada con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la petición.

### Instrucción:
Traduce este diálogo de videojuego al español manteniendo el tono conversacional.
Contexto previo:
{contexto}
{instruccion_glosario}

### Entrada:
{texto_nuevo}

### Respuesta:
"""

def monitor_portapapeles():
    global texto_anterior, ultima_traduccion
    while True:
        try:
            # Leer el portapapeles
            texto_actual = pyperclip.paste().strip()
            
            # Si hay texto nuevo, procesarlo
            if texto_actual and texto_actual != texto_anterior:
                texto_anterior = texto_actual
                
                # Enviar a la IA local
                prompt = construir_prompt(texto_actual)
                payload = {"model": MODELO, "prompt": prompt, "stream": False}
                
                respuesta = requests.post(OLLAMA_URL, json=payload)
                if respuesta.status_code == 200:
                    texto_traducido = respuesta.json().get("response", "").strip()
                    
                    # Actualizar memoria (solo últimas 5 líneas)
                    historial_contexto.append(f"Inglés: {texto_actual} -> Español: {texto_traducido}")
                    if len(historial_contexto) > 5:
                        historial_contexto.pop(0)
                        
                    # Actualizar estado para la web
                    ultima_traduccion = {"original": texto_actual, "traduccion": texto_traducido}
                    print(f"\nDetectado: {texto_actual}\nTraducido: {texto_traducido}")
                
        except Exception as e:
            pass
        time.sleep(1.5) # Pausa para no saturar el sistema

# Endpoint que tu panel web consultará
@app.route('/obtener_traduccion', methods=['GET'])
def obtener_traduccion():
    return jsonify(ultima_traduccion)

if __name__ == '__main__':
    # Lanzar el monitor del portapapeles en paralelo
    hilo_portapapeles = threading.Thread(target=monitor_portapapeles, daemon=True)
    hilo_portapapeles.start()
    
    print("Monitor de portapapeles iniciado.")
    print("Servidor web escuchando en http://localhost:5000/obtener_traduccion")
    # debug=False y use_reloader=False son obligatorios al usar threading
    app.run(port=5000, debug=False, use_reloader=False)
