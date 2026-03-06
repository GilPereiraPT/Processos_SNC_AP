import streamlit as st
import os
import csv
import io
from datetime import datetime

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
RAW_TAIL_START = 120  # índice Python

# MAPEAMENTO DE CENTROS DE CUSTO (DE 2024 PARA 2025)
CC_MAP = {
    "1020511": "12201101",
    "1020512": "12201102",
    "1020513": "12201103",
    "1020514": "12201104",
    "1020521": "12201201",
    "1020524": "12201202",
    "1020522": "12201203",
    "1020523": "12201204",
}

# =========================
# CSV (EXCEL) — CABEÇALHO FIXO
# =========================
CSV_HEADER = [
    "CC","Entidade","Data documento","Data Contabilistica","Nº CC","Série","Subtipo",
    "classificador economico","Classificador funcional","Fonte de financiamento","Programa","Medida",
    "Projeto","Regionalização","Atividade","Natureza","Departamento/Atividade","Conta Debito",
    "Conta a Credito","Valor Lançamento","Centro de custo","Observações Documento",
    "Observaçoes lançamento","Classificação Orgânica","Ano FD","Numero FD","Série FD","Projeto Documento"
]

CONST_CLASS_ECON = "07.02.05.01.78"
CONST_FONTE_FIN  = "513"
CONST_PROGRAMA   = '="015"'
CONST_MEDIDA     = '="022"'
CONST_DEP_ATIV   = "1"
CONST_CLASS_ORG  = "121904000"

# =========================
# FUNÇÕES TÉCNICAS
# =========================
def shift_for_date(line: str) -> str:
    idx = DATE_START_CURRENT_1B - 1
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    if len(core) < idx:
        core += " " * (idx - len(core))
    core = core[:idx] + (" " * SHIFT_SPACES) + core[idx:]
    return core + ("\n" if has_nl else "")

def read_digits(core: str, start_idx: int):
    if start_idx >= len(core) or not core[start_idx].isdigit():
        return "", start_idx
    i = start_idx
    while i < len(core) and core[i].isdigit():
        i += 1
    return core[start_idx:i], i

def find_account_pos(core, expect_1b, prefix, min_start_1b=None):
    expect0 = expect_1b - 1
    for delta in range(-WINDOW, WINDOW + 1):
        pos0 = expect0 + delta
        if pos0 < 0:
            continue
        if min_start_1b and (pos0 + 1) < min_start_1b:
            continue
        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos0 + 1, digits, end
    return None, "", 0

def ddmmaaaa_to_aaaammdd(s):
    s = (s or "").strip()
    return f"{s[4:8]}{s[2:4]}{s[0:2]}" if len(s) == 8 and s.isdigit() else ""

def valor_pt(v):
    v = (v or "").strip()
    if v.startswith("."):
        v = "0" + v
    return v.replace(".", ",")

# =========================
# TAIL: preservar a linha e só trocar o CC
# =========================
def split_tail_tokens_with_positions(tail: str):
    """
    Devolve lista de tokens não-espaço com posições:
    [(token, start, end), ...]
    """
    out = []
    in_token = False
    start = 0
    for i, ch in enumerate(tail):
        if not ch.isspace() and not in_token:
            start = i
            in_token = True
        elif ch.isspace() and in_token:
            out.append((tail[start:i], start, i))
            in_token = False
    if in_token:
        out.append((tail[start:], start, len(tail)))
    return out

def replace_cc_in_tail_preserving_layout(tail: str):
    """
    Na zona final da linha assume:
      token 1 = valor
      token 2 = centro de custo
    Só substitui o token 2 se estiver no mapa.
    Mantém o resto da tail igual.
    """
    tokens = split_tail_tokens_with_positions(tail)
    if len(tokens) < 2:
        return tail, "", ""

    val = tokens[0][0].replace("+", "").strip()
    cc_old, cc_start, cc_end = tokens[1]
    cc_new = CC_MAP.get(cc_old, cc_old)

    if cc_new == cc_old:
        return tail, val, cc_old

    # Substituição conservadora do token do CC
    new_tail = tail[:cc_start] + cc_new + tail[cc_end:]
    return new_tail, val, cc_new

