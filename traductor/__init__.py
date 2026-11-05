"""Núcleo compartido del Traductor IA.

Módulos:
    config       Rutas del proyecto, ajustes de Ollama y perfiles de juego (glosario/contexto/nombres).
    prompts      Instrucción ÚNICA usada tanto al traducir como al entrenar.
    texto        Utilidades de texto: etiquetas de formato, ajuste de línea, saltos y nombres.
    ollama       Cliente de Ollama con caché persistente, lotes, reintentos y autocorrección.
    csv_locales  Lectura/escritura de CSV de localización (DKTools_Localization, Godot...).
    registro     Configuración de logging con colores para la consola de Windows.
    motores      Estrategias de inyección por motor (RPG Maker, CSV, Unity).

Este paquete no importa nada pesado al cargarse para que lo puedan usar también
los scripts de entrenamiento sin arrastrar dependencias innecesarias.
"""

__version__ = "2.0.0"
