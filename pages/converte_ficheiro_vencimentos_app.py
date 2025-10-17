# app.py
import io
import pandas as pd
import streamlit as st
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment

st.set_page_config(page_title="Importar Ficheiro para Excel", layout="centered")

st.title("Importar ficheiro → Excel (formatado)")
st.caption("Versão Streamlit (PT-PT). Suporta ficheiros com ou sem extensão.")

# Aceita qualquer tipo de ficheiro
uploaded = st.file_uploader("Escolhe o ficheiro a importar", type=None)

def to_int_str(x: str) -> str:
    try:
        return str(int(x))
    except Exception:
        return x

def to_float(x: str):
    try:
        return float(x.replace(",", "."))
    except Exception:
        return None

def to_date(x: str):
    if len(x) == 8 and x.isdigit():
        try:
            return datetime.strptime(x, "%d%m%Y")
        except Exception:
            return x
    return x

def parse_txt(content: str) -> pd.DataFrame:
    dados = []
    for raw in content.splitlines():
        linha = raw.rstrip("\n\r")
        if len(linha) >= 192:
            COD      = linha[0:3].strip()
            Entidade = linha[11:21].strip()
            NE       = linha[21:55].strip()
            DataStr  = linha[55:63].strip()
            Deb      = linha[63:113].strip()
            Cred     = linha[113:155].strip()
            Valor    = linha[155:181].strip()
            Sinal    = linha[181:182].strip()
            CC       = linha[182:192].strip()

            dados.append([
                COD,
                to_int_str(Entidade),
                NE,
                to_date(DataStr),
                Deb,
                Cred,
                to_float(Valor),
                Sinal,
                CC
            ])
    cols = ["COD", "Entidade", "NE", "Data", "Deb", "Cred", "Valor", "Sinal", "CC"]
    df = pd.DataFrame(dados, columns=cols)
    total = df["Valor"].sum(skipna=True) if not df.empty else 0.0
    df_total = df.copy()
    df_total.loc[len(df_total)] = ["", "", "", "", "", "Total", total, "", ""]
    return df, df_total

def format_excel_and_get_bytes(df_total: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    df_total.to_excel(bio, index=False)
    bio.seek(0)

    wb = load_workbook(bio)
    ws = wb.active

    header_fill = PatternFill(start_color="C8C8C8", end_color="C8C8C8", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for cell in ws["D"][1:ws.max_row-1]:
        if hasattr(cell.value, "year"):
            cell.number_format = "DD/MM/YYYY"

    for cell in ws["G"][1:ws.max_row]:
        if cell.value is not None and cell.value != "Total":
            cell.number_format = "#,##0.00"

    for col in ["E", "F"]:
        for cell in ws[col][1:ws.max_row-1]:
            cell.alignment = Alignment(horizontal="left")

    total_row = ws[ws.max_row]
    for cell in total_row:
        cell.font = Font(bold=True)
    thin = Side(style="thin")
    for col_idx in range(1, ws.max_column + 1):
        ws.cell(ws.max_row, col_idx).border = Border(top=thin)

    for column_cells in ws.columns:
        max_len = 0
        col_letter = column_cells[0].column_letter
        for c in column_cells:
            v = "" if c.value is None else str(c.value)
            if len(v) > max_len:
                max_len = len(v)
        ws.column_dimensions[col_letter].width = max_len + 2

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()

if uploaded is not None:
    # Lê o ficheiro tentando várias codificações
    raw_bytes = uploaded.read()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("cp1252")
        except Exception:
            st.error("O ficheiro não parece ser de texto legível.")
            st.stop()

    df, df_total = parse_txt(text)

    if df.empty:
        st.warning("Nenhuma linha válida encontrada (verifica o layout/posições).")
    else:
        st.success(f"Importadas {len(df)} linhas (sem contar com a linha Total).")
        st.dataframe(df_total, use_container_width=True)

        excel_bytes = format_excel_and_get_bytes(df_total)
        st.download_button(
            "⬇️ Descarregar Excel formatado",
            excel_bytes,
            file_name=(uploaded.name or "ficheiro") + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("Carrega um ficheiro para começar (pode não ter extensão).")

st.caption("A app tenta automaticamente UTF-8 e cp1252 se o ficheiro não tiver extensão ou vier com acentuação Windows.")
