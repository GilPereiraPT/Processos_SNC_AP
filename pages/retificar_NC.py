import re
import streamlit as st
from datetime import datetime

# =========================
# FASE 1: TROCAS (o que já estava certo)
# =========================
SWAP_A_COL_1B = 63
SWAP_B_COL_1B = 113

# =========================
# FASE 2: ALINHAMENTOS FINAIS (o que pediste)
# =========================
CRED_START_1B = 98           # crédito começa aqui
CRED_LEN = 17                # 98-114

VAL_START_1B = 115           # valor começa aqui
VAL_LEN = 10                 # 115-124

SIGN_COL_1B = 125            # sinal
CC_START_1B = 126            # CC sem sinal
CC_LEN = 10                  # 126-135

FINAL_LEN = CC_START_1B - 1 + CC_LEN  # 135

# Extrações robustas (a partir da linha já trocada)
AMOUNT_RE = re.compile(r"(?:\d+)?\.\d{2}")          # 85.91, .01, 0.50
TAIL_RE   = re.compile(r"([+-])\s*(\d{1,12})\s*$")  # +12201101 no fim
ACCT_RE   = re.compile(r"\d{4,}")                   # contas >= 4 dígitos


# ---------- utils ----------
def ensure_len(s: str, n: int) -> str:
    return s + (" " * (n - len(s))) if len(s) < n else s

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

def put_field(core: str, start_1b: int, length: int, value: str, align: str = "left") -> str:
    core = ensure_len(core, start_1b - 1 + length)
    start0 = start_1b - 1
    end0 = start0 + length
    if align == "right":
        v = value[-length:].rjust(length)
    else:
        v = value[:length].ljust(length)
    return core[:start0] + v + core[end0:]


# ---------- Fase 1: swap em 63 ↔ 113 ----------
def swap_63_113(line: str) -> tuple[str, dict]:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line

    a0 = SWAP_A_COL_1B - 1
    b0 = SWAP_B_COL_1B - 1
    core = ensure_len(core, max(a0, b0) + 1)

    a, a_end = read_digits(core, a0)
    b, b_end = read_digits(core, b0)

    info = {"swap_ok": True, "A_antes": a, "B_antes": b}

    if a == "" or b == "":
        info["swap_ok"] = False
        return (core + ("\n" if has_nl else "")), info

    chars = list(core)
    write_over(chars, a0, a_end, b)
    write_over(chars, b0, b_end, a)

    out = "".join(chars)
    a2, _ = read_digits(out, a0)
    b2, _ = read_digits(out, b0)
    info["A_depois"] = a2
    info["B_depois"] = b2

    return (out + ("\n" if has_nl else "")), info


# ---------- Fase 2: alinhar crédito/valor/cc ----------
def extract_credit_account(core: str) -> str:
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

def apply_alignments(line: str) -> tuple[str, dict]:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    core = ensure_len(core, FINAL_LEN)

    cred = extract_credit_account(core)
    val = extract_amount(core)
    sign, cc = extract_sign_cc(core)

    ok = True
    issues = []
    if not cred:
        ok = False; issues.append("não encontrei crédito (começa por 7)")
    if not val:
        ok = False; issues.append("não encontrei valor (.dd)")
    if not cc:
        ok = False; issues.append("não encontrei sinal+CC no fim")

    info = {
        "align_ok": ok,
        "cred": cred,
        "valor": val,
        "sinal": sign,
        "cc_raw": cc,
        "issues": " | ".join(issues)
    }
    if not ok:
        return (core + ("\n" if has_nl else "")), info

    # normalizações
    sign = sign if sign in ["+", "-"] else "+"
    cc10 = cc.zfill(CC_LEN)[-CC_LEN:]

    # escrever nos sítios finais
    out = core
    out = put_field(out, CRED_START_1B, CRED_LEN, cred, align="left")
    out = put_field(out, VAL_START_1B,  VAL_LEN,  val,  align="right")
    out = put_field(out, SIGN_COL_1B,   1,        sign, align="left")
    out = put_field(out, CC_START_1B,   CC_LEN,   cc10, align="left")

    # truncar para remover “lixo” à direita que pode baralhar o importador
    out = out[:FINAL_LEN]

    info["cc10"] = cc10
    return (out + ("\n" if has_nl else "")), info


# ---------- Pipeline: (1) swaps -> (2) alinhamentos ----------
def process_text(text: str):
    lines = text.splitlines(keepends=True)
    out_lines = []
    diag = []
    bad = []

    for i, ln in enumerate(lines, start=1):
        ln1, info1 = swap_63_113(ln)
        ln2, info2 = apply_alignments(ln1)

        info = {"Linha": i, **info1, **info2}
        out_lines.append(ln2)

        if i <= 20:
            diag.append(info)
        if (not info1.get("swap_ok", True)) or (not info2.get("align_ok", True)):
            bad.append(info)

    return "".join(out_lines), diag, bad


# =========================
# UI
# =========================
st.set_page_config(page_title="Retificar TXT", layout="centered")
st.title("Retificar TXT — Trocas primeiro, alinhamentos depois")

st.markdown(
    f"""
**Ordem fixa:**
1) Troca contas em **{SWAP_A_COL_1B} ↔ {SWAP_B_COL_1B}**  
2) Alinha no ficheiro final:
- Crédito em **{CRED_START_1B}**
- Valor em **{VAL_START_1B}**
- Sinal em **{SIGN_COL_1B}**
- CC (sem +) em **{CC_START_1B}**
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
        st.warning(f"Há {len(bad)} linha(s) com falhas (swap ou extração para alinhamentos).")
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
