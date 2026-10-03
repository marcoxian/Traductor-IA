"""
Glosario v2 para el reentrenamiento del traductor.

Mejoras respecto a crear_glosario_rpg.py (v1):
  - Usa EXACTAMENTE la misma instrucción que auto_inyector.py al traducir. Si el modelo
    se entrena con un texto y luego se le pregunta con otro, aprende peor.
  - Elimina la plantilla "The X attack hits the enemy!" (generaba frases absurdas como
    "The Save attack hits the enemy!").
  - Añade términos de menú/estadísticas/mensajes de combate sacados de HILLS (RPG Maker MV).
  - Añade ejemplos con códigos de control (\\C[n], \\n, %1, \\I[n], \\V[n]...) para que el
    modelo aprenda a conservarlos intactos (el fallo más común en los registros).
  - Incorpora automáticamente las correcciones manuales de correcciones_*.csv
    (generadas por revisar_traduccion.py).

Uso:  python crear_glosario_v2.py
Salida: glosario_v2.jsonl
"""
import csv
import glob
import json
import random

random.seed(3407)

# Debe coincidir carácter a carácter con el prompt de OllamaTranslator.translate()
INSTRUCCION = ("Traduce este texto al español de España de forma natural. Devuelve ÚNICAMENTE "
               "la traducción directa, sin números de lista, sin comillas y sin notas.")

# ---------------------------------------------------------------------------
# 1. Términos de interfaz, estadísticas, estados y equipo
# ---------------------------------------------------------------------------
TERMINOS = {
    # Menú principal / sistema
    "New Game": "Nueva partida", "Continue": "Continuar", "Options": "Opciones",
    "Return to Title": "Volver al título", "Exit": "Salir", "Cancel": "Cancelar",
    "Save": "Guardar", "Load": "Cargar", "Save Files": "Partidas guardadas",
    "Save Count": "Veces guardado", "Current Location": "Ubicación actual",
    "Play Time": "Tiempo de juego", "Money": "Dinero", "Days": "Días",
    "Language": "Idioma", "Fast Travel": "Viaje rápido",
    "Toggle Sprint": "Correr siempre", "Remember Commands": "Recordar comandos",
    "BGM Volume": "Volumen de música", "BGS Volume": "Volumen de ambiente",
    "ME Volume": "Volumen de efectos musicales", "SE Volume": "Volumen de efectos",
    # Menú de juego
    "Item": "Objetos", "Items": "Objetos", "Skills": "Habilidades", "Equipment": "Equipo",
    "Equip": "Equipar", "Status": "Estado", "Formation": "Formación",
    "Weapons": "Armas", "Armor": "Armaduras", "Key Items": "Objetos clave",
    "Best Gear": "Equipo óptimo", "Unequip All": "Quitar todo",
    "Buy": "Comprar", "Sell": "Vender", "Owned": "En posesión",
    "Quests": "Misiones", "Main Quest": "Misión principal", "Sub Quests": "Misiones secundarias",
    "Ult Skill": "Habilidad definitiva",
    # Combate
    "Battle": "Luchar", "Retreat": "Huir", "Attack": "Atacar", "Defend": "Defender",
    "All Enemies": "Todos los enemigos", "All Allies": "Todos los aliados",
    "Random Enemy": "Enemigo aleatorio", "Critical Hit!!": "¡¡Golpe crítico!!",
    "Action failed!": "¡La acción ha fallado!", "Knocked Out": "Fuera de combate",
    "Unable to act.": "No puede actuar.",
    # Estadísticas (se mantienen las siglas habituales en España)
    "Level": "Nivel", "Max HP": "PV máx.", "Max MP": "PM máx.", "ATK": "ATQ", "DEF": "DEF",
    "Magic ATK": "ATQ mágico", "Magic DEF": "DEF mágica", "SPD": "VEL", "LUCK": "SUERTE",
    "CRI": "CRÍ", "Hit Rate": "Precisión", "Dodge": "Evasión", "HP": "PV", "MP": "PM", "TP": "PT",
    # Elementos
    "PHY": "FÍS", "Fire": "Fuego", "Ice": "Hielo", "Thunder": "Rayo", "Water": "Agua",
    "Earth": "Tierra", "Wind": "Viento", "Light": "Luz", "Dark": "Oscuridad",
    # Tipos de arma / armadura
    "Dagger": "Daga", "Longsword": "Espada larga", "Club": "Maza", "Axe": "Hacha",
    "Whip": "Látigo", "Staff": "Bastón", "Bow": "Arco", "Crossbow": "Ballesta", "Gun": "Arma de fuego",
    "Claw": "Garra", "Gauntlet": "Guantelete", "Lance": "Lanza",
    "Normal Armor": "Armadura normal", "Magic Armor": "Armadura mágica",
    "Light Armor": "Armadura ligera", "Heavy Armor": "Armadura pesada",
    "Small Shield": "Escudo pequeño", "Large Shield": "Escudo grande",
    "Finger": "Dedo", "Hands": "Manos", "Clothing": "Ropa", "Accessory": "Accesorio",
    # Estados
    "Poison": "Veneno", "Blind": "Ceguera", "Silence": "Silencio", "Rage": "Furia",
    "Frenzy": "Frenesí", "Confusion": "Confusión", "Charm": "Encanto", "Sleep": "Sueño",
    "Block": "Bloqueo", "Cover": "Cubrir", "Stun": "Aturdimiento", "Paralysis": "Parálisis",
    "Steal": "Robar", "Empty": "Vacío", "Burn": "Quemadura", "Bleed": "Sangrado",
    "Stealth": "Sigilo", "Fear": "Miedo", "Undying": "Inmortal", "Hangover": "Resaca",
    "ATK Up": "ATQ arriba", "ATK Down": "ATQ abajo", "DEF Up": "DEF arriba", "DEF Down": "DEF abajo",
    "Crit Up": "Crítico arriba", "Dodge Up": "Evasión arriba", "Dodge Down": "Evasión abajo",
    "Energy Up": "Energía arriba", "Endurance Up": "Aguante arriba", "Vitality Up": "Vitalidad arriba",
    "Fighting Spirit": "Espíritu de lucha", "Defense Stance": "Postura defensiva",
    "Morale Boost": "Subidón de moral", "Indomitable Will": "Voluntad indomable",
    # Objetos frecuentes
    "Healing Potion": "Poción curativa", "Medium Healing Potion": "Poción curativa media",
    "Supreme Healing Potion": "Poción curativa suprema", "Blue Herb": "Hierba azul",
    "Casino Chip": "Ficha de casino", "Job Posting": "Anuncio de trabajo",
    "Training Dummy": "Muñeco de entrenamiento", "Iron Armor": "Armadura de hierro",
    "Round Shield": "Escudo redondo", "Maid Uniform": "Uniforme de criada",
    "Bunny Suit": "Traje de conejita", "Adventurer's Outfit": "Atuendo de aventurera",
    "Guard": "Guardia", "Guard Captain": "Capitán de la guardia", "Mansion Guard": "Guardia de la mansión",
    "Mysterious Merchant": "Mercader misterioso", "Thug": "Matón", "Slaver": "Esclavista",
    "Homeless Man": "Vagabundo", "Laborer": "Peón", "Proprietress": "Dueña",
}

