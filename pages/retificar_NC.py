import streamlit as st
from datetime import datetime

# =========================
# LAYOUT FIXO (TEU ORIGINAL)
# =========================
DATE_START_CURRENT_1B = 52
SHIFT_SPACES = 3

DATE_START_FINAL_1B = DATE_START_CURRENT_1B + SHIFT_SPACES   # 55
DATE_LEN = 8  # DDMMAAAA
DATE_END_FINAL_1B = DATE_START_FINAL_1B + DATE_LEN - 1       # 62

A_EXPECT_1B = 62
B_EXPECT_1B = 113

A_MIN_START_1B = DATE_END_FINAL_1B + 1  # 63
A_PREFIX = "2"
B_PREFIX = "7"
WINDOW = 4 

# TUA LÓGICA DE MANIPULAÇÃO (MANTIDA)
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
        pos1b = pos0 + 1
        if pos0 < 0: continue
        if min_start_1b is not None and pos1b < min_start_1b: continue
        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos1b, digits, end
    return None, digits_at_expect, end_at_expect

# =========================
# PROCESSAMENTO COM ACERTO DE ALINHAMENTO
# =========================

def process_line(line: str):
    # 1. Executa exatamente o teu script original
    shifted = shift_for_date(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    min_len = 160 # Garantir largura para as colunas novas
    if len(core) < min_len:
        core = core.ljust(min_len)

    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=A_MIN_START_1B)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    ok = (a_pos is not None) and (b_pos is not None)
    info = {"A_col": a_pos, "A_lida": a_digits, "B_col": b_pos, "B_lida": b_digits, "OK": ok}

    if not ok:
        return shifted, info

    # 2. Faz o Swap Original
    chars = list(core)
    # Lemos os valores ANTES de apagar as zonas no swap
    # (O valor costuma estar depois da conta B, por volta da 130 no original)
    valor_raw = core[125:150].strip() 
    cc_raw = core[150:170].strip()

    # Teu Swap
    write_over(chars, a_pos - 1, a_end, b_digits)
    write_over(chars, b_pos - 1, b_end, a_digits)

    # 3. ACERTOS FINAIS DE ALINHAMENTO (As tuas regras novas)
    # Conta a Crédito na 90 (0-based: 89)
    write_over(chars, 89, 104, a_digits) 
    
    # Valor acaba na 119, alinhado à esquerda. 
    # Vamos fazê-lo começar na 105 (0-based: 104) até 119 (0-based: 119)
    # Limpamos a zona e escrevemos o valor
    for i in range(104, 119): chars[i] = " "
    for i, ch in enumerate(valor_raw):
        if 104 + i < 119: chars[104 + i] = ch

    # Centro de Custo na 122 (0-based: 121)
    # Limpamos a zona e escrevemos
    for i in range(121, 140): chars[i] = " "
    for i, ch in enumerate(cc_raw):
        if 121 + i < 160: chars[121 + i] = ch

    new_core = "".join(chars).rstrip()
    return new_core + ("\n" if has_nl else ""), info

def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag, bad = [], []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        if i <= 20: diag.append({"Linha": i, **info})
        if not info["OK"]:
            bad.append({"Linha": i, **info})
            out_lines.append(ln)
        else:
            out_lines.append(new_ln)

    return "".join(out_lines), diag, bad

# =========================
# UI (STREAMLIT)
# =========================
st.set_page_config(page_title="Retificar TXT", layout="wide")
st.title("Retificar TXT – Alinhamento Final")

uploaded = st.file_uploader("Ficheiro TXT", type=["txt"])
encoding = st.selectbox("Codificação", ["cp1252", "utf-8", "latin-1"])

if uploaded:
    text_in = uploaded.getvalue().decode(encoding)
    text_out, diag, bad = process_text(text_in)

    st.subheader("Diagnóstico")
    st.table(diag)

    if bad:
        st.error(f"Erro em {len(bad)} linhas.")
    else:
        st.success("Tudo OK!")
        st.download_button("Descarregar Corrigido", text_out.encode(encoding), "corrigido.txt")
