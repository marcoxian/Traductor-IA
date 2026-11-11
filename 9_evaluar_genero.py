"""9_evaluar_genero.py — ¿Respeta el modelo el género de quien habla? (banco de pruebas)

Toma frases REALES de tus juegos con hablante conocido (según su ``personajes.json``) en las que el
español tiene que marcar el género de quien habla ("I'm so tired" -> "cansado" / "cansada") y las
traduce con Ollama en tres condiciones:

  A. antes      prompt de antes de la ficha (contexto antiguo, sin pistas de personajes)
  B. con pista  contexto con la ficha + "PERSONAJES: Habla Ana (mujer)..."  (solo el modelo)
  C. pipeline   B + la concordancia determinista (lo que de verdad acaba en el juego)
  D. sin hablante (``--sin-hablante``): con ficha pero sin saber quién habla, como en Unity/XUnity

Mide el % de frases con el género CONTRARIO al de quien habla (y cuántas salen neutras, sin marca).
Guarda el resultado en ``workspace/_evaluaciones/`` para comparar modelos (p. ej. antes y después de
reentrenar). No uses juegos con los que se haya entrenado el modelo: la medida saldría inflada.

Juegos que se prueban: los de ``--juego perfil=RUTA`` o, si no se indica ninguno, los de
``workspace/_evaluaciones/juegos.json`` ({"perfil": "ruta de la carpeta del juego"}).

Uso:
    python 9_evaluar_genero.py --modelo IA_Traductora_v4 --por-genero 30
    python 9_evaluar_genero.py --juego mi_juego="D:\\Juegos\\Mi juego"
    python 9_evaluar_genero.py --solo-casos                      # lista las frases, sin llamar a Ollama
    python 9_evaluar_genero.py --comparar workspace/_evaluaciones/A.json workspace/_evaluaciones/B.json

Banco FIJO (``--banco``): ~95 frases y personajes inventados (``tests/datos/banco_traduccion.json``) por
categorías (género, a quién se habla, tú/usted, prohibiciones, frases hechas, palabras de España, dos
sentidos, opciones de menú...). No necesita juegos y sirve para comparar modelos (p. ej. v4 y v6).
    python 9_evaluar_genero.py --banco --modelo IA_Traductora_v4
    python 9_evaluar_genero.py --comparar workspace/_evaluaciones/banco_A.json workspace/_evaluaciones/banco_B.json

Prueba ESPEJO (``--invertir-protagonista``): el mismo juego con el protagonista del otro género. Mide con
muchas frases lo que más cuesta: un hombre que le habla a una protagonista mujer. Solo B y C (el contexto
antiguo de A diría lo contrario que la ficha).
    python 9_evaluar_genero.py --juego mi_juego --invertir-protagonista
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from traductor import config, prompts, xunity
from traductor.csv_locales import analizar_cabecera, leer_lineas, partir
from traductor.genero import HOMBRE, MUJER, contradice_genero, marcas_genero
from traductor.motores.rpgmaker import InyectorRPGMaker
from traductor.ollama import OllamaNoDisponible, OllamaTranslator
from traductor.personajes import (FichaPersonajes, InfoLinea, aplicar_concordancia, es_pensamiento,
                                  resolver_linea)
from traductor.registro import configurar_logging
from traductor.texto import (PATRON_CODIGOS, PATRON_NOMBRE_HABLANTE, PATRON_PREFIJO, evaluar_traduccion,
                             limpiar_respuesta, nombres_perdidos, separar_envoltorio, tiene_fallo_grave)

log = logging.getLogger("evaluar_genero")

# perfil de workspace -> carpeta del juego, de workspace/_evaluaciones/juegos.json (cada usuario, los suyos).
ARCHIVO_JUEGOS = config.DIR_WORKSPACE / "_evaluaciones" / "juegos.json"


def _juegos_por_defecto() -> dict[str, Path]:
    datos = config.cargar_json(ARCHIVO_JUEGOS, {})
    return {perfil: Path(ruta) for perfil, ruta in (datos.items() if isinstance(datos, dict) else ())
            if isinstance(ruta, str) and not perfil.startswith("_")}


JUEGOS_POR_DEFECTO = _juegos_por_defecto()
CONDICIONES = ("A_antes", "B_con_pista", "C_pipeline", "D_sin_hablante")
NOMBRES_CONDICION = {"A_antes": "A. antes (sin ficha)", "B_con_pista": "B. con pista (modelo)",
                     "C_pipeline": "C. pipeline completo", "D_sin_hablante": "D. sin hablante (Unity)"}

# Adjetivos ingleses que en español marcan el género de quien habla.
_ADJ_EN = (
    "tired|exhausted|ready|sure|certain|scared|frightened|terrified|worried|confused|excited|surprised|"
    "nervous|busy|alone|impressed|embarrassed|ashamed|curious|jealous|married|angry|mad|upset|interested|"
    "disappointed|convinced|lost|drunk|naked|wet|sick|stuck|bored|crazy|satisfied|relieved|shocked|horny|"
    "aroused|prepared|honored|honoured|flattered|grateful|thankful|serious|done|finished|dead|safe|"
    "pregnant|focused|amazed|annoyed|offended|obsessed|addicted|desperate|hurt|injured|trapped|screwed|"
    "fucked|soaked|stunned|frozen|tied|locked|spoiled|blessed"
)
_EN_1P_ADJ = re.compile(
    r"\bI(?:['’]m|\s+am|\s+was|['’]ve\s+been|\s+have\s+been|\s+feel|\s+felt)\s+"
    r"(?:(?:not|so|very|really|too|a\s+bit|a\s+little|kinda|kind\s+of|pretty|quite|just|still|already|"
    r"completely|totally|getting|always|never|also|definitely|absolutely|super|extremely|incredibly|"
    r"fucking|damn|all|more|less|that)\s+)*(?P<adj>" + _ADJ_EN + r")\b",
    re.IGNORECASE,
)
_MAX_CARACTERES = 220


@dataclass
class Caso:
    """Una frase de prueba: original en inglés, quién la dice y su género."""

    juego: str
    archivo: str
    original: str
    hablante: str
    genero: str
    pensamiento: bool = False
    info: InfoLinea | None = field(default=None, repr=False)
    resultados: dict = field(default_factory=dict)
    es_protagonista: bool = False

    def a_dict(self) -> dict:
        return {"juego": self.juego, "archivo": self.archivo, "original": self.original,
                "hablante": self.hablante, "genero": self.genero, "pensamiento": self.pensamiento,
                "es_protagonista": self.es_protagonista, "resultados": self.resultados}


def es_frase_de_prueba(texto: str) -> bool:
    """¿El español tendrá que marcar el género de quien habla? ("I'm not sure" -> "seguro/segura")."""
    return bool(texto) and len(texto) <= _MAX_CARACTERES and bool(_EN_1P_ADJ.search(texto))


def _caso(juego: str, archivo: str, ficha: FichaPersonajes, texto: str, info: InfoLinea | None) -> Caso | None:
    if not es_frase_de_prueba(texto):
        return None
    ctx = resolver_linea(ficha, texto, info)
    h = ctx.hablante
    if h is None or h.genero not in (HOMBRE, MUJER):
        return None
    return Caso(juego, archivo, texto, h.nombre, h.genero, ctx.pensamiento, info,
                es_protagonista=h.es_protagonista)


# --------------------------------------------------------------------------- Recogida de frases
def _es_rpgmaker(ruta: Path) -> bool:
    """¿Tiene carpeta de datos de RPG Maker (``www/data`` o ``data``)? Se mira antes de crear el inyector,
    que avisa con un ERROR si no la encuentra (y aquí se prueba con todos los juegos)."""
    return (ruta / "www" / "data").is_dir() or (ruta / "data").is_dir()


def casos_rpgmaker(juego: str, ruta: Path, ficha: FichaPersonajes) -> list[Caso]:
    """Originales en inglés (``*.json.bak``) con el hablante que da el motor (caja, código de hablante, cara...)."""
    if not _es_rpgmaker(ruta):
        return []
    inyector = InyectorRPGMaker(ruta, None)
    carpeta = inyector.obtener_carpeta_datos()
    if carpeta is None:
        return []
    casos = []
    for bak in sorted(carpeta.glob("*.json.bak")):
        try:
            datos = json.loads(bak.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        for texto, info in inyector.extraer_con_info(datos):
            c = _caso(juego, bak.name, ficha, texto, info)
            if c is not None:
                casos.append(c)
    return casos


def casos_csv(juego: str, ruta: Path, ficha: FichaPersonajes) -> list[Caso]:
    """``*.csv.original`` de localización con caja de nombre ``\\N<Nombre>`` (DKTools...)."""
    casos = []
    vistos: set[Path] = set()
    for original in sorted(ruta.rglob("*.csv.original")):
        if original.name != "main.csv.original" and any(p.name == "main.csv.original" for p in vistos):
            continue  # copias de seguridad con otro nombre: mismas frases
        vistos.add(original)
        _, lineas = leer_lineas(original)
        if not lineas:
            continue
        delim, _, col = analizar_cabecera(lineas)
        if col is None:
            continue
        for linea in lineas[1:]:
            partes, _ = partir(linea, delim)
            if len(partes) <= col:
                continue
            celda = partes[col]
            m = PATRON_NOMBRE_HABLANTE.match(celda)
            if not m:
                continue
            p = PATRON_PREFIJO.match(celda)
            texto = celda[p.end():] if p else celda
            c = _caso(juego, original.name, ficha, texto.replace("\\n", " ").strip(),
                      InfoLinea(hablante=m.group(2)))
            if c is not None:
                casos.append(c)
        if casos:
            break  # con un CSV completo basta (los demás suelen ser copias)
    return casos


def casos_xunity(juego: str, ruta: Path, ficha: FichaPersonajes) -> list[Caso]:
    """XUnity no dice quién habla: solo pensamientos "(...)", que son del protagonista."""
    casos = []
    for base in (ruta / "BepInEx" / "Translation", ruta / "Translation", ruta / "AutoTranslator"):
        for txt in sorted(base.glob("*/Text/_AutoGeneratedTranslations.txt")) if base.is_dir() else []:
            vistos = set()
            for original, _ in xunity.leer_pares(txt):
                if original in vistos or not es_pensamiento(original):
                    continue
                vistos.add(original)
                c = _caso(juego, txt.name, ficha, original, None)
                if c is not None:
                    casos.append(c)
    return casos


def textos_juego(ruta: Path) -> list[tuple[str, InfoLinea | None]]:
    """Todos los textos originales (en inglés) de un juego, con lo que sepa el motor de cada uno:
    RPG Maker (``*.json.bak``), CSV de localización (``main.csv.original``) o claves de XUnity."""
    inyector = InyectorRPGMaker(ruta, None) if _es_rpgmaker(ruta) else None
    carpeta = inyector.obtener_carpeta_datos() if inyector is not None else None
    textos: list[tuple[str, InfoLinea | None]] = []
    if carpeta is not None:
        for bak in sorted(carpeta.glob("*.json.bak")):
            try:
                textos += inyector.extraer_con_info(json.loads(bak.read_text(encoding="utf-8-sig")))
            except (OSError, json.JSONDecodeError):
                continue
    en_ingles = sum(1 for t, _ in textos[:1000] if len(re.findall(r"[A-Za-z]{2,}", t)) >= 3)
    if en_ingles < 0.3 * min(len(textos), 1000):  # sin textos o en chino/japonés: el inglés está en CSV
        textos = []
        for original in sorted(ruta.rglob("main.csv.original"))[:1]:
            _, lineas = leer_lineas(original)
            delim, _, col = analizar_cabecera(lineas) if lineas else (None, None, None)
            for linea in (lineas[1:] if col is not None else []):
                partes, _ = partir(linea, delim)
                if len(partes) > col:
                    p = PATRON_PREFIJO.match(partes[col])
                    m = PATRON_NOMBRE_HABLANTE.match(partes[col])
                    texto = (partes[col][p.end():] if p else partes[col]).replace("\\n", " ").strip()
                    textos.append((texto, InfoLinea(hablante=m.group(2)) if m else None))
    if not textos:
        for base in (ruta / "BepInEx" / "Translation", ruta / "Translation", ruta / "AutoTranslator"):
            for txt in sorted(base.glob("*/Text/_AutoGeneratedTranslations.txt")) if base.is_dir() else []:
                textos += [(o, None) for o, _ in xunity.leer_pares(txt)]
    return textos


def muestra_general(ruta: Path, n: int) -> list[tuple[str, InfoLinea | None]]:
    """``n`` frases cualesquiera (de diálogo o interfaz) para medir la calidad general, deterministas."""
    unicos: dict[str, InfoLinea | None] = {}
    for texto, info in textos_juego(ruta):
        if 12 <= len(texto) <= _MAX_CARACTERES and len(re.findall(r"[A-Za-z]{2,}", texto)) >= 3:
            unicos.setdefault(texto, info)
    orden = sorted(unicos, key=lambda t: hashlib.md5(t.encode("utf-8")).hexdigest())
    return [(t, unicos[t]) for t in orden[:n]]


def recoger_casos(juego: str, ruta: Path, ficha: FichaPersonajes, por_genero: int) -> list[Caso]:
    """Frases de prueba de un juego, equilibradas por género de quien habla (deterministas)."""
    casos = casos_rpgmaker(juego, ruta, ficha) or casos_csv(juego, ruta, ficha) or casos_xunity(juego, ruta, ficha)
    unicos: dict[str, Caso] = {}
    for c in casos:
        unicos.setdefault(c.original, c)
    por_grupo: dict[str, list[Caso]] = defaultdict(list)
    for c in unicos.values():
        por_grupo[c.genero].append(c)
    elegidos = []
    for genero in (HOMBRE, MUJER):
        grupo = sorted(por_grupo[genero], key=lambda c: hashlib.md5(c.original.encode("utf-8")).hexdigest())
        elegidos += grupo[:por_genero]
    return elegidos


# --------------------------------------------------------------------------- Evaluación
def puntuar(traduccion: str, genero: str) -> str:
    """'contrario' (error), 'correcto' (marca el género de quien habla) o 'neutra' (sin marca)."""
    if contradice_genero(traduccion, "1", genero):
        return "contrario"
    letra = "m" if genero == HOMBRE else "f"
    return "correcto" if f"1{letra}" in marcas_genero(traduccion) else "neutra"


def invertir_protagonista(perfil: config.Perfil) -> config.Perfil | None:
    """El mismo perfil con la protagonista del otro género (ficha y regla del contexto); None si no se
    conoce su género. El contexto propio del juego se quita porque suele repetir el género original
    ("Protagonista masculino: 1Hero..."): queda la regla de la ficha + el contexto global."""
    ficha = perfil.personajes
    prota = ficha.protagonista() if ficha is not None else None
    if prota is None or prota.genero not in (HOMBRE, MUJER):
        return None
    datos = ficha.to_dict()
    for p in datos["personajes"]:
        if p.get("nombre") == prota.nombre:
            p["genero"] = MUJER if prota.genero == HOMBRE else HOMBRE
    invertida = FichaPersonajes.from_dict(datos)
    contexto = " ".join(c for c in (invertida.regla_protagonista(),
                                     config.leer_contexto(config.CONTEXTO_GLOBAL, con_ficha=True)) if c)
    return dataclasses.replace(perfil, personajes=invertida, contexto=contexto)


class Evaluador:
    """Traduce cada frase como lo haría el pipeline (mismo prompt, limpieza y afinado), sin caché.

    ``con_antes=False`` no calcula la condición A (en la prueba espejo no tiene sentido).
    ``sin_hablante=True`` añade la condición D: la ficha del juego está, pero no se sabe quién habla
    (como en Unity/XUnity, donde solo se deduce el hablante de los pensamientos entre paréntesis)."""

    def __init__(self, modelo: str, perfil: config.Perfil, con_antes: bool = True, sin_hablante: bool = False):
        self.perfil = perfil
        self.con_antes = con_antes
        self.sin_hablante = sin_hablante
        self.perfil_antes = dataclasses.replace(perfil, contexto=perfil.contexto_legacy or perfil.contexto,
                                                personajes=None)
        self.t_ficha = OllamaTranslator(model_name=modelo, perfil=perfil, ruta_cache=None)
        self.t_antes = OllamaTranslator(model_name=modelo, perfil=self.perfil_antes, ruta_cache=None)

    @staticmethod
    def _traducir(t: OllamaTranslator, texto: str, contexto: str, personajes: str = "") -> str:
        prefijo, nucleo, sufijo = separar_envoltorio(texto)
        instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, contexto, t.perfil.terminos_para(texto),
                                                    personajes=personajes)
        respuesta = t._generar(prompts.formatear(instruccion, nucleo), t._tokens_para(nucleo, 180), temperature=0.1)
        limpio = limpiar_respuesta(respuesta or "", nucleo) or nucleo
        candidato = f"{prefijo}{limpio}{sufijo}" if (prefijo or sufijo) else limpio
        return t._afinar_salida(texto, candidato)

    def evaluar(self, caso: Caso) -> dict:
        ctx = resolver_linea(self.perfil.personajes, caso.original, caso.info)
        caso.resultados = {}
        if self.con_antes:
            a = self._traducir(self.t_antes, caso.original, self.perfil_antes.contexto)
            caso.resultados["A_antes"] = {"traduccion": a, "nota": puntuar(a, caso.genero)}
        b = self._traducir(self.t_ficha, caso.original, self.perfil.contexto, ctx.ficha())
        c = aplicar_concordancia(b, caso.original, ctx)
        caso.resultados["B_con_pista"] = {"traduccion": b, "nota": puntuar(b, caso.genero), "pista": ctx.ficha()}
        caso.resultados["C_pipeline"] = {"traduccion": c, "nota": puntuar(c, caso.genero)}
        if self.sin_hablante:
            # Lo que acaba en el juego cuando el motor no dice quién habla: misma ficha y concordancia,
            # pero el hablante solo se conoce si la línea es un pensamiento (del protagonista).
            ctx0 = resolver_linea(self.perfil.personajes, caso.original, None)
            d = aplicar_concordancia(self._traducir(self.t_ficha, caso.original, self.perfil.contexto, ctx0.ficha()),
                                     caso.original, ctx0)
            caso.resultados["D_sin_hablante"] = {"traduccion": d, "nota": puntuar(d, caso.genero), "pista": ctx0.ficha()}
        return caso.resultados

    def calidad(self, texto: str, info: InfoLinea | None) -> dict:
        """Calidad del PRIMER intento del modelo (como en B) según la puerta de calidad del pipeline."""
        ctx = resolver_linea(self.perfil.personajes, texto, info)
        traduccion = self._traducir(self.t_ficha, texto, self.perfil.contexto, ctx.ficha())
        problemas = evaluar_traduccion(texto, traduccion)
        ficha = self.perfil.personajes
        if ficha is not None and nombres_perdidos(traduccion, ficha.nombres_en(texto), self.perfil.terminos_para(texto)):
            problemas.append("nombre_perdido")  # leve: el pipeline reintenta, pero cuenta como fallo del modelo
        return {"original": texto, "traduccion": traduccion, "problemas": problemas,
                "grave": tiene_fallo_grave(problemas)}

    def cerrar(self) -> None:
        self.t_ficha.cerrar()
        self.t_antes.cerrar()


def resumir_calidad(resultados: list[dict]) -> dict:
    problemas = Counter(p for r in resultados for p in r["problemas"])
    return {"total": len(resultados), "con_fallo_grave": sum(1 for r in resultados if r["grave"]),
            "problemas": dict(problemas.most_common())}


def tabla_calidad(r: dict) -> str:
    if not r or not r.get("total"):
        return ""
    comunes = ", ".join(f"{k} {v}" for k, v in list(r["problemas"].items())[:6]) or "ninguno"
    return (f"Calidad general (primer intento, con pista): {r['total']} frases, "
            f"{_pct(r['con_fallo_grave'], r['total']).strip()} con fallos graves | problemas: {comunes}")


def _contar(casos: list[Caso], cond: str) -> dict:
    n = Counter(c.resultados[cond]["nota"] for c in casos if cond in c.resultados)
    return {"total": sum(n.values()), **{k: n[k] for k in ("contrario", "correcto", "neutra")}}


def resumir(casos: list[Caso]) -> dict:
    resumen: dict = {}
    for cond in CONDICIONES:
        resumen[cond] = {
            **_contar(casos, cond),
            "por_genero": {g: _contar([c for c in casos if c.genero == g], cond) for g in (HOMBRE, MUJER)},
            "por_rol": {"protagonista": _contar([c for c in casos if c.es_protagonista], cond),
                        "otro": _contar([c for c in casos if not c.es_protagonista], cond)},
        }
    return resumen


def _pct(parte: int, total: int) -> str:
    return f"{parte:4d} ({100.0 * parte / total:5.1f} %)" if total else "   -"


def tabla(resumen: dict, titulo: str = "") -> str:
    lineas = [titulo] if titulo else []
    lineas.append(f"{'Condición':26} {'frases':>6}   {'género CONTRARIO':>16}   {'género correcto':>16}   {'neutras':>14}")
    for cond in CONDICIONES:
        r = resumen.get(cond)
        if not r or not r.get("total"):
            continue
        lineas.append(f"{NOMBRES_CONDICION[cond]:26} {r['total']:6d}   {_pct(r['contrario'], r['total']):>16}   "
                      f"{_pct(r['correcto'], r['total']):>16}   {_pct(r['neutra'], r['total']):>14}")
    grupos = [("por_genero", g, f"habla un/a {g:6}") for g in (HOMBRE, MUJER)]
    grupos += [("por_rol", "protagonista", "habla la protagonista"), ("por_rol", "otro", "habla otro personaje")]
    for clave, grupo, nombre in grupos:
        partes = []
        for cond in CONDICIONES:
            g = resumen.get(cond, {}).get(clave, {}).get(grupo)
            if g and g["total"]:
                partes.append(f"{cond[0]} {100.0 * g['contrario'] / g['total']:.1f} % de {g['total']}")
        if partes:
            lineas.append(f"  {nombre:22}: género contrario  " + " | ".join(partes))
    return "\n".join(lineas)


def comparar(rutas: list[Path]) -> str:
    datos = [json.loads(r.read_text(encoding="utf-8")) for r in rutas]
    salida = [tabla(d["resumen"], f"== {d['modelo']} ({d['fecha']}, {r.name})")
              + ("\n" + tabla_calidad(d["calidad"]["resumen"]) if d.get("calidad") else "")
              for d, r in zip(datos, rutas)]
    if len(datos) == 2:
        antes = {c["original"]: c for c in datos[0]["casos"]}
        cambios = []
        for c in datos[1]["casos"]:
            previo = antes.get(c["original"])
            if previo is None:
                continue
            n0, n1 = previo["resultados"]["B_con_pista"]["nota"], c["resultados"]["B_con_pista"]["nota"]
            if n0 != n1:
                cambios.append(f"  [{c['hablante']} ({c['genero']})] {n0} -> {n1}: {c['original'][:70]}")
        salida.append(f"Frases que cambian en B (con pista): {len(cambios)}")
        salida += cambios[:40]
    return "\n\n".join(salida[:len(datos)]) + ("\n\n" + "\n".join(salida[len(datos):]) if len(salida) > len(datos) else "")


# --------------------------------------------------------------------------- Banco fijo (frases inventadas)
# Mide lo mismo en cualquier modelo y en cualquier momento: frases y personajes inventados, con lo que DEBE
# y NO DEBE salir. Dos condiciones: "modelo" (primer intento, sin arreglos: lo que sabe el modelo) y
# "pipeline" (traductor completo: reintentos, concordancia, arreglos de España...; lo que acaba en el juego).
BANCO_POR_DEFECTO = Path(__file__).resolve().parent / "tests" / "datos" / "banco_traduccion.json"
CONDICIONES_BANCO = ("modelo", "pipeline")
_PALABRA = re.compile(r"[^\W\d_]+")


def cargar_banco(ruta: Path) -> tuple[dict, FichaPersonajes]:
    """Lee el banco (JSON) y su ficha de personajes inventada. Valida los casos (expresiones y nombres)."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    ficha = FichaPersonajes.from_dict({"personajes": datos.get("personajes", [])})
    ids = set()
    for c in datos.get("casos", []):
        if c["id"] in ids:
            raise ValueError(f"Caso repetido en el banco: {c['id']}")
        ids.add(c["id"])
        for patron in c.get("debe", []) + c.get("no_debe", []):
            re.compile(patron, re.IGNORECASE)
        for clave in ("hablante", "oyente"):
            if c.get(clave) and ficha.buscar(c[clave]) is None:
                raise ValueError(f"{c['id']}: '{c[clave]}' no está en los personajes del banco")
    return datos, ficha