# ---------------------------------------------------------------------------
# 2. Mensajes de combate con marcadores (%1, %2...) -> enseñan a conservarlos
# ---------------------------------------------------------------------------
MENSAJES = {
    "%1 appears!": "¡Aparece %1!",
    "%1 is ambushed!": "¡%1 cae en una emboscada!",
    "%1 runs away!": "¡%1 huye!",
    "%1 is victorious!": "¡%1 sale victorioso!",
    "%1 is defeated!": "¡%1 ha sido derrotado!",
    "Obtained %1 %2!": "¡Has obtenido %1 %2!",
    "Obtained %1!": "¡Has obtenido %1!",
    "Learned %1!": "¡Has aprendido %1!",
    "%1 uses %2!": "¡%1 usa %2!",
    "%1 takes %2 DMG!": "¡%1 recibe %2 de daño!",
    "%1's %2 recovers %3!": "¡%1 recupera %3 de %2!",
    "%1's %2 lost %3!": "¡%1 pierde %3 de %2!",
    "%1 takes no DMG!": "¡%1 no recibe daño!",
    "%1 dodges the attack!": "¡%1 esquiva el ataque!",
    "%1 resists the spell!": "¡%1 resiste el hechizo!",
    "%1 reflects the spell!": "¡%1 refleja el hechizo!",
    "%1 counters!": "¡%1 contraataca!",
    "%1's %2 increases!": "¡Aumenta el %2 de %1!",
    "%1's %2 decreases!": "¡Disminuye el %2 de %1!",
    "Current %1": "%1 actual",
    "Until Next %1": "Hasta el siguiente %1",
    "%1 's Party": "Grupo de %1",
    "ATK increases by 25%.": "El ATQ aumenta un 25 %.",
    "DEF decreases by 50%.": "La DEF disminuye un 50 %.",
    "SPD decreases by 90%.": "La VEL disminuye un 90 %.",
}

