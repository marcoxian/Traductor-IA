"""
Reentrenamiento v2 del traductor (continúa desde el modelo actual, no desde cero).

Mezcla:
  - glosario_v2.jsonl (x3)  -> términos RPG, mensajes con %1, ejemplos con códigos, correcciones
  - una muestra del dataset general (dataset_entrenamiento.jsonl) -> para que no "olvide"
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

MODELO_BASE = "traductor_juegos_gguf_final"   # Modelo actual (entreno de 18h + mini glosario)
SALIDA = "traductor_juegos_v2"
REPETIR_GLOSARIO = 3
MUESTRA_GENERAL = 4000

# Debe coincidir con OllamaTranslator.translate() en auto_inyector.py
INSTRUCCION = ("Traduce este texto al español de España de forma natural. Devuelve ÚNICAMENTE "
               "la traducción directa, sin números de lista, sin comillas y sin notas.")
PLANTILLA = "### Instruction:\n{}\n\n### Input:\n{}\n\n### Response:\n{}"

random.seed(3407)

# ---------------------------------------------------------------- Datos
if not Path("glosario_v2.jsonl").exists():
    sys.exit("Falta glosario_v2.jsonl. Ejecuta antes: python crear_glosario_v2.py")

def leer_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

glosario = leer_jsonl("glosario_v2.jsonl")
general = leer_jsonl("dataset_entrenamiento.jsonl")
general = random.sample(general, min(MUESTRA_GENERAL, len(general)))

ejemplos = glosario * REPETIR_GLOSARIO + general
random.shuffle(ejemplos)
print(f"Ejemplos: {len(glosario)} de glosario x{REPETIR_GLOSARIO} + {len(general)} generales = {len(ejemplos)}")

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
        output_dir = "outputs_v2",
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
