import streamlit as st
from datetime import datetime


# =========================
# LAYOUT FIXO (1-based)
# =========================
# Passo 1: data deve passar de col 52 para col 55 -> inserir 3 espaços a partir da col 52
DATE_START_CURRENT_1B = 52
SHIFT_SPACES = 3

# Passo 2: DEPOIS do shift, as colunas corretas são estas (como disseste)
COL_A_1B = 62   # A deve começar por '2'
COL_B_1B = 113  # B deve começar por '7'

A_PREFIX = "2"
B_PREFIX = "7"


# =========================
# Core
# =========================
def shift_for_date(line: str) -> str:
    """Insere SHIFT_SPACES espaços a partir de DATE_START_CURRENT_1B (1-based)."""
    idx = DATE_START_CURRENT_1B - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    if len(core) < idx:
        core = core + (" " * (idx - len(core)))

    core = core[:idx] + (" " * SHIFT_SPACES) + core[idx:]
    return core + ("\n" if has_nl else "")


def read_digits(core: str, start_idx: int) -> tuple[str, int]:
    """Lê dígitos consecutivos a partir de start_idx (0-based)."""
    if start_idx >= len(core) or not core[start_idx].isdigit():
        return "", start_idx
    i = start_idx
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start_idx:i], i


def write_over(chars: list[str], start: int, old_end: int, new_text: str) -> None:
    """
    Substitui o run antigo por new_text sem deixar restos.
    Limpa até max(len_antigo, len_novo).
    """
    old_len = max(0, old_end - start)
    wipe_len = max(old_len, len(new_text))

    needed = start + wipe_len
    if needed > len(chars):
        chars.extend([" "] * (needed - len(chars)))

    for i in range(start, start + wipe_len):
        chars[i] = " "

    for i, ch in enumerate(new_text):
        chars[start + i] = ch


def swap_accounts_after_shift(line: str) -> tuple[str, str, str, bool]:
    """
    1) faz shift
    2) lê A na col 62 e B na col 113 (já após shift)
    3) valida A começa por 2 e B por 7
    4) troca
    """
    shifted = shift_for_date(line)

    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    A = COL_A_1B - 1
    B = COL_B_1B - 1

    min_len = max(A, B) + 1
    if len(core) < min_len:
        core = core + (" " * (min_len - len(core)))

    a_digits, a_end = read_digits(core, A)
    b_digits, b_end = read_digits(core, B)

    ok = a_digits.startswith(A_PREFIX) and b_digits.startswith(B_PREFIX)
    if not ok:
        # devolve shift feito, mas sinaliza falha
        return shifted, a_digits, b_digits, False

    chars = list(core)
    write_over(chars, A, a_end, b_digits)
    write_over(chars, B, b_end, a_digits)

    new_core = "".join(chars)
    return new_core + ("\n" if has_nl else ""), a_digits, b_digits, True


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag = []  # primeiras 20 linhas
    bad = []

    for i, ln in enumerate(lines, start=1):
        new_ln, a, b, ok = swap_accounts_after_shift(ln)
        out_lines.append(new_ln if ok else ln)  # se falhar, mantém original (para não estragar)
        if i <= 20:
            diag.append((i, a, b, ok))
        if not ok:
            bad.append((i, a, b))

    return "".join(out_lines), diag, bad


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT (layout fixo)", layout="centered")
st.title("Retificar TXT – layout fixo")

st.markdown(
    f"""
**Regras fixas aplicadas:**
1) Inserir **{SHIFT_SPACES} espaços** a partir da **coluna {DATE_START_CURRENT_1B}** (data 52 → 55)  
2) Após isso, trocar contas nas colunas:
- **A = coluna {COL_A_1B}** (tem de começar por **{A_PREFIX}**)  
- **B = coluna {COL_B_1B}** (tem de começar por **{B_PREFIX}**)
"""
)

encoding = st.selectbox("Codificação do ficheiro", ["cp1252", "utf-8", "latin-1"], index=0)
uploaded = st.file_uploader("Seleciona o ficheiro TXT", type=["txt"])

if uploaded:
    raw = uploaded.getvalue()
    try:
        text_in = raw.decode(encoding)
    except UnicodeDecodeError:
        st.error("Erro a ler o ficheiro com essa codificação. Experimenta cp1252 ou latin-1.")
        st.stop()

    text_out, diag, bad = process_text(text_in)

    st.subheader("Diagnóstico (primeiras 20 linhas)")
    st.table([{"Linha": n, "A lida": a, "B lida": b, "OK": ok} for (n, a, b, ok) in diag])

    if bad:
        st.error(
            f"Foram detetadas {len(bad)} linha(s) onde A não começa por '{A_PREFIX}' ou B não começa por '{B_PREFIX}'. "
            "Para evitar gerar um ficheiro incorreto, o download fica bloqueado."
        )
        st.write("Exemplos das linhas com problema (até 200):")
        st.table([{"Linha": n, "A lida": a, "B lida": b} for (n, a, b) in bad[:200]])
        st.stop()

    st.success("Validação OK. Ficheiro corrigido pronto.")

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
    st.info("Carrega o TXT para processar.")
