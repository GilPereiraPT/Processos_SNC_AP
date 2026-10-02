# -*- coding: utf-8 -*-
"""Sincronizacao segura e bidirecional de mapeamentos.csv com o GitHub."""
import base64
import csv
import io
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

OWNER = "GilPereiraPT"
REPO = "Processos_SNC_AP"
BRANCH = "main"
REMOTE_PATH = "mapeamentos.csv"
LOCAL_PATH = Path(__file__).resolve().parent / "mapeamentos.csv"
API = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{REMOTE_PATH}"
HEADERS = ["Cod. Convencao", "Cod. Entidade"]


def normalize_code(value):
    digits = str(value or "").strip()
    if not digits.isdigit():
        raise ValueError(f"Codigo invalido: {value!r}")
    return str(int(digits))


def parse_csv(data, source):
    text = data.decode("utf-8-sig")
    rdr = csv.DictReader(io.StringIO(text), delimiter=";")
    if rdr.fieldnames != HEADERS:
        raise ValueError(f"{source}: colunas inesperadas: {rdr.fieldnames!r}")
    records = {}
    for idx, row in enumerate(rdr, start=2):
        if None in row or None in row.values():
            raise ValueError(f"{source}: formato invalido na linha {idx}")
        key = normalize_code(row[HEADERS[0]])
        val = normalize_code(row[HEADERS[1]])
        if key in records and records[key] != val:
            raise ValueError(f"{source}: convenção repetida com entidades diferentes: {key}")
        records[key] = val
    return records


def render_csv(rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(HEADERS)
    for k in sorted(rows, key=lambda x: int(x)):
        writer.writerow([k, rows[k]])
    return out.getvalue().encode("utf-8-sig")


def request_json(method="GET", payload=None, token=None):
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "ULSLA-CCM-Sync",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        import json
        payload = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        API + (f"?ref={BRANCH}" if method == "GET" else ""),
        data=payload, headers=headers, method=method)
    import json
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"GitHub HTTP {exc.code}: {detail}") from exc


def write_local(data):
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCAL_PATH.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = LOCAL_PATH.with_name(f"mapeamentos.backup_{stamp}.csv")
        shutil.copy2(LOCAL_PATH, backup)
        print(f"Backup local: {backup.name}")
    fd, temp = tempfile.mkstemp(prefix="ccm_sync_", suffix=".tmp",
                                 dir=str(LOCAL_PATH.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(temp, LOCAL_PATH)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    local_exists = LOCAL_PATH.exists()
    local_raw = LOCAL_PATH.read_bytes() if local_exists else None
    local = parse_csv(local_raw, "Local") if local_exists else {}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    remote_obj = request_json(token=token)
    remote_raw = base64.b64decode(remote_obj["content"].replace("\n", ""))
    remote = parse_csv(remote_raw, "GitHub")
    remote_sha = remote_obj["sha"]

    conflicts = [(k, local[k], remote[k]) for k in local.keys() & remote.keys()
                 if local[k] != remote[k]]
    if conflicts:
        print("CONFLITO: a mesma convencao tem entidades diferentes. Nada foi alterado.")
        for k, lv, rv in sorted(conflicts):
            print(f"  Convencao {k}: local={lv}; GitHub={rv}")
        print("Corrija manualmente uma das tabelas e execute novamente.")
        return 2

    merged = {**remote, **local}
    needs_push = merged != remote
    needs_local = merged != local or not local_exists
    if not needs_push and not needs_local:
        print(f"CCM sincronizado: {len(merged)} convencoes. Sem alteracoes.")
        return 0
    merged_raw = render_csv(merged)

    if needs_push:
        if not token:
            print("Existem novos mapeamentos locais para publicar no GitHub.")
            # A janela evita qualquer necessidade de PowerShell ou linha de comandos.
            try:
                import tkinter as tk
                from tkinter import simpledialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                try:
                    token = simpledialog.askstring(
                        "Sincronizacao CCM - GitHub",
                        "Cole o token GitHub (Contents: Read and write).\n"
                        "O token nao sera guardado neste computador:",
                        show="*", parent=root
                    ) or ""
                finally:
                    root.destroy()
            except Exception as exc:
                print(f"Nao foi possivel abrir a janela de credenciais: {exc}")
                return 3
            token = token.strip()
            if not token:
                print("Sincronizacao cancelada: o GitHub nao foi alterado.")
                return 3
        request_json("PUT", {
            "message": "Sincronizar convencoes CCM locais",
            "content": base64.b64encode(merged_raw).decode("ascii"),
            "sha": remote_sha, "branch": BRANCH
        }, token=token)
        print(f"GitHub atualizado: {len(merged) - len(remote)} convencao(oes) acrescentada(s).")

    if needs_local:
        write_local(merged_raw)
        print(f"Tabela local atualizada: {len(merged) - len(local)} convencao(oes) acrescentada(s).")
    print(f"Sincronizacao concluida: {len(merged)} convencoes.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERRO NA SINCRONIZACAO: {exc}")
        print("Verifique a ligacao a rede, as credenciais e o ficheiro CSV.")
        sys.exit(1)
