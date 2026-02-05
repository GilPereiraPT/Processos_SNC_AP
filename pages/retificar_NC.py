import streamlit as st
from datetime import datetime

# =========================
# FORMATO FIXO (1-based)
# =========================
# Se o teu ficheiro original tem a data a começar na 52 e queres que fique na 55:
INSERT_FROM_COL_1B = 52
SHIFT_SPACES = 3

# Depois do alinhamento (com base no teu exemplo correto):
DEBIT_COL_1B = 63
CREDIT_COL_1B = 113


def shift_line(line: str) -> str:
    """Insere SHIFT_SPACES espaços a partir de INSERT_FROM_COL_1B."""
    idx = INSERT_FROM_COL_1B - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    if len(core) < idx:
        core += " " * (idx - len(core))

    core = core[:idx] + (" " * SHIFT_SPACES) + core[idx:]
    return core + ("\n" if has_nl else "")


def read_digits(core: str, start0: int) -> tuple[str, int]:
    """Lê dígitos consecutivos a partir de start0 (0-based)."""
    if start0 >= len(core) or not core[start0].isdigit():
        return "", start0
    i = start0
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start0:i], i


def write_over(chars: list[str], start0: int, old_end0: int, new_text: str) -> None:
    """Substitui o run antigo por new_text limpando restos."""
    old_len = max(0, old_end0 - start0)
    wipe_len = max(old_len, len(new_text))

    need = start0 + wipe_len
    if need > len(chars):
        chars.extend([" "] * (need - len(chars)))

    for i in range(start0, start0 + wipe_len):
        chars[i] = " "
    for i, ch in enumerate(new_text):
        chars[start0 + i] = ch


def swap_always(line: str) -> tuple[str, dict]:
    """
    1) Alinha data (shift)
    2) Troca SEMPRE os dígitos em DEBIT_COL_1B e CREDIT_COL_1B
    """
    shifted = shift_line(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    d0 = DEBIT_COL_1B - 1
    c0 = CREDIT_COL_1B - 1

    min_len = max(d0, c0) + 1
    if len(core) < min_len:
        core += " " * (min_len - len(core))

    deb, deb_end = read_digits(core, d0)
    cred, cred_end = read_digits(core, c0)

    info = {
        "deb_antes": deb,
        "cred_antes": cred,
        "OK": True
    }

    # Se numa das posições não houver dígitos, bloqueia (para não estragar)
    if deb == "" or cred == "":
        info["OK"] = False
        return shifted, info

    chars = list(core)
    write_over(chars, d0, deb_end, cred)
    write_over(chars, c0, cred_end, deb)

    new_core = "".join(chars)

    # Ler novamente para diagnóstico
    deb2, _ = read_digits(new_core, d0)
    cred2, _ = read_digits(new_core, c0)
    info["deb_depois"] = deb2
    info["cred_depois"] = cred2

    return new_core + ("\n" if has_nl else ""), info


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out = []
    diag = []
    bad = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = swap_always(ln)

        if i <= 20:
            diag.append({"Linha": i, **info})

        if not info["OK"]:
            bad.append({"Linha": i, **info})
            out.append(ln)  # não mexe
        else:
            out.append(new_ln)

    return "".join(out), diag, bad


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT (swap sempre)", layout="centered")
st.title("Retificar TXT – alinhar data + trocar Débito/Crédito")

st.markdown(
    f"""
**Regras fixas:**
- Inserir **{SHIFT_SPACES} espaços** a partir da **coluna {INSERT_FROM_COL_1B}** (data 52 → 55)
- Trocar **sempre** os números em:
  - Débito: **coluna {DEBIT_COL_1B}**
  - Crédito: **coluna {CREDIT_COL_1B}**
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

    text_out, diag, bad = process_text(text_in)

    st.subheader("Diagnóstico (primeiras 20 linhas)")
    st.table(diag)

    if bad:
        st.error(
            f"Em {len(bad)} linha(s) não foi possível ler dígitos em débito e/ou crédito nas colunas fixas. "
            "O download fica bloqueado para não gerar um ficheiro incorreto."
        )
        st.table(bad[:200])
        st.stop()

    st.success("OK. Troca efetuada. Ficheiro pronto.")

    st.download_button(
        "Descarregar TXT corrigido",
        data=text_out.encode(encoding),
        file_name=uploaded.name.rsplit(".", 1)[0] + f"_corrigido_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain",
    )
else:
    st.info("Carrega o TXT para processar.")
