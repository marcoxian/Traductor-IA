import sys
import torch

# Parche para torchao (evita el error de torch.intX en PyTorch 2.5)
for i in range(1, 8):
    if not hasattr(torch, f"int{i}"):
        setattr(torch, f"int{i}", torch.int8)

# Parche para FSDPModule (evita el error de trl en Windows)
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
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# 1. Cargar el modelo base en 4-bit (ahorra mucha VRAM)
max_seq_length = 2048 # Longitud máxima de contexto permitida durante el entrenamiento
print("Cargando modelo base...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Meta-Llama-3.1-8B-bnb-4bit", # Modelo base muy capaz para traducción
    max_seq_length = max_seq_length,
    dtype = None,
    load_in_4bit = True,
)

# 2. Configurar el adaptador LoRA (Solo entrenamos una fracción de la red)
print("Aplicando adaptadores LoRA...")
model = FastLanguageModel.get_peft_model(
    model,
    r = 16, # Rango de la matriz (16 es un buen equilibrio entre calidad y velocidad)
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)

# 3. Preparar el dataset
# Esta plantilla enseña al modelo cómo debe esperar que le hables cuando lo uses
alpaca_prompt = """A continuación hay una instrucción que describe una tarea, emparejada con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la petición.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
{}"""

EOS_TOKEN = tokenizer.eos_token
def formatting_prompts_func(examples):
    instructions = examples["instruction"]
    inputs       = examples["input"]
    outputs      = examples["output"]
    texts = []
    for instruction, input, output in zip(instructions, inputs, outputs):
        text = alpaca_prompt.format(instruction, input, output) + EOS_TOKEN
        texts.append(text)
    return { "text" : texts }

print("Cargando y formateando el dataset...")
# Importamos la librería 'datasets' (asegúrate de tenerla: pip install datasets)
dataset = load_dataset("json", data_files="dataset_entrenamiento.jsonl", split="train")
dataset = dataset.map(formatting_prompts_func, batched = True)

# 4. Configurar el Entrenador
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
        warmup_steps = 5,
        # max_steps = 300, # <-- Prueba rápida de 10 minutos
        num_train_epochs = 1, # <-- Entrena con el dataset completo. Tardará unas horas.
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 10,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
    ),
)

# 5. Iniciar Entrenamiento
print("¡Iniciando el Fine-Tuning en la GPU!")
trainer_stats = trainer.train()

# 6. Exportar el modelo terminado a GGUF (Formato nativo para Ollama)
print("Entrenamiento finalizado. Exportando a formato GGUF...")
# q4_k_m es una cuantización excelente que mantiene casi toda la inteligencia original ocupando poco espacio
model.save_pretrained_gguf("traductor_juegos_gguf", tokenizer, quantization_method = "q4_k_m")
print("¡Proceso 100% completado! Tienes tu modelo local en la carpeta 'traductor_juegos_gguf'.")