def extract_val_and_cc_from_tail(tail: str):
    tokens = split_tail_tokens_with_positions(tail.replace("+", " "))
    val = tokens[0][0].strip() if len(tokens) > 0 else ""
    cc_old = tokens[1][0].strip() if len(tokens) > 1 else ""
    cc_new = CC_MAP.get(cc_old, cc_old)
    return val, cc_new

# =========================
# PROCESSAMENTO TXT
# Só ajusta posições e converte CC
# =========================
def process_line(line: str):
    shifted = shift_for_date(line)

    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    if len(core) <= RAW_TAIL_START:
        return shifted

    prefix = core[:RAW_TAIL_START]
    tail = core[RAW_TAIL_START:]

    new_tail, _, _ = replace_cc_in_tail_preserving_layout(tail)
    out = prefix + new_tail

    return out + ("\n" if has_nl else "")

def process_text(text: str):
    return "".join(process_line(l) for l in text.splitlines(keepends=True))

# =========================
# CSV
# Lê sem trocar contas
# =========================
def line_to_csv_row(line: str):
    entidade = line[11:19].strip() if len(line) >= 19 else ""
    num_cc = line[27:39].strip() if len(line) >= 39 else ""

    shifted = shift_for_date(line)
    core = shifted.rstrip("\n")

    # Data documento
    data_ddmmaaaa = shifted[54:62].strip() if len(shifted) >= 62 else ""
    data_doc = ddmmaaaa_to_aaaammdd(data_ddmmaaaa)

    # Data contabilística = hoje
    data_contab = datetime.now().strftime("%Y%m%d")

    # Valor e CC
    tail = core[RAW_TAIL_START:] if len(core) > RAW_TAIL_START else ""
    val_raw, cc = extract_val_and_cc_from_tail(tail)
    cc = "".join(ch for ch in cc if ch.isdigit()).zfill(10)[-10:] if cc else ""

    # Contas sem troca
    a_pos, a_digits, _ = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=63)
    b_pos, b_digits, _ = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    if not a_pos or not b_pos:
        return None

    row = {h: "" for h in CSV_HEADER}

    row["CC"] = "CC"
    row["Entidade"] = entidade
    row["Data documento"] = data_doc
    row["Data Contabilistica"] = data_contab
    row["Nº CC"] = num_cc

    row["classificador economico"] = CONST_CLASS_ECON
    row["Fonte de financiamento"] = CONST_FONTE_FIN
    row["Programa"] = CONST_PROGRAMA
    row["Medida"] = CONST_MEDIDA
    row["Departamento/Atividade"] = CONST_DEP_ATIV
    row["Classificação Orgânica"] = CONST_CLASS_ORG

    row["Conta Debito"] = a_digits
    row["Conta a Credito"] = b_digits
    row["Valor Lançamento"] = valor_pt(val_raw)
    row["Centro de custo"] = cc

    return row

def build_csv(text):
    rows = []
    for ln in text.splitlines(keepends=True):
        r = line_to_csv_row(ln)
        if r:
            rows.append(r)

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=CSV_HEADER,
        delimiter=";",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n"
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

    return buf.getvalue(), len(rows)

# =========================
# INTERFACE STREAMLIT
# =========================
st.set_page_config(page_title="Retificador TXT / CSV", layout="wide")
st.title("Retificador Contabilístico Profissional")

uploaded = st.file_uploader("Selecione o ficheiro original", type=["txt"])

if uploaded:
    name, ext = os.path.splitext(uploaded.name)

    encoding = st.selectbox("Codificação (entrada/saída TXT)", ["cp1252", "utf-8", "latin-1"], index=0)
    try:
        text_in = uploaded.getvalue().decode(encoding)
    except UnicodeDecodeError:
        st.error("Não consegui ler o ficheiro com essa codificação. Experimenta cp1252 ou latin-1.")
        st.stop()

    formato = st.radio("Formato de saída", ["TXT corrigido", "CSV (Excel, separador ;)"], index=0)

    if formato == "TXT corrigido":
        txt_out = process_text(text_in)
        st.download_button(
            "💾 Descarregar TXT corrigido",
            data=txt_out.encode(encoding),
            file_name=f"{name}_corrigido{ext}",
            mime="text/plain"
        )
    else:
        csv_out, n = build_csv(text_in)
        st.download_button(
            "💾 Descarregar CSV",
            data=csv_out.encode("cp1252"),
            file_name=f"{name}_corrigido.csv",
            mime="text/csv"
        )
        st.success(f"CSV gerado com {n} linhas")
