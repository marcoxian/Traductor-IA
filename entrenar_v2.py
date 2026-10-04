"""
Reentrenamiento v2 del traductor (continúa desde el modelo actual, no desde cero).

Mezcla:
  - glosario_v2.jsonl (x3)  -> términos RPG, mensajes con %1, ejemplos con códigos, correcciones
  - una muestra del dataset general (dataset_base_general.jsonl) -> para que no "olvide"
    traducir frases normales al centrarse en el glosario

Todos los ejemplos usan EXACTAMENTE el mismo prompt que auto_inyector.py al traducir.

Requisitos: Ollama/traducción parados (la GPU tiene que estar libre).
Uso:
  python crear_glosario_v2.py
  python entrenar_v2.py
  ollama create IA_Traductora_v2 -f Modelfile_v2
  python auto_inyector.py --ruta "..." --modelo IA_Traductora_v2
"""
import sys
import json
import random
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

from pathlib import Path
from unsloth import FastLanguageModel
from datasets import Dataset
from trl import SFTTrainer
from transformers import TrainingArguments

modelo_candidato = Path("modelos/modelo_exportado_v2")
MODELO_BASE = str(modelo_candidato) if modelo_candidato.exists() else "modelo_exportado_v2"
salida_dir = Path("modelos") if Path("modelos").exists() else Path(".")
SALIDA = str(salida_dir / "traductor_juegos_v2")
REPETIR_GLOSARIO = 3
REPETIR_CORPUS = 2
MUESTRA_GENERAL = 4000

# Debe coincidir con OllamaTranslator.translate() en auto_inyector.py
INSTRUCCION = ("Traduce este texto al español de España de forma natural. Devuelve ÚNICAMENTE "
               "la traducción directa, sin números de lista, sin comillas y sin notas.")
PLANTILLA = "### Instruction:\n{}\n\n### Input:\n{}\n\n### Response:\n{}"

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
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

glosario = leer_jsonl(ruta_glosario)

corpus_extra = []
corpus_path = Path("datasets/corpus_videojuegos") if Path("datasets/corpus_videojuegos").exists() else Path("corpus_videojuegos")
if corpus_path.exists():
    for archivo in corpus_path.glob("*.jsonl"):
        corpus_extra.extend(leer_jsonl(archivo))

ruta_general = buscar_archivo("dataset_base_general.jsonl")
general = leer_jsonl(ruta_general) if ruta_general.exists() else []
if general:
    general = random.sample(general, min(MUESTRA_GENERAL, len(general)))

ejemplos = (glosario * REPETIR_GLOSARIO) + (corpus_extra * REPETIR_CORPUS) + general
random.shuffle(ejemplos)
print(f"Ejemplos: {len(glosario)} glosario(x{REPETIR_GLOSARIO}) + {len(corpus_extra)} corpus(x{REPETIR_CORPUS}) + {len(general)} gen = {len(ejemplos)}")

# ---------------------------------------------------------------- Modelo
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
textos = [PLANTILLA.format(INSTRUCCION, e["input"], e["output"]) + EOS_TOKEN for e in ejemplos]
dataset = Dataset.from_dict({"text": textos})

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 2,
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
        output_dir = "checkpoints_entrenamiento_v2",
        save_steps = 200,              # Puntos de control por si se corta
        save_total_limit = 2,
    ),
)

print("¡Iniciando el entrenamiento v2!")
trainer.train()

# ---------------------------------------------------------------- Exportar
print("Exportando a GGUF...")
model.save_pretrained_gguf(SALIDA, tokenizer, quantization_method = "q4_k_m")

ggufs = sorted(Path(".").glob(f"{SALIDA}*/*.gguf")) + sorted(Path(".").glob(f"{SALIDA}*.gguf"))
q4 = [g for g in ggufs if "q4_k_m" in g.name.lower()]
elegido = (q4 or ggufs or [None])[0]
if elegido:
    Path("Modelfile_v2").write_text(f"FROM ./{elegido.as_posix()}\n", encoding="utf-8")
    print(f"Modelfile_v2 creado apuntando a {elegido}")
    if not q4:
        print("AVISO: no se generó la versión Q4_K_M. Crea el modelo cuantizándolo con Ollama:")
        print("  ollama create IA_Traductora_v2 -q q4_K_M -f Modelfile_v2")
    else:
        print("Siguiente paso:  ollama create IA_Traductora_v2 -f Modelfile_v2")
else:
    print("AVISO: no encuentro el .gguf exportado; revisa las carpetas que empiezan por", SALIDA)
