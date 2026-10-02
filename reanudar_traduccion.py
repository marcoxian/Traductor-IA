import os
import glob
import datetime
import subprocess

def main():
    base_path = r'J:\SteamLibrary\steamapps\common\米可可大冒險\www\data'
    script_path = r'j:\PythonAI\Traductor IA\auto_inyector.py'
    # Solo procesar los archivos que se modificaron antes de hoy (1 de octubre) o que fallaron
    # (Básicamente, cualquiera cuyo timestamp sea anterior al 2 de octubre a las 00:00)
    cutoff = datetime.datetime(2026, 10, 2, 0, 0, 0).timestamp()

    for p in glob.glob(os.path.join(base_path, '*.json')):
        if os.path.getmtime(p) < cutoff:
            filename = os.path.basename(p)
            print(f"Traduciendo {filename}...")
            subprocess.run(['python', script_path, '--ruta', r'J:\SteamLibrary\steamapps\common\米可可大冒險', '--archivo', filename])

if __name__ == '__main__':
    main()