def perfil_banco(datos: dict, ficha: FichaPersonajes) -> config.Perfil:
    """Perfil global (glosarios de siempre) con la ficha y el contexto del banco, como un juego más."""
    base = config.cargar_perfil(None, auto_crear=False)
    contexto = " ".join(c for c in (ficha.regla_protagonista(),
                                     config.leer_contexto(config.CONTEXTO_GLOBAL, con_ficha=True),
                                     datos.get("contexto", "")) if c)
    return dataclasses.replace(base, juego="_banco", personajes=ficha, contexto=contexto)


def info_caso(caso: dict) -> InfoLinea:
    return InfoLinea(hablante=caso.get("hablante"), oyente=caso.get("oyente"), es_opcion=bool(caso.get("opcion")))


def puntuar_banco(caso: dict, traduccion: str) -> list[str]:
    """Fallos de una traducción del banco (vacío = bien)."""
    t = (traduccion or "").strip()
    if not t or t == caso["en"].strip():
        return ["sin traducir"]
    fallos = []
    for persona, clave in (("1", "genero_1p"), ("2", "genero_2p")):
        if caso.get(clave) and contradice_genero(t, persona, caso[clave]):
            fallos.append(f"género {persona}.ª persona")
    fallos += [f"falta /{p}/" for p in caso.get("debe", []) if not re.search(p, t, re.IGNORECASE)]
    fallos += [f"sobra /{p}/" for p in caso.get("no_debe", []) if re.search(p, t, re.IGNORECASE)]
    if caso.get("max_palabras") and len(_PALABRA.findall(PATRON_CODIGOS.sub(" ", t))) > caso["max_palabras"]:
        fallos.append("demasiado larga")
    return fallos


