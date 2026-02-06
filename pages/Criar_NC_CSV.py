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

# Constantes pedidas
CONST_CLASS_ECON = "07.02.05.01.78"
CONST_FONTE_FIN  = "513"
# IMPORTANTE: para o Excel não "comer" zeros à esquerda, forçar texto:
CONST_PROGRAMA   = '="015"'
CONST_MEDIDA     = '="022"'
CONST_DEP_ATIV   = "1"
CONST_CLASS_ORG  = "121904000"

# =========================
# FUNÇÕES TÉCNICAS (MANTIDAS)
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

def write_over(chars, start, old_end, new_text):
    old_len = max(0, old_end - start)
    wipe_len = max(old_len, len(new_text))
    need = start + wipe_len
    if need > len(chars):
        chars.extend([" "] * (need - len(chars)))
    for i in range(start, start + wipe_len):
        chars[i] = " "
    for i, ch in enumerate(new_text):
        chars[start + i] = ch

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

# =========================
# PROCESSAMENTO TXT (IGUAL AO TEU)
# =========================
def process_line(line: str):
    raw = line[120:].replace("+", " ").strip()
    parts = raw.split()
    val = parts[0] if len(parts) > 0 else ""
    cc_old = parts[1] if len(parts) > 1 else ""
    cc_new = CC_MAP.get(cc_old, cc_old)

    shifted = shift_for_date(line)
    has_nl = shifted.endswith("\n")
    core = shifted[:-1] if has_nl else shifted

    a_pos, a_digits, a_end = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=63)
    b_pos, b_digits, b_end = find_account_pos(core, B_EXPECT_1B, B_PREFIX)

    if not a_pos or not b_pos:
        return shifted

    chars = list(core)
    write_over(chars, a_pos - 1, a_end, b_digits)
    write_over(chars, b_pos - 1, b_end, a_digits)

    for i in range(89, len(chars)):
        chars[i] = " "

    # Conta Crédito na 90
    for i, ch in enumerate(a_digits):
        if 89 + i < len(chars):
            chars[89 + i] = ch

    # Valor: 105 até 119
    for i, ch in enumerate(val):
        if 104 + i < 119:
            chars[104 + i] = ch

    # Centro de Custo na 122
    for i, ch in enumerate(cc_new):
        if 121 + i < len(chars):
            chars[121 + i] = ch

    out = "".join(chars).rstrip()
    return out + ("\n" if has_nl else "")

def process_text(text: str):
    return "".join(process_line(l) for l in text.splitlines(keepends=True))

# =========================
# CSV
# =========================
def ddmmaaaa_to_aaaammdd(s):
    s = (s or "").strip()
    return f"{s[4:8]}{s[2:4]}{s[0:2]}" if len(s) == 8 and s.isdigit() else ""

def valor_pt(v):
    v = (v or "").strip()
    if v.startswith("."):
        v = "0" + v
    return v.replace(".", ",")

def line_to_csv_row(line: str):
    # Campos do TXT original por posição
    entidade = line[11:19].strip() if len(line) >= 19 else ""
    num_cc = line[27:39].strip() if len(line) >= 39 else ""

    # Valor e CC (pelo método que já tinhas validado)
    raw = line[120:].replace("+", " ").strip()
    parts = raw.split()
    val_raw = parts[0] if len(parts) > 0 else ""
    cc_old = parts[1] if len(parts) > 1 else ""
    cc = CC_MAP.get(cc_old, cc_old)
    # normalizar CC a 10 dígitos (texto)
    cc = "".join(ch for ch in cc if ch.isdigit()).zfill(10)[-10:]

    # Data documento (após shift: 55-62 => índices 54-61)
    shifted = shift_for_date(line)
    data_ddmmaaaa = shifted[54:62].strip() if len(shifted) >= 62 else ""
    data_doc = ddmmaaaa_to_aaaammdd(data_ddmmaaaa)

    # Data contabilística = hoje
    data_contab = datetime.now().strftime("%Y%m%d")

    # Contas (após swap: débito=b_digits, crédito=a_digits)
    core = shifted.rstrip("\n")
    a_pos, a_digits, _ = find_account_pos(core, A_EXPECT_1B, A_PREFIX, min_start_1b=63)
    b_pos, b_digits, _ = find_account_pos(core, B_EXPECT_1B, B_PREFIX)
    if not a_pos or not b_pos:
        return None

    row = {h: "" for h in CSV_HEADER}

    # CC = Crédito a Cliente (literal)
    row["CC"] = "CC"

    row["Entidade"] = entidade
    row["Data documento"] = data_doc
    row["Data Contabilistica"] = data_contab
    row["Nº CC"] = num_cc

    # Constantes
    row["classificador economico"] = CONST_CLASS_ECON
    row["Fonte de financiamento"] = CONST_FONTE_FIN
    row["Programa"] = CONST_PROGRAMA     # forçado a texto no Excel
    row["Medida"] = CONST_MEDIDA         # forçado a texto no Excel
    row["Departamento/Atividade"] = CONST_DEP_ATIV
    row["Classificação Orgânica"] = CONST_CLASS_ORG

    # Contas e valores
    row["Conta Debito"] = b_digits
    row["Conta a Credito"] = a_digits
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
        # Excel/PT: cp1252 costuma ser o mais compatível
        st.download_button(
            "💾 Descarregar CSV",
            data=csv_out.encode("cp1252"),
            file_name=f"{name}_corrigido.csv",
            mime="text/csv"
        )
        st.success(f"CSV gerado com {n} linhas")
