# app.py
import re
import json
import math
import time as time_mod
import requests
import pandas as pd
from io import BytesIO
from datetime import date, datetime, time
import streamlit as st

st.set_page_config(page_title="Pagamentos Ifthenpay", layout="wide")
st.header("📥 Exportar Pagamentos Ifthenpay (MB)")

# ======================================================
# 🔐 secrets
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
    """Tenta interpretar JSON mesmo quando vem embrulhado em XML/HTML."""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # remover tags XML/HTML
    no_xml = re.sub(r"<[^>]+>", "", text).strip()
    try:
        return json.loads(no_xml)
    except Exception:
        return None

def ensure_rows(data):
    """Devolve sempre uma lista de registos a partir de vários formatos possíveis."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # camadas comuns
        for k in ["payments", "result", "Results", "data", "Data", "Table", "Rows", "value", "Value"]:
            if k in data:
                v = data[k]
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    return ensure_rows(v)
        return [data]
    return []

def _to_float_pt(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip().replace(" ", "")
    # remover separadores de milhar comuns
    s = s.replace(".", "").replace("\u00A0", "")
    # vírgula decimal -> ponto
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def beautify_cols(df: pd.DataFrame) -> pd.DataFrame:
    # Normalização de nomes
    ren = {
        "Entidade": "Entidade", "entidade": "Entidade", "Entity": "Entidade",
        "SubEntidade": "Subentidade", "Subentidade": "Subentidade",
        "subentidade": "Subentidade", "Subentity": "Subentidade",
        "Referencia": "Referência", "referencia": "Referência", "ReferenciaMB": "Referência",
        "Valor": "Valor", "valor": "Valor", "amount": "Valor", "Amount": "Valor",
        "Estado": "Estado", "estado": "Estado", "Status": "Estado",
        "Terminal": "Terminal", "terminal": "Terminal",
    }
    df = df.rename(columns=ren)

    # DataHora – vários candidatos
    cand_dt = [
        "DataHora","datahora","DataHoraPagamento","dataHoraPagamento",
        "DataPagamento","dataPagamento","dtHr","dtHrPagamento","data_hora","datetime"
    ]
    col_dt = next((c for c in cand_dt if c in df.columns), None)
    if col_dt:
        df["DataHora"] = pd.to_datetime(df[col_dt], errors="coerce", dayfirst=True)
    else:
        df["DataHora"] = pd.NaT

    # Valor – aceitar vírgula/ponto e remover milhar
    if "Valor" in df.columns:
        df["Valor"] = df["Valor"].apply(_to_float_pt)

    # Estado – normalização simples
    if "Estado" in df.columns:
        df["Estado"] = df["Estado"].astype(str).str.strip().str.upper()

    # Referência – manter como texto e preservar zeros à esquerda
    if "Referência" in df.columns:
        df["Referência"] = df["Referência"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()

    # Ordenação por DataHora se existir algo válido
    if "DataHora" in df.columns and df["DataHora"].notna().any():
        df = df.sort_values("DataHora")

    preferred = ["Entidade", "Subentidade", "Referência", "Valor", "DataHora", "Estado", "Terminal"]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    return df[cols]

def export_excel_bytes(detalhe: pd.DataFrame, resumo_mes_ent: pd.DataFrame, resumo_ent: pd.DataFrame) -> BytesIO:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xlw:
        detalhe.to_excel(xlw, index=False, sheet_name="Detalhe")
        resumo_mes_ent.to_excel(xlw, index=True, sheet_name="Resumo_Mes_Entidade")
        resumo_ent.to_excel(xlw, index=True, sheet_name="Resumo_Entidade")
    bio.seek(0)
    return bio

def export_csv_bytes(df: pd.DataFrame) -> BytesIO:
    bio = BytesIO()
    bio.write(df.to_csv(index=False, sep=";").encode("utf-8"))
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
# 🔒 Validações rápidas
# ======================================================
def _is_num(s: str) -> bool:
    return bool(re.fullmatch(r"\d+", s.strip()))

if submit:
    if not _is_num(entidade):
        st.error("A *Entidade* deve ser numérica.")
        st.stop()
    if subentidade and not _is_num(subentidade):
        st.error("A *Subentidade* deve ser numérica.")
        st.stop()
    if datetime.combine(dt_inicio_d, hora_inicio) > datetime.combine(dt_fim_d, hora_fim):
        st.error("A *Data/Hora Início* não pode ser posterior à *Data/Hora Fim*.")
        st.stop()
    if valor.strip():
        if _to_float_pt(valor) is None:
            st.error("O campo *Valor* (opcional) não é numérico válido.")
            st.stop()

# ======================================================
# 🚀 Chamada API + Resumos
# ======================================================
@st.cache_data(ttl=180, show_spinner=False)
def fetch_ifthenpay(payload: dict, timeout: int = 20, retries: int = 2, backoff: float = 0.8):
    url = "https://ifthenpay.com/ifmbws/ifmbws.asmx/getPaymentsJsonWithSandBoxV2"
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json, text/plain, */*"}
    last_exc = None
    for i in range(retries):
        try:
            r = requests.post(url, data=payload, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
            last_exc = requests.RequestException(f"HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            last_exc = e
        time_mod.sleep(backoff * (i + 1))
    if last_exc:
        raise last_exc

if submit:
    dt_inicio_sel = datetime.combine(dt_inicio_d, hora_inicio)
    dt_fim_sel    = datetime.combine(dt_fim_d, hora_fim)
    st.caption(f"Intervalo a aplicar localmente: {dt_inicio_sel:%d-%m-%Y %H:%M:%S} → {dt_fim_sel:%d-%m-%Y %H:%M:%S}")

    payload = {
        "chavebackoffice": CHAVE,
        "entidade": entidade.strip(),
        "subentidade": subentidade.strip(),
        "dtHrInicio": fmt_ddmmyyyy_hhmmss(dt_inicio_d, hora_inicio),
        "dtHrFim": fmt_ddmmyyyy_hhmmss(dt_fim_d, hora_fim),
        "referencia": referencia.strip(),
        "valor": (str(_to_float_pt(valor)).replace(".", ",")) if valor.strip() else "",
        "sandbox": "1" if sandbox == "Sim" else "0",
    }

    with st.spinner("A contactar a API Ifthenpay…"):
        try:
            resp = fetch_ifthenpay(payload)
        except requests.Timeout:
            st.error("A chamada à API excedeu o tempo limite (*timeout*). Encurta o intervalo de datas.")
            st.stop()
        except requests.RequestException as e:
            st.error(f"Erro de ligação à API: {e}")
            st.stop()

    # Interpretar a resposta
    try:
        data = resp.json()
    except Exception:
        data = try_parse_json(resp.text)

    if data is None:
        st.error("Não foi possível interpretar a resposta da API.")
        st.code(resp.text[:1000])
        st.stop()

    rows = ensure_rows(data)
    if not rows:
        st.info("⚠️ Nenhum pagamento devolvido.")
        st.stop()

    df_raw = pd.json_normalize(rows)
    df = beautify_cols(df_raw)

    # ---- Filtro local por intervalo
    removed = 0
    if "DataHora" in df.columns and df["DataHora"].notna().any():
        before = len(df)
        mask = (df["DataHora"] >= dt_inicio_sel) & (df["DataHora"] <= dt_fim_sel)
        df = df.loc[mask].copy()
        removed = before - len(df)

    if df.empty:
        st.info("⚠️ Sem registos no intervalo selecionado após o filtro local.")
        if removed > 0:
            st.caption(f"(Foram removidos {removed} registos fora do intervalo.)")
        st.stop()

    # ===== Métricas rápidas =====
    st.success(f"✅ {len(df)} pagamentos dentro do intervalo.")
    if removed > 0:
        st.caption(f"🧹 Filtragem local removeu {removed} registos fora do intervalo.")

    def _fmt_eur(x: float) -> str:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return ""
        return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    colA, colB, colC = st.columns(3)
    with colA:
        st.metric("Total €", _fmt_eur(df["Valor"].sum() if "Valor" in df.columns else 0.0))
    with colB:
        st.metric("Média €", _fmt_eur(df["Valor"].mean() if "Valor" in df.columns else 0.0))
    with colC:
        st.metric("N.º registos", len(df))

    # ===== Detalhe =====
    st.subheader("🔎 Detalhe")
    st.dataframe(df, use_container_width=True)

    # ==================================================
    # 📊 Resumos por Mês e por Entidade
    # ==================================================
    if "Valor" in df.columns and df["Valor"].notna().any() and "Entidade" in df.columns:
        # ignorar linhas sem DataHora para o resumo mensal
        df_res = df.copy()
        if "DataHora" in df_res.columns:
            df_res = df_res[df_res["DataHora"].notna()].copy()

        if not df_res.empty:
            df_res["AnoMes"] = df_res["DataHora"].dt.to_period("M").astype(str)

            # 1) Resumo Mês × Entidade
            grp_mes_ent = df_res.groupby(["AnoMes", "Entidade"], dropna=False, as_index=False)["Valor"].sum()
            tabela_mes_ent = grp_mes_ent.pivot(index="AnoMes", columns="Entidade", values="Valor").fillna(0.0)
            tabela_mes_ent = tabela_mes_ent.sort_index()

            st.subheader("📅 Resumo por Mês × Entidade (soma de Valor)")
            st.dataframe(tabela_mes_ent, use_container_width=True)

            st.subheader("📈 Gráfico mensal (todas as entidades)")
            st.bar_chart(tabela_mes_ent)

        # 2) Resumo por Entidade (total no período)
        resumo_ent = df.groupby("Entidade", dropna=False)["Valor"].sum().sort_values(ascending=False)
        st.subheader("🏦 Total por Entidade (período selecionado)")
        st.dataframe(resumo_ent.to_frame("Valor"), use_container_width=True)

        st.subheader("📊 Top Entidades")
        st.bar_chart(resumo_ent.head(15))

        # ===== Export =====
        fname_base = f"pagamentos_ifthenpay_{dt_inicio_sel:%Y%m%d%H%M%S}_{dt_fim_sel:%Y%m%d%H%M%S}"
        bio_xlsx = export_excel_bytes(df, tabela_mes_ent if 'tabela_mes_ent' in locals() else pd.DataFrame(),
                                      resumo_ent.to_frame("Valor"))
        st.download_button(
            "💾 Descarregar Excel (Detalhe + Resumos)",
            bio_xlsx,
            file_name=fname_base + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.download_button(
            "⬇️ Descarregar CSV (Detalhe)",
            export_csv_bytes(df),
            file_name=fname_base + ".csv",
            mime="text/csv",
        )
    else:
        st.warning("Não foi possível criar resumos: faltam colunas 'Entidade' e/ou 'Valor'.")