class EvaluadorBanco:
    """Traduce los casos del banco en las dos condiciones (sin caché ni historial)."""

    def __init__(self, modelo: str, perfil: config.Perfil):
        self.perfil = perfil
        self.t = OllamaTranslator(model_name=modelo, perfil=perfil, ruta_cache=None, usar_historial=False)
        self.t.semilla = 42  # sin ruido de una pasada a otra: así se comparan dos modelos de verdad

    def modelo(self, caso: dict) -> str:
        """Primer intento del modelo con el prompt de hoy (ficha, glosario y pistas), solo con la limpieza
        de la respuesta: sin reintentos ni arreglos."""
        texto = caso["en"]
        ctx = resolver_linea(self.perfil.personajes, texto, info_caso(caso))
        prefijo, nucleo, sufijo = separar_envoltorio(texto)
        instruccion = prompts.construir_instruccion(prompts.INSTRUCCION, self.perfil.contexto,
                                                    self.perfil.terminos_para(texto), personajes=ctx.ficha())
        respuesta = self.t._generar(prompts.formatear(instruccion, nucleo), self.t._tokens_para(nucleo, 180),
                                    temperature=0.1)
        limpio = limpiar_respuesta(respuesta or "", nucleo) or nucleo
        return f"{prefijo}{limpio}{sufijo}" if (prefijo or sufijo) else limpio

    def pipeline(self, caso: dict) -> str:
        """Lo que usan los motores: traducción con reintentos + revisión de etiquetas (autocorrección)."""
        return self.t.traducir_textos([caso["en"]], info=[info_caso(caso)])[0]

    def evaluar(self, caso: dict) -> dict:
        res = {}
        for cond, funcion in (("modelo", self.modelo), ("pipeline", self.pipeline)):
            traduccion = funcion(caso)
            res[cond] = {"traduccion": traduccion, "fallos": puntuar_banco(caso, traduccion)}
        return res

    def cerrar(self) -> None:
        self.t.cerrar()


