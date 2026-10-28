"""Gestor local, sem dependencias adicionais, para modulos Streamlit ULSLA.
Inicia apenas os processos explicitamente pedidos; nao toca nos dados existentes.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

BASE = Path(__file__).resolve().parent
CFG_FILE = BASE / 'portal_ulsla.json'
LOGS = BASE / 'logs_portal'

def config():
    return json.loads(CFG_FILE.read_text(encoding='utf-8'))

def available(port: int, timeout=0.7) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=timeout):
            return True
    except OSError:
        return False

def ready(port: int, timeout=1.5) -> bool:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{int(port)}/_stcore/health', timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False

def start_module(script: str, port: int, wait: float=8.0):
    """Returns (ok, detail); never kills a user process or starts another if port busy."""
    path = BASE / script
    if not path.is_file():
        return False, f'Não foi encontrado {script} em {BASE}'
    if ready(port):
        return True, f'Aplicação já ativa na porta {port}'
    if available(port):
        return False, f'Porta {port} ocupada por outro serviço. Verifique a configuração.'
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f'{Path(script).stem}_{port}.log', 'ab', buffering=0)
    cmd = [sys.executable, '-m', 'streamlit', 'run', str(path), '--server.address', '127.0.0.1', '--server.port', str(port), '--server.headless', 'true', '--browser.gatherUsageStats', 'false']
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
                                creationflags=flags, stdin=subprocess.DEVNULL, close_fds=True)
    except Exception as exc:
        log.close()
        return False, f'Falha no arranque de {script}: {exc}'
    finally:
        log.close()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if ready(port, timeout=0.4):
            return True, f'Aplicação iniciada na porta {port}'
        if proc.poll() is not None:
            return False, f'O processo terminou com código {proc.returncode}. Consultar logs_portal/{Path(script).stem}_{port}.log'
        time.sleep(0.25)
    return False, f'Arranque em curso na porta {port}; aguarde e atualize o estado. Consulte logs_portal.'

def run_all():
    cfg = config()
    targets = [('Portal ULSLA','portal_ulsla.py',8500)]
    for mod in cfg.get('modulos',[]):
        targets.append((mod['nome'],mod['script'],int(mod['porta'])))
    for title,script,port in targets:
        ok, msg = start_module(script, port, wait=12)
        print(f'{"[OK]" if ok else "[AVISO]"} {title}: {msg}', flush=True)
    if ready(8500):
        webbrowser.open('http://127.0.0.1:8500')
    else:
        print('O portal ainda nao esta pronto. Consulte logs_portal.', flush=True)

if __name__ == '__main__':
    run_all()
