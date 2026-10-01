import json

# Glosario especializado de términos RPG/videojuegos Inglés -> Español
rpg_glossary = {
    # === Combate y habilidades ===
    "Slash": "Tajo", "Claw": "Garra", "Pierce": "Perforación", "Hit": "Golpe",
    "Sweep": "Barrido", "Bodyslam": "Embestida", "Absorb": "Absorber", "Bind": "Atar",
    "Curse": "Maldición", "Flash": "Destello", "Breath": "Aliento", "Shout": "Grito",
    "Song": "Canción", "Fog": "Niebla", "Pollen": "Polen", "Sonic Wave": "Onda sónica",
    "Death": "Muerte", "Revive": "Revivir", "Heal": "Curar", "Cure": "Sanar",
    "Powerup": "Potenciar", "Powerdown": "Debilitar", "Barrage": "Ráfaga",
    "Triple Slash": "Tajo triple", "V Strike": "Golpe en V",
    "Rain of Death": "Lluvia de muerte", "Divine Arrow": "Flecha divina",
    # === Elementos ===
    "Fire": "Fuego", "Ice": "Hielo", "Thunder": "Trueno", "Water": "Agua",
    "Earth": "Tierra", "Wind": "Viento", "Light": "Luz", "Darkness": "Oscuridad",
    "Neutral": "Neutral", "Poison": "Veneno",
    # === Estados alterados ===
    "Blind": "Ceguera", "Silence": "Silencio", "Sleep": "Sueño", "Confusion": "Confusión",
    "Paralyze": "Parálisis", "Rage": "Furia", "Guard": "Guardia", "Immortal": "Inmortal",
    # === Tipos de ataque ===
    "Physical": "Físico", "Effect": "Efecto", "Special": "Especial", "Normal": "Normal",
    "One": "Único", "All": "Total",
    # === Equipo y objetos ===
    "Shield": "Escudo", "Armor": "Armadura", "Sword": "Espada", "Dagger": "Daga",
    "Hammer": "Martillo", "Gauntlets": "Guanteletes", "Ring": "Anillo",
    "Weapon": "Arma", "Potion": "Poción", "Elixir": "Elixir", "Antidote": "Antídoto",
    "Key": "Llave", "Item": "Objeto",
    # === Personajes y roles ===
    "Adventurer": "Aventurera", "Village Chief": "Jefe de aldea",
    "Hero": "Héroe", "Warrior": "Guerrero", "Mage": "Mago", "Thief": "Ladrón",
    # === Interfaz de juego ===
    "New Game": "Nueva partida", "Continue": "Continuar", "Save": "Guardar",
    "Load": "Cargar", "Settings": "Ajustes", "Exit Game": "Salir del juego",
    "Equipment": "Equipamiento", "Skills": "Habilidades", "Status": "Estado",
    "Formation": "Formación", "Fight": "Luchar", "Retreat": "Huir",
    "Attack": "Atacar", "Defend": "Defender", "Buy": "Comprar", "Sell": "Vender",
    # === Tipos de proyectil / animación ===
    "Shoot": "Disparo", "Laser": "Láser", "Light Pillar": "Pilar de luz",
    "Ball of Light": "Esfera de luz", "Glowing Light": "Luz radiante",
    "Arrow Special": "Flecha especial",
    # === Términos de batalla ===
    "Critical Hit": "Golpe crítico", "Miss": "Fallo", "Evasion": "Evasión",
    "Counterattack": "Contraataque", "Victory": "Victoria", "Defeat": "Derrota",
    "Experience": "Experiencia", "Level Up": "Subir de nivel",
    "HP": "PV", "MP": "PM", "TP": "PT",
    # === Monstruos ===
    "Tentacle": "Tentáculo", "Slime": "Limo", "Bat": "Murciélago",
    "Orc": "Orco", "Minotaur": "Minotauro", "Dragon": "Dragón",
    # === Localizaciones ===
    "Dungeon": "Mazmorra", "Cave": "Cueva", "Village": "Aldea",
    "Castle": "Castillo", "Forest": "Bosque", "Tower": "Torre",
}

instruction = "Traduce este texto de videojuego RPG del inglés al español de España."

output_lines = []
for en, es in rpg_glossary.items():
    entry = {
        "instruction": instruction,
        "input": en,
        "output": es
    }
    output_lines.append(json.dumps(entry, ensure_ascii=False))

    # Añadir variantes con contexto de frase para mejor aprendizaje
    entry_ctx = {
        "instruction": instruction,
        "input": f"The {en} attack hits the enemy!",
        "output": f"¡El ataque de {es} golpea al enemigo!"
    }
    output_lines.append(json.dumps(entry_ctx, ensure_ascii=False))

with open("glosario_rpg.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print(f"Glosario RPG creado: {len(output_lines)} líneas de entrenamiento en 'glosario_rpg.jsonl'")
