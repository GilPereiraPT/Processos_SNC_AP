# -*- coding: utf-8 -*-
import re
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

# =========================================================
# ⚙️ Funções de Mapeamento
# =========================================================
@st.cache_data
def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """Lê o ficheiro de mapeamentos (detecta separador automaticamente)."""
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        mapping = {}
        c_col, e_col = df.columns[0], df.columns[1]
        for _, row in df.iterrows():
            c = re.sub(r"\D", "", str(row[c_col])).zfill(6)
            e = str(row[e_col]).strip().replace(".0", "").replace(" ", "")
            if c and e and e.lower() != "nan":
                mapping[c] = e
        return mapping, df
    except Exception as e:
        st.error(f"❌ Erro ao carregar mapeamento: {e}")
        return {}, None


# =========================================================
# 🧩 Lógica de Transformação Rígida
# =========================================================
def transform_line(line: str, mapping: Dict[str, str], expected_len: int = None) -> str:
    """Transforma uma linha mantendo colunas fixas e apenas 1 espaço antes da entidade."""
    original_len = len(line)
    if expected_len is None:
        expected_len = original_len

    # 1️⃣ Corrigir Coluna 12 (Posição 11)
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # 2️⃣ Corrigir CC "+93  " -> "+9197"
    line = re.sub(r"\+93\s\s", "+9197", line)

    # 3️⃣ Substituir Convenção → Entidade (mantendo alinhamento)
    m = re.search(r"^(\S+)(\s+)(\S+)", line)
    if m:
        token2 = m.group(3)
        start_pos, end_pos = m.start(3), m.end(3)

        matched_conv = next(
            (c for c in sorted(mapping.keys(), key=len, reverse=True) if c in token2),
            None
        )
        if matched_conv:
            ent_code = mapping[matched_conv]
            try:
                ent7 = f"{int(ent_code):07d}"

                # tenta substituir "0"+convenção primeiro, senão substitui a convenção
                pattern7 = "0" + matched_conv
                if pattern7 in token2:
                    new_token2 = token2.replace(pattern7, ent7, 1)
                else:
                    idx = token2.find(matched_conv)
                    new_token2 = token2[:idx] + ent7 + token2[idx + len(matched_conv):]

                # ✅ Correção específica: linhas 903/904/906 — retirar apenas o '0' inicial do token2
                if line.startswith(("903", "904", "906")) and new_token2.startswith("0"):
                    new_token2 = new_token2[1:]

                # manter largura original do token2 (rigidez)
                new_token2 = new_token2.ljust(len(token2))

                # Garante apenas 1 espaço antes da entidade
                pre_space = line[:start_pos].rstrip() + " "
                post_content = line[end_pos:]

                new_line = pre_space + new_token2 + post_content

                # Ajuste de comprimento total
                if len(new_line) > expected_len:
                    new_line = new_line[:expected_len]
                elif len(new_line) < expected_len:
                    new_line = new_line.ljust(expected_len)

                line = new_line

            except ValueError:
                pass

    # 4️⃣ Remover NIF no fim (9 dígitos) mantendo espaço único
    line = re.sub(r"\s\d{9}$", " ", line)

    # 5️⃣ Garantir comprimento fixo final
    if len(line) > expected_len:
        line = line[:expected_len]
    elif len(line) < expected_len:
        line = line.ljust(expected_len)

    return line


def split_keep_eol(text: str):
    """
    Divide em linhas preservando EOL (\n / \r\n).
    Devolve lista de tuplos: (linha_sem_eol, eol_original)
    """
    parts = text.splitlines(keepends=True)
    out = []
    for p in parts:
        if p.endswith("\r\n"):
            out.append((p[:-2], "\r\n"))
        elif p.endswith("\n"):
            out.append((p[:-1], "\n"))
        elif p.endswith("\r"):
            out.append((p[:-1], "\r"))
        else:
            out.append((p, ""))  # última linha pode não ter EOL
    return out


def guess_default_eol(text: str) -> str:
    """Escolhe EOL mais provável para o ficheiro."""
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    if "\r" in text:
        return "\r"
    return "\n"


# =========================================================
# 🎨 Interface Streamlit
# =========================================================
st.set_page_config(page_title="Conversor MCDT/Termas (Formato Rígido)", layout="wide")
st.title("🏥 Conversor de ficheiros MCDT / Termas — Formato Rígido v2027.5")
st.caption("Mantém colunas fixas, garante 1 espaço antes da entidade e preserva EOL para o ERP.")

mapping_dict, _ = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("⚠️ Ficheiro 'mapeamentos.csv' não encontrado ou inválido.")
else:
    st.success(f"✅ Mapeamento carregado com {len(mapping_dict)} códigos válidos.")

    uploaded_files = st.file_uploader("📂 Submeta ficheiros para conversão individual", accept_multiple_files=True)

    if uploaded_files:
        for f in uploaded_files:
            content = f.read()
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = content.decode("latin-1")

            default_eol = guess_default_eol(text)
            lines_with_eol = split_keep_eol(text)
            total = len(lines_with_eol)

            st.info(f"📄 Ficheiro **{f.name}** contém {total:,} linhas. A processar...")

            progress = st.progress(0, text="A converter...")
            processed_parts = []
            len_diff = 0

            for i, (line_body, eol) in enumerate(lines_with_eol):
                if not line_body.strip():
                    processed_parts.append(line_body + eol)
                    continue

                expected_len = len(line_body)
                new_body = transform_line(line_body, mapping_dict, expected_len)

                if len(new_body) != expected_len:
                    len_diff += 1

                # 🔒 Preservar exactamente o EOL original
                processed_parts.append(new_body + eol)

                if i % 50 == 0 or i == total - 1:
                    progress.progress(i / total)

            progress.progress(1.0, text="Conversão concluída ✅")

            # ✅ Garantir que o ficheiro termina com newline (muitos ERPs exigem)
            output = "".join(processed_parts)
            if not output.endswith(("\r\n", "\n", "\r")):
                output += default_eol

            st.success(f"✅ Conversão terminada para {f.name}")
            st.write(f"📏 Linhas processadas: {total:,}")
            st.write(f"⚠️ Linhas ajustadas em comprimento: {len_diff:,}")
            st.write(f"↩️ EOL detetado/forçado no fim: `{default_eol.encode('unicode_escape').decode()}`")

            output_bytes = output.encode("utf-8")

            st.download_button(
                label=f"📥 Guardar ficheiro corrigido — {f.name}",
                data=output_bytes,
                file_name=f"CORRIGIDO_{f.name}",
                mime="text/plain",
                key=f"download_{f.name}"
            )
