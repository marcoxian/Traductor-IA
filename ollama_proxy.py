import os
from flask import Flask, request, Response
import logging

# Reutilizamos la clase OllamaTranslator que ya tiene todas nuestras mejoras (glosario, sanitización, etc)
from importlib.machinery import SourceFileLoader
traductor_modulo = SourceFileLoader("traductor", "1_traducir_juego.py").load_module()

app = Flask(__name__)
# Instanciamos el traductor de Ollama
translator = traductor_modulo.OllamaTranslator(model_name="IA_Traductora")

# Desactivar logs por defecto de flask
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/translate', methods=['GET'])
def translate():
    text = request.args.get('text', '')
    if not text:
        return Response("", status=200, mimetype='text/plain')
        
    print(f"\n[NeoCrisis] Recibido: {text}", flush=True)
    translated = translator.translate(text)
    print(f"[NeoCrisis] Traducido: {translated}", flush=True)
    
    return Response(translated, status=200, mimetype='text/plain; charset=utf-8')

if __name__ == '__main__':
    print("=== Servidor Proxy de Traducción Iniciado ===")
    print("Escuchando en http://localhost:11435/translate")
    print("Esperando textos de XUnity.AutoTranslator...")
    app.run(host='127.0.0.1', port=11435)
