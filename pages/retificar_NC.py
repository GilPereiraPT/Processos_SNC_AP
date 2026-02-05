import streamlit as st
import os

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

# MAPEAMENTO DE CENTROS DE CUSTO (DE 2024 PARA 2025)
CC_MAP = {
    "1020511": "12201101",
    "1020512": "12201102",
    "1020513": "12201103",
    "1020514": "12201104",
    "1020521": "12201201",
    "1020524": "12201202",
    "1020522": "12201203",
    "1020523": "12201204"
}

# =========================
# FUNÇÕES TÉCNICAS (MANTIDAS)
# =========================
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
# LÓGICA DE PROCESSAMENTO
# =========================

def process_line(line: str):
    # 1. Capturar Valor e CC ANTES de mexer na linha (Limpeza do '+')
    raw_after_accounts = line[120:].replace("+", " ").strip()
    parts = raw_after_accounts.split()
    
    val_to_use = parts[0] if len(parts) > 0 else ""
    cc_old = parts[1] if len(parts) > 1 else ""

    # Aplicação da tabela de conversão
    cc_new = CC_MAP.get(cc_old, cc_old)

    # 2. Shift e Swap originais
    shifted = shift_for_date(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted
    
    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=63)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    if not a_pos or not b_pos:
        return shifted, {"OK": False}

    chars = list(core)
    write_over(chars, a_pos - 1, a_end, b_digits)
    write_over(chars, b_pos - 1, b_end, a_digits)

    # 3. RECTIFICAÇÃO FINAL DE ALINHAMENTO
    for i in range(89, len(chars)):
        chars[i] = " "

    # Conta Crédito na 90
    for i, ch in enumerate(a_digits):
        if 89 + i < len(chars): chars[89 + i] = ch

    # Valor: 105 até 119
    for i, ch in enumerate(val_to_use):
        if 104 + i < 119:
            chars[104 + i] = ch

    # Centro de Custo na 122
    for i, ch in enumerate(cc_new):
        if 121 + i < len(chars):
            chars[121 + i] = ch

    new_line = "".join(chars).rstrip()
    return new_line + ("\n" if has_nl else ""), {"OK": True, "CC_Novo": cc_new}

def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    for ln in lines:
        new_ln, _ = process_line(ln)
        out_lines.append(new_ln)
    return "".join(out_lines)

# =========================
# INTERFACE STREAMLIT
# =========================
st.set_page_config(page_title="Retificador TXT", layout="wide")
st.title("Retificador Contabilístico Profissional")

uploaded = st.file_uploader("Selecione o ficheiro original", type=["txt"])

if uploaded:
    # Gerar o nome do ficheiro: NomeOriginal_corrigido.txt
    file_name, file_ext = os.path.splitext(uploaded.name)
    new_filename = f"{file_name}_corrigido{file_ext}"

    encoding = st.selectbox("Codificação", ["cp1252", "utf-8", "latin-1"])
    text_in = uploaded.getvalue().decode(encoding)
    
    text_out = process_text(text_in)
    
    st.success(f"Ficheiro pronto para criar: {new_filename}")
    
    st.download_button(
        label=f"💾 Descarregar {new_filename}",
        data=text_out.encode(encoding),
        file_name=new_filename,
        mime="text/plain"
    )
