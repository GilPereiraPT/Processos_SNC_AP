# app.py
import re
import json
import requests
import pandas as pd
from io import BytesIO
from datetime import date, datetime, time
import streamlit as st

st.set_page_config(page_title="Pagamentos Ifthenpay", layout="wide")
st.header("📥 Exportar Pagamentos Ifthenpay (MB)")

# ======================================================
# 🔐 Ler chave do secrets (.streamlit/secrets.toml)
# ------------------------------------------------------
# Formato:
# [ifthenpay]
# backoffice_key = "A_TUA_CHAVE"
# ======================================================
try:
    CHAVE = st.secrets["ifthenpay"]["backoffice_key"]
except Exception:
    st.error("Não encontrei `ifthenpay.backoffice_key` em `secrets`. Define em `.streamlit/secrets.toml`.")
    st.stop()

# ======================================================
# 🧰 Helpers
# ======================================================
def fmt_ddmmyyyy_hhmmss(d: date, t: time) -> str:
    return datetime.combine(d, t).strftime("%d-%m-%Y %H:%M:%S")

def try_parse_json(text: str):
    """Tenta obter JSON: direto, bloco {...}/[...] dentro do texto, ou removendo tags XML."""
    # 1) direto
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) primeiro bloco json
    m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 3) sem XML
    no_xml = re.sub(r"<[^>]+>", "", text).strip()
    try:
        return json.loads(no_xml)
    except Exception:
        return None

def ensure_rows(data):
    """Normaliza a estrutura devolvida pela API para lista de linhas."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["payments", "result", "Results", "data", "Data", "Table", "Rows"]:
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return []

def beautify_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Uniformiza nomes e tipos, e cria/ordena DataHora."""
    ren = {
        "Entidade": "Entidade", "entidade": "Entidade",
        "SubEntidade": "Subentidade", "subentidade": "Subentidade",
        "Referencia": "Referência", "referencia": "Referência",
        "Valor": "Valor", "valor": "Valor",
        "Estado": "Estado", "estado": "Estado",
        "Terminal": "Terminal", "terminal": "Terminal",
    }
    df = df.rename(columns=ren)

    # Tentar identificar a coluna de data/hora real
    cand_dt = [
        "DataHora", "datahora",
        "DataHoraPagamento", "dataHoraPagamento",
        "DataPagamento", "dataPagamento",
        "dtHr", "dtHrPagamento"
    ]
    col_dt = next((c for c in cand_dt if c in df.columns), None)
    if col_dt:
        df["DataHora"] = pd.to_datetime(df[col_dt], errors="coerce", dayfirst=True)
    else:
        df["DataHora"] = pd.NaT

    # Valor numérico
    if "Valor" in df.columns:
        df["Valor"] = pd.to_numeric(
            df["Valor"].astype(str).str.replace(",", ".", regex=False),
            errors="coerce"
        )

    # Ordenar por DataHora se existir
    if "DataHora" in df.columns:
        df = df.sort_values("DataHora")

    # Reordenar colunas mais comuns (se existirem)
    preferred = ["Entidade", "Subentidade", "Referência", "Valor", "DataHora", "Estado", "Terminal"]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    return df[cols]

def export_excel_bytes(df: pd.DataFrame, fname_base: str) -> BytesIO:
    bio = BytesIO()
    df.to_excel(bio, index=False, engine="openpyxl")
    bio.seek(0)
    return bio

# ======================================================
# 📋 Formulário
# ======================================================
with st.form("form_pagamentos"):
    col1, col2, col3 = st.columns(3)
    with col1:
        entidade = st.text_input("🏦 Entidade", value="12377")
    with col2:
        subentidade = st.text_input("🏢 Subentidade", value="143")
    with col3:
        sandbox = st.selectbox("🧪 Sandbox", options=["Não", "Sim"], index=0)

    today = date.today()
    col4, col5, col6, col7 = st.columns(4)
    with col4:
        dt_inicio_d = st.date_input("📅 Data Início", value=date(today.year, 7, 1), format="DD-MM-YYYY")
    with col5:
        dt_fim_d = st.date_input("📅 Data Fim", value=date(today.year, 7, 30), format="DD-MM-YYYY")
    with col6:
        hora_inicio = st.time_input("⏰ Hora Início", value=time(0, 0, 0))
    with col7:
        hora_fim = st.time_input("⏰ Hora Fim", value=time(23, 59, 59))

    referencia = st.text_input("🔎 Referência (opcional)", value="")
    valor = st.text_input("💶 Valor (opcional)", value="")

    submit = st.form_submit_button("🔄 Obter Pagamentos")