# ---------------------------------------------------------------------------
# 3. Frases base para generar ejemplos con códigos de control
# ---------------------------------------------------------------------------
FRASES = [
    ("Welcome to the public baths.", "Bienvenida a los baños públicos."),
    ("I'll pay you a referral fee.", "Te pagaré una comisión por recomendarlo."),
    ("Something about a guest?", "¿Algo sobre un invitado?"),
    ("Should I wait in the room?", "¿Debería esperar en la habitación?"),
    ("The floor is slippery.", "El suelo resbala."),
    ("Thanks for coming.", "Gracias por venir."),
    ("That's not bad at all!", "¡No está nada mal!"),
    ("Let me know if you find someone.", "Avísame si encuentras a alguien."),
    ("I don't have enough money.", "No tengo suficiente dinero."),
    ("Where did he go?", "¿Adónde ha ido?"),
    ("Be careful out there.", "Ten cuidado ahí fuera."),
    ("This is the men's bath!", "¡Este es el baño de hombres!"),
    ("I feel so much better now.", "Ahora me siento mucho mejor."),
    ("We should come back later.", "Deberíamos volver más tarde."),
    ("The guild has a new job for you.", "El gremio tiene un nuevo trabajo para ti."),
    ("You received a reward.", "Has recibido una recompensa."),
    ("Don't touch me!", "¡No me toques!"),
    ("I'm a little tired today.", "Hoy estoy un poco cansada."),
    ("He is a complete drunk.", "Es un borracho de cuidado."),
    ("Do you need anything else?", "¿Necesitas algo más?"),
]

PALABRAS = [
    ("Healing Potion", "Poción curativa"), ("the guild", "el gremio"),
    ("500 G", "500 G"), ("Gadola", "Gadola"), ("the boiler", "la caldera"),
    ("the mansion", "la mansión"), ("Key Items", "Objetos clave"),
]


def con_codigos():
    """Genera pares (en, es) con códigos colocados en posiciones equivalentes."""
    pares = []
    for en, es in FRASES:
        c = random.choice([2, 4, 5, 16, 20])
        pares.append((f"\\C[{c}]{en}\\C[0]", f"\\C[{c}]{es}\\C[0]"))
        pares.append((f"{en}\\!", f"{es}\\!"))
        pares.append((f"{en}\\.", f"{es}\\."))
    # Dos frases unidas por salto de línea literal \n
    for _ in range(40):
        (e1, s1), (e2, s2) = random.sample(FRASES, 2)
        pares.append((f"{e1}\\n{e2}", f"{s1}\\n{s2}"))
    # Palabra coloreada dentro de la frase
    for en_w, es_w in PALABRAS:
        c = random.choice([2, 4, 6, 14])
        pares.append((f"Bring me \\C[{c}]{en_w}\\C[0], please.", f"Tráeme \\C[{c}]{es_w}\\C[0], por favor."))
        pares.append((f"Did you find \\C[{c}]{en_w}\\C[0]?", f"¿Has encontrado \\C[{c}]{es_w}\\C[0]?"))
    # Iconos y variables
    pares += [
        ("You got \\I[176]Healing Potion x\\V[12]!", "¡Has conseguido \\I[176]Poción curativa x\\V[12]!"),
        ("You have \\V[5] G left.", "Te quedan \\V[5] G."),
        ("\\N[1] picked up the key.", "\\N[1] ha cogido la llave."),
        ("It costs \\C[17]\\V[30]\\C[0] G. Will you pay?", "Cuesta \\C[17]\\V[30]\\C[0] G. ¿Vas a pagar?"),
        ("Welcome, {name}!", "¡Bienvenida, {name}!"),
        ("Hmph. The only decent thing about him is his repair skills. We'll see how\\nlong it lasts.",
         "Bah. Lo único decente que tiene son sus dotes de reparación. Ya veremos cuánto\\ndura."),
    ]
    return pares


def correcciones_manuales():
    """Lee correcciones_*.csv / revision_*.csv con la columna 'correccion' rellenada."""
    pares = []
    for ruta in glob.glob("correcciones_*.csv") + glob.glob("revision_*.csv"):
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f, delimiter=";"):
                en = (fila.get("ingles") or "").strip()
                es = (fila.get("correccion") or "").strip()
                if en and es:
                    pares.append((en, es))
        print(f"  Correcciones leídas de {ruta}")
    return pares


def entrada(en, es):
    return {"instruction": INSTRUCCION, "input": en, "output": es}


def main():
    datos = []
    datos += [entrada(en, es) for en, es in TERMINOS.items()]
    datos += [entrada(en, es) for en, es in MENSAJES.items()]
    datos += [entrada(en, es) for en, es in FRASES]
    datos += [entrada(en, es) for en, es in con_codigos()]
    manuales = correcciones_manuales()
    # Las correcciones humanas valen más: se repiten 2 veces
    datos += [entrada(en, es) for en, es in manuales] * 2

    random.shuffle(datos)
    with open("glosario_v2.jsonl", "w", encoding="utf-8") as f:
        for d in datos:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"Glosario v2 creado: {len(datos)} ejemplos en 'glosario_v2.jsonl'")
    print(f"  Términos: {len(TERMINOS)} | Mensajes: {len(MENSAJES)} | "
          f"Con códigos: {len(con_codigos())} | Correcciones manuales: {len(manuales)}")


if __name__ == "__main__":
    main()
