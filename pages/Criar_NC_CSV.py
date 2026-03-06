import streamlit as st
import os
import csv
import io
from datetime import datetime

# =========================
# NOVO FICHEIRO DE ENTRADA
# =========================
# Layout observado no ficheiro recebido:
# 1-3     : código
# 12-18   : entidade
# 28-35   : nº CC
# 52-?    : data(8) + conta débito (prefixo 7)
# 110-114 : conta a crédito (prefixo 2)
# 160-?   : valor
# 178-?   : sinal + centro de custo

# =========================
# FICHEIRO FINAL (TXT)
# =========================
# Colunas do TXT final:
# 1/3   : Nome COD
# 12/21 : Entidade
# 22/55 : NE
# 56/63 : Data
# 64/113: Deb
# 114/155: Cred
# 156/181: Valor
# 182   : Sinal
# 183/192: CC

# =========================
# MAPEAMENTO DE CENTROS DE CUSTO
# =========================
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
# CSV (EXCEL)
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
# FUNÇÕES AUXILIARES
# =========================
def slice_safe(s: str, start: int, end: int) -> str:
    return s[start:end] if len(s) > start else ""

def ddmmaaaa_to_aaaammdd(s: str) -> str:
    s = (s or "").strip()
    return f"{s[4:8]}{s[2:4]}{s[0:2]}" if len(s) == 8 and s.isdigit() else ""

def valor_pt(v: str) -> str:
    v = (v or "").strip()
    if v.startswith("."):
        v = "0" + v
    return v.replace(".", ",")

def fix_cc(cc: str) -> str:
    cc = (cc or "").strip()
    return CC_MAP.get(cc, cc)

def extract_source_fields(line: str):
    """
    Extrai os campos do NOVO ficheiro de entrada.
    """
    line = line.rstrip("\n")

    cod = slice_safe(line, 0, 3).strip()
    entidade = slice_safe(line, 11, 18).strip()
    num_cc = slice_safe(line, 27, 35).strip()

    data_deb_raw = slice_safe(line, 51, 67).strip()  # data + conta 7
    conta_credito = slice_safe(line, 109, 114).strip()  # conta 2
    valor = slice_safe(line, 159, 177).strip()
    sinal_cc = slice_safe(line, 177, 188).strip()

    data_doc = data_deb_raw[:8] if len(data_deb_raw) >= 8 else ""
    conta_debito = data_deb_raw[8:] if len(data_deb_raw) > 8 else ""

    sinal = ""
    cc = ""
    if sinal_cc:
        sinal = sinal_cc[0] if sinal_cc[0] in "+-" else ""
        cc = sinal_cc[1:] if sinal else sinal_cc

    cc = fix_cc(cc)

    return {
        "cod": cod,
        "entidade": entidade,
        "num_cc": num_cc,
        "data_doc": data_doc,
        "conta_debito": conta_debito,
        "conta_credito": conta_credito,
        "valor": valor,
        "sinal": sinal,
        "cc": cc,
    }

def fw(text: str, width: int, align="left") -> str:
    text = (text or "")
    if len(text) > width:
        return text[:width]
    if align == "right":
        return text.rjust(width)
    return text.ljust(width)

# =========================
# TXT FINAL
# =========================
def build_output_txt_line(line: str) -> str:
    f = extract_source_fields(line)

    out = (
        fw(f["cod"], 3) +                  # 1-3
        " " * 8 +                         # 4-11
        fw(f["entidade"], 10) +           # 12-21
        fw(f["num_cc"], 34) +             # 22-55
        fw(f["data_doc"], 8) +            # 56-63
        fw(f["conta_debito"], 50) +       # 64-113
        fw(f["conta_credito"], 42) +      # 114-155
        fw(f["valor"], 26, "right") +     # 156-181
        fw(f["sinal"], 1) +               # 182
        fw(f["cc"], 10)                   # 183-192
    )
    return out + "\n"

def process_text_to_txt(text: str) -> str:
    return "".join(build_output_txt_line(line) for line in text.splitlines() if line.strip())

# =========================
# CSV
# =========================
def line_to_csv_row(line: str):
    f = extract_source_fields(line)

    if not any(f.values()):
        return None

    row = {h: "" for h in CSV_HEADER}
    row["CC"] = "CC"
    row["Entidade"] = f["entidade"]
    row["Data documento"] = ddmmaaaa_to_aaaammdd(f["data_doc"])
    row["Data Contabilistica"] = datetime.now().strftime("%Y%m%d")
    row["Nº CC"] = f["num_cc"]

    row["classificador economico"] = CONST_CLASS_ECON
    row["Fonte de financiamento"] = CONST_FONTE_FIN
    row["Programa"] = CONST_PROGRAMA
    row["Medida"] = CONST_MEDIDA
    row["Departamento/Atividade"] = CONST_DEP_ATIV
    row["Classificação Orgânica"] = CONST_CLASS_ORG

    row["Conta Debito"] = f["conta_debito"]
    row["Conta a Credito"] = f["conta_credito"]

    valor_csv = f["valor"]
    if f["sinal"] == "-":
        valor_csv = "-" + valor_csv.lstrip("-")

    row["Valor Lançamento"] = valor_pt(valor_csv)
    row["Centro de custo"] = "".join(ch for ch in f["cc"] if ch.isdigit()).zfill(10)[-10:] if f["cc"] else ""

    return row

def build_csv(text: str):
    rows = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
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
# STREAMLIT
# =========================
st.set_page_config(page_title="Conversor TXT / CSV", layout="wide")
st.title("Conversor Contabilístico")

uploaded = st.file_uploader("Selecione o ficheiro original", type=["txt"])

if uploaded:
    name, ext = os.path.splitext(uploaded.name)

    encoding = st.selectbox("Codificação", ["cp1252", "utf-8", "latin-1"], index=0)

    try:
        text_in = uploaded.getvalue().decode(encoding)
    except UnicodeDecodeError:
        st.error("Não consegui ler o ficheiro com essa codificação. Experimenta cp1252 ou latin-1.")
        st.stop()

    formato = st.radio(
        "Formato de saída",
        ["TXT final", "CSV (Excel, separador ;)"],
        index=0
    )

    # Pré-visualização
    preview_lines = [ln for ln in text_in.splitlines() if ln.strip()][:5]
    if preview_lines:
        st.subheader("Pré-visualização")
        prev = []
        for ln in preview_lines:
            prev.append(extract_source_fields(ln))
        st.dataframe(prev, use_container_width=True)

    if formato == "TXT final":
        txt_out = process_text_to_txt(text_in)
        st.download_button(
            "💾 Descarregar TXT final",
            data=txt_out.encode(encoding),
            file_name=f"{name}_final.txt",
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
