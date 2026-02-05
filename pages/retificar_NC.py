import streamlit as st
from datetime import datetime

# =========================================================
# CONFIGURAÇÃO DE COLUNAS (COORDENADAS 1-BASED)
# =========================================================
# 1. Zona da Data
DATE_START_OLD = 52
SHIFT = 3
DATE_START_NEW = 55  # 52 + 3
DATE_LEN = 8

# 2. Zona de Contas (Swap)
A_EXPECT_1B = 62 
A_PREFIX = "2"
WINDOW = 4
COL_CONTA_CREDITO = 90

# 3. Zona de Valores e Centro de Custo
COL_VALOR_START = 105
COL_VALOR_END = 119
COL_CENTRO_CUSTO = 122

# =========================================================
# FUNÇÕES AUXILIARES DE MANIPULAÇÃO
# =========================================================

def write_at(chars_list, col_1b, text, fixed_len=None):
    """Escreve texto numa posição exata. Se fixed_len existir, limpa a zona primeiro."""
    start_0b = col_1b - 1
    if fixed_len:
        # Limpa o campo com espaços para garantir alinhamento à esquerda
        for i in range(fixed_len):
            if start_0b + i < len(chars_list):
                chars_list[start_0b + i] = " "
    
    for i, char in enumerate(text):
        if start_0b + i < len(chars_list):
            if fixed_len and i >= fixed_len: 
                break
            chars_list[start_0b + i] = char

def read_digits(text, start_idx):
    """Lê uma sequência de dígitos."""
    if start_idx >= len(text) or not text[start_idx].isdigit():
        return "", start_idx
    i = start_idx
    while i < len(text) and text[i].isdigit():
        i += 1
    return text[start_idx:i], i

def find_account_pos_simple(core, expect_1b, prefix):
    """Procura a conta (ex: prefixo 2) numa janela de tolerância."""
    expect0 = expect_1b - 1
    for delta in range(-WINDOW, WINDOW + 1):
        pos0 = expect0 + delta
        if pos0 < 0: continue
        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos0 + 1, digits, end
    return None, "", 0

# =========================================================
# PROCESSAMENTO DE LINHA
# =========================================================

def process_line(line: str):
    has_nl = line.endswith("\n")
    original_core = line.rstrip('\n\r')
    
    # Ignorar linhas curtas (cabeçalhos ou vazias)
    if len(original_core) < 80:
        return line, {"OK": False, "Info": "Linha Curta/Cabeçalho"}

    # --- 1. EXTRAÇÃO DO ORIGINAL ---
    # Data (na 52)
    data_content = original_core[DATE_START_OLD-1 : DATE_START_OLD-1 + DATE_LEN]
    
    # Conta A (Débito - Prefixo 2)
    a_pos, a_digits, a_end = find_account_pos_simple(original_core, A_EXPECT_1B, A_PREFIX)
    
    # Conta B (está na posição onde deve ficar o Crédito: 90)
    b_digits, _ = read_digits(original_core, COL_CONTA_CREDITO - 1)
    
    # Valor (estava na zona do valor original)
    valor_original = original_core[COL_VALOR_START-1 : COL_VALOR_END].strip()
    
    # Centro de Custo (na 122)
    cc_original = original_core[COL_CENTRO_CUSTO-1 :].strip()

    # --- 2. RECONSTRUÇÃO (Garantia de Coordenadas) ---
    # Criamos uma linha "vazia" de 200 caracteres
    chars = list(" " * 200)
    
    # Repor a parte inicial (antes da data)
    for i in range(min(DATE_START_OLD - 1, len(original_core))):
        chars[i] = original_core[i]

    # Carimbar Data na 55
    write_at(chars, DATE_START_NEW, data_content)
    
    if a_pos:
        # SWAP: A vai para a 90 (Crédito)
        write_at(chars, COL_CONTA_CREDITO, a_digits)
        # B vai para a posição ajustada de A (62 + 3 = 65)
        write_at(chars, A_EXPECT_1B + SHIFT, b_digits)
    
    # VALOR: Alinhado à esquerda entre 105 e 119
    largura_valor = (COL_VALOR_END - COL_VALOR_START) + 1
    write_at(chars, COL_VALOR_START, valor_original, fixed_len=largura_valor)
    
    # CENTRO DE CUSTO: Fixo na 122
    write_at(chars, COL_CENTRO_CUSTO, cc_original)

    # Finalizar linha
    final_line = "".join(chars).rstrip()
    return final_line + ("\n" if has_nl else ""), {"OK": a_pos is not None, "A": a_digits}

# =========================================================
# INTERFACE STREAMLIT
# =========================================================

st.set_page_config(page_title="Retificador TXT Contabilidade", layout="wide")

st.title("🛠️ Retificador de Ficheiro TXT")
st.markdown(f"""
**Configurações de Alinhamento:**
- **Data:** Início na Col {DATE_START_NEW}
- **Conta Crédito:** Col {COL_CONTA_CREDITO}
- **Valor:** Alinhado à esquerda (Col {COL_VALOR_START} até {COL_VALOR_END})
- **Centro de Custo:** Início na Col {COL_CENTRO_CUSTO}
""")

encoding = st.selectbox("Encoding", ["cp1252", "utf-8", "latin-1"])
uploaded = st.file_uploader("Selecione o ficheiro original", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()
    try:
        text_in = raw.decode(encoding)
    except:
        st.error("Erro de codificação. Tente outro encoding (ex: cp1252).")
        st.stop()

    lines = text_in.splitlines(keepends=True)
    out_lines = []
    diag = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        out_lines.append(new_ln)
        if i <= 15:
            diag.append({"Linha": i, **info})

    st.subheader("Diagnóstico das primeiras 15 linhas")
    st.table(diag)

    final_txt = "".join(out_lines)
    
    st.success("Ficheiro processado!")
    
    ts = datetime.now().strftime("%H%M%S")
    st.download_button(
        label="💾 Descarregar Ficheiro Corrigido",
        data=final_txt.encode(encoding),
        file_name=f"importacao_corrigida_{ts}.txt",
        mime="text/plain"
    )
