import subprocess
import sys

# 🔧 Altere somente aqui o comentário do commit
COMMIT_MESSAGE = "Fix: Oculta janelas de console ao gerenciar tarefas"

def run_cmd(cmd):
    """Executa um comando e mostra a saída em tempo real"""
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        sys.exit(result.returncode)

def main():
    print("📌 Adicionando alterações...")
    run_cmd("git add .")

    print(f"📌 Commitando com mensagem: {COMMIT_MESSAGE}")
    run_cmd(f'git commit -m "{COMMIT_MESSAGE}"')

    print("📌 Fazendo pull com rebase...")
    run_cmd("git pull origin main --rebase")

    print("📌 Enviando para o GitHub...")
    run_cmd("git push origin main")

    print("✅ Tudo sincronizado com sucesso!")

if __name__ == "__main__":
    main()
