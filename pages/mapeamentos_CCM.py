# -*- coding: utf-8 -*-
import re
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

# =========================================================
# ⚙️ Estado global
# =========================================================
if "mapping_dict" not in st.session_state:
    st.session_state.mapping_dict = {}

if "missing_codes" not in st.session_state:
    st.session_state.missing_codes = set()

# =========================================================
# ⚙️ Funções de Mapeamento
# =========================================================
@st.cache_data(ttl=3600)
def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
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
# 🧩 Transformação + deteção de erros
# =========================================================
def transform_line(line: str, mapping: Dict[str, str], expected_len: int = None):
    original_len = len(line)
    if expected_len is None:
        expected_len = original_len

    missing_found = set()

    # 1️⃣ Corrigir Coluna 12
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # 2️⃣ Corrigir CC
    line = re.sub(r"\+93\s\s", "+9197", line)

    # 3️⃣ Processar tokens
    parts = line.split(maxsplit=2)

    if len(parts) >= 2:
        token2 = parts[1]

        matched_conv = next(
            (c for c in sorted(mapping.keys(), key=len, reverse=True) if c in token2),
            None
        )

        if matched_conv:
            ent_code = mapping[matched_conv]

            try:
                ent7 = f"{int(ent_code):07d}"

                pattern7 = "0" + matched_conv
                if pattern7 in token2:
                    new_token2 = token2.replace(pattern7, ent7, 1)
                else:
                    idx = token2.find(matched_conv)
                    new_token2 = token2[:idx] + ent7 + token2[idx + len(matched_conv):]

                if line.lstrip().startswith(("903", "904", "906")) and new_token2.startswith("0"):
                    new_token2 = new_token2[1:]

                new_token2 = new_token2.ljust(len(token2))

                # reconstrução segura
                prefix = line[:line.find(token2)]
                suffix = line[line.find(token2) + len(token2):]

                line = prefix.rstrip() + " " + new_token2 + suffix

            except:
                pass

        else:
            # 🔍 detetar possíveis códigos não mapeados
            possible_codes = re.findall(r"\d{6}", token2)
            for code in possible_codes:
                if code not in mapping:
                    missing_found.add(code)

    # 4️⃣ Remover NIF
    line = re.sub(r"\s\d{9}\s*$", " ", line)

    # 5️⃣ Ajuste comprimento
    if len(line) > expected_len:
        line = line[:expected_len]
    elif len(line) < expected_len:
        line = line.ljust(expected_len)

    return line, missing_found


# =========================================================
# 📄 Utilitários
# =========================================================
def split_keep_eol(text: str):
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
            out.append((p, ""))

    return out


def guess_default_eol(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    if "\r" in text:
        return "\r"
    return "\n"


# =========================================================
# 🎨 Interface
# =========================================================
st.set_page_config(page_title="Conversor MCDT", layout="wide")
st.title("🏥 Conversor MCDT / Termas — com Auto-Aprendizagem")

# carregar mapping inicial
if not st.session_state.mapping_dict:
    mapping_dict, _ = load_default_mapping("mapeamentos.csv")
    st.session_state.mapping_dict = mapping_dict

mapping_dict = st.session_state.mapping_dict

st.success(f"✅ Mapeamentos ativos: {len(mapping_dict)}")

# botão refresh
if st.button("🔄 Recarregar mapeamento original"):
    st.cache_data.clear()
    st.session_state.mapping_dict = load_default_mapping("mapeamentos.csv")[0]
    st.rerun()

# upload ficheiros
uploaded_files = st.file_uploader("📂 Submeter ficheiros", accept_multiple_files=True)

# =========================================================
# 🚀 PROCESSAMENTO
# =========================================================
if uploaded_files:
    for f in uploaded_files:
        content = f.read()

        try:
            text = content.decode("utf-8-sig")
        except:
            try:
                text = content.decode("utf-8")
            except:
                text = content.decode("latin-1")

        default_eol = guess_default_eol(text)
        lines = split_keep_eol(text)

        total = len(lines)
        progress = st.progress(0)

        processed = []
        missing_all = set()

        for i, (line_body, eol) in enumerate(lines):

            if not line_body.strip():
                processed.append(line_body + eol)
                continue

            new_line, missing = transform_line(line_body, mapping_dict)

            missing_all.update(missing)
            processed.append(new_line + eol)

            if i % 500 == 0 or i == total - 1:
                progress.progress(i / total)

        progress.progress(1.0)

        # guardar missing
        st.session_state.missing_codes.update(missing_all)

        output = "".join(processed)

        if not output.endswith(("\n", "\r\n", "\r")):
            output += default_eol

        st.success(f"✅ {f.name} convertido")

        st.download_button(
            f"📥 Download {f.name}",
            output.encode("utf-8"),
            f"CORRIGIDO_{f.name}",
            "text/plain"
        )

# =========================================================
# 🧠 UI de aprendizagem
# =========================================================
if st.session_state.missing_codes:

    st.warning("⚠️ Existem códigos sem mapeamento")

    new_entries = {}

    for code in sorted(st.session_state.missing_codes):
        col1, col2 = st.columns([1, 2])

        with col1:
            st.write(f"Conv: {code}")

        with col2:
            val = st.text_input(f"Entidade", key=f"input_{code}")
            if val:
                new_entries[code] = val

    if st.button("💾 Guardar novos mapeamentos"):
        for k, v in new_entries.items():
            st.session_state.mapping_dict[k] = v

        st.session_state.missing_codes.clear()

        st.success("✅ Mapeamentos atualizados!")
        st.rerun()

    # export CSV atualizado
    if st.button("📤 Exportar CSV atualizado"):
        df = pd.DataFrame(
            list(st.session_state.mapping_dict.items()),
            columns=["Convencao", "Entidade"]
        )

        csv = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "📥 Download CSV",
            csv,
            "mapeamentos_atualizado.csv",
            "text/csv"
        )
