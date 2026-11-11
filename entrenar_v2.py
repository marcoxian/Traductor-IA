"""
Reentrenamiento v2 del traductor (continúa desde el modelo actual, no desde cero).

Mezcla:
  - glosario_v2.jsonl (x3)  -> términos RPG, mensajes con %1, ejemplos con códigos, correcciones
  - una muestra del corpus de videojuegos (datasets/corpus_videojuegos/*.jsonl)
  - dataset_genero*.jsonl ENTEROS (pistas "PERSONAJES: Habla Ana (mujer)..." en instruccion_completa)
  - una muestra del dataset general (dataset_base_general.jsonl) -> para que no "olvide"
    traducir frases normales al centrarse en el glosario

Todos los ejemplos usan EXACTAMENTE el mismo prompt que el traductor al traducir.

Requisitos: Ollama/traducción parados (la GPU tiene que estar libre).
Uso:
  python entrenar_v2.py --solo-datos              # resume el dataset sin cargar el modelo (no usa la GPU)
  python entrenar_v2.py                           # entrena y exporta como v2 (copia el GGUF anterior)
  python entrenar_v2.py --version 3               # salida en modelos/traductor_juegos_v3 + Modelfile_v3
  ollama create IA_Traductora_v3 -f Modelfile_v3  # crea el modelo nuevo SIN tocar IA_Traductora_v2
  python 9_evaluar_genero.py --modelo IA_Traductora_v3   # compáralo antes de cambiar de modelo
"""
import argparse
import json
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser(description="Reentrenamiento del traductor de videojuegos con Unsloth")
parser.add_argument("--modo", choices=["balanceado", "completo"], default="balanceado",
                    help="Modalidad de entrenamiento: balanceado (~25-30 min) o completo (~2.5h)")
parser.add_argument("--muestras-corpus", type=int, default=None,
                    help="Número personalizado de muestras del corpus de videojuegos")
parser.add_argument("--version", type=int, default=2,
                    help="Versión de salida: modelos/traductor_juegos_vN, Modelfile_vN, checkpoints propios (2)")
parser.add_argument("--base", default=None,
                    help="Modelo base (carpeta HF). Por defecto modelos/modelo_exportado_v2")
parser.add_argument("--solo-datos", action="store_true",
                    help="Preparar y resumir el dataset (con ejemplos de prompt) sin cargar el modelo ni la GPU")
parser.add_argument("--casos-dificiles", action="store_true",
                    help="Incluir workspace/*/casos_dificiles.jsonl (frases que el modelo falló y arregló en un reintento)")
parser.add_argument("--sin-neutros", action="store_true",
                    help="No pasar a forma neutra los ejemplos sin pista de hablante que tienen género (U3)")
args, _ = parser.parse_known_args()

modelo_candidato = Path(args.base) if args.base else Path("modelos/modelo_exportado_v2")
MODELO_BASE = str(modelo_candidato) if modelo_candidato.exists() else "modelo_exportado_v2"
salida_dir = Path("modelos") if Path("modelos").exists() else Path(".")
SALIDA = str(salida_dir / f"traductor_juegos_v{args.version}")
MODELFILE = Path(f"Modelfile_v{args.version}")
CHECKPOINTS = "checkpoints_entrenamiento_v2" if args.version == 2 else f"checkpoints_entrenamiento_v{args.version}"
NOMBRE_OLLAMA = f"IA_Traductora_v{args.version}"

if args.modo == "balanceado":
    REPETIR_GLOSARIO = 3
    REPETIR_CORPUS = 1
    MUESTRA_CORPUS = args.muestras_corpus if args.muestras_corpus is not None else 10000
    MUESTRA_GENERAL = 3000
    print(f"--- Modo seleccionado: BALANCEADO (~25-30 min) ---")
else:
    REPETIR_GLOSARIO = 3
    REPETIR_CORPUS = 2
    MUESTRA_CORPUS = args.muestras_corpus
    MUESTRA_GENERAL = 4000
    print(f"--- Modo seleccionado: COMPLETO (~2.5 horas) ---")

from traductor.prompts import INSTRUCCION, PLANTILLA

random.seed(3407)

# ---------------------------------------------------------------- Datos
def buscar_archivo(nombre):
    p_data = Path("datasets") / nombre
    if p_data.exists(): return p_data
    p_root = Path(nombre)
    if p_root.exists(): return p_root
    return p_data

