import streamlit as st
from datetime import datetime

# =========================
# ESPECIFICAÇÕES (1-based, inclusive)
# =========================
POS_DEB_START = 60
POS_DEB_END   = 109   # 50 chars
POS_CRE_START = 110
POS_CRE_END   = 159   # 50 chars

POS_CC_START  = 179
POS_CC_END    = 188   # 10 chars

POS_TYPE_START = 1
POS_TYPE_END   = 3    # "905"

LINE_MIN_LEN = POS_CC_END  # precisamos pelo menos até ao CC


def slice_1b(s: str, start: int, end: int) -> str:
    """Slice por posições 1-based inclusive."""
    return s[start-1:end]


def replace_1b(s: str, start: int, end: int, value: str) -> str:
    """Substitui o intervalo 1-based inclusive por value (ajusta ao comprimento do intervalo)."""
    seg_len = end - start + 1
    value = value[:seg_len].ljust(seg_len)
    return s[:start-1] + value + s[end:]


def ensure_len(s: str, min_len: int) -> str:
    if len(s) < min_len:
        return s + (" " * (min_len - len(s)))
    return s


def process_line(line: str) -> tuple[str, dict]:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    core = ensure_len(core, LINE_MIN_LEN)

    tipo = slice_1b(core, POS_TYPE_START, POS_TYPE_END)

    deb = slice_1b(core, POS_DEB_START, POS_DEB_END)
    cre = slice_1b(core, POS_CRE_START, POS_CRE_END)
    cc  = slice_1b(core, POS_CC_START, POS_CC_END)

    # Trocar sempre débito e crédito (campos completos de 50)
    swapped = core
    swapped = replace_1b(swapped, POS_DEB_START, POS_DEB_END, cre)
    swapped = replace_1b(swapped, POS_CRE_START, POS_CRE_END, deb)

    # Diagnóstico
    info = {
        "Tipo": tipo.strip(),
        "Deb_antes": deb.strip(),
        "Cre_antes": cre.strip(),
        "Deb_depois": cre.strip(),
        "Cre_depois": deb.strip(),
        "CC": cc,
        "CC_vazio": (cc.strip() == ""),
        "OK": True
    }

    # Se quiseres processar só linhas 905, ativa esta regra:
    # if tipo != "905":
    #     info["OK"] = False
    #     return line, info

    return swapped + ("\n" if has_nl else ""), info


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out = []
    diag = []
    cc_empty = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        out.append(new_ln)

        if i <= 20:
            diag.append({"Linha": i, **info})

        if info["CC_vazio"]:
            cc_empty.append({"Linha": i, "Tipo": info["Tipo"], "CC_raw(179-188)": info["CC"]})

    return "".join(out), diag, cc_empty


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT 905", layout="centered")
st.title("Retificar TXT 905 – troca Conta Débito / Conta Crédito")

st.markdown(
    """
**Operação aplicada (fixa):**
- Trocar os campos:
  - Conta Débito **60–109 (50)**
  - Conta Crédito **110–159 (50)**

O resto da linha fica exatamente igual.
"""
)

encoding = st.selectbox("Codificação do ficheiro", ["cp1252", "utf-8", "latin-1"], index=0)
uploaded = st.file_uploader("Seleciona o ficheiro TXT", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()
    try:
        text_in = raw.decode(encoding)
    except UnicodeDecodeError:
        st.error("Erro de codificação. Experimenta cp1252 ou latin-1.")
        st.stop()

    text_out, diag, cc_empty = process_text(text_in)

    st.subheader("Diagnóstico (primeiras 20 linhas)")
    st.table(diag)

    if cc_empty:
        st.warning(f"Centro de custo vazio em {len(cc_empty)} linha(s). (Campo 179–188 está só com espaços.)")
        st.table(cc_empty[:200])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = uploaded.name.rsplit(".", 1)[0] + f"_905_swap_{ts}.txt"

    st.download_button(
        "Descarregar TXT corrigido",
        data=text_out.encode(encoding),
        file_name=out_name,
        mime="text/plain",
    )
else:
    st.info("Carrega o TXT para processar.")
