import re
import streamlit as st
from datetime import datetime

# ============================================================
# PASSO A (já feito convosco): SWAP + SHIFT
# ============================================================
SHIFT_AT_COL_1B = 52
SHIFT_SPACES = 3

DEB_START_1B, DEB_END_1B = 60, 109
CRE_START_1B, CRE_END_1B = 110, 159

LINE_MIN_LEN = max(CRE_END_1B, SHIFT_AT_COL_1B)

# ============================================================
# PASSO B (novo): POSIÇÕES FINAIS
# ============================================================
NEW_CRED_START_1B = 98
NEW_CRED_END_1B   = 114  # 17 chars

NEW_VAL_START_1B  = 115
NEW_VAL_END_1B    = 124  # 10 chars

NEW_SIGN_COL_1B   = 125  # 1 char

NEW_CC_START_1B   = 126
NEW_CC_END_1B     = 135  # 10 chars (sem +)

FINAL_LEN = NEW_CC_END_1B  # vamos truncar/normalizar para 135


# ----------------------------
# utilitários fixos (1-based)
# ----------------------------
def ensure_len(s: str, min_len: int) -> str:
    return s + (" " * (min_len - len(s))) if len(s) < min_len else s

def slice_1b(s: str, start: int, end: int) -> str:
    return s[start - 1:end]

def replace_1b(s: str, start: int, end: int, value: str, align: str = "left") -> str:
    seg_len = end - start + 1
    if align == "right":
        value = value[-seg_len:].rjust(seg_len)
    else:
        value = value[:seg_len].ljust(seg_len)
    return s[:start - 1] + value + s[end:]


# ----------------------------
# Passo A: swap + shift
# ----------------------------
def swap_deb_cred(core: str) -> str:
    deb = slice_1b(core, DEB_START_1B, DEB_END_1B)
    cre = slice_1b(core, CRE_START_1B, CRE_END_1B)
    out = core
    out = replace_1b(out, DEB_START_1B, DEB_END_1B, cre, align="left")
    out = replace_1b(out, CRE_START_1B, CRE_END_1B, deb, align="left")
    return out

def shift_from_col_52(core: str) -> str:
    idx0 = SHIFT_AT_COL_1B - 1
    core = ensure_len(core, idx0)
    return core[:idx0] + (" " * SHIFT_SPACES) + core[idx0:]


# ----------------------------
# Extração robusta (para o passo B)
# ----------------------------
ACCOUNT_RE = re.compile(r"\d{4,}")          # contas (>=4 dígitos, ajusta se necessário)
AMOUNT_RE  = re.compile(r"(?:\d+)?\.\d{2}") # valores: 85.91, .01, 0.50
TAIL_RE    = re.compile(r"([+-])\s*(\d{1,12})\s*$")  # +12201101 no fim

def extract_accounts(core: str) -> tuple[str, str]:
    """
    Devolve (acc2, acc7) = primeira conta a começar por 2 e primeira a começar por 7.
    """
    acc2 = ""
    acc7 = ""
    for m in ACCOUNT_RE.finditer(core):
        v = m.group(0)
        if not acc2 and v.startswith("2"):
            acc2 = v
        if not acc7 and v.startswith("7"):
            acc7 = v
        if acc2 and acc7:
            break
    return acc2, acc7

def extract_amount(core: str) -> str:
    """
    Tenta apanhar o valor monetário (última ocorrência tipo 85.91 / .01).
    """
    matches = list(AMOUNT_RE.finditer(core))
    return matches[-1].group(0) if matches else ""

def extract_sign_cc(core: str) -> tuple[str, str]:
    """
    Procura no fim algo tipo +12201101. Devolve (sign, cc_digits).
    """
    m = TAIL_RE.search(core)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


# ----------------------------
# Passo B: reformatar posições finais
# ----------------------------
def apply_final_layout(core: str) -> tuple[str, dict]:
    """
    Escreve:
      crédito 98–114
      valor   115–124
      sinal   125
      CC      126–135 (sem sinal)
    Trunca/normaliza a linha para 135 chars.
    """
    core = ensure_len(core, FINAL_LEN)

    acc2, acc7 = extract_accounts(core)  # débito/credito por prefixo (para validação)
    amount = extract_amount(core)
    sign, cc = extract_sign_cc(core)

    # Validar mínimos para não estragar
    ok = True
    issues = []
    if not acc7:
        ok = False; issues.append("Não encontrei conta a começar por 7 (crédito).")
    if not amount:
        ok = False; issues.append("Não encontrei valor no formato .dd.")
    if not cc:
        ok = False; issues.append("Não encontrei sinal+CC no fim da linha.")

    if not ok:
        info = {
            "OK": False,
            "issues": " | ".join(issues),
            "acc2": acc2,
            "acc7": acc7,
            "amount": amount,
            "tail_sign": sign,
            "tail_cc": cc,
        }
        return core, info

    # Normalizações
    cred_out = acc7  # crédito é o que começa por 7
    # valor em 10 chars: manter exatamente como está mas alinhado à direita
    # exemplo ".01" vira "      .01"
    val_out = amount
    sign_out = sign if sign in ["+", "-"] else "+"
    cc_out = cc.zfill(10)[-10:]  # CC a 10 dígitos, sem sinal

    out = core
    out = replace_1b(out, NEW_CRED_START_1B, NEW_CRED_END_1B, cred_out, align="left")
    out = replace_1b(out, NEW_VAL_START_1B, NEW_VAL_END_1B, val_out, align="right")
    out = replace_1b(out, NEW_SIGN_COL_1B, NEW_SIGN_COL_1B, sign_out, align="left")
    out = replace_1b(out, NEW_CC_START_1B, NEW_CC_END_1B, cc_out, align="left")

    # Truncar para não levar “restos” que confundem o importador
    out = out[:FINAL_LEN]

    info = {
        "OK": True,
        "cred(98)": cred_out,
        "val(115)": val_out,
        "sign(125)": sign_out,
        "cc(126)": cc_out,
    }
    return out, info


# ============================================================
# Pipeline por linha
# ============================================================
def process_line(line: str) -> tuple[str, dict]:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    core = ensure_len(core, LINE_MIN_LEN)

    # 1) swap
    core = swap_deb_cred(core)

    # 2) shift col 52
    core = shift_from_col_52(core)

    # 3) layout final
    core = ensure_len(core, FINAL_LEN)
    final_core, info = apply_final_layout(core)

    return final_core + ("\n" if has_nl else ""), info


def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag = []
    bad = []

    for i, ln in enumerate(lines, start=1):
        new_ln, info = process_line(ln)
        out_lines.append(new_ln if info.get("OK") else ln)
        if i <= 20:
            diag.append({"Linha": i, **info})
        if not info.get("OK"):
            bad.append({"Linha": i, **info})

    return "".join(out_lines), diag, bad


# ============================================================
# UI Streamlit
# ============================================================
st.set_page_config(page_title="Retificar TXT 905", layout="centered")
st.title("Retificar TXT – swap + shift + reposicionar Crédito/Valor/CC")

st.markdown(
    """
**Operações fixas:**
1) Troca **Débito 60–109** ↔ **Crédito 110–159**  
2) Insere **3 espaços** a partir da **coluna 52**  
3) Reposiciona no ficheiro final:
- Crédito começa na **coluna 98**
- Valor começa na **coluna 115**
- Sinal em **125**
- CC (sem +) começa na **coluna 126**
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
            f"Falhou a extração/validação em {len(bad)} linha(s). "
            "Nessas linhas o ficheiro NÃO foi alterado para evitar estragos."
        )
        st.table(bad[:200])

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
