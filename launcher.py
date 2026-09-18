from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


ROOT = Path(__file__).resolve().parent
APP_PATH = ROOT / "app.py"
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "streamlit-local.log"


def popup(title: str, message: str, error: bool = True) -> None:
    root = tk.Tk()
    root.withdraw()
    if error:
        messagebox.showerror(title, message)
    else:
        messagebox.showinfo(title, message)
    root.destroy()


def find_free_port(start: int = 8501, end: int = 8599) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Não foi encontrada uma porta local livre entre 8501 e 8599.")


def wait_until_ready(url: str, process: subprocess.Popen, timeout: int = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    if not APP_PATH.exists():
        popup("Ficheiro em falta", f"Não foi encontrado:\n{APP_PATH}")
        return 1

    try:
        import streamlit  # noqa: F401
    except Exception:
        popup(
            "Streamlit não instalado",
            "A instalação local ainda não está preparada.\n\n"
            "Execute primeiro o ficheiro INSTALAR_LOCAL.bat.",
        )
        return 2

    LOG_DIR.mkdir(exist_ok=True)
    port = find_free_port()
    local_url = f"http://127.0.0.1:{port}"
    health_url = f"{local_url}/_stcore/health"

    env = os.environ.copy()
    env["ULSLA_LOCAL_MODE"] = "1"

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]

    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write("\n\n=== Novo arranque local ===\n")
        log.flush()

        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

        if not wait_until_ready(health_url, process):
            try:
                process.terminate()
            except Exception:
                pass
            popup(
                "Erro ao iniciar",
                "Não foi possível iniciar o Hub Financeiro local.\n\n"
                f"Consulte o registo em:\n{LOG_PATH}",
            )
            return 3

        webbrowser.open(local_url, new=2)

        print("")
        print("========================================================")
        print("  HUB FINANCEIRO ULSLA — MODO LOCAL")
        print("========================================================")
        print(f"  Endereço: {local_url}")
        print("  Pode usar a aplicação no navegador normalmente.")
        print("  Feche esta janela ou prima Ctrl+C para terminar.")
        print("========================================================")
        print("")

        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
