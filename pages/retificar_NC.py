import streamlit as st
from datetime import datetime

# =========================
# LAYOUT FIXO (ORIGINAL)
# =========================
DATE_START_CURRENT_1B = 52
SHIFT_SPACES = 3

A_EXPECT_1B = 62
B_EXPECT_1B = 113
A_PREFIX = "2"
B_PREFIX = "7"
WINDOW = 4 

def shift_for_date(line: str) -> str:
    idx = DATE_START_CURRENT_1B - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    if len(core) < idx:
        core = core + (" " * (idx - len(core)))
    core = core[:idx] + (" " * SHIFT_SPACES) + core[idx:]
    return core + ("\n" if has_nl else "")

def read_digits(core: str, start_idx: int) -> tuple[str, int]:
    if start_idx >= len(core) or not core[start_idx].isdigit():
        return "", start_idx
    i = start_idx
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start_idx:i], i

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

def find_account_pos(core: str, expect_1b: int, prefix: str, min_start_1b: int | None = None):
    expect0 = expect_1b - 1
    digits_at_expect, end_at_expect = read_digits(core, expect0)
    for delta in range(-WINDOW, WINDOW + 1):
        pos0 = expect0 + delta
        if pos0 < 0: continue
        if min_start_1b is not None and (pos0 + 1) < min_start_1b: continue
        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos0 + 1, digits, end
    return None, digits_at_expect, end_at_expect

# =========================
# PROCESSAMENTO CORRIGIDO
# =========================

def process_line(line: str):
    # 0. Captura o valor e CC da linha ORIGINAL (antes do shift empurrar tudo)
    # Ajuste estas posições se o valor no seu ficheiro original estiver noutro local
    valor_orig = line[120:150].strip() 
    cc_orig = line[150:].strip()

    # 1. Teu Shift Original
    shifted = shift_for_date(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    # 2. Teu Swap Original
    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=63)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    ok = (a_pos is not None) and (b_pos is not None)
    if not ok:
        return shifted, {"OK": False}

    chars = list(core)
    # Executa o swap de contas
    write_over(chars, a_pos - 1, a_end, b_digits)
    write_over(chars, b_pos - 1, b_end, a_digits)

    # 3. LIMPEZA E REALINHAMENTO FINAL (ESTRITO)
    # Vamos limpar da coluna 89 (index 0) até ao fim para evitar duplicados
    for i in range(89, len(chars)):
        chars[i] = " "

    # Conta Crédito na 90
    for i, ch in enumerate(a_digits):
        if 89 + i < len(chars): chars[89 + i] = ch

    # Valor: Alinhado à esquerda. Como deve acabar na 119, 
    # vamos definir o início por exemplo na 105.
    col_valor_start = 104 # Coluna 105 (0-based)
    for i, ch in enumerate(valor_orig):
        if col_valor_start + i < 119: # Não passa da 119
            chars[col_valor_start + i] = ch

    # Centro de Custo na 122 (0-based index 121)
    for i, ch in enumerate(cc_orig):
        if 121 + i < len(chars):
            chars[121 + i] = ch

    new_line = "".join(chars).rstrip()
    return new_line + ("\n" if has_nl else ""), {"OK": True, "A": a_digits}

def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag = []
    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        out_lines.append(new_ln)
        if i <= 20:
            diag.append({"Linha": i, **info})
    return "".join(out_lines), diag

# =========================
# UI STREAMLIT
# =========================
st.set_page_config(page_title="Corretor Contabilístico", layout="wide")
st.title("Ajuste Final de Colunas")

uploaded = st.file_uploader("Carregar TXT", type=["txt"])
if uploaded:
    encoding = st.selectbox("Encoding", ["cp1252", "utf-8"])
    text_in = uploaded.getvalue().decode(encoding)
    text_out, diag = process_text(text_in)
    
    st.table(diag)
    st.download_button("Descarregar corrigido", text_out.encode(encoding), "corrigido.txt")
