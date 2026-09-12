import os
import zipfile

ADDON_NAME = "Cut3D"
ZIP_FILENAME = f"{ADDON_NAME}_addon.zip"

FILES_TO_INCLUDE = [
    "__init__.py",
    "properties.py",
    "connectors.py",
    "cut_math.py",
    "draft_engine.py",
    "cutter_engine.py",
    "ui_panel.py",
    "exporter.py",
]

def create_zip():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(base_dir, ZIP_FILENAME)

    print(f"[Cut3D] Empacotando addon em '{zip_path}'...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for filename in FILES_TO_INCLUDE:
            filepath = os.path.join(base_dir, filename)
            if os.path.exists(filepath):
                arcname = os.path.join(ADDON_NAME, filename)
                zipf.write(filepath, arcname)
                print(f"  + Adicionado: {arcname}")
            else:
                print(f"  ! Arquivo nao encontrado: {filename}")

    print(f"\nConcluido com sucesso! Arquivo gerado: {ZIP_FILENAME}")
    print("Para instalar no Blender:")
    print("1. Abra o Blender")
    print("2. Vá em Edit > Preferences > Add-ons")
    print("3. Clique na seta superior / 'Install from Disk...'")
    print(f"4. Selecione o arquivo '{ZIP_FILENAME}' e ative a caixa de seleção!")

if __name__ == "__main__":
    create_zip()
