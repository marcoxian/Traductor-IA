# Traductor IA: traducción de videojuegos con IA local

Herramientas para traducir videojuegos del inglés al **español de España** con un modelo de lenguaje que se
ejecuta en tu propio ordenador mediante [Ollama](https://ollama.com). Funciona con **RPG Maker MV/MZ**,
**Ren'Py**, **Unity** (a través de BepInEx y XUnity.AutoTranslator) y juegos con **CSV de idiomas**
(DKTools, Godot…).

No envía nada a internet: los textos del juego, la traducción y el modelo se quedan en tu máquina.

---

## Qué hace

- **Traduce el juego entero o en tiempo real.** En RPG Maker, Ren'Py y CSV inyecta la traducción en los archivos
  del juego, con copia del original. En Unity, un proxy local traduce mientras juegas.
- **Sabe quién habla.** El Paso 0 crea una *ficha de personajes* (protagonista, personajes y su género). El
  traductor la usa para que cada personaje hable con su género («Estoy cansado» o «Estoy cansada») y corrige
  después la concordancia de forma determinista.
- **Puerta de calidad.** Rechaza y reintenta las traducciones vacías, en inglés, recortadas, con bucles, con
  etiquetas rotas o con nombres perdidos. Nada malo entra en la caché.
- **Palabras con dos sentidos.** Decide por el contexto de la frase si *chest* es «cofre» o «pecho», o si *safe* es
  «caja fuerte». Se lo indica al modelo y comprueba el resultado.
- **Vocabulario para juegos adultos.** Es opcional y editable (`glosarios/glosario_adulto.json`): mantiene el
  registro del original sin suavizarlo ni cambiar una palabra por otra. Los insultos se traducen con un insulto.
- **Modelo automático.** Elige el modelo según tenga o no ficha de personajes el juego. Puedes fijar otro para
  cada juego.
- **Retraducción selectiva.** Si cambias de modelo o mejoras las reglas, `--solo-genero` conserva lo que ya estaba
  bien y solo vuelve a pedir las frases afectadas. Funciona en RPG Maker y en CSV de idiomas.
- **Códigos del juego a salvo.** Si el modelo pierde una pausa (`\!`, `\|`, `\.`), se vuelve a poner entre las
  mismas frases; las celdas entrecomilladas de un CSV conservan su caja de nombre.
- **Centro de Control.** Aplicación de escritorio con todo el flujo, monitor de progreso en la bandeja del sistema
  y copias de seguridad.
- **Medidas, no impresiones.** Incluye un banco de pruebas de género (`9_evaluar_genero.py`) para comparar modelos
  con datos.

---

## Qué no incluye este repositorio (y por qué)

Este repositorio contiene **solo código**:

- pruebas con ejemplos inventados;
- diccionarios genéricos: términos de interfaz, vocabulario adulto y contexto de estilo;
- **plantillas de ejemplo** (`*.ejemplo.json`).

**No incluye, y no debe subirse nunca:**

| Qué | Por qué | Cómo lo consigues tú |
|---|---|---|
| Textos, traducciones o volcados de juegos | Tienen derechos de autor de sus creadores | Salen de los juegos que tengas tú (`workspace/`, ignorado por git) |
| Glosarios, fichas de personajes y correcciones de juegos concretos | Contienen nombres y textos de esos juegos | Créalos con las plantillas de `glosarios/*.ejemplo.json` y el Paso 0 |
| Datos de entrenamiento (`datasets/`) | Se construyen con textos de juegos o corpus con su propia licencia | Usa juegos que tengas o corpus públicos (p. ej. OPUS), respetando su licencia |
| Modelos entrenados (`modelos/`, GGUF) | Se entrenan con esos textos y además pesan varios GB | Usa un modelo base de Ollama (`ollama pull llama3.1`) o entrena el tuyo (ver *Entrenamiento*) |
| Partidas guardadas y cachés | Son datos personales de tu partida | Se generan solas en tu ordenador |

**Uso responsable:**

- Traduce solo juegos que tengas, y úsalos para tu uso personal.
- Respeta el EULA y los términos de cada juego y plataforma.
- No distribuyas archivos de un juego traducido sin permiso de sus autores. Si quieres compartir una traducción,
  pide permiso o distribuye solo un parche que no contenga el juego.
- Las herramientas de terceros (Ollama, BepInEx, XUnity.AutoTranslator, Unsloth, el modelo base…) tienen sus propias
  licencias. Este repositorio no las incluye: las instalas tú. Si redistribuyes un modelo derivado de Llama, cumple
  su licencia.

El `.gitignore` ya excluye `workspace/`, `datasets/`, `modelos/`, `privado/` y los glosarios propios. Si creas
herramientas para un juego concreto, guárdalas en `privado/`.

---

## Requisitos e instalación

- Windows 10/11 (la mayor parte funciona también en Linux).
- Python 3.10.
- [Ollama](https://ollama.com) instalado y en marcha (`http://localhost:11434`).
- Una GPU NVIDIA con unos 8 GB de VRAM para traducir con soltura. Para entrenar hacen falta unos 12 GB.

Instalación en Windows:

```bat
setup.bat
```

Crea el entorno `venv_traductor` con las dependencias: PyTorch con CUDA, Unsloth para entrenar y Flask para el
monitor web.

### El modelo

Los nombres de modelo por defecto (`IA_Traductora_v4` con ficha de personajes e `IA_Traductora` sin ella) son los
de modelos entrenados con este proyecto. Si no los tienes, tienes dos opciones:

- descargar un modelo base, `ollama pull llama3.1`, y elegirlo en el Centro de Control (se guarda para cada juego)
  o pasarlo con `--modelo llama3.1`;
- cambiar los de por defecto con variables de entorno: `TRADUCTOR_MODELO_CON_FICHA`, `TRADUCTOR_MODELO_SIN_FICHA` y
  `TRADUCTOR_MODELO`.

El Centro de Control avisa si el modelo elegido no está instalado en Ollama.

---

## Primeros pasos

1. Abre el **Centro de Control**: `iniciar_monitor_bandeja.bat`.
2. Elige la carpeta del juego con **Examinar carpeta…**. El motor se detecta solo.
3. **Paso 0, personajes:** analiza el juego y revisa su ficha, sobre todo el género del protagonista.
4. **Paso 1, traducir:** el **modo seguro** va frase a frase y con la conversación anterior como contexto; el **modo
   turbo** va por lotes y es más rápido. Si el juego ya estaba traducido, marca **«♻ Juego ya traducido»**.
5. Revisa en el juego. Las herramientas de los pasos 2 a 8 ayudan a corregir lo que quede.

Por consola es lo mismo:

```bash
python 0_analizar_juego.py --ruta "D:\Juegos\MiJuego"
python 1_traducir_juego.py --ruta "D:\Juegos\MiJuego" --modo seguro
python 1_traducir_juego.py --ruta "D:\Juegos\MiJuego" --solo-genero     # juego ya traducido
```

---

## Flujo de trabajo (pasos numerados)

| Paso | Programa | Qué hace |
|---|---|---|
| 0 | `0_analizar_juego.py` | Crea `personajes.json`: protagonista, personajes, género con evidencia (pronombres, tratamientos…), alias y códigos de hablante. Si falta la ficha, el Paso 1 lo ejecuta solo. |
| 1 | `1_traducir_juego.py` | Traduce con Ollama (`--modo seguro/turbo`, `--modelo X` o `auto`, `--solo-genero`, `--archivo`, `--motor`). |
| 2 | `2_generar_revision.py` | Hoja CSV con el original, la traducción y los problemas, para revisar en una hoja de cálculo. |
| 3 | `3_reparar_etiquetas_ia.py` | Repara con la IA las etiquetas de formato rotas de esa hoja. |
| 4 | `4_aplicar_parches.py` | Inyecta tus correcciones o un diccionario en los archivos del juego. |
| 5 | `5_traducir_nombres_personajes.py` | Unifica los nombres de las cajas de diálogo con `workspace/<juego>/nombres_hablantes.csv` (`ingles;correccion`) y `nombres_propios.txt`. El motor CSV ya usa esa tabla al traducir. |
| 6 | `6_auditoria_semantica.py` | Corrige falsos amigos (*party* → grupo, *item* → objeto, *save* → guardar…). |
| 7 | `7_arreglar_partida_rpgmaker.py` | Aplica las correcciones a una partida guardada de RPG Maker (`.rpgsave`) sin empezar de nuevo. |
| 8 | `8_auditar_genero.py` | Audita y corrige el género de un juego ya traducido (también sobre una copia del archivo de XUnity). La 2.ª persona que no nombra a quien escucha se marca como `probable` si todos los que están en la escena son del otro género ("¿Estás segura?" a un protagonista hombre); se aplica solo con `--corregir --segunda`, tras revisar el informe. Lo mismo con el plural de grupo ("vosotros dos" a dos chicas → "vosotras dos"). |
| 9 | `9_evaluar_genero.py` | Banco de pruebas: ¿respeta el modelo el género de quien habla? Condiciones A (sin ficha), B (con pista), C (proceso completo) y D (`--sin-hablante`: sin saber quién habla, como en Unity). |

---

## Perfil de cada juego (`workspace/<juego>/`, privado)

| Archivo | Para qué |
|---|---|
| `personajes.json` | Ficha de personajes (Paso 0); se puede editar con `herramientas_extra/editor_personajes.py` |
| `glosario.json` | Términos obligatorios de ese juego (`{"inglés": "español"}`) |
| `glosario_bd.json` | Nombres de objetos, habilidades… de RPG Maker, traducidos una vez para que el inventario y los diálogos digan lo mismo (se crea solo; puedes corregirlo) |
| `contexto.txt` | Tono y ambientación; las líneas con `#` se ignoran |
| `nombres_protegidos.json` | Nombres que el modelo deforma (nombre -> expresión regular) |
| `ajustes.json` | Modelo de ese juego (`{"modelo": "auto"}` o uno concreto) y, en Unity, `tablas_unity` (ver `--pretraducir`) |
| `cache/` | Caché de traducciones por modelo |

Archivos **globales y privados** en `glosarios/`, a partir de sus plantillas `*.ejemplo.json`:

- `glosario_activo.json`: términos para todos los juegos.
- `nombres_protegidos.json`: nombres protegidos globales.
- `correcciones_locales.json`: tus correcciones de nombres y lugares que el modelo deforma, comodines del
  protagonista y códigos de hablante sin ficha. Se aplican al retocar cada traducción.
- `auditoria_semantica_local.json`: frases concretas para el Paso 6.

Genéricos y públicos: `contexto.txt` (estilo de español de España), `glosario_interfaz_rpgmaker.csv` (menús de RPG
Maker) y `glosario_adulto.json`.

---

## Calidad de la traducción

- **Concordancia de género.** Con la ficha, el prompt indica quién habla y a quién («Habla Ana (mujer).
  Probablemente se dirige al protagonista (hombre).»). Después se corrige la 1.ª persona, la 2.ª cuando se nombra a
  quien escucha y la 3.ª con nombre. El plural de grupo («nosotras», «estáis listos») solo cuando es seguro: si
  habla un hombre, «nosotros» va en masculino; si se nombra a un hombre que escucha, «vosotros» también; y si el
  inglés dice que el grupo son quien habla y quien escucha («both of us»), va en el género de los dos. También los
  sustantivos de persona tras «ser» que en inglés no tienen género («I'm an expert» → «Soy una experta», «soy su
  socia», «la elegida»). Las reglas son conservadoras: ante la duda, no se toca.
- **Cifras.** Si la traducción pierde, cambia o inventa un número («Charm+178» → «Encanto+96», «You have:5» →
  «Tienes:»), se reintenta diciendo al modelo las cifras del original. Un número escrito con letras («2 teams» →
  «dos equipos») vale.
- **Español de España** (`traductor/espana.py`). Cambia el vocabulario de Latinoamérica que se puede cambiar sin
  riesgo: «enojado» → «enfadado», «lindo» → «bonito», «apúrate» → «date prisa» y «te extraño» → «te echo de
  menos» (solo si el inglés dice *hurry* o *miss*). «Ustedes» con confianza solo se avisa, porque arreglarlo pide
  conjugar los verbos y en España también es de respeto.
- **Palabras con dos sentidos** (`traductor/ambiguas.py`). Pistas como «her chest», «stab you in the chest»,
  «treasure chest», «open the chest» o «get it off your chest» (frase hecha). Solo decide cuando el contexto es
  claro, y solo cambia la caché de esas frases.
- **Vocabulario adulto** (`glosarios/glosario_adulto.json`). Cada palabra lleva la traducción que prefieras; un
  valor vacío la desactiva. No se aplica en insultos ni en otros sentidos (el gallo, nombres propios, frases
  hechas). «You're a pussy» o «don't be a dick» son siempre insultos; la exclamación («What a pussy!») la decide
  la frase: con pistas de sexo es la parte del cuerpo, con pistas de cobardía o de mala persona es un insulto, y
  sin pistas se acepta cualquiera de los dos y decide el modelo con la frase anterior.
- **Coletillas pegadas.** Quita restos en inglés pegados al final de la traducción que algunos corpus de
  entrenamiento enseñan («ESTRELLAConstellation name (optional)»).
- **Nombres.** Restaura los nombres protegidos que el modelo deforma, sin pisar nunca un nombre que esté tal cual en
  el original.

---

## Unity y XUnity.AutoTranslator

`1_traducir_juego.py` sobre un juego de Unity instala la configuración de BepInEx y XUnity.AutoTranslator, y un
pequeño plugin que arranca el proxy de traducción (`ollama_proxy.py`) al abrir el juego. El plugin lee dónde está
este proyecto en `BepInEx/plugins/AutoProxyLauncher/traductor_ia_ruta.txt`, que se escribe al instalarlo, o en la
variable de entorno `TRADUCTOR_IA_RUTA`. Su código fuente está en `traductor/motores/recursos/AutoProxyPlugin.cs`.

Para corregir un juego de Unity ya traducido sin tocar el original, usa el Centro de Control: *Preparar copia
corregida* → *Instalar* / *Deshacer*.

**Quién habla.** XUnity manda las frases sueltas, sin decir quién las dice. Si el juego guarda sus diálogos como
objetos `Dialogue` y sus personajes como objetos `Character` (con nombre y sexo), el traductor los lee de los
archivos del juego (necesita `pip install UnityPy`) y crea `workspace/<juego>/hablantes_unity.json`. El proxy
usa esa tabla para el género de cada frase; los personajes que no están en la ficha toman el sexo que dice el
juego. La tabla guarda también quiénes hablan en cada conversación, y `8_auditar_genero.py` la usa para repasar
la 2.ª persona y el plural de un juego de Unity ya traducido. Si el juego no usa ese formato, todo funciona como
antes. Si sus tablas de texto traen ruso o ucraniano, la auditoría las usa como pista: esos idiomas dicen el sexo
de quien habla («я устала») y de quien escucha («ты уверена»).

**Juego ya traducido.** `--solo-genero` (o «♻ Juego ya traducido») en un juego de Unity no abre el proxy: repasa
`_AutoGeneratedTranslations.txt` y solo vuelve a pedir las frases con el género equivocado para quien habla,
una palabra de dos sentidos mal elegida o un fallo grave. La frase nueva solo entra si es mejor que la anterior;
el resto del archivo queda igual byte a byte. Conviene hacerlo sobre una copia.

**Traducir por adelantado (`--pretraducir`).** Muchos juegos de Unity llevan todo su texto dentro, en tablas
(`TextAsset` en CSV o TSV con una columna por idioma: `ID,ZH,EN,JA…`). Con `--pretraducir`, antes de abrir el
proxy se lee la columna inglesa de esas tablas (necesita UnityPy), se traduce en el orden de la historia y se
escribe en `_AutoGeneratedTranslations.txt`. Al jugar, XUnity encuentra las frases ya hechas y no hay esperas;
el proxy solo traduce lo que el juego monta al vuelo («Día 3», «Ánimo 50 %»).
- Si el archivo ya tenía otra traducción automática, la nueva la sustituye salvo que sea peor. Las líneas que
  no están en las tablas también se retraducen.
- Si la tabla trae ruso o ucraniano, sirve de pista del sexo de quien habla: en esos idiomas el pasado cambia
  con el sexo («я увидел» lo dice él, «я увидела» lo dice ella). Así «I'm sure» sale «estoy segura» cuando
  habla una chica, aunque el juego no diga quién habla.
- Se leen los `.assets`, los `level*` y también `data.unity3d` (juegos que lo empaquetan todo en un archivo).
- Se guarda cada 50 frases; si se corta, se puede relanzar y lo hecho sale de la caché.
- Lo propio de cada juego va en `ajustes.json` del perfil, sección `tablas_unity` (todo opcional):

  ```json
  "tablas_unity": {
    "omitir": ["tabla_vieja*"],
    "columna_hablante": {"TextData*": 1},
    "hablantes": {"莉莉": "Lily", "主角": "Protagonist", "？？？": ""},
    "variables": {"{flag=Flag_Heroine}": "Lily"}
  }
  ```

  - `omitir`: tablas que el juego no enseña.
  - `columna_hablante` y `hablantes`: en qué columna dice la tabla quién habla y a qué personaje de la ficha
    corresponde cada valor (`""` = nadie de la ficha). Si la pista rusa de una línea contradice al personaje,
    gana la pista.
  - `variables`: códigos que el juego cambia por un nombre antes de enseñar la frase. XUnity ve la frase ya
    cambiada, así que se traduce con el nombre puesto.

---

## Entrenamiento (opcional)

Puedes afinar un modelo propio con QLoRA y Unsloth y exportarlo a GGUF para Ollama:

```bash
python preparar_datos_v2.py                       # glosario y ejemplos con la misma instrucción que al traducir
python entrenar_v2.py --solo-datos --version 2    # resume los datos sin usar la GPU
python entrenar_v2.py --version 2 --casos-dificiles
ollama create IA_Traductora_v2 -f Modelfile_v2
python 9_evaluar_genero.py --modelo IA_Traductora_v2    # mídelo antes de usarlo
```

- Los datos de entrenamiento son tuyos (`datasets/`, privado). `herramientas_extra/dataset_genero.py` genera
  ejemplos con la pista de quién habla, y sus espejos (no los hace si el inglés fija el sexo: anatomía,
  «I'm a maid»…), a partir de un corpus con hablantes.
- Los ejemplos SIN pista de hablante que tienen género en 1.ª o 2.ª persona («Estoy segura») pasan a una forma
  neutra («Seguro que…», «¿Todo listo?») o se quitan, para que el modelo no aprenda a adivinar. Se desactiva
  con `--sin-neutros`.
- Al cargar los datos, `entrenar_v2.py` corrige o descarta los ejemplos que enseñan fallos conocidos: sentido
  equivocado de *chest*, coletillas pegadas, vocabulario que no es de España, palabras vulgares suavizadas.
- Las frases que el traductor arregla en un reintento se guardan en `workspace/<juego>/casos_dificiles.jsonl`.
  Inclúyelas con `--casos-dificiles`.

---

## Herramientas

- `herramientas_extra/monitor_bandeja.py`: el Centro de Control (`iniciar_monitor_bandeja.bat`).
- `herramientas_extra/servidor_progreso.py`: monitor web del progreso en `http://localhost:5050`.
- `herramientas_extra/crear_respaldo.py`: copia de seguridad ZIP de la traducción de un juego y de su perfil.
- `herramientas_extra/gestor_rpgmaker.py`: busca, inspecciona y parchea diálogos de RPG Maker con registro de
  cambios.
- `herramientas_extra/editor_personajes.py` y `configurar_perfil_juego.py`: editar la ficha de personajes.
- `herramientas_extra/instalar_correccion.py`: preparar, instalar o deshacer una corrección de XUnity con
  comprobaciones de seguridad.
- `diagnostico.bat`, `iniciar_modo_depuracion.bat` y `consola_cmd.bat`: diagnóstico del sistema y depuración.

---

## Pruebas

```bash
python -m unittest discover -s tests
```

No necesitan Ollama ni ningún juego, porque el modelo se simula. Usan nombres y frases inventados, y archivos de
prueba en `tests/datos/`.

---

## Estructura

```text
traductor/              núcleo: configuración, prompts, ficha de personajes, género, palabras con dos sentidos,
                        retoque y puerta de calidad (texto.py), cliente de Ollama con caché
traductor/motores/      RPG Maker, Ren'Py, CSV de idiomas, Unity/XUnity y detección del motor
herramientas_extra/     Centro de Control, monitor web, editor de personajes, respaldos y utilidades
glosarios/              diccionarios genéricos y plantillas *.ejemplo.json (los propios, privados)
tests/                  pruebas unitarias (tests/datos: archivos de prueba)
0_ ... 9_*.py           pasos del flujo de trabajo
ollama_proxy.py         proxy de traducción en tiempo real para XUnity
preparar_datos_v2.py    datos de entrenamiento;  entrenar_v2.py: entrenamiento con Unsloth
workspace/ datasets/ modelos/ privado/    PRIVADOS: nunca se suben (ver arriba)
```

---

## Licencia

El código está bajo la licencia [MIT](LICENSE). No se incluyen ni se distribuyen textos, traducciones ni modelos
derivados de juegos comerciales.
