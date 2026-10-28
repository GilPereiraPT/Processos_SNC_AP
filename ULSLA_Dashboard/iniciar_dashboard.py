# -*- coding: utf-8 -*-
"""Arranque robusto do Dashboard ULSLA sem dependência de PowerShell."""
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def porta_disponivel(porta):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(('127.0.0.1', porta))
            return True
        except OSError:
            return False


def main():
    if not (ROOT / 'app.py').is_file():
        sys.exit('ERRO: app.py não foi encontrado.')
    for porta in range(8514, 9000):
        if not porta_disponivel(porta):
            continue
        print(f'Dashboard ULSLA: http://localhost:{porta}', flush=True)
        comando = [sys.executable, '-m', 'streamlit', 'run', 'app.py',
                   '--server.port', str(porta), '--server.address', '127.0.0.1',
                   '--server.headless', 'false']
        try:
            return subprocess.call(comando, cwd=str(ROOT))
        except OSError as exc:
            print('Erro ao iniciar o Streamlit:', exc)
            return 1
    print('ERRO: não foi encontrada nenhuma porta livre entre 8514 e 8999.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
