import streamlit as st
from datetime import datetime

# =========================
# REGRAS FIXAS
# =========================
SHIFT_AT_COL_1B = 52
SHIFT_SPACES = 3

# Campos para troca (1-based inclusive)
# (mantive o que já estavas a usar para o swap por largura fixa)
DEB_START_1B, DEB_END_1B = 60, 109
CRE_START_1B, CRE_END_1B = 110, 159

LINE_MIN_LEN = max(CRE_END_1B, SHIFT_AT_COL_1B)


def ensure_len(s: str, min_len: int) -> str:
    return s + (" " * (min_len - len(s))) if len(s) < min_len else s


def slice_1b(s: str, start: int, end: int) -> str:
    return s[start - 1:end]


def replace_1b(s: str, start: int, end: int, value: str) -> str:
    seg_len = end - start + 1
    value = value[:seg_len].ljust(seg_len)
    return s[:start - 1] + value + s[end:]


def swap_deb_cred(core: str) -> str:
    deb = slice_1b(core, DEB_START_1B, DEB_END_1B)
    cre = slice_1b(core, CRE_START_1B, CRE_END_1B)
    out = core
    out = replace_1b(out, DEB_START_1B, DEB_END_1B, cre)
    out = replace_1b(out, CRE_START_1B, CRE_END_1B, deb)
    return out


def already_shifted(core: str) -> bool:
    """
    Heurística simples para não shiftar 2x:
    - se as colunas 52-54 já forem espaços, assumimos que o shift já foi aplicado.
    """
    core = ensure_len(core, SHIFT_AT_COL_1B + SHIFT_SPACES)
    block = core[SHIFT_AT_COL_1B - 1:SHIFT_AT_COL_1B - 1 + SHIFT_SPACES]
    return block == (" " * SHIFT_SPACES)


def shift_from_col_52(core: str) -> str:
    """
    Insere 3 espaços a partir da coluna 52 (1-based).
    Aumenta o comprimento da linha em 3.
    """
    idx0 = SHIFT_AT_COL_1B - 1
    core = ensure_len(core, idx0)
    return core[:idx0] + (" " * SHIFT_SPACES) + core[idx0:]


def process_line(line: str) -> tuple[str, dict]:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    core = ensure_len(core, LINE_MIN_LEN)

    # 1) swap
    swapped = swap_deb_cred(core)

    # 2) shift na col 52 (se ainda não foi aplicado)
    did_shift = False
    if not already_shifted(swapped):
        swapped = shift_from_col_52(swapped)
        did_shift = True

    # Diagnóstico (apenas para inspeção rápida)
    deb_after = slice_1b(swapped, DEB_START_1B + (SHIFT_SPACES if did_shift else 0), DEB_END_1B + (SHIFT_SPACES if did_shift else 0)).strip()
    cre_after = slice_1b(swapped, CRE_START_1B + (SHIFT_SPACES if did_shift else 0), CRE_END_1B + (SHIFT_SPACES if did_shift else 0)).strip()

    info = {
        "swap": "sim",
        "shift_col52": "sim" if did_shift else "já tinha",
        "deb_depois": deb_after,
        "cred_depois": cre_after,
        "OK": True
    }

    return swapped + ("\n" if has_nl else ""), info


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out = []
    diag = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        out.append(new_ln)
        if i <= 20:
            diag.append({"Linha": i, **info})

    return "".join(out), diag


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT 905", layout="centered")
st.title("Retificar TXT – Troca Débito/Crédito + Shift na coluna 52")

st.markdown(
    f"""
**Processo fixo aplicado:**
1) Trocar campos **{DEB_START_1B}–{DEB_END_1B}** ↔ **{CRE_START_1B}–{CRE_END_1B}**  
2) Inserir **{SHIFT_SPACES} espaços** a partir da **coluna {SHIFT_AT_COL_1B}** (por linha) *(não aplica 2x)*  
"""
)

encoding = st.selectbox("Codificação", ["cp1252", "utf-8", "latin-1"], index=0)
uploaded = st.file_uploader("Seleciona o ficheiro TXT", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()
    try:
        text_in = raw.decode(encoding)
    except UnicodeDecodeError:
        st.error("Erro de codificação. Experimenta cp1252 ou latin-1.")
        st.stop()

    text_out, diag = process_text(text_in)

    st.subheader("Diagnóstico (primeiras 20 linhas)")
    st.table(diag)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = uploaded.name.rsplit(".", 1)[0] + f"_corrigido_{ts}.txt"

    st.download_button(
        "Descarregar TXT corrigido",
        data=text_out.encode(encoding),
        file_name=out_name,
        mime="text/plain",
    )
else:
    st.info("Carrega o TXT para processar.")