# ======================================================
# 🚀 Chamada API e filtragem local
# ======================================================
if submit:
    url = "https://ifthenpay.com/ifmbws/ifmbws.asmx/getPaymentsJsonWithSandBoxV2"
    payload = {
        "chavebackoffice": CHAVE,
        "entidade": entidade.strip(),
        "subentidade": subentidade.strip(),
        "dtHrInicio": fmt_ddmmyyyy_hhmmss(dt_inicio_d, hora_inicio),
        "dtHrFim": fmt_ddmmyyyy_hhmmss(dt_fim_d, hora_fim),
        "referencia": referencia.strip(),
        "valor": valor.strip(),
        "sandbox": "1" if sandbox == "Sim" else "0",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
    }

    dt_inicio_sel = datetime.combine(dt_inicio_d, hora_inicio)
    dt_fim_sel    = datetime.combine(dt_fim_d, hora_fim)
    st.caption(f"Intervalo a aplicar localmente: {dt_inicio_sel:%d-%m-%Y %H:%M:%S} → {dt_fim_sel:%d-%m-%Y %H:%M:%S}")

    st.info("A contactar a API Ifthenpay…")
    try:
        # Tentativa + 1 retry simples
        resp = None
        for _ in range(2):
            r = requests.post(url, data=payload, headers=headers, timeout=20)
            if r.status_code == 200:
                resp = r
                break
        if resp is None:
            st.error(f"Erro HTTP {r.status_code}: {r.text[:300]}")
            st.stop()

        # Parsing resiliente
        try:
            data = resp.json()
        except Exception:
            data = try_parse_json(resp.text)

        if data is None:
            st.error("Não foi possível interpretar a resposta da API (formato inesperado).")
            st.code(resp.text[:1000])
            st.stop()

        rows = ensure_rows(data)
        if not rows:
            if isinstance(data, dict) and any(k.lower() in data for k in ["erro", "error", "mensagem", "message"]):
                st.warning(f"Resposta da API: {data}")
            else:
                st.info("⚠️ Nenhum pagamento encontrado para a pesquisa.")
            st.stop()

        df_raw = pd.json_normalize(rows)
        df = beautify_cols(df_raw)

        # ====== Filtro local pelo intervalo selecionado ======
        removed = 0
        if "DataHora" in df.columns and df["DataHora"].notna().any():
            before = len(df)
            mask = (df["DataHora"] >= dt_inicio_sel) & (df["DataHora"] <= dt_fim_sel)
            df = df.loc[mask].copy()
            removed = before - len(df)

        # Feedback
        if df.empty:
            st.info("⚠️ Sem registos no intervalo selecionado após o filtro local.")
            if removed > 0:
                st.caption(f"(Foram removidos {removed} registos fora do intervalo.)")
            st.stop()

        st.success(f"✅ {len(df)} pagamentos dentro do intervalo.")
        if removed > 0:
            st.caption(f"🧹 Filtragem local removeu {removed} registos fora do intervalo devolvido pela API.")

        st.dataframe(df, use_container_width=True)

        # ====== Métricas rápidas ======
        if "Valor" in df.columns:
            colA, colB, colC = st.columns(3)
            with colA:
                st.metric("Total €", f"{df['Valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            with colB:
                st.metric("Média €", f"{df['Valor'].mean():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            with colC:
                st.metric("N.º registos", len(df))

        # ====== Exportar Excel ======
        fname = f"pagamentos_ifthenpay_{dt_inicio_sel:%Y%m%d%H%M%S}_{dt_fim_sel:%Y%m%d%H%M%S}.xlsx"
        bio = export_excel_bytes(df, fname)
        st.download_button(
            "💾 Descarregar Excel",
            bio,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except requests.Timeout:
        st.error("A chamada à API excedeu o tempo limite (timeout). Tenta encurtar o intervalo de datas.")
    except requests.RequestException as e:
        st.error(f"Erro de ligação à API: {e}")
    except Exception as e:
        st.error(f"Ocorreu um erro inesperado: {e}")
