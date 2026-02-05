import re
import streamlit as st
from datetime import datetime

# ============================================================
# FASE 1 — Troca de contas (já validada no teu ficheiro)
# ============================================================
# No teu caso, o que funcionou foi trocar os runs numéricos em:
DEBIT_COL_1B = 63
CREDIT_COL_1B = 113

# ============================================================
# FASE 2 — Alinhamentos finais (o que pediste agora)
# ============================================================
NEW_CRED_START_1B = 98
NEW_CRED_END_1B   = 114  # 17 chars

NEW_VAL_START_1B  = 115
NEW_VAL_END_1B    = 124  # 10 chars

NEW_SIGN_COL_1B   = 125  # 1 char

NEW_CC_START_1B   = 126
NEW_CC_END_1B     = 135  # 10 chars (sem sinal)

FINAL_LEN = NEW_CC_END_1B

# regex para extrair do texto após trocas
AMOUNT_RE = re.compile(r"(?:\d+)?\.\d{2}")         # 85.91, .01, 0.50
TAIL_RE   = re.compile(r"([+-])\s*(\d{1,12})\s*$") # +12201101 no fim
ACCT_RE   = re.compile(r"\d{4,}")                  # contas com >=4 dígitos


# ----------------------------
# utilitários (1-based)
# ----------------------------
def ensure_len(s: str, min_len: int) -> str:
    return s + (" " * (min_len - len(s))) if len(s) < min_len else s

def replace_1b(s: str, start: int, end: int, value: str, align: str = "left") -> str:
    seg_len = end - start + 1
    if align == "right":
        value = value[-seg_len:].rjust(seg_len)
    else:
        value = value[:seg_len].ljust(seg_len)
    return s[:start - 1] + value + s[end:]


# ----------------------------
# Fase 1: swap runs numéricos em 63 ↔ 113
# ----------------------------
def read_digits(core: str, start0: int) -> tuple[str, int]:
    if start0 >= len(core) or not core[start0].isdigit():
        return "", start0
    i = start0
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start0:i], i

def write_over(chars: list[str], start0: int, old_end0: int, new_text: str) -> None:
    old_len = max(0, old_end0 - start0)
    wipe_len = max(old_len, len(new_text))

    need = start0 + wipe_len
    if need > len(chars):
        chars.extend([" "] * (need - len(chars)))

    for i in range(start0, start0 + wipe_len):
        chars[i] = " "
    for i, ch in enumerate(new_text):
        chars[start0 + i] = ch

def swap_accounts_only(core: str) -> tuple[str, dict]:
    d0 = DEBIT_COL_1B - 1
    c0 = CREDIT_COL_1B - 1
    core = ensure_len(core, max(d0, c0) + 1)

    deb, deb_end = read_digits(core, d0)
    cre, cre_end = read_digits(core, c0)

    info = {"deb_antes": deb, "cred_antes": cre, "swap_ok": True}

    # se não conseguir ler em algum dos lados, não mexe
    if deb == "" or cre == "":
        info["swap_ok"] = False
        return core, info

    chars = list(core)
    write_over(chars, d0, deb_end, cre)
    write_over(chars, c0, cre_end, deb)

    out = "".join(chars)
    deb2, _ = read_digits(out, d0)
    cre2, _ = read_digits(out, c0)
    info["deb_depois"] = deb2
    info["cred_depois"] = cre2
    return out, info


# ----------------------------
# Fase 2: alinhar Crédito / Valor / Sinal / CC
# ----------------------------
def extract_credit_account(core: str) -> str:
    # regra prática: procurar a primeira conta que começa por 7
    for m in ACCT_RE.finditer(core):
        v = m.group(0)
        if v.startswith("7"):
            return v
    return ""

def extract_amount(core: str) -> str:
    matches = list(AMOUNT_RE.finditer(core))
    return matches[-1].group(0) if matches else ""

def extract_sign_cc(core: str) -> tuple[str, str]:
    m = TAIL_RE.search(core)
    if not m:
        return "", ""
    return m.group(1), m.group(2)

def apply_alignments(core: str) -> tuple[str, dict]:
    core = ensure_len(core, FINAL_LEN)

    cred = extract_credit_account(core)
    amount = extract_amount(core)
    sign, cc = extract_sign_cc(core)

    ok = True
    issues = []
    if not cred:
        ok = False; issues.append("não encontrei conta crédito (a começar por 7)")
    if not amount:
        ok = False; issues.append("não encontrei valor no formato .dd")
    if not cc:
        ok = False; issues.append("não encontrei sinal+CC no fim da linha")

    info = {
        "align_ok": ok,
        "cred(7x)": cred,
        "valor": amount,
        "sinal": sign,
        "cc_raw": cc,
        "issues": " | ".join(issues)
    }
    if not ok:
        return core, info

    cc10 = cc.zfill(10)[-10:]
    sign = sign if sign in ["+", "-"] else "+"

    # escrever nos novos sítios
    out = core
    out = replace_1b(out, NEW_CRED_START_1B, NEW_CRED_END_1B, cred, align="left")
    out = replace_1b(out, NEW_VAL_START_1B, NEW_VAL_END_1B, amount, align="right")
    out = replace_1b(out, NEW_SIGN_COL_1B, NEW_SIGN_COL_1B, sign, align="left")
    out = replace_1b(out, NEW_CC_START_1B, NEW_CC_END_1B, cc10, align="left")

    # truncar para evitar “restos” à direita a confundir o importador
    out = out[:FINAL_LEN]

    info["cc10"] = cc10
    return out, info


# ----------------------------
# Pipeline por linha: (1) trocas -> (2) alinhamentos
# ----------------------------
def process_line(line: str) -> tuple[str, dict]:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    core, swap_info = swap_accounts_only(core)
    core, align_info = apply_alignments(core)

    info = {**swap_info, **align_info}
    return core + ("\n" if has_nl else ""), info


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag = []
    bad = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        out_lines.append(new_ln)

        if i <= 20:
            diag.append({"Linha": i, **info})

        if (not info.get("swap_ok", True)) or (not info.get("align_ok", True)):
            bad.append({"Linha": i, **info})

    return "".join(out_lines), diag, bad


# ============================================================
# UI
# ============================================================
st.set_page_config(page_title="Retificar TXT 905", layout="centered")
st.title("Retificar TXT — (1) Trocas de contas -> (2) Alinhamentos finais")

st.markdown(
    f"""
**Ordem fixa (como pediste):**
1) **Trocar contas** (runs numéricos) em **{DEBIT_COL_1B} ↔ {CREDIT_COL_1B}**
2) **Alinhar**:
   - Crédito começa em **{NEW_CRED_START_1B}**
   - Valor começa em **{NEW_VAL_START_1B}**
   - CC começa em **{NEW_CC_START_1B}** (sem '+'), com **sinal em {NEW_SIGN_COL_1B}**
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
        st.warning(
            f"Há {len(bad)} linha(s) com problemas de leitura/extração (swap ou alinhamentos). "
            "Essas linhas foram exportadas na mesma (para inspeção), mas convém validar o diagnóstico."
        )
        st.table(bad[:200])

    out_name = uploaded.name.rsplit(".", 1)[0] + f"_corrigido_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    st.download_button(
        "Descarregar TXT corrigido",
        data=text_out.encode(encoding),
        file_name=out_name,
        mime="text/plain",
    )
else:
    st.info("Carrega o TXT para processar.")