ruta_glosario = buscar_archivo("glosario_v2.jsonl")
if not ruta_glosario.exists():
    sys.exit(f"Falta glosario_v2.jsonl (buscado en datasets/ y raíz). Ejecuta antes: python preparar_datos_v2.py")

def leer_jsonl(ruta):
    res = []
    with open(ruta, encoding="utf-8") as f:
        for l in f:
            if not l.strip():
                continue
            d = json.loads(l)
            if "input" not in d and "ingles" in d:
                d["input"] = d["ingles"]
            if "output" not in d and "espanol" in d:
                d["output"] = d["espanol"]
            res.append(d)
    return res

glosario = leer_jsonl(ruta_glosario)

corpus_extra = []
# dataset_genero_*.jsonl (herramientas_extra/dataset_genero.py): ejemplos con la pista de quién habla
# ("PERSONAJES: Habla Ana (mujer)...") en 'instruccion_completa'. Se usan ENTEROS (sin submuestreo)
# para que el modelo aprenda a respetar el género del hablante.
corpus_genero = []
archivos_genero = []
corpus_path = Path("datasets/corpus_videojuegos") if Path("datasets/corpus_videojuegos").exists() else Path("corpus_videojuegos")
if corpus_path.exists():
    for archivo in sorted(corpus_path.glob("*.jsonl")):
        if archivo.name.startswith("dataset_genero"):
            corpus_genero.extend(leer_jsonl(archivo))
            archivos_genero.append(archivo.name)
        else:
            corpus_extra.extend(leer_jsonl(archivo))

if MUESTRA_CORPUS is not None and len(corpus_extra) > MUESTRA_CORPUS:
    corpus_extra = random.sample(corpus_extra, MUESTRA_CORPUS)
corpus_extra.extend(corpus_genero)
if corpus_genero:
    print(f"Ejemplos de género con pistas de hablante: {len(corpus_genero)} (incluidos enteros: {', '.join(archivos_genero)})")

# Casos difíciles (traductor/ollama.py los guarda al traducir): la versión que pasó la puerta de calidad
# en un reintento, con la instrucción normal. Enseñan al modelo a acertar a la primera.
if args.casos_dificiles:
    vistos = set()
    corpus_dificiles = []
    for archivo in sorted(Path("workspace").glob("*/casos_dificiles.jsonl")):
        # La puerta de calidad acepta reintentos que no siempre están bien ("I'm cumming" -> "Estoy
        # corriendo"): si hay una versión revisada a mano, se usa esa; si no, se avisa.
        revisado = archivo.with_name("casos_dificiles_revisados.jsonl")
        if revisado.exists():
            archivo = revisado
        else:
            print(f"⚠ {archivo.parent.name}: casos difíciles SIN revisar (no hay {revisado.name}).")
        for e in leer_jsonl(archivo):
            clave = (e.get("input"), e.get("instruccion_completa"))
            if clave in vistos or not e.get("input") or not e.get("output"):
                continue
            vistos.add(clave)
            corpus_dificiles.append(e)
    corpus_extra.extend(corpus_dificiles)
    print(f"Casos difíciles (arreglados en un reintento): {len(corpus_dificiles)}")

ruta_general = buscar_archivo("dataset_base_general.jsonl")
general = leer_jsonl(ruta_general) if ruta_general.exists() else []
if general:
    general = random.sample(general, min(MUESTRA_GENERAL, len(general)))


