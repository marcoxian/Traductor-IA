import sys
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
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048
print("Cargando modelo base de 18h (traductor_juegos_gguf)...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "traductor_juegos_gguf", # Cargamos tu modelo ya entrenado, no el de cero
    max_seq_length = max_seq_length,
    dtype = None,
    load_in_4bit = True,
)

print("Aplicando adaptadores LoRA para el mini-entrenamiento...")
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

alpaca_prompt = """### Instruction:
{}

### Input:
{}

### Response:
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

print("Cargando glosario RPG...")
dataset = load_dataset("json", data_files="glosario_rpg.jsonl", split="train")
dataset = dataset.map(formatting_prompts_func, batched = True)

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
        max_steps = 60, # <-- Muy pocos pasos porque el dataset es pequeño (230 lineas)
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 10,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs_mini",
    ),
)

print("¡Iniciando el Mini Fine-Tuning de 5 minutos!")
trainer_stats = trainer.train()

print("Entrenamiento finalizado. Exportando GGUF actualizado...")
# Sobrescribe el GGUF que Ollama usa
model.save_pretrained_gguf("traductor_juegos_gguf_final", tokenizer, quantization_method = "q4_k_m")
print("¡GGUF finalizado! Lo tienes en 'traductor_juegos_gguf_final_gguf'.")
