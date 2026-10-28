"""Prepara um ambiente local independente para o Dashboard ULSLA."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 10):
        print('É necessário Python 3.10 ou superior. Recomenda-se Python 3.11.')
        return 1
    folder = ROOT / '.venv'
    python = folder / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.is_file():
        print('A criar o ambiente Python local...', flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    subprocess.check_call([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'requirements.txt')], cwd=ROOT)
    print('Instalação concluída. Abra INICIAR_LOCAL.bat ou execute .venv/bin/python iniciar_local.py.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print('Não foi possível concluir a instalação:', exc)
        sys.exit(1)
