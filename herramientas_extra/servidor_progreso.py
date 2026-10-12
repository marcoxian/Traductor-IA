"""servidor_progreso.py — Servidor web local ligero para monitorizar la traducción en tiempo real.
Usa únicamente la librería estándar de Python (http.server) y sirve una interfaz moderna en http://localhost:5050.
"""

import http.server
import json
import os
import re
import socketserver
import sys
import time
from pathlib import Path

PORT = 5050
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from traductor.progreso import ARCHIVO_PROGRESO, leer_progreso, proceso_vivo  # noqa: E402

# Respaldo antiguo (solo si no existe workspace/progreso_actual.json)
LOG_FILE = Path(r"C:\Users\marco\.gemini\antigravity-ide\brain\1776e6af-5320-4277-ad33-b0236d3a1cb4\.system_generated\tasks\task-2867.log")
CACHE_FILE = RAIZ / "workspace" / "treasure_of_nadia" / "cache" / "cache_IA_Traductora.json"
TOTAL_ESTIMADO = 34500

HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Monitor de Traducción — Treasure of Nadia</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(23, 32, 54, 0.7);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.4);
      --accent-grad: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --success: #10b981;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 30px 20px;
      overflow-x: hidden;
      background-image: 
        radial-gradient(circle at 15% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
        radial-gradient(circle at 85% 80%, rgba(168, 85, 247, 0.15) 0%, transparent 40%);
    }
    .container {
      width: 100%;
      max-width: 860px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--card-border);
    }
    .title-area h1 {
      font-size: 1.6rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: var(--accent-grad);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      display: inline-block;
    }
    .title-area p {
      color: var(--text-muted);
      font-size: 0.9rem;
      margin-top: 4px;
    }
    .status-badge {
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 10px var(--success);
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(1.2); }
    }
    .main-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 28px;
      backdrop-filter: blur(16px);
      box-shadow: 0 20px 40px -15px rgba(0,0,0,0.5);
    }
    .progress-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .percentage {
      font-size: 3rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      background: var(--accent-grad);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .fraction {
      font-size: 1.1rem;
      color: var(--text-muted);
      font-weight: 600;
    }
    .progress-track {
      width: 100%;
      height: 18px;
      background: rgba(255, 255, 255, 0.06);
      border-radius: 999px;
      overflow: hidden;
      position: relative;
      border: 1px solid rgba(255, 255, 255, 0.08);
      margin-bottom: 24px;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      background: var(--accent-grad);
      border-radius: 999px;
      box-shadow: 0 0 20px var(--accent-glow);
      transition: width 0.6s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
    }
    .stat-card {
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 16px;
    }
    .stat-label {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: 0.05em;
    }
    .stat-value {
      font-size: 1.25rem;
      font-weight: 700;
      margin-top: 6px;
      color: #fff;
      font-family: 'JetBrains Mono', monospace;
    }
    .feed-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 24px;
      backdrop-filter: blur(16px);
    }
    .feed-header {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: #cbd5e1;
    }
    .feed-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.85rem;
    }
    .feed-item {
      padding: 10px 14px;
      background: rgba(255, 255, 255, 0.02);
      border-left: 3px solid var(--accent);
      border-radius: 0 8px 8px 0;
      color: #e2e8f0;
      line-height: 1.4;
      transition: background 0.2s ease;
    }
    footer {
      text-align: center;
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="title-area">
        <h1 id="titulo-juego">Treasure of Nadia</h1>
        <p id="subtitulo">Monitor de Traducción en Vivo con IA (Modo Turbo)</p>
      </div>
      <div class="status-badge" id="status-badge">
        <div class="pulse-dot"></div>
        <span id="status-text">Traduciendo en vivo</span>
      </div>
    </header>

    <main class="main-card">
      <div class="progress-header">
        <div class="percentage" id="pct-val">0%</div>
        <div class="fraction" id="fraction-val">0 / 34.500 frases</div>
      </div>
      <div class="progress-track">
        <div class="progress-fill" id="progress-bar"></div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Archivo actual</div>
          <div class="stat-value" id="cur-file">Iniciando...</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Archivos procesados</div>
          <div class="stat-value" id="files-val">0 / 218</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Tiempo restante estimado</div>
          <div class="stat-value" id="eta-val">Calculando...</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Velocidad</div>
          <div class="stat-value" id="speed-val">~450 frases/min</div>
        </div>
      </div>
    </main>

    <section class="feed-card">
      <div class="feed-header">
        <span>⚡ Últimas frases traducidas por la IA</span>
      </div>
      <div class="feed-list" id="feed-list">
        <div class="feed-item">Esperando diálogos...</div>
      </div>
    </section>

    <footer>
      Actualización automática cada segundo • Traductor IA de Videojuegos
    </footer>
  </div>

  <script>
    let ultimasLineasSerializadas = "";

    async function actualizar() {
      try {
        const res = await fetch('/api/progreso');
        const data = await res.json();
        
        document.getElementById('pct-val').textContent = data.porcentaje + '%';
        document.getElementById('fraction-val').textContent = data.frases.toLocaleString() + ' / ' + data.total_estimado.toLocaleString() + ' frases';
        document.getElementById('progress-bar').style.width = data.porcentaje + '%';
        
        document.getElementById('cur-file').textContent = data.archivo_actual || 'Completando...';
        document.getElementById('files-val').textContent = data.archivos_hechos + ' / ' + data.archivos_totales;
        document.getElementById('eta-val').textContent = data.tiempo_restante;
        if (data.juego) {
          document.getElementById('titulo-juego').textContent = data.juego;
          document.title = 'Monitor de Traducción — ' + data.juego;
        }
        if (data.subtitulo) document.getElementById('subtitulo').textContent = data.subtitulo;
        if (data.velocidad) document.getElementById('speed-val').textContent = data.velocidad;
        
        if (data.completado) {
          document.getElementById('status-text').textContent = '¡Completado al 100%!';
          document.getElementById('status-badge').style.background = 'rgba(16, 185, 129, 0.25)';
        } else if (data.estado_texto) {
          document.getElementById('status-text').textContent = data.estado_texto;
          document.getElementById('status-badge').style.background = '';
        }

        // Solo actualizar el DOM si realmente hay frases nuevas
        const nuevasSerializadas = JSON.stringify(data.ultimas_lineas || []);
        if (nuevasSerializadas !== ultimasLineasSerializadas) {
          ultimasLineasSerializadas = nuevasSerializadas;
          const list = document.getElementById('feed-list');
          if (data.ultimas_lineas && data.ultimas_lineas.length > 0) {
            list.innerHTML = data.ultimas_lineas.map(l => `<div class="feed-item">${escapeHtml(l)}</div>`).join('');
          }
        }
      } catch (e) {
        console.error('Error fetching progress:', e);
      }
    }

    function escapeHtml(text) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
      return text.replace(/[&<>"']/g, m => map[m]);
    }

    setInterval(actualizar, 1500);
    actualizar();
  </script>
</body>
</html>
"""

TEXTO_ESTADOS = {
    "preparando": "Preparando…",
    "traduciendo": "Traduciendo en vivo",
    "detenido": "Detenido",
    "error": "Error",
}


def _formatear_eta(segundos):
    if segundos is None:
        return "Calculando..."
    minutos = round(segundos / 60)
    if minutos < 1:
        return "menos de 1 minuto"
    if minutos < 60:
        return f"~{minutos} minutos"
    return f"~{minutos // 60} h {minutos % 60:02d} min"


def obtener_datos_progreso():
    """Lee el estado compartido que publica 1_traducir_juego.py (traductor/progreso.py)."""
    d = leer_progreso(ARCHIVO_PROGRESO)
    if d is None:
        return _datos_legacy()

    estado = d.get("estado", "preparando")
    if estado in ("traduciendo", "preparando") and not proceso_vivo(d.get("pid")):
        estado = "detenido"
    completado = estado == "completado"
    if completado:
        tiempo = "¡Finalizado con éxito!"
    elif estado in ("error", "detenido"):
        tiempo = d.get("mensaje") or TEXTO_ESTADOS[estado]
    else:
        tiempo = _formatear_eta(d.get("eta_segundos"))

    juego = (d.get("juego") or "").replace("_", " ").title()
    fpm = d.get("velocidad_fpm") or 0
    return {
        "porcentaje": d.get("porcentaje", 0.0),
        "frases": d.get("frases_hechas", 0),
        "total_estimado": d.get("frases_totales", 0),
        "archivo_actual": "Completado (Todos los archivos listos)" if completado else d.get("archivo_actual", ""),
        "archivos_hechos": d.get("archivos_hechos", 0),
        "archivos_totales": d.get("archivos_totales", 0),
        "tiempo_restante": tiempo,
        "ultimas_lineas": [f["texto"] for f in d.get("ultimas_frases", [])[:6]],
        "completado": completado,
        "juego": juego,
        "subtitulo": f"Monitor de Traducción en Vivo con IA (Modo {str(d.get('modo', '')).title()})",
        "velocidad": f"~{fpm:.0f} frases/min" if fpm else "—",
        "estado_texto": TEXTO_ESTADOS.get(estado, ""),
    }


def _datos_legacy():
    frases_cache = 0
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                frases_cache = len(d)
        except Exception:
            pass

    pct = min(100.0, round((frases_cache / TOTAL_ESTIMADO) * 100, 1))

    # Leer log
    archivo_actual = "Map105.json"
    archivos_hechos = 112
    archivos_totales = 218
    ultimas_lineas = []
    completado = False

    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lineas = f.readlines()
                for l in reversed(lineas):
                    m = re.search(r'\[(\d+)/(\d+)\]\s+Analizando:\s+([^\s\.]+\.json)', l)
                    if m and archivo_actual == "Map105.json":
                        archivos_hechos = int(m.group(1))
                        archivos_totales = int(m.group(2))
                        archivo_actual = m.group(3)
                    
                    if "✔" in l and "Guardado con éxito" not in l and len(ultimas_lineas) < 6:
                        texto_limpio = l.split("✔", 1)[1].strip()
                        if texto_limpio and texto_limpio not in ultimas_lineas:
                            ultimas_lineas.append(texto_limpio)

                    if "Proceso completado" in l or archivos_hechos >= 218:
                        completado = True

                    if len(ultimas_lineas) >= 6 and archivo_actual != "Map105.json":
                        break
        except Exception:
            pass

    if completado or archivos_hechos >= 218:
        pct = 100.0
        completado = True
        tiempo_str = "¡Finalizado con éxito!"
    else:
        restantes = max(0, TOTAL_ESTIMADO - frases_cache)
        minutos_restantes = max(1, round(restantes / 450))
        tiempo_str = f"~{minutos_restantes} minutos"

    return {
        "porcentaje": pct,
        "frases": frases_cache,
        "total_estimado": frases_cache if completado else TOTAL_ESTIMADO,
        "archivo_actual": "Completado (Todos los archivos listos)" if completado else archivo_actual,
        "archivos_hechos": archivos_hechos,
        "archivos_totales": archivos_totales,
        "tiempo_restante": tiempo_str,
        "ultimas_lineas": ultimas_lineas,
        "completado": completado
    }

class ProgresoHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/progreso":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            datos = obtener_datos_progreso()
            self.wfile.write(json.dumps(datos, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

    def log_message(self, format, *args):
        # Silenciar logs en consola para no ensuciar
        return

def iniciar_servidor():
    with socketserver.TCPServer(("0.0.0.0", PORT), ProgresoHandler) as httpd:
        print(f"Servidor de progreso activo en http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    iniciar_servidor()