# Fase 4 (W6, U1): antes de entrenar se arreglan los ejemplos que enseñan fallos conocidos, sin tocar los
# archivos: "chest" de cuerpo traducido "cofre" (34 frases de un juego en glosario_v2.jsonl) o "safe" como
# cofre (traductor.ambiguas), las colas de KDE pegadas ("HTMLName", "POZOConstellation name (optional)") y los
# artículos de "cofre" ("la cofre"). Si el sentido no se puede arreglar con un cambio seguro, el ejemplo se quita.
def limpiar_ejemplos(lista, nombre):
    from traductor import ambiguas
    from traductor.espana import coger_a_follar
    from traductor.gramatica import arreglar_determinantes
    from traductor.texto import quitar_cola_pegada
    def sentido_mal(en, t):  # "chest"/"safe" al revés (las palabras vulgares se cuentan aparte)
        return [d for d in ambiguas.sentido_equivocado(en, t) if d.sentido not in ambiguas.SENTIDOS_VULGARES]

    def vulgar_mal(en, t):
        return [d for d in ambiguas.sentido_equivocado(en, t) if d.sentido in ambiguas.SENTIDOS_VULGARES]

    limpios, corregidos, quitados, latam, vulgares = [], 0, 0, 0, 0
    for e in lista:
        en, es = e.get("input"), e.get("output")
        if not isinstance(en, str) or not isinstance(es, str):
            limpios.append(e)
            continue
        # AC: antes de mirar el vocabulario latino, los arreglos seguros: "cógeme" -> "fóllame" (si el inglés
        # habla de sexo) y "muchos actualizaciones" -> "muchas actualizaciones". Así esos ejemplos no se pierden.
        nuevo = arreglar_determinantes(coger_a_follar(ambiguas.arreglar_articulos(quitar_cola_pegada(en, es)), en))
        nuevo = ambiguas.espanol_de_espana(en, nuevo)
        if nuevo is None:  # W8: vocabulario de Latinoamérica sin arreglo seguro ("acabar", "coger", "vagina")
            latam += 1
            continue
        if sentido_mal(en, nuevo):
            nuevo = ambiguas.forzar_sentido(en, nuevo)
            if sentido_mal(en, nuevo):
                quitados += 1
                continue
        if vulgar_mal(en, nuevo):  # palabra vulgar suavizada o cambiada ("pussy" -> "polla"): no se aprende
            vulgares += 1
            continue
        if nuevo != es:
            e = {**e, "output": nuevo}
            corregidos += 1
        limpios.append(e)
    if corregidos or quitados or latam or vulgares:
        print(f"Limpieza de {nombre}: {corregidos} corregidos; quitados: {quitados} por 'chest'/'safe', "
              f"{latam} por vocabulario de Latinoamérica, {vulgares} por palabras vulgares suavizadas o cambiadas.")
    return limpios


# U3: sin pista de quién habla, "Estoy segura" es una apuesta de género que el modelo aprendería como regla
# (D10: sin ficha fallaba más que v1, que deja más frases neutras). Los ejemplos SIN pista con género en
# 1.ª o 2.ª persona se pasan a su forma neutra ("Seguro que…", "¿Todo listo?"); si no la tienen, se quitan.
# Los de género con pista (instruccion_completa) no se tocan: ahí el género sí lo decide la pista.
def neutralizar_sin_pista(lista, nombre):
    from traductor.genero import neutralizar_genero
    resultado, neutros, quitados = [], 0, 0
    for e in lista:
        es = e.get("output")
        if e.get("instruccion_completa") or not isinstance(es, str):
            resultado.append(e)
            continue
        neutro = neutralizar_genero(es)
        if neutro is None:
            quitados += 1
        elif neutro != es:
            resultado.append({**e, "output": neutro})
            neutros += 1
        else:
            resultado.append(e)
    if neutros or quitados:
        print(f"Sin pista de {nombre}: {neutros} pasados a forma neutra, {quitados} quitados (género sin forma neutra).")
    return resultado


glosario = limpiar_ejemplos(glosario, ruta_glosario.name)
corpus_extra = limpiar_ejemplos(corpus_extra, "corpus de videojuegos")
general = limpiar_ejemplos(general, "dataset_base_general (muestra)")
if not args.sin_neutros:
    glosario = neutralizar_sin_pista(glosario, ruta_glosario.name)
    corpus_extra = neutralizar_sin_pista(corpus_extra, "corpus de videojuegos")
    general = neutralizar_sin_pista(general, "dataset_base_general (muestra)")

ejemplos = (glosario * REPETIR_GLOSARIO) + (corpus_extra * REPETIR_CORPUS) + general
random.shuffle(ejemplos)
print(f"Dataset listo: {len(glosario)} glosario(x{REPETIR_GLOSARIO}) + {len(corpus_extra)} corpus(x{REPETIR_CORPUS}) + {len(general)} gen = {len(ejemplos)} ejemplos totales.")

# Regla de oro: todos los ejemplos usan INSTRUCCION, salvo los que traen 'instruccion_completa'
# (INSTRUCCION + contexto/PERSONAJES exactamente como los construye el traductor al traducir).
def texto_de(e):
    return PLANTILLA.format(e.get("instruccion_completa") or INSTRUCCION, e["input"], e["output"])

