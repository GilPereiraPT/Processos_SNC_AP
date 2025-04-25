# launcher.py
import sys, os, subprocess
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

APP_PATH = "app.py"

def show_popup(title, message):
    root = tk.Tk(); root.withdraw()
    messagebox.showerror(title, message)
    root.destroy()

def main():
    if not Path(APP_PATH).exists():
        show_popup("Ficheiro em falta", f"O ficheiro não existe:\n{APP_PATH}")
        sys.exit(1)

    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", APP_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=os.getcwd()
    )
    out, err = proc.communicate(timeout=20)
    if proc.returncode != 0:
        msg = out + "\n" + err
        show_popup("Erro ao iniciar a app", msg[:2000])

if __name__ == "__main__":
    main()
