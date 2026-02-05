import streamlit as st
from datetime import datetime

# =========================
# LAYOUT FIXO
# =========================
DATE_START_CURRENT_1B = 52
SHIFT_SPACES = 3

# Depois do shift:
DATE_START_FINAL_1B = DATE_START_CURRENT_1B + SHIFT_SPACES   # 55
DATE_LEN = 8  # DDMMAAAA
DATE_END_FINAL_1B = DATE_START_FINAL_1B + DATE_LEN - 1       # 62

# Contas (referência que tens usado)
A_EXPECT_1B = 62
B_EXPECT_1B = 113

# Restrição CRÍTICA: A nunca pode começar dentro da data
A_MIN_START_1B = DATE_END_FINAL_1B + 1  # 63

A_PREFIX = "2"
B_PREFIX = "7"
WINDOW = 4  # procura um pouco mais larga, mas com limite mínimo para A


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
    """
    Procura na janela +/- WINDOW um run de dígitos que comece por prefix.
    Se min_start_1b estiver definido, ignora posições antes desse mínimo.
    Devolve (pos_1b, digits, end_idx_0based) ou (None, digits_na_expect, end_na_expect).
    """
    expect0 = expect_1b - 1
    digits_at_expect, end_at_expect = read_digits(core, expect0)

    for delta in range(-WINDOW, WINDOW + 1):
        pos0 = expect0 + delta
        pos1b = pos0 + 1
        if pos0 < 0:
            continue
        if min_start_1b is not None and pos1b < min_start_1b:
            continue

        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos1b, digits, end

    return None, digits_at_expect, end_at_expect


def process_line(line: str):
    shifted = shift_for_date(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    # garantir tamanho mínimo para as leituras
    min_len = max(B_EXPECT_1B, A_MIN_START_1B)  # 1-based
    if len(core) < min_len:
        core = core + (" " * (min_len - len(core)))

    # A: só pode começar a partir da col 63
    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=A_MIN_START_1B)
    # B: sem mínimo extra (mas podes pôr um mínimo semelhante se quiseres)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    ok = (a_pos is not None) and (b_pos is not None)

    info = {
        "A_col": a_pos,
        "A_lida": a_digits,
        "B_col": b_pos,
        "B_lida": b_digits,
        "OK": ok,
    }

    if not ok:
        # devolve só shift para inspeção
        return shifted, info

    A0 = a_pos - 1
    B0 = b_pos - 1

    chars = list(core)
    write_over(chars, A0, a_end, b_digits)
    write_over(chars, B0, b_end, a_digits)

    new_core = "".join(chars)
    return new_core + ("\n" if has_nl else ""), info


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag = []
    bad = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)

        if i <= 20:
            diag.append({"Linha": i, **info})

        if not info["OK"]:
            bad.append({"Linha": i, **info})
            out_lines.append(ln)  # não mexe nessa linha
        else:
            out_lines.append(new_ln)

    return "".join(out_lines), diag, bad


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT (fixo)", layout="centered")
st.title("Retificar TXT – alinhamento + troca (fixo e seguro)")

st.markdown(
    f"""
**Regras fixas:**
- Inserir **{SHIFT_SPACES} espaços** a partir da **coluna {DATE_START_CURRENT_1B}** ⇒ data passa a começar na **{DATE_START_FINAL_1B}**
- Data ocupa 8 dígitos ⇒ termina na **coluna {DATE_END_FINAL_1B}**
- **A (prefixo 2) só pode começar a partir da coluna {A_MIN_START_1B}** (para nunca apanhar o ano)
- B (prefixo 7) é procurada perto da coluna {B_EXPECT_1B}
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
            f"Falhou a deteção/validação em {len(bad)} linha(s). "
            "O download fica bloqueado para não gerar um ficheiro incorreto."
        )
        st.write("Exemplos (até 200):")
        st.table(bad[:200])
        st.stop()

    st.success("Tudo OK. Ficheiro corrigido pronto.")

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