def resumir_banco(resultados: list[dict]) -> dict:
    """% de casos bien por condición, en total y por categoría."""
    resumen: dict = {}
    for cond in CONDICIONES_BANCO:
        por_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in resultados:
            par = por_cat[r["categoria"]]
            par[1] += 1
            par[0] += 0 if r["resultados"][cond]["fallos"] else 1
        bien = sum(b for b, _ in por_cat.values())
        total = sum(n for _, n in por_cat.values())
        resumen[cond] = {"bien": bien, "total": total, "por_categoria": {k: {"bien": b, "total": n}
                                                                          for k, (b, n) in sorted(por_cat.items())}}
    return resumen


def tabla_banco(resumen: dict, titulo: str = "") -> str:
    lineas = [titulo] if titulo else []
    m, p = resumen.get("modelo", {}), resumen.get("pipeline", {})
    if not m.get("total"):
        return "\n".join(lineas)
    lineas.append(f"{'Categoría':24} {'casos':>5}   {'modelo (1.er intento)':>22}   {'pipeline completo':>18}")
    for cat in m["por_categoria"]:
        cm, cp = m["por_categoria"][cat], p.get("por_categoria", {}).get(cat, {"bien": 0, "total": 0})
        lineas.append(f"{cat:24} {cm['total']:5d}   {_pct(cm['bien'], cm['total']):>22}   {_pct(cp['bien'], cp['total']):>18}")
    lineas.append(f"{'TOTAL':24} {m['total']:5d}   {_pct(m['bien'], m['total']):>22}   {_pct(p.get('bien', 0), p.get('total', 0)):>18}")
    return "\n".join(lineas)