if args.solo_datos:
    con_pista = [e for e in ejemplos if e.get("instruccion_completa")]
    longitudes = sorted(len(texto_de(e)) for e in ejemplos)
    print(f"Con instrucción completa (contexto/PERSONAJES): {len(con_pista)} "
          f"({100.0 * len(con_pista) / max(1, len(ejemplos)):.1f} %)")
    print(f"Longitud del prompt (caracteres): mediana {longitudes[len(longitudes) // 2]}, "
          f"p99 {longitudes[int(len(longitudes) * 0.99)]}, máx {longitudes[-1]}")
    for e in random.Random(7).sample(con_pista, min(2, len(con_pista))):
        print("-" * 80)
        print(texto_de(e))
    print("-" * 80)
    print(f"Salida prevista: {SALIDA}_gguf/ -> {MODELFILE} -> ollama create {NOMBRE_OLLAMA} -f {MODELFILE}")
    sys.exit(0)

# ---------------------------------------------------------------- Modelo (imports pesados: GPU)
import torch

# Parche para torchao
for i in range(1, 8):
    if not hasattr(torch, f"int{i}"):
        setattr(torch, f"int{i}", torch.int8)

# Parche para FSDPModule
try:
    import torch.distributed.fsdp
except ImportError:
    pass
if not hasattr(torch.distributed, "fsdp"):
    import types
    fsdp_module = types.ModuleType("torch.distributed.fsdp")
    sys.modules["torch.distributed.fsdp"] = fsdp_module
    torch.distributed.fsdp = fsdp_module
if not hasattr(torch.distributed.fsdp, "FSDPModule"):
    torch.distributed.fsdp.FSDPModule = type("FSDPModule", (), {})

from unsloth import FastLanguageModel
from datasets import Dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048
print(f"Cargando modelo base ({MODELO_BASE})...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODELO_BASE,
    max_seq_length = max_seq_length,
    dtype = None,
    load_in_4bit = True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)

EOS_TOKEN = tokenizer.eos_token
textos = [texto_de(e) + EOS_TOKEN for e in ejemplos]
dataset = Dataset.from_dict({"text": textos})

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 1,
    packing = False,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 10,
        num_train_epochs = 1,
        learning_rate = 1e-4,          # Más bajo que el original: ajuste fino, no reaprender
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 10,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = CHECKPOINTS,
        save_steps = 200,              # Puntos de control por si se corta
        save_total_limit = 2,
    ),
)

print("¡Iniciando el entrenamiento!")
trainer.train()

# ---------------------------------------------------------------- Exportar
# El GGUF de una exportación anterior con la misma versión NO se pierde: se aparta con la fecha.
sello = datetime.now().strftime("%Y%m%d_%H%M")
for previo in (Path(f"{SALIDA}_gguf"),):
    if previo.exists():
        apartado = previo.with_name(f"{previo.name}_anterior_{sello}")
        previo.rename(apartado)
        print(f"GGUF anterior apartado en {apartado} (bórralo cuando ya no lo necesites)")
if MODELFILE.exists():
    shutil.copy2(MODELFILE, MODELFILE.with_name(f"{MODELFILE.name}.anterior_{sello}"))

print("Exportando a GGUF...")
model.save_pretrained_gguf(SALIDA, tokenizer, quantization_method = "q4_k_m")

ggufs = sorted(Path(".").glob(f"{SALIDA}*/*.gguf")) + sorted(Path(".").glob(f"{SALIDA}*.gguf"))
ggufs = [g for g in ggufs if "_anterior_" not in str(g)]
q4 = [g for g in ggufs if "q4_k_m" in g.name.lower()]
elegido = (q4 or ggufs or [None])[0]
if elegido:
    # TEMPLATE {{ .Prompt }}: el prompt (plantilla Alpaca de traductor/prompts.py) llega tal cual, como en
    # IA_Traductora_v2. Sin esta línea Ollama podría aplicar la plantilla de chat que trae el GGUF.
    MODELFILE.write_text(f"FROM ./{elegido.as_posix()}\nTEMPLATE {{{{ .Prompt }}}}\n", encoding="utf-8")
    print(f"{MODELFILE} creado apuntando a {elegido}")
    if not q4:
        print("AVISO: no se generó la versión Q4_K_M. Crea el modelo cuantizándolo con Ollama:")
        print(f"  ollama create {NOMBRE_OLLAMA} -q q4_K_M -f {MODELFILE}")
    else:
        print(f"Siguiente paso:  ollama create {NOMBRE_OLLAMA} -f {MODELFILE}")
        print(f"Y compáralo:     python 9_evaluar_genero.py --modelo {NOMBRE_OLLAMA}")
else:
    print("AVISO: no encuentro el .gguf exportado; revisa las carpetas que empiezan por", SALIDA)
