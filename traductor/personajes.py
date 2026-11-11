"""Ficha de personajes de cada juego: protagonista, personajes principales y su género.

Se guarda en ``workspace/<juego>/personajes.json``. La crea el Paso 0 (``0_analizar_juego.py``)
analizando los archivos del juego y la puedes revisar a mano o desde el Centro de Control.
Con ella el traductor sabe:

  - quién es el protagonista y su género (regla fija que se añade al contexto del juego);
  - quién habla en cada línea (caja de nombre, código de hablante, cara del mensaje,
    personaje de Ren'Py...), a quién se dirige y a quién menciona;
  - qué concordancia aplicar después de traducir (``aplicar_concordancia``).

Formato (todas las claves son opcionales salvo ``nombre``)::

    {
      "version": 1,
      "titulo": "Mi juego",
      "motor": "RPGMaker",
      "reglas": {
        "opciones_del_protagonista": true,      # las opciones (code 102) las dice el protagonista
        "pensamientos_del_protagonista": true,  # "(Qué raro...)" sin hablante = pensamiento del prota
        "npc_hablan_al_protagonista": true      # si habla un NPC, probablemente se dirige al prota
      },
      "personajes": [
        {"nombre": "1Hero", "genero": "hombre", "rol": "protagonista",
         "alias": ["\\\\N[1]"], "codigos": ["Mc"], "confirmado": true},
        {"nombre": "Ana", "genero": "mujer", "rol": "principal", "codigos": ["Al"],
         "descripcion": "Arqueóloga", "apariciones": 1658, "menciones": 120,
         "confianza": 0.95, "evidencia": ["she x14", "Miss x2"], "confirmado": false}
      ]
    }

Valores de ``genero``: ``hombre``, ``mujer``, ``neutro`` (usar lenguaje sin marca de género)
o ``desconocido``. Valores de ``rol``: ``protagonista``, ``principal``, ``secundario``, ``extra``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .genero import (DESCONOCIDO, HOMBRE, MUJER, NEUTRO, contradice_genero, convencion_de, corregir_plural,
                     corregir_primera_persona, corregir_segunda_persona, corregir_tercera_persona,
                     es_genero_marcado, normalizar_genero, personas_con_genero_en)

log = logging.getLogger(__name__)

ARCHIVO_PERSONAJES = "personajes.json"
VERSION_FICHA = 1

ROLES = ("protagonista", "principal", "secundario", "extra")
_ORDEN_ROL = {r: i for i, r in enumerate(ROLES)}

REGLAS_POR_DEFECTO = {
    "opciones_del_protagonista": True,
    "pensamientos_del_protagonista": True,
    "npc_hablan_al_protagonista": True,
}

# Marcadores con los que los juegos sustituyen el nombre del protagonista en el texto.
MARCADORES_PROTAGONISTA = ("1Hero", "\\N[1]", "\\n[1]", "[mcname]", "[mc]", "[name]", "[player_name]",
                           "[playername]", "[pname]", "{ProtagonistName}", "{PlayerName}", "{player}",
                           "{Player}", "{name}", "%PLAYER%", "<player>")

_CODIGOS_RPG = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|\\[{}<>|.!^$]|<[^>]*>|\[/?[a-z]+(?:=[^\]]*)?\]")
_INTERJECCIONES_EN = (r"(?i:hey|hi|hello|oh|ah|thanks|thank\s+you|sorry|ok|okay|well|yes|yeah|no|look|"
                      r"listen|come\s+on|wait|good\s+morning|good\s+night|morning|bye|goodbye|dear|my\s+dear|"
                      r"so|please|excuse\s+me|welcome|welcome\s+back|congrats|congratulations|hmm|um|uh)")
_HABLANTE_CONJUNTO = re.compile(r"\s(?:&|and|y|e)\s|＆|/|\+", re.IGNORECASE)


def limpiar_nombre(nombre: str) -> str:
    """'\\C[2]Ana\\C[0]' -> 'Ana'; '<b>Sora</b>' -> 'Sora'; quita espacios y dos puntos finales."""
    if not nombre:
        return ""
    limpio = nombre
    # \N[1] (nombre del actor 1) se conserva: identifica al protagonista
    limpio = re.sub(r"\\[Cc]\[\d+\]|\\[Ii]\[\d+\]|\\[Ff][Ss]\[\d+\]|\\[{}]", "", limpio)
    limpio = re.sub(r"<[^>]*>", "", limpio)
    return limpio.strip().strip(":：").strip()


# --------------------------------------------------------------------------- Modelo
@dataclass
class Personaje:
    """Un personaje del juego."""

    nombre: str
    genero: str = DESCONOCIDO
    rol: str = "secundario"
    alias: list[str] = field(default_factory=list)
    codigos: list[str] = field(default_factory=list)
    descripcion: str = ""
    apariciones: int = 0
    menciones: int = 0
    confianza: float = 0.0
    evidencia: list[str] = field(default_factory=list)
    confirmado: bool = False

    def __post_init__(self):
        self.nombre = (self.nombre or "").strip()
        self.genero = normalizar_genero(self.genero)
        rol = (self.rol or "secundario").strip().lower()
        self.rol = rol if rol in _ORDEN_ROL else "secundario"
        self.alias = _sin_duplicados(a for a in (self.alias or []) if a and a.strip() and a.strip() != self.nombre)
        self.codigos = _sin_duplicados(c for c in (self.codigos or []) if c and str(c).strip())
        self.evidencia = [str(e) for e in (self.evidencia or [])][:30]
        try:
            self.confianza = max(0.0, min(1.0, float(self.confianza or 0.0)))
        except (TypeError, ValueError):
            self.confianza = 0.0
        self.apariciones = int(self.apariciones or 0)
        self.menciones = int(self.menciones or 0)
        self.confirmado = bool(self.confirmado)

    @property
    def es_protagonista(self) -> bool:
        return self.rol == "protagonista"

    @property
    def genero_conocido(self) -> bool:
        return self.genero in (HOMBRE, MUJER, NEUTRO)

    def nombres(self) -> list[str]:
        """Nombre principal + alias (sin vacíos ni duplicados)."""
        return _sin_duplicados([self.nombre, *self.alias])

    def etiqueta(self) -> str:
        return f"{self.nombre} ({self.genero})"

    def to_dict(self) -> dict:
        d = {"nombre": self.nombre, "genero": self.genero, "rol": self.rol}
        if self.alias:
            d["alias"] = list(self.alias)
        if self.codigos:
            d["codigos"] = list(self.codigos)
        if self.descripcion:
            d["descripcion"] = self.descripcion
        d["apariciones"] = self.apariciones
        d["menciones"] = self.menciones
        d["confianza"] = round(self.confianza, 2)
        if self.evidencia:
            d["evidencia"] = list(self.evidencia)
        d["confirmado"] = self.confirmado
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Personaje":
        if isinstance(d, str):
            return cls(nombre=d)
        return cls(
            nombre=str(d.get("nombre") or d.get("name") or ""),
            genero=d.get("genero", d.get("gender", DESCONOCIDO)),
            rol=d.get("rol", d.get("role", "secundario")),
            alias=list(d.get("alias") or d.get("aliases") or []),
            codigos=[str(c) for c in (d.get("codigos") or d.get("codes") or [])],
            descripcion=str(d.get("descripcion") or d.get("description") or ""),
            apariciones=d.get("apariciones", 0),
            menciones=d.get("menciones", 0),
            confianza=d.get("confianza", 0.0),
            evidencia=list(d.get("evidencia") or []),
            confirmado=d.get("confirmado", False),
        )


def _sin_duplicados(valores: Iterable[str]) -> list[str]:
    vistos: set[str] = set()
    res: list[str] = []
    for v in valores:
        v = str(v).strip()
        if v and v not in vistos:
            vistos.add(v)
            res.append(v)
    return res


@dataclass
class FichaPersonajes:
    """Protagonista + personajes de un juego, con índices para buscarlos rápido."""

    personajes: list[Personaje] = field(default_factory=list)
    titulo: str = ""
    motor: str = ""
    reglas: dict = field(default_factory=lambda: dict(REGLAS_POR_DEFECTO))
    version: int = VERSION_FICHA

    def __post_init__(self):
        reglas = dict(REGLAS_POR_DEFECTO)
        reglas.update({k: bool(v) for k, v in (self.reglas or {}).items()})
        self.reglas = reglas
        self.reindexar()

    # ----------------------------------------------------------------- Índices
    def reindexar(self) -> None:
        """Recalcula los índices; llámalo si modificas ``personajes`` a mano."""
        self.personajes = [p for p in self.personajes if p.nombre]
        self.personajes.sort(key=lambda p: (_ORDEN_ROL.get(p.rol, 9), -(p.apariciones + p.menciones)))
        self._por_nombre: dict[str, Personaje] = {}
        self._por_codigo: dict[str, Personaje] = {}
        self._por_codigo_cf: dict[str, Personaje] = {}
        nombres_mencion: list[tuple[str, Personaje]] = []
        prota = self.protagonista()
        for p in self.personajes:
            for n in p.nombres():
                self._por_nombre.setdefault(n.casefold(), p)
                limpio = limpiar_nombre(n)
                if limpio:
                    self._por_nombre.setdefault(limpio.casefold(), p)
                if len(limpio) >= 2:
                    nombres_mencion.append((limpio, p))
            for c in p.codigos:
                self._por_codigo.setdefault(c, p)
                self._por_codigo_cf.setdefault(c.casefold(), p)
        if prota is not None:
            for marcador in MARCADORES_PROTAGONISTA:
                self._por_nombre.setdefault(marcador.casefold(), prota)
                nombres_mencion.append((marcador, prota))
        self._menciones: list[tuple[re.Pattern, Personaje]] = []
        self._formas_mencion: list[str] = []   # nombre de la ficha de cada patrón de ``_menciones``
        self._vocativos: list[tuple[tuple[re.Pattern, ...], Personaje]] = []
        vistos: set[str] = set()
        for nombre, p in sorted(nombres_mencion, key=lambda x: -len(x[0])):
            if nombre in vistos:
                continue
            vistos.add(nombre)
            self._formas_mencion.append(nombre)
            variantes = {re.escape(nombre)}
            if nombre[:1].isalpha():
                variantes.add(re.escape(nombre.upper()))
            alternativas = "|".join(sorted(variantes, key=len, reverse=True))
            patron_nombre = rf"(?<![\w\\])(?:{alternativas})(?![\w])"
            self._menciones.append((re.compile(patron_nombre), p))
            self._vocativos.append(((
                re.compile(rf"^(?:{_INTERJECCIONES_EN}\s*,?\s+)?{patron_nombre}\s*[,!?…]"),
                re.compile(rf",\s*(?:(?i:my|dear|my dear)\s+)?{patron_nombre}\s*[.!?…~]*\s*$"),
                # También en mitad del texto, si cierra la frase: "Are you crazy, Ana? You can't..."
                re.compile(rf",\s*(?:(?i:my|dear|my dear)\s+)?{patron_nombre}\s*[.!?…~]+(?=\s)"),
                re.compile(rf"(?:^|[.!?…]\s+){_INTERJECCIONES_EN}\s*,?\s+{patron_nombre}"),
            ), p))

    # ----------------------------------------------------------------- Consultas
    def protagonista(self) -> Personaje | None:
        for p in self.personajes:
            if p.es_protagonista:
                return p
        return None

    def buscar(self, nombre: str | None) -> Personaje | None:
        """Busca por nombre o alias ('\\C[2]Ana\\C[0]', 'ANA', 'Ana:'...). '\\N[1]' = protagonista."""
        if not nombre:
            return None
        crudo = str(nombre).strip()
        p = self._por_nombre.get(crudo.casefold())
        if p is not None:
            return p
        limpio = limpiar_nombre(crudo)
        if not limpio:
            return None
        p = self._por_nombre.get(limpio.casefold())
        if p is not None:
            return p
        if re.fullmatch(r"\\[Nn]\[1\]", limpio) and self.protagonista():
            return self.protagonista()
        if _HABLANTE_CONJUNTO.search(f" {limpio} "):
            return None  # 'Ana & Carla' habla en plural: no se fuerza un género
        # 'Ana Bikini', 'Ana (?)', 'Officer Ana' -> primera/última palabra si es única
        palabras = [w for w in re.split(r"[\s(),（）?？]+", limpio) if w]
        for w in (palabras[:1] + palabras[-1:]) if len(palabras) > 1 else []:
            p = self._por_nombre.get(w.casefold())
            if p is not None:
                return p
        return None

    def por_codigo(self, codigo: str | None) -> Personaje | None:
        """Busca por código de hablante ('He', 'Mc', 'face:Actor1#0', 'renpy:mc'...).
        Para códigos de hablante largos ('HeFrOp', 'Al,An,De') prueba también con las 2-3 primeras letras."""
        if not codigo:
            return None
        c = str(codigo).strip()
        p = self._por_codigo.get(c) or self._por_codigo_cf.get(c.casefold())
        if p is not None or ":" in c:
            return p  # 'renpy:m' o 'face:X#0' solo coinciden exactos ('renpy:m' no es el código de hablante 'Re')
        base = c.split(",")[0]
        for n in (3, 2):
            if len(base) > n:
                p = self._por_codigo.get(base[:n])
                if p is not None:
                    return p
        return None

    def mencionados_en(self, texto: str, excluir: Iterable[Personaje | None] = ()) -> list[Personaje]:
        """Personajes cuyo nombre (o alias) aparece en ``texto`` como palabra completa."""
        if not texto or not self._menciones:
            return []
        excluidos = {id(p) for p in excluir if p is not None}
        encontrados: list[Personaje] = []
        ids: set[int] = set()
        for patron, p in self._menciones:
            if id(p) in ids or id(p) in excluidos:
                continue
            if patron.search(texto):
                ids.add(id(p))
                encontrados.append(p)
        return encontrados

    def nombres_en(self, texto: str) -> list[str]:
        """Nombres de personajes tal y como aparecen en ``texto`` ('Ana', 'MARISA', 'Father Brian'),
        sin los marcadores del protagonista ('1Hero', '\\N[1]'...), que ya protegen otras reglas."""
        if not texto or not self._menciones:
            return []
        marcadores = {m.casefold() for m in MARCADORES_PROTAGONISTA}
        encontrados: list[str] = []
        for patron, _ in self._menciones:
            m = patron.search(texto)
            if m and m.group(0).casefold() not in marcadores and m.group(0) not in encontrados:
                encontrados.append(m.group(0))
        return encontrados

    def formas_en(self, texto: str) -> dict[str, str]:
        """Cómo nombra ``texto`` a cada personaje: {nombre de la ficha: nombre o alias que aparece}.

        "'Lucky' Bruno" con alias "Bruno" y el texto "Thanks, Bruno." -> {"'Lucky' Bruno": "Bruno"}. Gana la
        forma más larga ("'Lucky' Bruno" si sale entera). Los marcadores del protagonista ('\\N[1]') no
        cuentan: el prompt sigue usando su nombre."""
        if not texto or not self._menciones:
            return {}
        marcadores = {m.casefold() for m in MARCADORES_PROTAGONISTA}
        formas: dict[str, str] = {}
        for (patron, p), forma in zip(self._menciones, self._formas_mencion):
            if p.nombre in formas or forma.casefold() in marcadores:
                continue
            if patron.search(texto):
                formas[p.nombre] = forma
        return formas

    def vocativo_en(self, texto: str, excluir: Personaje | None = None) -> Personaje | None:
        """Personaje al que se habla por su nombre: 'Chloe, ...', 'Hey Chloe!', '..., Chloe?'."""
        if not texto or not self._vocativos:
            return None
        visible = _CODIGOS_RPG.sub(" ", texto)
        visible = re.sub(r"\s+", " ", visible).strip().strip("\"'“”«»*()")
        for patrones, p in self._vocativos:
            if p is excluir:
                continue
            if any(pat.search(visible) for pat in patrones):
                return p
        return None

    def con_genero_conocido(self) -> list[Personaje]:
        return [p for p in self.personajes if p.genero_conocido]

    def pendientes_de_revisar(self) -> list[Personaje]:
        """Personajes importantes con género desconocido, poca confianza o sin confirmar."""
        return [p for p in self.personajes
                if not p.confirmado and p.rol in ("protagonista", "principal")
                and (p.genero == DESCONOCIDO or p.confianza < 0.75)]

    # ----------------------------------------------------------------- Textos para el prompt
    def regla_protagonista(self) -> str:
        """Regla fija sobre el protagonista para el contexto del juego ("" si no se conoce)."""
        p = self.protagonista()
        if p is None or p.genero == DESCONOCIDO:
            return ""
        n = p.nombre
        if p.genero == HOMBRE:
            return (f"Protagonista: {n} (hombre). Cuando él habla o piensa usa masculino en primera persona "
                    f"(\"estoy cansado\", \"estoy listo\"); cuando le hablan a él usa masculino "
                    f"(\"bienvenido\", \"¿estás seguro?\").")
        if p.genero == MUJER:
            return (f"Protagonista: {n} (mujer). Cuando ella habla o piensa usa femenino en primera persona "
                    f"(\"estoy cansada\", \"estoy lista\"); cuando le hablan a ella usa femenino "
                    f"(\"bienvenida\", \"¿estás segura?\").")
        return (f"Protagonista: {n} (género no marcado). Evita adjetivos con género para el protagonista: "
                f"usa construcciones neutras (\"tengo sueño\" en vez de \"estoy cansado/a\").")

    def huella(self) -> str:
        """Hash de lo que influye en la traducción (nombres, géneros, roles, códigos y reglas)."""
        datos = [(p.nombre, p.genero, p.rol, tuple(p.alias), tuple(p.codigos)) for p in self.personajes]
        bruto = json.dumps([datos, sorted(self.reglas.items())], ensure_ascii=False)
        return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:10]

    def resumen(self) -> str:
        p = self.protagonista()
        prota = p.etiqueta() if p else "sin protagonista"
        conocidos = len(self.con_genero_conocido())
        return f"{len(self.personajes)} personajes ({conocidos} con género), protagonista: {prota}"

    # ----------------------------------------------------------------- Serialización
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "titulo": self.titulo,
            "motor": self.motor,
            "reglas": dict(self.reglas),
            "personajes": [p.to_dict() for p in self.personajes],
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "FichaPersonajes":
        if isinstance(datos, list):
            datos = {"personajes": datos}
        if not isinstance(datos, dict):
            return cls()
        crudos = [d for d in (datos.get("personajes") or []) if d]
        # 'm' es ambigua (mujer/male): se interpreta según el resto de letras del archivo.
        conv = convencion_de(d.get("genero", d.get("gender")) for d in crudos if isinstance(d, dict))
        personajes = []
        for d in crudos:
            p = Personaje.from_dict(d)
            if isinstance(d, dict) and p.genero == DESCONOCIDO:
                p.genero = normalizar_genero(d.get("genero", d.get("gender")), conv)
            personajes.append(p)
        # Compatibilidad: {"protagonista": {...}} separado
        prota = datos.get("protagonista")
        if isinstance(prota, (dict, str)) and prota:
            pp = Personaje.from_dict(prota)
            pp.rol = "protagonista"
            if pp.nombre and not any(p.nombre == pp.nombre for p in personajes):
                personajes.insert(0, pp)
        return cls(
            personajes=personajes,
            titulo=str(datos.get("titulo") or ""),
            motor=str(datos.get("motor") or ""),
            reglas=datos.get("reglas") or {},
            version=int(datos.get("version") or VERSION_FICHA),
        )

    @classmethod
    def cargar(cls, ruta: Path) -> "FichaPersonajes | None":
        """Lee ``personajes.json``. Devuelve None si no existe; si está roto lo avisa y devuelve None."""
        ruta = Path(ruta)
        if not ruta.exists():
            return None
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("No se pudo leer %s (%s). Se ignora la ficha de personajes.", ruta, e)
            return None
        return cls.from_dict(datos)

    def guardar(self, ruta: Path) -> Path:
        """Escritura atómica (tmp + os.replace) en UTF-8 legible."""
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_name(f"{ruta.name}.tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                       newline="\n")
        os.replace(tmp, ruta)
        return ruta

    # ----------------------------------------------------------------- Fusión
    def _localizar(self, otro: Personaje) -> Personaje | None:
        for n in otro.nombres():
            p = self.buscar(n)
            if p is not None:
                return p
        for c in otro.codigos:
            p = self._por_codigo.get(c)
            if p is not None:
                return p
        return None

    def fusionar(self, nueva: "FichaPersonajes") -> "FichaPersonajes":
        """Mezcla un análisis nuevo con esta ficha SIN perder lo que el usuario confirmó.

        - Personajes ``confirmado: true``: solo se actualizan contadores, alias y códigos nuevos.
        - Personajes sin confirmar: se adopta el género/rol nuevo si tiene más confianza o el
          actual es desconocido.
        - Personajes nuevos: se añaden. Los que ya no aparecen en el análisis se conservan.
        """
        for np_ in nueva.personajes:
            actual = self._localizar(np_)
            if actual is None:
                self.personajes.append(Personaje.from_dict(np_.to_dict()))
                continue
            actual.apariciones = max(actual.apariciones, np_.apariciones)
            actual.menciones = max(actual.menciones, np_.menciones)
            actual.alias = _sin_duplicados([*actual.alias, *(n for n in np_.nombres() if n != actual.nombre)])
            actual.codigos = _sin_duplicados([*actual.codigos, *np_.codigos])
            if not actual.descripcion and np_.descripcion:
                actual.descripcion = np_.descripcion
            if actual.confirmado:
                continue
            if np_.genero != DESCONOCIDO and (actual.genero == DESCONOCIDO or np_.confianza >= actual.confianza):
                actual.genero = np_.genero
                actual.confianza = np_.confianza
                actual.evidencia = list(np_.evidencia)
            if _ORDEN_ROL.get(np_.rol, 9) < _ORDEN_ROL.get(actual.rol, 9):
                actual.rol = np_.rol
        if not self.titulo:
            self.titulo = nueva.titulo
        if not self.motor:
            self.motor = nueva.motor
        # Solo un protagonista: si hay varios, se queda el confirmado o el de más apariciones.
        protas = [p for p in self.personajes if p.es_protagonista]
        if len(protas) > 1:
            protas.sort(key=lambda p: (not p.confirmado, -(p.apariciones + p.menciones)))
            for p in protas[1:]:
                p.rol = "principal"
        self.reindexar()
        return self


# --------------------------------------------------------------------------- Línea a línea
@dataclass(frozen=True)
class InfoLinea:
    """Lo que el motor del juego sabe de una línea (todo opcional).

    - ``hablante``: nombre que muestra el juego (caja de nombre, hablante de MZ, Ren'Py...).
    - ``codigo``: código del hablante (prefijo 'He', cara 'face:Actor1#0', variable Ren'Py 'renpy:mc').
    - ``es_opcion``: opción de diálogo que elige el jugador (la dice el protagonista).
    - ``es_pensamiento``: True/False si el motor lo sabe; None = detectarlo por el texto "(...)".
    - ``destinatario``: nombre de a quién se habla, si el motor lo sabe.
    - ``genero``: género de quien habla según el propio juego ('hombre'/'mujer'). Solo se usa si el hablante no
      está en la ficha (extras como "Woman" o "Guard 2"); si está, manda la ficha.
    - ``oyente``: a quién se habla PROBABLEMENTE, deducido de los turnos de la conversación (nombre o código
      como en ``hablante``/``codigo``; ver ``oyentes_por_turnos``). No es seguro: va como pista al modelo y,
      si la traducción lo contradice, se reintenta; nunca se corrige solo.
    """

    hablante: str | None = None
    codigo: str | None = None
    es_opcion: bool = False
    es_pensamiento: bool | None = None
    destinatario: str | None = None
    genero: str | None = None
    oyente: str | None = None


def oyentes_por_turnos(hablantes: Sequence[str | None], ventana: int = 3) -> list[str | None]:
    """A quién habla probablemente cada línea, por los turnos de la conversación (A-B-A).

    ``hablantes`` son las líneas en orden (nombre o código de quien habla; None = narrador). Si el último
    que habló antes que X y el primero que habla después de X (como mucho ``ventana`` líneas) son la misma
    persona Y, X le habla a Y. Medido en un juego ya revisado a mano: la 2.ª persona coincide con ese
    oyente en 315 frases y lo contradice en 14 (y esas 14 eran fallos)."""
    oyentes: list[str | None] = [None] * len(hablantes)
    for i, x in enumerate(hablantes):
        if x is None:
            continue
        antes = next((h for h in reversed(hablantes[max(0, i - ventana):i]) if h is not None and h != x), None)
        despues = next((h for h in hablantes[i + 1:i + 1 + ventana] if h is not None and h != x), None)
        if antes is not None and antes == despues:
            oyentes[i] = antes
    return oyentes


_PENSAMIENTO = re.compile(r"^[\s\"'“”«»*~]*[(（][^()（）]*[A-Za-zÁÉÍÓÚáéíóúñÑ][^()（）]*[)）][\s\"'“”«»*~.!?…]*$")


def es_pensamiento(texto: str) -> bool:
    """True si la línea entera va entre paréntesis: '(Qué raro...)' o '<i>(Ni hablar.)</i>'."""
    if not texto:
        return False
    visible = _CODIGOS_RPG.sub("", texto)
    return bool(_PENSAMIENTO.match(visible.strip()))


@dataclass
class ContextoLinea:
    """Quién habla, a quién y a quién se menciona en una línea concreta (ya resuelto con la ficha)."""

    hablante: Personaje | None = None
    destinatario: Personaje | None = None
    destinatario_explicito: bool = False
    mencionados: list[Personaje] = field(default_factory=list)
    pensamiento: bool = False
    destinatario_por_turnos: bool = False   # el destinatario sale de los turnos (InfoLinea.oyente)
    # Cómo los nombra el texto ({"'Lucky' Bruno": "Bruno"}): el prompt usa esa forma para que el modelo no
    # copie el apodo de la ficha ("Gracias, Afortunado Bruno"). No entra en la firma (la caché no cambia).
    formas: dict[str, str] = field(default_factory=dict)

    @property
    def vacio(self) -> bool:
        return not self.firma()

    def _con_genero(self, p: Personaje | None) -> bool:
        return p is not None and p.genero_conocido

    def _nombre(self, p: Personaje) -> str:
        return self.formas.get(p.nombre, p.nombre)

    def etiqueta_de(self, p: Personaje) -> str:
        """'Bruno (hombre)': como ``Personaje.etiqueta()`` pero con el nombre tal como sale en el texto."""
        return f"{self._nombre(p)} ({p.genero})"

    def ficha(self) -> str:
        """Texto compacto para el prompt. Vacío si no hay nada útil sobre género."""
        partes: list[str] = []
        h = self.hablante if self._con_genero(self.hablante) else None
        d = self.destinatario if self._con_genero(self.destinatario) and self.destinatario is not self.hablante else None
        if h is not None:
            if self.pensamiento:
                partes.append(f"Es un pensamiento de {self.etiqueta_de(h)}.")
            elif h.es_protagonista:
                partes.append(f"Habla el protagonista, {self.etiqueta_de(h)}.")
            else:
                partes.append(f"Habla {self.etiqueta_de(h)}.")
        if d is not None:
            if self.destinatario_explicito:
                partes.append(f"Se dirige a {self.etiqueta_de(d)}.")
            else:
                partes.append(f"Probablemente se dirige a {self.etiqueta_de(d)}.")
        otros = [p for p in self.mencionados if p.genero_conocido and p is not h and p is not d]
        if otros:
            partes.append("Mencionados: " + ", ".join(self.etiqueta_de(p) for p in otros[:6]) + ".")
        if not partes:
            return ""
        if h is not None or d is not None:
            yo = self._nombre(h) if h is not None else None
            tu = self._nombre(d) if d is not None else None
            guia = []
            if yo:
                guia.append(f"'yo' = {yo}")
            if tu:
                guia.append(f"'tú' = {tu}")
            partes.append("Concuerda el género (" + ", ".join(guia) + ").")
        return " ".join(partes)

    def firma(self) -> str:
        """Cadena estable para la clave de caché ('' si la línea no aporta nada de género)."""
        trozos: list[str] = []
        h = self.hablante if self._con_genero(self.hablante) else None
        d = self.destinatario if self._con_genero(self.destinatario) and self.destinatario is not self.hablante else None
        if h is not None:
            trozos.append(f"h:{h.nombre}={h.genero}{'~p' if self.pensamiento else ''}")
        if d is not None:
            trozos.append(f"d:{d.nombre}={d.genero}{'' if self.destinatario_explicito else '?'}")
        otros = sorted(f"{p.nombre}={p.genero}" for p in self.mencionados
                       if p.genero_conocido and p is not h and p is not d)
        if otros:
            trozos.append("m:" + ",".join(otros))
        return ";".join(trozos)

    def etiqueta_historial(self) -> str:
        """Prefijo para el historial de conversación ('Ana: ')."""
        if self.hablante is None:
            return ""
        return f"{self.hablante.nombre}: "


def oyente_contradicho(ctx: ContextoLinea | None, original: str, traduccion: str) -> bool:
    """¿La 2.ª persona de la traducción va en el género contrario al del oyente sacado de los turnos?

    Solo con el oyente de ``InfoLinea.oyente`` (no con el protagonista "probable" de siempre) y si el inglés
    no dice ya ese género ("you're a good girl"). No se corrige solo: el traductor reintenta con una nota."""
    if ctx is None or not ctx.destinatario_por_turnos or ctx.destinatario is None or ctx.pensamiento:
        return False
    d = ctx.destinatario
    if d is ctx.hablante or d.genero not in (HOMBRE, MUJER) or not contradice_genero(traduccion, "2", d.genero):
        return False
    contrario = MUJER if d.genero == HOMBRE else HOMBRE
    return contrario not in personas_con_genero_en(original)


def resolver_linea(ficha: FichaPersonajes | None, texto: str, info: InfoLinea | None = None) -> ContextoLinea:
    """Averigua hablante, destinatario y personajes mencionados de una línea (texto ORIGINAL)."""
    if ficha is None or not ficha.personajes:
        return ContextoLinea()
    info = info or InfoLinea()
    reglas = ficha.reglas
    prota = ficha.protagonista()

    hablante: Personaje | None = None
    if info.es_opcion and reglas.get("opciones_del_protagonista", True) and prota is not None:
        hablante = prota
    if hablante is None and info.hablante:
        hablante = ficha.buscar(info.hablante)
    if hablante is None and info.codigo:
        hablante = ficha.por_codigo(info.codigo)
    if hablante is None and info.genero and normalizar_genero(info.genero) in (HOMBRE, MUJER):
        hablante = Personaje(nombre=info.hablante or "Hablante", genero=info.genero, rol="extra")
    pensamiento = (not info.es_opcion) and (
        info.es_pensamiento if info.es_pensamiento is not None else es_pensamiento(texto))
    if hablante is None and pensamiento:
        if reglas.get("pensamientos_del_protagonista", True) and prota is not None:
            hablante = prota
        else:
            pensamiento = False

    destinatario: Personaje | None = None
    explicito = por_turnos = False
    oyente = None
    if not pensamiento and info.oyente and not info.es_opcion:
        oyente = ficha.por_codigo(info.oyente) or ficha.buscar(info.oyente)
        if oyente is hablante:
            oyente = None
    if not pensamiento:
        voc = ficha.vocativo_en(texto, excluir=hablante)
        if voc is not None:
            destinatario, explicito = voc, True
        elif info.destinatario:
            destinatario = ficha.buscar(info.destinatario)
            explicito = destinatario is not None
        elif oyente is not None and hablante is not None:
            destinatario, por_turnos = oyente, True
        elif (hablante is not None and prota is not None and hablante is not prota
              and not info.es_opcion and reglas.get("npc_hablan_al_protagonista", True)):
            destinatario = prota

    mencionados = ficha.mencionados_en(texto, excluir=(hablante, destinatario))
    return ContextoLinea(hablante=hablante, destinatario=destinatario, destinatario_explicito=explicito,
                         mencionados=mencionados, pensamiento=pensamiento, destinatario_por_turnos=por_turnos,
                         formas=ficha.formas_en(texto))


# "Nosotros" que son exactamente quien habla y quien escucha. "Join us" o "we" a secas no valen: el
# grupo puede incluir a otros ("Join us, Ana" = únete a nosotros, que ya estamos aquí).
_EN_LOS_DOS = re.compile(r"\b(?:both of us|the two of us|we both|us both|we two|us two|you and (?:I|me)|"
                         r"me and you|between (?:you and me|us two))\b", re.IGNORECASE)


def es_los_dos(original: str) -> bool:
    """True si el inglés dice que el grupo del "nosotros" son quien habla y quien escucha."""
    return bool(_EN_LOS_DOS.search(original or ""))


def _concordar_plural(texto: str, original: str, ctx: ContextoLinea) -> str:
    """Plural de grupo, solo en los casos seguros (un grupo con un hombre va en masculino):

    - Habla un hombre: "nosotras"/"estamos listas" -> masculino (él está en el grupo).
    - Se nombra a un hombre que escucha: "vosotras"/"¿estáis listas?" -> masculino.
    - Se nombra a quien escucha y el inglés dice que el grupo son los dos ("both of us", "you and I"):
      "nosotros" va en el género de la pareja ("Ana, las dos lo sabemos").
    """
    h, d = ctx.hablante, ctx.destinatario
    explicito = d is not None and ctx.destinatario_explicito and d is not h
    if h is not None and h.genero == HOMBRE:
        texto = corregir_plural(texto, HOMBRE, "1")
    if explicito and d.genero == HOMBRE:
        texto = corregir_plural(texto, HOMBRE, "2")
    if explicito and not ctx.pensamiento and _EN_LOS_DOS.search(original or ""):
        if d.genero == HOMBRE:
            texto = corregir_plural(texto, HOMBRE, "1")
        elif (h is not None and h.genero == MUJER and d.genero == MUJER
              and HOMBRE not in personas_con_genero_en(original)):
            texto = corregir_plural(texto, MUJER, "1")
    return texto


def aplicar_concordancia(traducido: str, original: str, ctx: ContextoLinea | None) -> str:
    """Corrige de forma determinista el género de la traducción con lo que se sabe de la línea.

    - 1.ª persona según quien habla (si se conoce su género).
    - 2.ª persona y vocativos SOLO si el destinatario es explícito (se le nombra en la frase).
    - 3.ª persona ("Ana está cansado") y títulos ("mi amigo Ana") para los personajes nombrados.
    """
    if not traducido or ctx is None:
        return traducido
    res = traducido
    h = ctx.hablante
    if h is not None and es_genero_marcado(h.genero):
        res = corregir_primera_persona(res, h.genero, original)
    d = ctx.destinatario
    if d is not None and ctx.destinatario_explicito and d is not h and es_genero_marcado(d.genero):
        res = corregir_segunda_persona(res, d.genero)
    res = _concordar_plural(res, original, ctx)
    nombrados = list(ctx.mencionados)
    if d is not None and ctx.destinatario_explicito:
        nombrados.append(d)
    for p in nombrados:
        if not es_genero_marcado(p.genero):
            continue
        for n in p.nombres():
            limpio = limpiar_nombre(n)
            if len(limpio) >= 2 and limpio in res:
                res = corregir_tercera_persona(res, limpio, p.genero)
    return res


def ruta_ficha(carpeta_juego: Path) -> Path:
    """Ruta de ``personajes.json`` dentro de ``workspace/<juego>/``."""
    return Path(carpeta_juego) / ARCHIVO_PERSONAJES