def comparar_banco(datos: list[dict], rutas: list[Path]) -> str:
    salida = [tabla_banco(d["resumen"], f"== {d['modelo']} ({d['fecha']}, {r.name})") for d, r in zip(datos, rutas)]
    if len(datos) == 2:
        antes = {c["id"]: c for c in datos[0]["casos"]}
        for cond in CONDICIONES_BANCO:
            cambios = []
            for c in datos[1]["casos"]:
                previo = antes.get(c["id"])
                if previo is None:
                    continue
                b0, b1 = not previo["resultados"][cond]["fallos"], not c["resultados"][cond]["fallos"]
                if b0 != b1:
                    cambios.append(f"  {'MEJORA' if b1 else 'EMPEORA'} {c['id']}: {c['en'][:50]} -> "
                                   f"{c['resultados'][cond]['traduccion'][:60]}")
            salida.append(f"Casos que cambian en '{cond}': {len(cambios)}\n" + "\n".join(cambios))
    return "\n\n".join(salida)


def ejecutar_banco(ruta: Path, modelo: str, salida: str | None) -> int:
    datos, ficha = cargar_banco(ruta)
    perfil = perfil_banco(datos, ficha)
    ev = EvaluadorBanco(modelo, perfil)
    inicio = time.time()
    resultados = []
    try:
        for i, caso in enumerate(datos["casos"], 1):
            resultados.append({"id": caso["id"], "categoria": caso["categoria"], "en": caso["en"],
                               "resultados": ev.evaluar(caso)})
            if i % 10 == 0 or i == len(datos["casos"]):
                log.info("  %d/%d casos (%.0f s)", i, len(datos["casos"]), time.time() - inicio)
    except OllamaNoDisponible as e:
        log.error("Ollama no disponible: %s", e)
        return 3
    finally:
        ev.cerrar()
    resumen = resumir_banco(resultados)
    fecha = datetime.now().strftime("%Y-%m-%d_%H%M")
    destino = Path(salida) if salida else config.DIR_WORKSPACE / "_evaluaciones" / f"banco_{modelo}_{fecha}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"banco": str(ruta.name), "version_banco": datos.get("version"), "modelo": modelo,
                                   "fecha": fecha, "resumen": resumen, "casos": resultados},
                                  ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(tabla_banco(resumen, f"Banco fijo ({len(resultados)} casos), modelo {modelo} ({time.time() - inicio:.0f} s)"))
    fallidos = [r for r in resultados if r["resultados"]["pipeline"]["fallos"]]
    if fallidos:
        print(f"\nFallan en el pipeline ({len(fallidos)}):")
        for r in fallidos:
            print(f"  {r['id']}: {r['en'][:55]} -> {r['resultados']['pipeline']['traduccion'][:60]} "
                  f"[{', '.join(r['resultados']['pipeline']['fallos'])}]")
    print(f"Resultados: {destino}")
    return 0


