import os
import glob
import subprocess

def main():
    base_path = r'J:\SteamLibrary\steamapps\common\米可可大冒險\www\data'
    script_path = r'j:\PythonAI\Traductor IA\auto_inyector.py'
    
    # Archivos que sabemos que quedaron pendientes o se corrompieron hoy
    target_files = [
        "MapInfos.json", "States.json", "Tilesets.json", "Troops.json"
    ]
    # Añadir los mapas del 008 al 034
    for i in range(8, 35):
        target_files.append(f"Map{i:03d}.json")
        
    for filename in target_files:
        p = os.path.join(base_path, filename)
        if os.path.exists(p):
            print(f"Traduciendo {filename}...")
            subprocess.run(['python', script_path, '--ruta', r'J:\SteamLibrary\steamapps\common\米可可大冒險', '--archivo', filename])

if __name__ == '__main__':
    main()
