import os
import subprocess
import sys
import shutil
from pathlib import Path

# ================== 1. CONFIGURAÇÕES ==================
# Use pathlib para lidar com caminhos de forma robusta e multiplataforma
BASE_DIR = Path(__file__).parent.resolve()

# O nome do script a ser compilado.
# Mude aqui se o nome do seu arquivo principal for diferente.
SCRIPT_NAME = "calendario_investing.py" 
# Nome do executável final
EXE_NAME = "CalendarioEconomico" 

# Caminho para o ícone
ICON_PATH = BASE_DIR / "image" / "AJJ_ComCor.ico"

# Pastas para incluir no executável
DATA_TO_ADD = ["image", "sound"]

# Pastas geradas pelo PyInstaller que serão limpas
BUILD_DIR = BASE_DIR / "build"
DIST_DIR = BASE_DIR / "dist"

# ================== 2. FUNÇÕES AUXILIARES ==================

def check_pyinstaller():
    """Verifica se o PyInstaller está instalado e, se não, o instala."""
    try:
        import PyInstaller
        print("PyInstaller já está instalado.")
    except ImportError:
        print("PyInstaller não encontrado. Instalando...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            print("PyInstaller instalado com sucesso.")
        except subprocess.CalledProcessError as e:
            print(f"Erro ao instalar PyInstaller: {e}", file=sys.stderr)
            sys.exit(1) # Encerra o script se a instalação falhar

def clean_previous_builds():
    """Remove diretórios de build anteriores e arquivos .spec para uma compilação limpa."""
    print("Limpando builds anteriores...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
        print(f"Diretório '{BUILD_DIR.name}' removido.")
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        print(f"Diretório '{DIST_DIR.name}' removido.")
    
    spec_file = BASE_DIR / f"{EXE_NAME}.spec"
    if spec_file.exists():
        spec_file.unlink()
        print(f"Arquivo '{spec_file.name}' removido.")

def build_executable():
    """Constrói e executa o comando PyInstaller de forma segura."""
    script_path = BASE_DIR / SCRIPT_NAME
    if not script_path.exists():
        print(f"Erro: O script principal '{SCRIPT_NAME}' não foi encontrado!", file=sys.stderr)
        sys.exit(1)

    # Constrói o comando como uma lista de argumentos (mais seguro que shell=True)
    command = [
        sys.executable,  # Caminho para o interpretador Python
        '-m', 'PyInstaller',
        '--noconsole',          # '--windowed' é um alias para isso
        '--onefile',
        '--name', EXE_NAME,
        '--icon', str(ICON_PATH),
        # --- CORREÇÃO APLICADA AQUI ---
        # Este argumento embute um manifesto no .exe que diz ao Windows
        # para SEMPRE solicitar permissão de administrador ao ser executado.
        '--uac-admin',
    ]

    # Adiciona as pastas de dados de forma multiplataforma
    # os.pathsep é o separador correto (';' no Windows, ':' no Linux/macOS)
    for folder_name in DATA_TO_ADD:
        folder_path = BASE_DIR / folder_name
        if folder_path.exists():
            # O formato correto para --add-data é "origem;destino_no_exe"
            command.extend(['--add-data', f'{folder_path}{os.pathsep}{folder_name}'])
        else:
            print(f"Aviso: A pasta de dados '{folder_name}' não foi encontrada e será ignorada.")

    command.append(str(script_path))

    print("\nExecutando o seguinte comando PyInstaller:")
    # Usa shlex.join para mostrar o comando de forma legível (opcional, mas bom para debug)
    try:
        import shlex
        print(" ".join(shlex.quote(str(arg)) for arg in command))
    except ImportError:
        print(command)

    try:
        # Executa o comando
        print("\nIniciando a compilação... Isso pode levar alguns minutos.")
        subprocess.check_call(command)
        print("\n" + "="*50)
        print(f"✅ Executável criado com sucesso em: {DIST_DIR / (EXE_NAME + '.exe')}")
        print("="*50)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Erro durante a compilação do PyInstaller: {e}", file=sys.stderr)
        sys.exit(1)

# ================== 3. EXECUÇÃO PRINCIPAL ==================

if __name__ == "__main__":
    check_pyinstaller()
    clean_previous_builds()
    build_executable()
