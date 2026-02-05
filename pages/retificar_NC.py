import streamlit as st
from datetime import datetime

# =========================
# LAYOUT FIXO (ORIGINAL)
# =========================
DATE_START_CURRENT_1B = 52
SHIFT_SPACES = 3

DATE_START_FINAL_1B = DATE_START_CURRENT_1B + SHIFT_SPACES   # 55
DATE_LEN = 8  
DATE_END_FINAL_1B = DATE_START_FINAL_1B + DATE_LEN - 1       # 62

A_EXPECT_1B = 62
B_EXPECT_1B = 113
A_MIN_START_1B = DATE_END_FINAL_1B + 1  # 63

A_PREFIX = "2"
B_PREFIX = "7"
WINDOW = 4

# NOVOS ALINHAMENTOS SOLICITADOS
COL_CONTA_CREDITO = 90
COL_VALOR_START = 105
COL_VALOR_END = 119
COL_CENTRO_CUSTO = 122

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

def process_line(line: str):
    # 1. Teu processo original de Shift
    shifted = shift_for_date(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    min_len = max(B_EXPECT_1B, A_MIN_START_1B, 150) 
    if len(core) < min_len:
        core = core + (" " * (min_len - len(core)))

    # 2. Teu processo original de Procura e Swap
    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=A_MIN_START_1B)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    ok = (a_pos is not None) and (b_pos is not None)
    info = {"A_col": a_pos, "A_lida": a_digits, "B_col": b_pos, "B_lida": b_digits, "OK": ok}

    if not ok:
        return shifted, info

    chars = list(core)
    
    # Executa o SWAP original
    write_over(chars, a_pos - 1, a_end, b_digits)
    write_over(chars, b_pos - 1, b_end, a_digits)

    # 3. ACERTOS DE ALINHAMENTO POSTERIORES (Novas Regras)
    # Extrair valores antes de limpar as zonas para realinhamento
    # Lemos o valor da zona onde ele ficou após o swap (perto da 113/115)
    temp_core = "".join(chars)
    # Aqui assumimos que o valor está à frente da conta B. 
    # Para garantir, podes ajustar esta leitura se o valor vier de outra coluna:
    valor_extraido = temp_core[114:130].strip() 
    cc_extraido = temp_core[130:150].strip()

    # Re-posicionamento Absoluto (Forçar as colunas finais)
    # Conta a Crédito na 90
    write_over(chars, COL_CONTA_CREDITO - 1, COL_CONTA_CREDITO + 15, a_digits) # (a_digits foi para crédito)
    
    # Valor: Alinhado à esquerda até 119 (começando por ex. na 105)
    largura_valor = (COL_VALOR_END - COL_VALOR_START) + 1
    write_over(chars, COL_VALOR_START - 1, COL_VALOR_END, valor_extraido.ljust(largura_valor))
    
    # Centro de Custo na 122
    write_over(chars, COL_CENTRO_CUSTO - 1, COL_CENTRO_CUSTO + 15, cc_original := cc_extraido)

    new_core = "".join(chars)
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
# UI (MANTIDA)
# =========================
st.set_page_config(page_title="Retificar TXT", layout="centered")
st.title("Retificar TXT – Original + Alinhamentos")

encoding = st.selectbox("Codificação", ["cp1252", "utf-8", "latin-1"], index=0)
uploaded = st.file_uploader("Seleciona o ficheiro TXT", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()
    try:
        text_in = raw.decode(encoding)
    except:
        st.error("Erro de codificação.")
        st.stop()

    text_out, diag, bad = process_text(text_in)
    st.subheader("Diagnóstico")
    st.table(diag)

    if not bad:
        st.success("Tudo OK.")
        st.download_button("Descarregar TXT", data=text_out.encode(encoding), file_name="corrigido.txt")
    else:
        st.error(f"Erros em {len(bad)} linhas.")
        st.table(bad[:50])
