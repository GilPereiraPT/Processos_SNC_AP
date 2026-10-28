"""Inicia apenas o portal em 127.0.0.1; os módulos abrem pelos botões do portal."""
from pathlib import Path
import subprocess
import sys
import webbrowser
from ulsla_launcher import available, ready

ROOT = Path(__file__).resolve().parent


def main():
    if ready(8500):
        webbrowser.open('http://127.0.0.1:8500')
        return 0
    if available(8500):
        print('A porta 8500 está ocupada. Feche a aplicação que a está a utilizar e volte a iniciar.')
        return 1
    return subprocess.call([sys.executable, '-m', 'streamlit', 'run', str(ROOT/'portal_ulsla.py'),
                           '--server.address', '127.0.0.1', '--server.port', '8500',
                           '--server.headless', 'false', '--browser.gatherUsageStats', 'false'], cwd=ROOT)


if __name__ == '__main__':
    sys.exit(main())
