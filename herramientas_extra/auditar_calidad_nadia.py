"""auditar_calidad_nadia.py
Audita la calidad de la traducción al español de Treasure of Nadia.
Detecta:
1. Errores de traducción automática / IA cutre (calcos del inglés: 'luce como', 'suena como', falsos amigos).
2. Errores de vocabulario o erratas groseras (ej: 'muestra segura' por 'muerte segura').
3. Mezcla de dialectos (Español Latino vs Español de España: verga/polla, coger/follar, auto/coche, ustedes/vosotros).
4. Traducciones literales sin sentido.
"""

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def auditar():
    fpath = Path("datasets/corpus_videojuegos/dataset_extra_nadia.jsonl")
    if not fpath.exists():
        print(f"Error: {fpath} no existe.")
        return

    with open(fpath, encoding="utf-8") as f:
        pares = [json.loads(l) for l in f if l.strip()]

    print(f"Total pares analizados en Nadia: {len(pares)}")

    # 1. Detectar dialecto predominante
    latino_terms = ["ustedes", "verga", "culo", "coger", "auto", "computadora", "maldición", "platicar", "chucha", "pendejo"]
    espana_terms = ["vosotros", "polla", "coño", "follar", "coche", "ordenador", "joder", "charlar", "gilipollas", "capullo"]

    conteo_latino = {t: 0 for t in latino_terms}
    conteo_espana = {t: 0 for t in espana_terms}

    # 2. Detectar calcos directos del inglés
    calcos = [
        (re.compile(r'\bluce como\b', re.I), "luce como (looks like)"),
        (re.compile(r'\bsuena como\b', re.I), "suena como (sounds like)"),
        (re.compile(r'\bsiento como si\b', re.I), "siento como si (I feel like)"),
        (re.compile(r'\bde ninguna manera\b', re.I), "de ninguna manera (no way)"),
        (re.compile(r'\bno puedo esperar para\b', re.I), "no puedo esperar para (can't wait to)"),
        (re.compile(r'\bhace sentido\b', re.I), "hace sentido (makes sense)"),
        (re.compile(r'\btomar ventaja\b', re.I), "tomar ventaja (take advantage)"),
        (re.compile(r'\buna muestra segura\b', re.I), "muestra segura (certain death erróneo)"),
    ]

    ejemplos_calcos = []
    ejemplos_latino = []
    ejemplos_espana = []
    errores_graves = []

    for p in pares:
        en = p.get("ingles", "")
        es = p.get("espanol", "")
        ctx = p.get("contexto", "")
        es_low = es.lower()

        # Contar dialecto
        for t in latino_terms:
            if re.search(r'\b' + re.escape(t) + r'\b', es_low):
                conteo_latino[t] += 1
                if len(ejemplos_latino) < 5 and t in ["verga", "coger", "ustedes", "maldición"]:
                    ejemplos_latino.append((en, es, t))

        for t in espana_terms:
            if re.search(r'\b' + re.escape(t) + r'\b', es_low):
                conteo_espana[t] += 1
                if len(ejemplos_espana) < 5:
                    ejemplos_espana.append((en, es, t))

        # Calcos
        for patron, nombre in calcos:
            if patron.search(es):
                ejemplos_calcos.append((en, es, nombre))

        # Detectar incoherencias flagrantes (muerte traducida como muestra, etc.)
        if "death" in en.lower() and "muert" not in es_low:
            if any(w in en.lower() for w in ["certain death", "to death"]):
                errores_graves.append((en, es))

    total_lat = sum(conteo_latino.values())
    total_esp = sum(conteo_espana.values())

    print("\n=== 1. ANÁLISIS DE DIALECTO (LATINO vs ESPAÑA) ===")
    print(f"Marcadores de Español Latino: {total_lat}")
    for k, v in conteo_latino.items():
        if v > 0:
            print(f"  - '{k}': {v}")

    print(f"\nMarcadores de Español de España: {total_esp}")
    for k, v in conteo_espana.items():
        if v > 0:
            print(f"  - '{k}': {v}")

    print("\nEjemplos de léxico latino detectado:")
    for en, es, t in ejemplos_latino[:5]:
        print(f"  [{t}] EN: {en} -> ES: {es}")

    print("\n=== 2. CALCOS ESTRUCTURALES DEL INGLÉS (IA / TRADUCTOR AUTOMÁTICO) ===")
    print(f"Total calcos detectados: {len(ejemplos_calcos)}")
    for en, es, motivo in ejemplos_calcos[:10]:
        print(f"  [{motivo}]")
        print(f"    EN: {en}")
        print(f"    ES: {es}")

    if errores_graves:
        print("\n=== 3. TRADUCCIONES FALLIDAS DETECTADAS ===")
        for en, es in errores_graves[:5]:
            print(f"    EN: {en}")
            print(f"    ES: {es}")

if __name__ == "__main__":
    auditar()
