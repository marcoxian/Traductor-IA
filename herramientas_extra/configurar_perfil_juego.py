"""configurar_perfil_juego.py — Asistente de configuración de contexto para juegos nuevos.

Permite preparar o editar el contexto específico de cualquier juego (género del protagonista,
lista de personajes, sinopsis y reglas de traducción) antes o durante la traducción para que la IA
tenga siempre el máximo contexto posible y no cometa fallos de género ni modismos.

--protagonista/--genero también crean o actualizan el protagonista en ``personajes.json`` (la ficha
de personajes que usa el traductor) y lo marcan como confirmado para que el análisis automático
del Paso 0 no lo cambie.

Uso:
    python herramientas_extra/configurar_perfil_juego.py --listar
    python herramientas_extra/configurar_perfil_juego.py --juego <nombre> --protagonista "Carlos" --genero hombre
    python herramientas_extra/configurar_perfil_juego.py --juego <nombre> --ruta-juego "C:/Juegos/MiJuego"
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# Añadir raíz del proyecto al sys.path
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from traductor import config
from traductor.genero import DESCONOCIDO, normalizar_genero
from traductor.personajes import ARCHIVO_PERSONAJES, FichaPersonajes, Personaje
from traductor.registro import configurar_logging

log = logging.getLogger("configurar_perfil")


def listar_perfiles() -> None:
    print("\n=======================================================")
    print("[*] PERFILES DE JUEGO EN WORKSPACE")
    print("=======================================================")
    if not config.DIR_WORKSPACE.is_dir():
        print("No hay perfiles creados todavía.")
        return

    carpetas = sorted([d for d in config.DIR_WORKSPACE.iterdir() if d.is_dir() and not d.name.startswith("_")])
    if not carpetas:
        print("La carpeta workspace está vacía.")
        return

    for c in carpetas:
        tiene_ctx = (c / "contexto.txt").exists()
        glosario_count = len(config.cargar_json(c / "glosario.json", {}))
        print(f"• {c.name:30} | Contexto propio: {'SÍ' if tiene_ctx else 'NO '} | Términos: {glosario_count:<5} "
              f"| {describir_ficha(c)}")
    print("=======================================================\n")


def describir_ficha(carpeta: Path) -> str:
    """'Ficha: SÍ (12 personajes) | Protagonista: Noelia (mujer)' o 'Ficha: NO ...'."""
    ficha = FichaPersonajes.cargar(carpeta / ARCHIVO_PERSONAJES)
    if ficha is None:
        return "Ficha: NO  (sin personajes.json: protagonista en masculino por defecto)"
    prota = ficha.protagonista()
    if prota is None:
        return f"Ficha: SÍ ({len(ficha.personajes)} personajes) | Protagonista: ⚠ sin definir"
    aviso = "  ⚠ falta el género" if prota.genero == DESCONOCIDO else ""
    return f"Ficha: SÍ ({len(ficha.personajes)} personajes) | Protagonista: {prota.etiqueta()}{aviso}"


def actualizar_protagonista(carpeta: Path, nombre: str | None = None, genero: str | None = None) -> FichaPersonajes:
    """Crea o actualiza el protagonista en ``<carpeta>/personajes.json``.

    - Si ``nombre`` es otro personaje de la ficha, ese pasa a ser el protagonista (el anterior
      queda como principal). Si es un nombre nuevo, se renombra al protagonista y el nombre
      anterior se conserva como alias para seguir reconociéndolo.
    - ``genero`` admite hombre/mujer/neutro y las letras h/m/n (m = mujer).
    - Queda ``confirmado`` (el análisis automático ya no lo cambia) salvo que su género siga
      siendo desconocido, para que el Centro de Control siga avisando de que falta.
    """
    ruta = carpeta / ARCHIVO_PERSONAJES
    ficha = FichaPersonajes.cargar(ruta) or FichaPersonajes(titulo=carpeta.name.replace("_", " ").title())
    nombre = (nombre or "").strip()
    prota = ficha.protagonista()
    if nombre:
        existente = ficha.buscar(nombre)
        if existente is not None and existente is not prota:
            if prota is not None:
                prota.rol = "principal"
            existente.rol = "protagonista"
            prota = existente
        elif prota is None:
            prota = Personaje(nombre=nombre, rol="protagonista")
            ficha.personajes.append(prota)
        elif existente is None and prota.nombre != nombre:
            anteriores = [prota.nombre, *prota.alias] if prota.nombre != "Protagonista" else list(prota.alias)
            prota.alias = [a for a in dict.fromkeys(anteriores) if a and a != nombre]
            prota.nombre = nombre
    elif prota is None:
        prota = Personaje(nombre="Protagonista", rol="protagonista")
        ficha.personajes.append(prota)
    if genero:
        prota.genero = normalizar_genero(genero, convencion="es")
    if prota.genero != DESCONOCIDO:
        prota.confirmado = True
        prota.confianza = 1.0
    ficha.reindexar()
    ficha.guardar(ruta)
    return ficha


def configurar_perfil(juego: str,
                       ruta_juego: str | None = None,
                       protagonista: str | None = None,
                       genero: str | None = None,
                       sinopsis: str | None = None) -> None:
    carpeta = config.inicializar_perfil_nuevo(juego, ruta_juego)
    p_contexto = carpeta / "contexto.txt"

    contenido_actual = p_contexto.read_text(encoding="utf-8") if p_contexto.exists() else ""
    lineas = contenido_actual.splitlines()

    gen_desc = "Hombre" if (genero and genero.lower().startswith("h")) else ("Mujer" if (genero and genero.lower().startswith("m")) else None)

    modificado = False
    nuevas_lineas = []
    encontro_prota = False

    for l in lineas:
        if l.strip().startswith("- Protagonista:"):
            encontro_prota = True
            prota_final = protagonista or (l.split(":", 1)[1].strip() if ":" in l else "Hombre")
            # Sin duplicar la anotación anterior: "X (Género: Hombre)" / "X (Hombre por defecto)"
            prota_final = re.sub(r"\s*\((?:G[ée]nero:[^)]*|[^)]*por defecto[^)]*)\)\s*$", "", prota_final)
            if gen_desc:
                nuevas_lineas.append(f"- Protagonista: {prota_final} (Género: {gen_desc})")
            else:
                nuevas_lineas.append(f"- Protagonista: {prota_final}")
            modificado = True
        elif l.strip().startswith("- Sinopsis") and sinopsis:
            nuevas_lineas.append(f"- Sinopsis: {sinopsis}")
            modificado = True
        else:
            nuevas_lineas.append(l)

    if not encontro_prota and (protagonista or gen_desc):
        prota_txt = protagonista or "Protagonista"
        if gen_desc:
            prota_txt += f" (Género: {gen_desc})"
        nuevas_lineas.append(f"- Protagonista: {prota_txt}")
        modificado = True

    if modificado or not p_contexto.exists():
        p_contexto.write_text("\n".join(nuevas_lineas) + "\n", encoding="utf-8")

    print("\n[OK] Perfil configurado con éxito en:", carpeta)
    print("-------------------------------------------------------")
    print(p_contexto.read_text(encoding="utf-8"))
    print("-------------------------------------------------------")

    if protagonista or genero:
        ficha = actualizar_protagonista(carpeta, protagonista, genero)
        prota = ficha.protagonista()
        print(f"[OK] Ficha de personajes actualizada: {carpeta / ARCHIVO_PERSONAJES}")
        print(f"     Protagonista: {prota.etiqueta()}{' (confirmado)' if prota.confirmado else ''}")
        if prota.genero == DESCONOCIDO:
            print("     ⚠ Falta el género del protagonista: añade --genero hombre|mujer|neutro")
    print(f"     {describir_ficha(carpeta)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configuración y enriquecimiento de contexto para juegos")
    parser.add_argument("--listar", action="store_true", help="Lista todos los perfiles existentes")
    parser.add_argument("--juego", type=str, help="Nombre del juego o carpeta en workspace")
    parser.add_argument("--ruta-juego", type=str, help="Ruta de la carpeta del juego a escanear")
    parser.add_argument("--protagonista", type=str, help="Nombre del protagonista")
    parser.add_argument("--genero", type=str, choices=["hombre", "mujer", "neutro", "h", "m", "n"],
                        help="Género del protagonista (h = hombre, m = mujer, n = neutro)")
    parser.add_argument("--sinopsis", type=str, help="Breve descripción de la historia o detalles")

    args = parser.parse_args()

    if args.listar:
        listar_perfiles()
        return

    if not args.juego and not args.ruta_juego:
        listar_perfiles()
        print("Usa --juego <nombre> o --ruta-juego <ruta> para configurar un perfil.")
        return

    nombre_juego = args.juego or (Path(args.ruta_juego).name if args.ruta_juego else "nuevo_juego")
    configurar_perfil(nombre_juego, args.ruta_juego, args.protagonista, args.genero, args.sinopsis)


if __name__ == "__main__":
    main()
