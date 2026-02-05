import streamlit as st
from datetime import datetime


# =========================================================
# 1) Ajustar posição da data (52 -> 55, 1-based)
# =========================================================
def shift_for_date(line: str, from_col_1b: int = 52, shift: int = 3) -> str:
    """
    Insere 'shift' espaços a partir de from_col_1b (1-based),
    empurrando o resto da linha para a direita.
    """
    idx = from_col_1b - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    if len(core) < idx:
        core = core + (" " * (idx - len(core)))

    core = core[:idx] + (" " * shift) + core[idx:]
    return core + ("\n" if has_nl else "")


# =========================================================
# 2) Troca de contas (62 ↔ 113, 1-based)
# =========================================================
def read_digits(core: str, start: int):
    if start >= len(core) or not core[start].isdigit():
        return "", start
    i = start
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start:i], i


def write_over(chars, start: int, old_end: int, new_text: str):
    old_len = max(0, old_end - start)
    wipe_len = max(old_len, len(new_text))

    needed = start + wipe_len
    if needed > len(chars):
        chars.extend([" "] * (needed - len(chars)))

    for i in range(start, start + wipe_len):
        chars[i] = " "

    for i, ch in enumerate(new_text):
        chars[start + i] = ch


def swap_accounts(line: str, col_a_1b=62, col_b_1b=113) -> str:
    A = col_a_1b - 1
    B = col_b_1b - 1

    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    if len(core) <= max(A, B):
        core = core + (" " * (max(A, B) - len(core) + 1))

    a_digits, a_end = read_digits(core, A)
    b_digits, b_end = read_digits(core, B)

    chars = list(core)

    write_over(chars, A, a_end, b_digits)
    write_over(chars, B, b_end, a_digits)

    return "".join(chars) + ("\n" if has_nl else "")


# =========================================================
# 3) Pipeline completo
# =========================================================
def process_text(text: str) -> str:
    lines = text.splitlines(keepends=True)

    # passo 1: deslocar data
    lines = [shift_for_date(ln) for ln in lines]

    # passo 2: trocar contas
    lines = [swap_accounts(ln) for ln in lines]

    return "".join(lines)


# =========================================================
# UI Streamlit
# =========================================================
st.set_page_config(page_title="Retificar TXT Contabilidade", layout="centered")
st.title("Retificação de ficheiro TXT – Contabilidade")
st.caption("1️⃣ Ajusta a posição da data (52 → 55)  |  2️⃣ Troca contas (62 ↔ 113)")

encoding = st.selectbox(
    "Codificação do ficheiro",
    ["cp1252", "utf-8", "latin-1"],
    index=0
)

uploaded = st.file_uploader("Seleciona o ficheiro TXT", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()

    try:
        text_in = raw.decode(encoding)
    except UnicodeDecodeError:
        st.error("Erro de codificação. Experimenta outra opção.")
        st.stop()

    text_out = process_text(text_in)

    st.success("Ficheiro processado com sucesso.")

    st.subheader("Pré-visualização (primeiras 5 linhas)")
    st.code("\n".join(text_out.splitlines()[:5]), language="text")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = uploaded.name.replace(".txt", f"_corrigido_{ts}.txt")

    st.download_button(
        "Descarregar TXT corrigido",
        data=text_out.encode(encoding),
        file_name=out_name,
        mime="text/plain"
    )
else:
    st.info("Carrega um ficheiro TXT para iniciar o processamento.")
