"""crear_respaldo.py — Copia de seguridad comprimida (ZIP) de la traducción de un juego y de su perfil.

Guarda en ``backups/<perfil>_<fecha>.zip``:
  - los archivos traducidos del juego, según su motor: RPG Maker (``www/data`` o ``data``), Ren'Py (``game/tl``),
    Unity con XUnity (``BepInEx/Translation`` o ``AutoTranslator``) o CSV de idiomas (``*.csv`` y ``*.csv.original``);
  - la carpeta del perfil en ``workspace/<perfil>`` (ficha de personajes, glosarios, caché de traducciones...).

Uso:  python herramientas_extra/crear_respaldo.py --ruta "D:\\Juegos\\Mi juego"
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from traductor import config  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def carpetas_de_traduccion(ruta: Path) -> list[Path]:
    """Carpetas del juego que contienen su traducción (las que existan)."""
    candidatas = [ruta / "www" / "data", ruta / "data", ruta / "game" / "tl", ruta / "BepInEx" / "Translation",
                  ruta / "AutoTranslator"]
    return [c for c in candidatas if c.is_dir()]


def archivos_csv(ruta: Path) -> list[Path]:
    return [p for p in ruta.rglob("*.csv*") if p.suffix in (".csv", ".original") and p.is_file()]


def crear_respaldo(ruta: Path, destino: Path | None = None) -> Path:
    perfil = config.resolver_juego(None, ruta) or ruta.name
    destino = destino or (RAIZ / "backups" / f"{perfil}_{datetime.now():%Y%m%d_%H%M%S}.zip")
    destino.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for carpeta in carpetas_de_traduccion(ruta):
            for p in carpeta.rglob("*"):
                if p.is_file():
                    z.write(p, Path("juego") / p.relative_to(ruta))
                    n += 1
        if not carpetas_de_traduccion(ruta):
            for p in archivos_csv(ruta):
                z.write(p, Path("juego") / p.relative_to(ruta))
                n += 1
        carpeta_perfil = config.carpeta_juego(perfil)
        if carpeta_perfil.is_dir() and carpeta_perfil.name != "_comun":
            for p in carpeta_perfil.rglob("*"):
                if p.is_file():
                    z.write(p, Path("perfil") / p.relative_to(carpeta_perfil))
                    n += 1
    print(f"✔ Respaldo de '{perfil}': {n} archivos en {destino}")
    return destino


def main() -> int:
    ap = argparse.ArgumentParser(description="Copia de seguridad (ZIP) de la traducción de un juego y su perfil")
    ap.add_argument("--ruta", required=True, help="Carpeta del juego")
    ap.add_argument("--destino", help="Archivo .zip de salida (por defecto backups/<perfil>_<fecha>.zip)")
    args = ap.parse_args()
    ruta = Path(args.ruta)
    if not ruta.is_dir():
        print(f"✖ No existe la carpeta del juego: {ruta}")
        return 1
    crear_respaldo(ruta, Path(args.destino) if args.destino else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
