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

# =========================
# 🔐 Ler chave do secrets
# =========================
chave = None
try:
    chave = st.secrets["ifthenpay"]["backoffice_key"]
except Exception:
    st.error("Não encontrei `ifthenpay.backoffice_key` em `secrets`. Define em `.streamlit/secrets.toml`.")
    st.stop()

# =========================
# ⚙️ Formulário
# =========================
with st.form("form_pagamentos"):
    col1, col2, col3 = st.columns(3)
    with col1:
        entidade = st.text_input("🏦 Entidade", value="12377")
    with col2:
        subentidade = st.text_input("🏢 Subentidade", value="143")
    with col3:
        sandbox = st.selectbox("🧪 Sandbox", options=["Não", "Sim"], index=0)

    col4, col5, col6, col7 = st.columns(4)
    today = date.today()
    with col4:
        dt_inicio_d = st.date_input("📅 Data Início", value=date(today.year, 7, 1))
    with col5:
        dt_fim_d = st.date_input("📅 Data Fim", value=date(today.year, 7, 30))
    with col6:
        hora_inicio = st.time_input("⏰ Hora Início", value=time(0, 0, 0))
    with col7:
        hora_fim = st.time_input("⏰ Hora Fim", value=time(23, 59, 59))

    referencia = st.text_input("🔎 Referência (opcional)", value="")
    valor = st.text_input("💶 Valor (opcional)", value="")

    submit = st.form_submit_button("🔄 Obter Pagamentos")

# =========================
# 🔎 Helpers
# =========================
def fmt_ddmmyyyy_hhmmss(d: date, t: time) -> str:
    dt = datetime.combine(d, t)
    return dt.strftime("%d-%m-%Y %H:%M:%S")

def try_parse_json(text: str):
    """Tenta obter JSON de 3 formas: json direto, json 'nu' no texto, json dentro de XML."""
    # 1) Tentar json direto
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) Procurar o primeiro bloco {...} ou [...]
    m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 3) Remover tags XML e tentar novamente
    no_xml = re.sub(r"<[^>]+>", "", text).strip()
    try:
        return json.loads(no_xml)
    except Exception:
        return None

def ensure_rows(data):
    """Normaliza a estrutura devolvida pela API para lista de registos."""
    if data is None:
        return []
    # Alguns formatos possíveis: lista direta, dict com chave 'payments'/'result'/'Table' etc.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["payments", "result", "Results", "data", "Data", "Table", "Rows"]:
            if key in data and isinstance(data[key], list):
                return data[key]
        # se vier apenas um objeto
        return [data]
    return []

def beautify_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Arruma nomes mais legíveis e tenta converter datas/valores."""
    ren = {
        "Entidade": "Entidade",
        "SubEntidade": "Subentidade",
        "subentidade": "Subentidade",
        "entidade": "Entidade",
        "Referencia": "Referência",
        "referencia": "Referência",
        "Valor": "Valor",
        "valor": "Valor",
        "DataHora": "DataHora",
        "datahora": "DataHora",
        "Estado": "Estado",
        "estado": "Estado",
        "Terminal": "Terminal",
        "terminal": "Terminal"
    }
    df = df.rename(columns=ren)

    # Converter DataHora se vier string:
    if "DataHora" in df.columns:
        df["DataHora"] = pd.to_datetime(df["DataHora"], errors="coerce", dayfirst=True)

    # Converter Valor para numérico:
    if "Valor" in df.columns:
        df["Valor"] = (
            pd.to_numeric(df["Valor"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
        )

    # Ordenar por DataHora se existir
    if "DataHora" in df.columns:
        df = df.sort_values("DataHora")

    return df

# =========================
# 🚀 Chamada API
# =========================
if submit:
    url = "https://ifthenpay.com/ifmbws/ifmbws.asmx/getPaymentsJsonWithSandBoxV2"
    payload = {
        "chavebackoffice": chave,
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

    st.info("A contactar a API Ifthenpay…")
    try:
        # retries simples
        for attempt in range(2):
            resp = requests.post(url, data=payload, headers=headers, timeout=20)
            if resp.status_code == 200:
                break
        else:
            st.error(f"Erro HTTP {resp.status_code}: {resp.text[:300]}")
            st.stop()

        # Tentar resp.json(); se falhar, usar parser resiliente
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
            # Mensagens de erro comuns da API
            if isinstance(data, dict) and any(k.lower() in data for k in ["erro", "error", "mensagem", "message"]):
                st.warning(f"Resposta da API: {data}")
            else:
                st.info("⚠️ Nenhum pagamento encontrado para o intervalo selecionado.")
            st.stop()

        df = pd.json_normalize(rows)
        df = beautify_cols(df)

        st.success(f"✅ Foram encontrados {len(df)} pagamentos.")
        st.dataframe(df, use_container_width=True)

        # Exportar Excel
        bio = BytesIO()
        df.to_excel(bio, index=False, engine="openpyxl")
        bio.seek(0)
        fname = f"pagamentos_ifthenpay_{dt_inicio_d.strftime('%Y%m%d')}_{dt_fim_d.strftime('%Y%m%d')}.xlsx"

        st.download_button(
            "💾 Descarregar Excel",
            bio,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Pequeno sumário (se houver Valor)
        if "Valor" in df.columns:
            colA, colB, colC = st.columns(3)
            with colA:
                st.metric("Total €", f"{df['Valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            with colB:
                st.metric("Média €", f"{df['Valor'].mean():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            with colC:
                st.metric("N.º registos", len(df))

    except requests.Timeout:
        st.error("A chamada à API excedeu o tempo limite (timeout). Tenta encurtar o intervalo de datas.")
    except requests.RequestException as e:
        st.error(f"Erro de ligação à API: {e}")
    except Exception as e:
        st.error(f"Ocorreu um erro inesperado: {e}")
