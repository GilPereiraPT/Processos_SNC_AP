import streamlit as st
from datetime import datetime


# =========================
# 1) Shift para alinhar a data
# =========================
def shift_for_date(line: str, from_col_1b: int, shift: int) -> str:
    idx = from_col_1b - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    if len(core) < idx:
        core = core + (" " * (idx - len(core)))

    core = core[:idx] + (" " * shift) + core[idx:]
    return core + ("\n" if has_nl else "")


# =========================
# 2) Swap contas (runs de dígitos)
# =========================
def read_digits(core: str, start: int) -> tuple[str, int]:
    if start >= len(core) or not core[start].isdigit():
        return "", start
    i = start
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start:i], i


def write_over(chars: list[str], start: int, old_end: int, new_text: str) -> None:
    old_len = max(0, old_end - start)
    wipe_len = max(old_len, len(new_text))

    needed = start + wipe_len
    if needed > len(chars):
        chars.extend([" "] * (needed - len(chars)))

    for i in range(start, start + wipe_len):
        chars[i] = " "

    for i, ch in enumerate(new_text):
        chars[start + i] = ch


def swap_accounts(line: str, col_a_1b: int, col_b_1b: int) -> tuple[str, str, str]:
    """Devolve (linha_nova, conta_lida_A, conta_lida_B)"""
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

    return "".join(chars) + ("\n" if has_nl else ""), a_digits, b_digits


def adjusted_col(original_col_1b: int, insert_from_col_1b: int, shift: int) -> int:
    """Se a coluna estiver a partir do ponto de inserção, ajusta-a (+shift)."""
    return original_col_1b + shift if original_col_1b >= insert_from_col_1b else original_col_1b


def process_text(text: str,
                 insert_from_col_1b: int,
                 shift: int,
                 orig_col_a_1b: int,
                 orig_col_b_1b: int):
    lines = text.splitlines(keepends=True)

    # Passo 1: shift em todas as linhas
    shifted_lines = [shift_for_date(ln, insert_from_col_1b, shift) for ln in lines]

    # Ajustar colunas para o ficheiro já com shift
    eff_col_a = adjusted_col(orig_col_a_1b, insert_from_col_1b, shift)
    eff_col_b = adjusted_col(orig_col_b_1b, insert_from_col_1b, shift)

    # Passo 2: swap
    out_lines = []
    diag = []
    for i, ln in enumerate(shifted_lines, start=1):
        new_ln, a, b = swap_accounts(ln, eff_col_a, eff_col_b)
        out_lines.append(new_ln)
        if i <= 20:
            diag.append((i, a, b))

    return "".join(out_lines), diag, eff_col_a, eff_col_b


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT Contabilidade", layout="centered")
st.title("Retificação TXT – alinhar data + trocar contas")

with st.expander("Parâmetros", expanded=True):
    st.markdown("### Passo 1 — alinhar a data")
    insert_from_col_1b = st.number_input("Data começa atualmente na coluna (1-based)", min_value=1, value=52, step=1)
    shift = st.number_input("Inserir quantos espaços (ex.: 3 para 52→55)", min_value=0, value=3, step=1)

    st.markdown("### Passo 2 — colunas das contas (no ficheiro ORIGINAL)")
    orig_col_a_1b = st.number_input("Coluna A (início da conta que está hoje no sítio errado)", min_value=1, value=62, step=1)
    orig_col_b_1b = st.number_input("Coluna B (início da conta que deve trocar com A)", min_value=1, value=113, step=1)

    encoding = st.selectbox("Codificação", ["cp1252", "utf-8", "latin-1"], index=0)

uploaded = st.file_uploader("Upload do TXT", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()
    try:
        text_in = raw.decode(encoding)
    except UnicodeDecodeError:
        st.error("Erro de codificação. Experimenta cp1252 ou latin-1.")
        st.stop()

    text_out, diag, eff_a, eff_b = process_text(
        text_in,
        int(insert_from_col_1b),
        int(shift),
        int(orig_col_a_1b),
        int(orig_col_b_1b),
    )

    st.success(f"Processado. Após o shift, a troca foi feita nas colunas efetivas: A={eff_a} e B={eff_b} (1-based).")

    st.subheader("Diagnóstico (primeiras 20 linhas)")
    st.write("Mostra o que foi lido em A e B (antes da troca).")
    st.table([{"Linha": n, "Lido em A": a, "Lido em B": b} for (n, a, b) in diag])

    st.subheader("Pré-visualização (primeiras 5 linhas corrigidas)")
    st.code("\n".join(text_out.splitlines()[:5]), language="text")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = uploaded.name.rsplit(".", 1)[0] + f"_corrigido_{ts}.txt"

    st.download_button(
        "Descarregar TXT corrigido",
        data=text_out.encode(encoding),
        file_name=out_name,
        mime="text/plain",
    )
else:
    st.info("Carrega o ficheiro TXT.")