# --------------------------------------------------------------------------- CLI
def _juegos(args) -> dict[str, Path]:
    if not args.juego:
        return dict(JUEGOS_POR_DEFECTO)
    juegos = {}
    for valor in args.juego:
        perfil, _, ruta = valor.partition("=")
        juegos[perfil.strip()] = Path(ruta.strip().strip('"')) if ruta else JUEGOS_POR_DEFECTO.get(perfil.strip(), Path())
    return juegos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Banco de pruebas de género: ¿respeta el modelo a quien habla?")
    ap.add_argument("--modelo", default=config.MODELO_POR_DEFECTO, help="Modelo de Ollama a evaluar")
    ap.add_argument("--juego", action="append", help="perfil=RUTA_DEL_JUEGO (repetible). Por defecto: "
                    + ", ".join(JUEGOS_POR_DEFECTO))
    ap.add_argument("--por-genero", type=int, default=25, help="Frases por juego y género de quien habla (25)")
    ap.add_argument("--solo-casos", action="store_true", help="Solo listar las frases de prueba (sin Ollama)")
    ap.add_argument("--calidad", type=int, default=0, metavar="N",
                    help="Medir también la calidad general con N frases cualesquiera por juego (puerta de calidad)")
    ap.add_argument("--salida", help="JSON de resultados (por defecto workspace/_evaluaciones/<modelo>_<fecha>.json)")
    ap.add_argument("--comparar", nargs="+", help="Comparar resultados guardados (2 o más JSON)")
    ap.add_argument("--invertir-protagonista", action="store_true",
                    help="Prueba espejo: la protagonista con el otro género (solo condiciones B y C)")
    ap.add_argument("--sin-hablante", action="store_true",
                    help="Añadir la condición D: con ficha pero sin saber quién habla (como en Unity/XUnity)")
    ap.add_argument("--banco", nargs="?", const=str(BANCO_POR_DEFECTO), metavar="JSON",
                    help="Banco fijo de frases inventadas (por defecto tests/datos/banco_traduccion.json): mide el "
                         "modelo y el pipeline por categorías, sin necesitar juegos")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)
    configurar_logging(detallado=args.debug)

    if args.comparar:
        rutas = [Path(r) for r in args.comparar]
        datos = [json.loads(r.read_text(encoding="utf-8")) for r in rutas]
        print(comparar_banco(datos, rutas) if all("banco" in d for d in datos) else comparar(rutas))
        return 0
    if args.banco:
        return ejecutar_banco(Path(args.banco), args.modelo, args.salida)

    todos: list[Caso] = []
    perfiles: dict[str, config.Perfil] = {}
    generales: dict[str, list[tuple[str, InfoLinea | None]]] = {}
    for juego, ruta in _juegos(args).items():
        if not ruta.exists():
            log.warning("Se omite %s: no existe %s", juego, ruta)
            continue
        perfil = config.cargar_perfil(juego, auto_crear=False)
        if perfil.personajes is None:
            log.warning("Se omite %s: no tiene personajes.json (ejecuta el Paso 0).", juego)
            continue
        if args.invertir_protagonista:
            invertido = invertir_protagonista(perfil)
            if invertido is None:
                log.warning("Se omite %s: no se sabe el género de su protagonista.", juego)
                continue
            perfil = invertido
            log.info("%s: protagonista invertida -> %s", juego, perfil.personajes.protagonista().etiqueta())
        casos = recoger_casos(juego, ruta, perfil.personajes, args.por_genero)
        cuenta = Counter(c.genero for c in casos)
        log.info("%s: %d frases (%d habla hombre, %d habla mujer)", juego, len(casos), cuenta[HOMBRE], cuenta[MUJER])
        perfiles[juego] = perfil
        todos += casos
        if args.calidad > 0:
            generales[juego] = muestra_general(ruta, args.calidad)
    if not todos:
        print("No hay frases de prueba (¿rutas de los juegos y personajes.json correctos?).")
        return 1
    if args.solo_casos:
        for c in todos:
            print(f"[{c.juego}] {c.hablante} ({c.genero}){' [pensamiento]' if c.pensamiento else ''}: {c.original}")
        print(f"Total: {len(todos)} frases ({sum(c.es_protagonista for c in todos)} de la protagonista)")
        return 0

    inicio = time.time()
    evaluadores = {j: Evaluador(args.modelo, p, con_antes=not args.invertir_protagonista,
                                sin_hablante=args.sin_hablante) for j, p in perfiles.items()}
    calidad: list[dict] = []
    try:
        for i, caso in enumerate(todos, 1):
            evaluadores[caso.juego].evaluar(caso)
            if i % 10 == 0 or i == len(todos):
                log.info("  %d/%d frases evaluadas (%.0f s)", i, len(todos), time.time() - inicio)
        for juego, frases in generales.items():
            for texto, info in frases:
                calidad.append({"juego": juego, **evaluadores[juego].calidad(texto, info)})
            log.info("  calidad general de %s: %d frases (%.0f s)", juego, len(frases), time.time() - inicio)
    except OllamaNoDisponible as e:
        log.error("Ollama no disponible: %s", e)
        return 3
    finally:
        for ev in evaluadores.values():
            ev.cerrar()

    evaluados = [c for c in todos if c.resultados]
    resumen = resumir(evaluados)
    fecha = datetime.now().strftime("%Y-%m-%d_%H%M")
    sufijo = "_espejo" if args.invertir_protagonista else ""
    salida = Path(args.salida) if args.salida else config.DIR_WORKSPACE / "_evaluaciones" / f"{args.modelo}_{fecha}{sufijo}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    datos = {"modelo": args.modelo, "fecha": fecha, "resumen": resumen, "casos": [c.a_dict() for c in evaluados],
             "invertir_protagonista": bool(args.invertir_protagonista), "sin_hablante": bool(args.sin_hablante)}
    if calidad:
        datos["calidad"] = {"resumen": resumir_calidad(calidad), "casos": calidad}
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(tabla(resumen, f"Modelo {args.modelo}: {len(evaluados)} frases de {len(perfiles)} juegos"
                         f"{' (PRUEBA ESPEJO: protagonista invertida)' if args.invertir_protagonista else ''} "
                         f"({time.time() - inicio:.0f} s)"))
    if calidad:
        print(tabla_calidad(datos["calidad"]["resumen"]))
    print(f"Resultados: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
