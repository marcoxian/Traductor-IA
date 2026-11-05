"""dataset_genero.py — Corpus de entrenamiento con el género bien puesto y pistas de hablante.

Dos usos (con la ficha ``workspace/<juego>/personajes.json`` del juego del que sale el corpus):

1. ``--reparar``: corrige en el corpus la concordancia de género según quién habla. Ejemplo real del
   corpus de un juego: "Al,Sa,Op.¿Qué? Estoy confundido." (Ana, mujer) -> "confundida".
   El modelo aprendía de esos pares que las mujeres hablan en masculino. Se guarda copia ``.bak``.
2. ``--generar SALIDA.jsonl``: crea ejemplos con la MISMA instrucción que se usa al traducir
   (``CONTEXTO DEL JUEGO: <protagonista>`` + ``PERSONAJES: Habla Ana (mujer)...``) en el campo
   ``instruccion_completa``, que ``entrenar_v2.py`` respeta. Así el modelo aprende a usar la pista.
   Guárdalo en ``datasets/corpus_videojuegos/dataset_genero_<juego>.jsonl`` para que el
   entrenamiento lo use entero (no se submuestrea).

   Además de los ejemplos tal cual, genera "espejos" (solo si el cambio es limpio y el inglés no
   fija el género de esa persona: "sir", "my boyfriend", "Henry"...):
   - del HABLANTE: misma frase con el género de quien habla invertido ("Estoy lista" -> "Estoy listo").
   - de la PROTAGONISTA: la misma ficha con la protagonista del otro género (regla del contexto,
     pista y 2.ª persona: "¿Estás listo?" -> "¿Estás lista?"). Cubre lo que el corpus de un juego con
     protagonista hombre no tiene: alguien que le habla a una protagonista MUJER.
   - DOBLE: protagonista y hablante invertidos (un hombre que le habla a una mujer, desde las
     frases en que una mujer le habla a un hombre).

Sin ``--reparar`` ni ``--generar`` solo muestra cuántas líneas cambiarían (no escribe nada).

Uso:
    python herramientas_extra/dataset_genero.py --corpus datasets/corpus_videojuegos/dataset_extra_mi_juego.jsonl --juego mi_juego
    python herramientas_extra/dataset_genero.py --corpus ... --juego ... --reparar
    python herramientas_extra/dataset_genero.py --corpus ... --juego ... --generar datasets/corpus_videojuegos/dataset_genero_mi_juego.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from traductor import config, prompts  # noqa: E402
from traductor.genero import (HOMBRE, MUJER, corregir_primera_persona, corregir_segunda_persona,  # noqa: E402
                              marcas_genero, personas_con_genero_en)
from traductor.motores.rpgmaker import codigo_v21  # noqa: E402
from traductor.personajes import (MARCADORES_PROTAGONISTA, FichaPersonajes, InfoLinea, Personaje,  # noqa: E402
                                  aplicar_concordancia, limpiar_nombre, resolver_linea, ruta_ficha)
from traductor.texto import PATRON_PREFIJO_V21  # noqa: E402


def _campos(registro: dict) -> tuple[str, str] | None:
    """(clave inglés, clave español) del registro: input/output o ingles/espanol."""
    if isinstance(registro.get("input"), str) and isinstance(registro.get("output"), str):
        return "input", "output"
    if isinstance(registro.get("ingles"), str) and isinstance(registro.get("espanol"), str):
        return "ingles", "espanol"
    return None


def _separar_prefijo(texto: str) -> tuple[str, str, str | None]:
    """'Al,Sa,Op.¿Qué?' -> ('Al,Sa,Op.', '¿Qué?', 'Al')."""
    m = PATRON_PREFIJO_V21.match(texto)
    if not m:
        return "", texto, None
    return m.group(1) + ".", m.group(2), codigo_v21(m.group(1))


def _orden_estable(ejemplo: dict) -> str:
    """Orden determinista (por hash) para elegir siempre los mismos ejemplos neutros."""
    return hashlib.md5((ejemplo["input"] + "\x00" + ejemplo["instruccion_completa"]).encode("utf-8")).hexdigest()


def _opuesto(genero: str) -> str:
    return MUJER if genero == HOMBRE else HOMBRE


def _letra(genero: str) -> str:
    return "m" if genero == HOMBRE else "f"


def _ficha_invertida(ficha: FichaPersonajes, nombres: Iterable[str]) -> FichaPersonajes:
    """Copia de la ficha con el género (hombre/mujer) de los personajes ``nombres`` invertido. Si uno
    es el protagonista cambia también la regla del CONTEXTO ("Protagonista: X (mujer)...")."""
    nombres = set(nombres)
    datos = ficha.to_dict()
    for p in datos.get("personajes", []):
        if p.get("nombre") in nombres and p.get("genero") in (HOMBRE, MUJER):
            p["genero"] = _opuesto(p["genero"])
    return FichaPersonajes.from_dict(datos)


def _ficha_espejo(ficha: FichaPersonajes, personaje: Personaje) -> FichaPersonajes:
    """Copia de la ficha con el género de ``personaje`` invertido."""
    return _ficha_invertida(ficha, [personaje.nombre])


_MARCADORES_NEUTROS = {m.casefold() for m in MARCADORES_PROTAGONISTA}


def _ingles_fija_genero(en: str, p: Personaje) -> bool:
    """True si el inglés delata el género de ``p``: una palabra de persona de su género ("sir",
    "girl"...) o un nombre suyo que no sea un marcador neutro ("Henry" sí; "1Hero" o "\\N[1]" no)."""
    if p.genero in personas_con_genero_en(en):
        return True
    for n in p.nombres():
        limpio = limpiar_nombre(n)
        if len(limpio) >= 2 and limpio.casefold() not in _MARCADORES_NEUTROS \
                and re.search(rf"(?<![\w\\]){re.escape(limpio)}(?!\w)", en, re.IGNORECASE):
            return True
    return False


def _marcas_de(marcas: set[str], persona: str) -> set[str]:
    return {m for m in marcas if m.startswith(persona)}


def ejemplo_invertido(ficha: FichaPersonajes, nombres: Iterable[str], en: str, es: str,
                      info: InfoLinea | None, cache: dict | None = None,
                      etiqueta: str = "genero_invertido") -> dict | None:
    """El mismo ejemplo con el género de los personajes ``nombres`` invertido en la ficha, en la
    regla del protagonista, en la pista y en la traducción.

    Si habla uno de ellos se invierte la 1.ª persona; si se le habla, la 2.ª y los vocativos
    ("¿Estás listo, 1Hero?" -> "¿Estás lista, 1Hero?"). Devuelve None si la inversión no es limpia,
    si se nombra en 3.ª persona a alguien invertido ("1Hero is so tired": el inglés diría "he"), si
    la 2.ª persona puede ser de alguien invertido sin saberse a quién se habla, o si el inglés fija
    su género ("Thank you, sir", "Henry", "my boyfriend").
    """
    nombres = frozenset(nombres)
    ctx = resolver_linea(ficha, en, info)
    h = ctx.hablante
    if h is None or h.genero not in (HOMBRE, MUJER):
        return None
    d = ctx.destinatario if ctx.destinatario is not h else None
    invertidos = [p for p in ficha.personajes if p.nombre in nombres and p.genero in (HOMBRE, MUJER)]
    if not invertidos:
        return None
    nombrados = ficha.mencionados_en(en)
    for p in invertidos:
        if _ingles_fija_genero(en, p):
            return None
        if p in nombrados and p is not h and not (p is d and ctx.destinatario_explicito):
            return None  # se habla de él/ella en 3.ª persona
    marcas = marcas_genero(es)
    habla_invertido = h.nombre in nombres
    escucha_invertido = d is not None and d.nombre in nombres
    if d is None and _marcas_de(marcas, "2") and any(p is not h for p in invertidos):
        return None  # "¿estás listo?" sin saber a quién: podría ser a alguien invertido
    salida = es
    if habla_invertido:
        salida = corregir_primera_persona(salida, _opuesto(h.genero), en)
    if escucha_invertido:
        salida = corregir_segunda_persona(salida, _opuesto(d.genero))
    nuevas = marcas_genero(salida)
    for persona, invertido, p in (("1", habla_invertido, h), ("2", escucha_invertido, d)):
        if invertido:
            vieja, nueva = f"{persona}{_letra(p.genero)}", f"{persona}{_letra(_opuesto(p.genero))}"
            if vieja in nuevas or (vieja in marcas and nueva not in nuevas):
                return None
        elif _marcas_de(nuevas, persona) != _marcas_de(marcas, persona):
            return None
    clave = nombres
    invertida = cache.get(clave) if cache is not None else None
    if invertida is None:
        invertida = _ficha_invertida(ficha, nombres)
        if cache is not None:
            cache[clave] = invertida
    ctx_inv = resolver_linea(invertida, en, info)
    if ctx_inv.hablante is None or ctx_inv.hablante.nombre != h.nombre:
        return None
    if ctx_inv.hablante.genero != (_opuesto(h.genero) if habla_invertido else h.genero):
        return None
    pista = ctx_inv.ficha()
    if not pista:
        return None
    instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, invertida.regla_protagonista(),
                                                personajes=pista)
    return {"input": en, "output": salida, "instruccion_completa": instruccion, "contexto": etiqueta}


def ejemplo_espejo(ficha: FichaPersonajes, en: str, es: str, info: InfoLinea | None, ctx,
                   cache: dict[str, FichaPersonajes] | None = None) -> dict | None:
    """El mismo ejemplo con el género de QUIEN HABLA invertido en la pista y en la traducción.

    "I'm ready." + "Habla Jessica (mujer)" -> "Estoy lista." genera también
    "I'm ready." + "Habla Jessica (hombre)" -> "Estoy listo.". Así el modelo aprende que el género lo
    decide la pista y no el nombre ni un "masculino por defecto" (clave para protagonistas mujer).
    Solo se genera si la inversión es limpia (la 1.ª persona cambia entera de género).
    """
    h = ctx.hablante
    if h is None or h.genero not in (HOMBRE, MUJER):
        return None
    letra, letra_op = ("m", "f") if h.genero == HOMBRE else ("f", "m")
    if f"1{letra}" not in marcas_genero(es) or _ingles_fija_genero(en, h):
        return None  # "I'm a good girl" no puede decirlo un hombre
    opuesto = MUJER if h.genero == HOMBRE else HOMBRE
    salida = corregir_primera_persona(es, opuesto, en)
    marcas = marcas_genero(salida)
    if salida == es or f"1{letra_op}" not in marcas or f"1{letra}" in marcas:
        return None
    cache = cache if cache is not None else {}
    espejo = cache.get(h.nombre)
    if espejo is None:
        espejo = cache[h.nombre] = _ficha_espejo(ficha, h)
    ctx_espejo = resolver_linea(espejo, en, info)
    if ctx_espejo.hablante is None or ctx_espejo.hablante.genero != opuesto:
        return None
    instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, espejo.regla_protagonista(),
                                                personajes=ctx_espejo.ficha())
    return {"input": en, "output": salida, "instruccion_completa": instruccion, "contexto": "genero_hablante_espejo"}


def _clave(e: dict) -> tuple[str, str, str]:
    return e["input"], e["output"], e["instruccion_completa"]


def procesar(corpus: Path, ficha: FichaPersonajes, *, reparar: bool = False, generar: Path | None = None,
             proporcion_neutros: float = 1.0, espejo: bool = True, espejo_protagonista: bool = True) -> Counter:
    """Recorre el corpus JSONL. Devuelve estadísticas (líneas, corregidas, ejemplos...).

    Ejemplos generados: todos los que tienen marca de género en 1.ª/2.ª persona, su versión espejo
    (``espejo``) y ``proporcion_neutros`` ejemplos SIN marca por cada uno con marca (la pista no debe
    inventar género donde no lo hay). Los neutros se eligen de forma determinista.

    Con ``espejo_protagonista`` se añade la misma "familia" con la protagonista del otro género
    (espejo de la protagonista, doble espejo y sus neutros, con la misma proporción).
    """
    stats: Counter = Counter()
    contexto = ficha.regla_protagonista()
    registros: list[str] = []
    marcados: dict[tuple[str, str, str], dict] = {}
    espejos: dict[tuple[str, str, str], dict] = {}
    neutros: dict[tuple[str, str, str], dict] = {}
    fichas_espejo: dict[str, FichaPersonajes] = {}
    prota = ficha.protagonista()
    invertir_prota = espejo_protagonista and prota is not None and prota.genero in (HOMBRE, MUJER)
    espejos_prota: dict[tuple[str, str, str], dict] = {}
    dobles: dict[tuple[str, str, str], dict] = {}
    neutros_prota: dict[tuple[str, str, str], dict] = {}
    fichas_invertidas: dict = {}
    with open(corpus, encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                registros.append(linea)
                continue
            try:
                d = json.loads(linea)
            except json.JSONDecodeError:
                registros.append(linea)
                continue
            claves = _campos(d)
            if claves is None:
                registros.append(linea)
                continue
            stats["lineas"] += 1
            k_en, k_es = claves
            _, en, codigo = _separar_prefijo(d[k_en])
            pref_es, es, _ = _separar_prefijo(d[k_es])
            info = InfoLinea(codigo=codigo) if codigo else None
            ctx = resolver_linea(ficha, en, info)
            if ctx.vacio:
                registros.append(linea)
                continue
            stats["con_personaje"] += 1
            corregido = aplicar_concordancia(es, en, ctx)
            if corregido != es:
                stats["corregidas"] += 1
                if stats["corregidas"] <= 8:
                    print(f"  · {es[:60]!r} -> {corregido[:60]!r}  [{ctx.firma()[:50]}]")
                if reparar:
                    d[k_es] = pref_es + corregido
                    linea = json.dumps(d, ensure_ascii=False) + "\n"
            registros.append(linea if linea.endswith("\n") else linea + "\n")
            if generar is not None and ctx.ficha():
                instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, contexto, personajes=ctx.ficha())
                ejemplo = {"input": en, "output": corregido, "instruccion_completa": instruccion,
                           "contexto": "genero_hablante"}
                marcas = marcas_genero(corregido)
                if marcas:
                    marcados.setdefault((en, corregido, instruccion), ejemplo)
                    if espejo:
                        e = ejemplo_espejo(ficha, en, corregido, info, ctx, fichas_espejo)
                        if e is not None:
                            espejos.setdefault(_clave(e), e)
                    if invertir_prota:
                        e = ejemplo_invertido(ficha, [prota.nombre], en, corregido, info, fichas_invertidas,
                                              "genero_protagonista_espejo")
                        if e is not None:
                            espejos_prota.setdefault(_clave(e), e)
                        h = ctx.hablante
                        if (h is not None and h is not prota and h.genero in (HOMBRE, MUJER)
                                and f"1{_letra(h.genero)}" in marcas):
                            e = ejemplo_invertido(ficha, [prota.nombre, h.nombre], en, corregido, info,
                                                  fichas_invertidas, "genero_doble_espejo")
                            if e is not None:
                                dobles.setdefault(_clave(e), e)
                else:
                    neutros.setdefault((en, corregido, instruccion), ejemplo)
                    if invertir_prota:
                        e = ejemplo_invertido(ficha, [prota.nombre], en, corregido, info, fichas_invertidas,
                                              "genero_protagonista_espejo")
                        if e is not None:
                            neutros_prota.setdefault(_clave(e), e)
    if reparar and stats["corregidas"]:
        copia = corpus.with_name(corpus.name + ".bak")
        if not copia.exists():
            shutil.copy2(corpus, copia)
        tmp = corpus.with_name(corpus.name + ".tmp")
        tmp.write_text("".join(registros), encoding="utf-8")
        os.replace(tmp, corpus)
    if generar is not None:
        cupo = int(round(len(marcados) * max(proporcion_neutros, 0.0)))
        elegidos = sorted(neutros.values(), key=_orden_estable)[:cupo]
        ejemplos = list(marcados.values()) + list(espejos.values()) + elegidos
        # Familia con la protagonista invertida, sin repetir lo que ya está (el espejo del hablante
        # cuando habla la protagonista es el mismo ejemplo que su espejo de protagonista).
        vistos = {_clave(e) for e in ejemplos}
        nuevos_prota = [e for k, e in espejos_prota.items() if k not in vistos]
        vistos.update(_clave(e) for e in nuevos_prota)
        nuevos_dobles = [e for k, e in dobles.items() if k not in vistos]
        vistos.update(_clave(e) for e in nuevos_dobles)
        cupo_prota = int(round(len(nuevos_prota) * max(proporcion_neutros, 0.0)))
        neutros_elegidos = sorted((e for k, e in neutros_prota.items() if k not in vistos),
                                  key=_orden_estable)[:cupo_prota]
        ejemplos += nuevos_prota + nuevos_dobles + neutros_elegidos
        generar.parent.mkdir(parents=True, exist_ok=True)
        tmp = generar.with_name(generar.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for e in ejemplos:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, generar)
        stats["ejemplos"] = len(ejemplos)
        stats["ejemplos_con_genero"] = len(marcados)
        stats["ejemplos_espejo"] = len(espejos)
        stats["ejemplos_neutros"] = len(elegidos)
        stats["ejemplos_espejo_protagonista"] = len(nuevos_prota)
        stats["ejemplos_doble_espejo"] = len(nuevos_dobles)
        stats["ejemplos_neutros_protagonista"] = len(neutros_elegidos)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Repara el género de un corpus y genera ejemplos con pistas de hablante.")
    ap.add_argument("--corpus", required=True, help="Archivo JSONL (input/output o ingles/espanol)")
    ap.add_argument("--juego", required=True, help="Perfil en workspace/<juego>/ con personajes.json")
    ap.add_argument("--reparar", action="store_true", help="Corregir el corpus en su sitio (copia .bak)")
    ap.add_argument("--generar", help="Escribir aquí los ejemplos con instruccion_completa (JSONL)")
    ap.add_argument("--neutros", type=float, default=1.0,
                    help="Ejemplos con pista pero SIN marca de género por cada ejemplo con marca (por defecto 1.0)")
    ap.add_argument("--sin-espejo", action="store_true",
                    help="No generar la versión con el género del hablante invertido")
    ap.add_argument("--sin-espejo-protagonista", action="store_true",
                    help="No generar la versión con la protagonista del otro género (ni el doble espejo)")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"No existe el corpus: {corpus}")
        return 1
    juego = config.resolver_juego(args.juego)
    ficha = FichaPersonajes.cargar(ruta_ficha(config.carpeta_juego(juego)))
    if ficha is None:
        print(f"El perfil '{juego}' no tiene personajes.json: ejecuta antes 0_analizar_juego.py")
        return 2
    print(f"Ficha: {ficha.resumen()}")
    stats = procesar(corpus, ficha, reparar=args.reparar, generar=Path(args.generar) if args.generar else None,
                     proporcion_neutros=args.neutros, espejo=not args.sin_espejo,
                     espejo_protagonista=not args.sin_espejo_protagonista)
    print(f"Líneas: {stats['lineas']} | con personaje conocido: {stats['con_personaje']} | "
          f"con género corregible: {stats['corregidas']}{' (CORREGIDAS en el archivo)' if args.reparar else ''}")
    if args.generar:
        print(f"Ejemplos generados: {stats['ejemplos']} ({stats['ejemplos_con_genero']} con marca de género, "
              f"{stats['ejemplos_espejo']} espejo, {stats['ejemplos_neutros']} neutros; protagonista invertida: "
              f"{stats['ejemplos_espejo_protagonista']} espejo, {stats['ejemplos_doble_espejo']} doble, "
              f"{stats['ejemplos_neutros_protagonista']} neutros) -> {args.generar}")
    if not args.reparar and stats["corregidas"]:
        print("Para corregirlas en el corpus añade --reparar (se guarda una copia .bak).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
