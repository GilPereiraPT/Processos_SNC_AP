import streamlit as st
from datetime import datetime

# =========================
# CONFIGURAÇÃO DE LAYOUT (FIXO)
# =========================
DATE_START_CURRENT_1B = 52
SHIFT_SPACES = 3

# Cálculos automáticos baseados no shift
DATE_START_FINAL_1B = DATE_START_CURRENT_1B + SHIFT_SPACES
DATE_LEN = 8  # DDMMAAAA
DATE_END_FINAL_1B = DATE_START_FINAL_1B + DATE_LEN - 1

# Referências de Colunas para Contas
A_EXPECT_1B = 62
B_EXPECT_1B = 113
A_MIN_START_1B = DATE_END_FINAL_1B + 1  # Segurança: A nunca entra na data (63)

A_PREFIX = "2" # Ex: Fornecedores
B_PREFIX = "7" # Ex: Proveitos
WINDOW = 4     # Tolerância de pesquisa

def shift_for_date(line: str) -> str:
    """Insere os espaços para empurrar a data para a direita."""
    idx = DATE_START_CURRENT_1B - 1
    # Removemos o newline para manipular a string e recolocamos no fim
    line_content = line.rstrip('\n\r')
    
    if len(line_content) < idx:
        line_content = line_content.ljust(idx)

    # Inserção dos espaços
    new_line = line_content[:idx] + (" " * SHIFT_SPACES) + line_content[idx:]
    return new_line

def read_digits(text: str, start_idx: int) -> tuple[str, int]:
    """Lê uma sequência de dígitos a partir de um ponto."""
    if start_idx >= len(text) or not text[start_idx].isdigit():
        return "", start_idx
    i = start_idx
    while i < len(text) and text[i].isdigit():
        i += 1
    return text[start_idx:i], i

def write_over(chars: list[str], start: int, old_end: int, new_text: str) -> None:
    """Escreve o novo texto por cima do antigo, limpando o excesso com espaços."""
    old_len = max(0, old_end - start)
    wipe_len = max(old_len, len(new_text))
    
    # Expandir lista se necessário
    if start + wipe_len > len(chars):
        chars.extend([" "] * (start + wipe_len - len(chars)))

    # Limpa a zona anterior
    for i in range(start, start + wipe_len):
        chars[i] = " "
    
    # Escreve o novo valor
    for i, ch in enumerate(new_text):
        chars[start + i] = ch

def find_account_pos(core: str, expect_1b: int, prefix: str, min_start_1b: int = None):
    """Procura a conta dentro da janela de tolerância."""
    expect0 = expect_1b - 1
    
    for delta in range(-WINDOW, WINDOW + 1):
        pos0 = expect0 + delta
        pos1b = pos0 + 1
        
        if pos0 < 0 or (min_start_1b and pos1b < min_start_1b):
            continue

        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos1b, digits, end
    
    # Se falhar, tenta ler o que está na posição esperada para diagnóstico
    d, e = read_digits(core, expect0)
    return None, d, e

def process_line(line: str):
    """Processa uma única linha: shift + troca de contas."""
    core = shift_for_date(line)
    
    # Garante largura mínima para evitar erros de índice
    min_required = max(B_EXPECT_1B + 10, A_MIN_START_1B + 10)
    if len(core) < min_required:
        core = core.ljust(min_required)

    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=A_MIN_START_1B)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    ok = (a_pos is not None) and (b_pos is not None)
    info = {"A_col": a_pos, "A_lida": a_digits, "B_col": b_pos, "B_lida": b_digits, "OK": ok}

    if not ok:
        return core + "\n", info

    # Executa a troca (Swap)
    chars = list(core)
    write_over(chars, a_pos - 1, a_end, b_digits)
    write_over(chars, b_pos - 1, b_end, a_digits)
    
    return "".join(chars) + "\n", info

# --- Interface Streamlit (UI) ---
st.set_page_config(page_title="Corretor Contabilístico", layout="wide")
st.title("🛠️ Ajuste de Ficheiro TXT para Contabilidade")

with st.expander("Ver Regras de Transformação"):
    st.write(f"- **Shift:** +{SHIFT_SPACES} espaços na coluna {DATE_START_CURRENT_1B}.")
    st.write(f"- **Conta A:** Prefixo `{A_PREFIX}`, esperada na col {A_EXPECT_1B} (mínimo col {A_MIN_START_1B}).")
    st.write(f"- **Conta B:** Prefixo `{B_PREFIX}`, esperada na col {B_EXPECT_1B}.")

col1, col2 = st.columns(2)
with col1:
    encoding = st.selectbox("Codificação do Ficheiro", ["cp1252", "utf-8", "iso-8859-1"])
with col2:
    uploaded = st.file_uploader("Upload do ficheiro .txt", type=["txt"])

if uploaded:
    raw_bytes = uploaded.getvalue()
    try:
        content = raw_bytes.decode(encoding)
    except Exception:
        st.error("Erro ao descodificar. Tente outro 'Encoding'.")
        st.stop()

    lines = content.splitlines()
    processed_lines = []
    diagnostics = []
    errors = []

    for idx, line in enumerate(lines, 1):
        new_line, info = process_line(line)
        processed_lines.append(new_line)
        
        if idx <= 15: # Apenas para amostra
            diagnostics.append({"Linha": idx, **info})
        
        if not info["OK"]:
            errors.append({"Linha": idx, **info})

    st.subheader("🔍 Diagnóstico (Amostra)")
    st.table(diagnostics)

    if errors:
        st.warning(f"⚠️ Detetadas {len(errors)} linhas com problemas de validação.")
        if st.checkbox("Mostrar erros detalhados"):
            st.table(errors[:100])
    else:
        st.success("✅ Validação concluída com sucesso em todas as linhas!")

    # Resultado Final
    final_txt = "".join(processed_lines)
    
    st.download_button(
        label="💾 Descarregar Ficheiro Corrigido",
        data=final_txt.encode(encoding),
        file_name=f"CONTABILIDADE_{datetime.now().strftime('%H%M%S')}.txt",
        mime="text/plain"
    )
