import streamlit as st
from datetime import datetime

# =========================
# FORMATO FIXO (1-based)
# =========================
# Se o teu ficheiro original tem a data a começar na 52:
INSERT_FROM_COL_1B = 52
SHIFT_SPACES = 3  # 52 -> 55

# Depois do shift, segundo o teu exemplo correto:
DATE_START_FINAL_1B = 55          # 55-62
DEBIT_COL_1B = 63                # conta débito começa aqui
CREDIT_COL_1B = 113              # conta crédito começa aqui

DEBIT_PREFIX = "2"
CREDIT_PREFIX = "7"


def shift_line(line: str) -> str:
    """Insere 3 espaços a partir da coluna 52 (1-based)."""
    idx = INSERT_FROM_COL_1B - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    if len(core) < idx:
        core += " " * (idx - len(core))

    core = core[:idx] + (" " * SHIFT_SPACES) + core[idx:]
    return core + ("\n" if has_nl else "")


def read_digits(core: str, start0: int) -> tuple[str, int]:
    """Lê dígitos consecutivos a partir de start0 (0-based)."""
    if start0 >= len(core) or not core[start0].isdigit():
        return "", start0
    i = start0
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start0:i], i


def write_over(chars: list[str], start0: int, old_end0: int, new_text: str) -> None:
    """Substitui o run antigo por new_text limpando restos."""
    old_len = max(0, old_end0 - start0)
    wipe_len = max(old_len, len(new_text))

    need = start0 + wipe_len
    if need > len(chars):
        chars.extend([" "] * (need - len(chars)))

    for i in range(start0, start0 + wipe_len):
        chars[i] = " "
    for i, ch in enumerate(new_text):
        chars[start0 + i] = ch


def process_line(line: str) -> tuple[str, dict]:
    """
    1) shift (52->55)
    2) lê runs em 63 e 113
    3) se estiverem trocadas (7 em débito e 2 em crédito), troca
    4) valida resultado final (2 em débito, 7 em crédito)
    """
    shifted = shift_line(line)

    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    d0 = DEBIT_COL_1B - 1
    c0 = CREDIT_COL_1B - 1
    min_len = max(d0, c0) + 1
    if len(core) < min_len:
        core += " " * (min_len - len(core))

    deb, deb_end = read_digits(core, d0)
    cred, cred_end = read_digits(core, c0)

    status = {
        "deb_lida": deb,
        "cred_lida": cred,
        "acao": "",
        "OK": False
    }

    # Caso 1: já está correto
    if deb.startswith(DEBIT_PREFIX) and cred.startswith(CREDIT_PREFIX):
        status["acao"] = "mantida"
        status["OK"] = True
        return shifted, status

    # Caso 2: está trocado -> troca
    if deb.startswith(CREDIT_PREFIX) and cred.startswith(DEBIT_PREFIX):
        chars = list(core)
        write_over(chars, d0, deb_end, cred)
        write_over(chars, c0, cred_end, deb)
        new_core = "".join(chars)

        # revalidar
        deb2, _ = read_digits(new_core, d0)
        cred2, _ = read_digits(new_core, c0)

        status["acao"] = "trocada"
        status["deb_lida"] = deb2
        status["cred_lida"] = cred2
        status["OK"] = deb2.startswith(DEBIT_PREFIX) and cred2.startswith(CREDIT_PREFIX)

        return new_core + ("\n" if has_nl else ""), status

    # Caso 3: inesperado (não bate em 2/7) -> erro
    status["acao"] = "erro"
    status["OK"] = False
    return shifted, status


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out = []
    diag = []
    bad = []
    counts = {"mantida": 0, "trocada": 0, "erro": 0}

    for i, ln in enumerate(lines, start=1):
        new_ln, stt = process_line(ln)
        out.append(new_ln if stt["OK"] else ln)  # se erro, não mexe na linha
        counts[stt["acao"]] += 1

        if i <= 20:
            diag.append({"Linha": i, **stt})
        if not stt["OK"]:
            bad.append({"Linha": i, **stt})

    return "".join(out), diag, bad, counts


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT (fixo)", layout="centered")
st.title("Retificar TXT – formato fixo (data + contas)")

st.markdown(
    f"""
**Formato aplicado (fixo):**
- Inserir **{SHIFT_SPACES} espaços** a partir da **coluna {INSERT_FROM_COL_1B}** (para a data ficar em **{DATE_START_FINAL_1B}–{DATE_START_FINAL_1B+7}**)
- Contas:
  - Débito na **coluna {DEBIT_COL_1B}** (deve começar por **{DEBIT_PREFIX}**)
  - Crédito na **coluna {CREDIT_COL_1B}** (deve começar por **{CREDIT_PREFIX}**)
- Se estiverem trocadas (7/2), o programa troca automaticamente.
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

    text_out, diag, bad, counts = process_text(text_in)

    st.subheader("Resumo")
    st.write(counts)

    st.subheader("Diagnóstico (primeiras 20 linhas)")
    st.table(diag)

    if bad:
        st.error(
            f"Há {len(bad)} linha(s) com padrão inesperado (não bate em 2/7). "
            "Para não gerar um ficheiro incorreto, o download fica bloqueado."
        )
        st.write("Exemplos (até 200):")
        st.table(bad[:200])
        st.stop()

    st.success("OK. Ficheiro corrigido pronto a descarregar.")

    st.subheader("Pré-visualização (primeiras 5 linhas)")
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
