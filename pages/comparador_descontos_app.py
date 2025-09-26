# app_devolucoes_streamlit.py
# Streamlit app para registo e monitorização de devoluções de medicamentos/produtos de saúde
# Backend: SQLite (via SQLAlchemy)
# Autor: preparado para ULSLA (PT-PT)

import os
import io
import datetime as dt
from decimal import Decimal

import streamlit as st
import pandas as pd
from sqlalchemy import (
    create_engine, Column, Integer, String, Date, DateTime, Numeric, Boolean, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError

# =====================
# Configuração geral
# =====================
APP_TITLE = "Devoluções – SF / SFIN"
DB_PATH = os.environ.get("DEVOLUCOES_DB", "data/devolucoes.db")
DOCS_DIR = os.environ.get("DEVOLUCOES_DOCS_DIR", "data/docs")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

# =====================
# Base de dados (SQLAlchemy)
# =====================
Base = declarative_base()

def get_engine():
    return create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)

engine = get_engine()
SessionLocal = sessionmaker(bind=engine)

class Devolucao(Base):
    __tablename__ = "devolucoes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    # Dados principais
    fornecedor = Column(String(200), nullable=False)
    email_fornecedor = Column(String(200), nullable=True)
    produto = Column(Text, nullable=False)
    motivo = Column(Text, nullable=False)
    tipo = Column(String(20), nullable=False)  # "Troca" | "Crédito"
    quantidade = Column(String(50), nullable=True)  # manter string p/ casos não numéricos (unidades/caixas)
    lote = Column(String(100), nullable=True)
    validade = Column(Date, nullable=True)

    # Documentos
    docs_paths = Column(Text, nullable=True)  # paths separados por ;

    # Nota de Devolução
    nd_numero = Column(String(100), nullable=True)
    nd_data = Column(Date, nullable=True)

    # Estados e datas de processo
    estado = Column(String(40), nullable=False, default="Em curso")  # Em curso | Enviado fornecedor | A aguardar crédito | Crédito recebido | Fechado
    data_envio_fornecedor = Column(Date, nullable=True)
    data_transporte = Column(Date, nullable=True)

    # Nota de Crédito
    nc_numero = Column(String(100), nullable=True)
    nc_valor = Column(Numeric(14,2), nullable=True)
    nc_data_rececao = Column(Date, nullable=True)

    # Comunicação SFIN
    comunicou_sfin = Column(Boolean, default=False)
    data_comunicacao_sfin = Column(Date, nullable=True)

    # Outros
    observacoes = Column(Text, nullable=True)

Base.metadata.create_all(bind=engine)

# =====================
# Utilitários
# =====================

def to_date(x):
    if not x:
        return None
    if isinstance(x, (dt.date, dt.datetime)):
        return x if isinstance(x, dt.date) else x.date()
    try:
        return dt.datetime.strptime(str(x), "%Y-%m-%d").date()
    except Exception:
        try:
            return dt.datetime.strptime(str(x), "%d/%m/%Y").date()
        except Exception:
            return None


def save_uploaded_files(files):
    paths = []
    for f in files:
        # nome único: datahora_id_original
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = f.name.replace(" ", "_")
        out_path = os.path.join(DOCS_DIR, f"{ts}_{safe_name}")
        with open(out_path, "wb") as w:
            w.write(f.getbuffer())
        paths.append(out_path)
    return ";".join(paths) if paths else None


def record_to_dict(r: Devolucao):
    return {
        "ID": r.id,
        "Criado": r.created_at,
        "Atualizado": r.updated_at,
        "Fornecedor": r.fornecedor,
        "Email fornecedor": r.email_fornecedor,
        "Produto": r.produto,
        "Motivo": r.motivo,
        "Tipo": r.tipo,
        "Quantidade": r.quantidade,
        "Lote": r.lote,
        "Validade": r.validade,
        "Docs": r.docs_paths,
        "N.º Nota Devolução": r.nd_numero,
        "Data ND": r.nd_data,
        "Estado": r.estado,
        "Data envio fornecedor": r.data_envio_fornecedor,
        "Data transporte": r.data_transporte,
        "N.º Nota Crédito": r.nc_numero,
        "Valor NC": float(r.nc_valor) if r.nc_valor is not None else None,
        "Data receção NC": r.nc_data_rececao,
        "Comunicou SFIN": r.comunicou_sfin,
        "Data comunicação SFIN": r.data_comunicacao_sfin,
        "Observações": r.observacoes,
    }


def df_all(session, filtros=None):
    q = session.query(Devolucao)
    if filtros:
        if filtros.get("estado") and filtros["estado"] != "(Todos)":
            q = q.filter(Devolucao.estado == filtros["estado"])
        if filtros.get("tipo") and filtros["tipo"] != "(Todos)":
            q = q.filter(Devolucao.tipo == filtros["tipo"])
        if filtros.get("fornecedor"):
            q = q.filter(Devolucao.fornecedor.ilike(f"%{filtros['fornecedor']}%"))
        if filtros.get("pendentes_only"):
            q = q.filter(Devolucao.estado.in_(["Em curso", "Enviado fornecedor", "A aguardar crédito"]))
    rows = q.order_by(Devolucao.created_at.desc()).all()
    return pd.DataFrame([record_to_dict(r) for r in rows])


# =====================
# Sidebar – Filtros e Exportação
# =====================
with st.sidebar:
    st.header("Filtros")
    estado = st.selectbox("Estado", options=["(Todos)", "Em curso", "Enviado fornecedor", "A aguardar crédito", "Crédito recebido", "Fechado"], index=0)
    tipo = st.selectbox("Tipo", options=["(Todos)", "Troca", "Crédito"], index=0)
    fornecedor_f = st.text_input("Fornecedor contém")
    pendentes = st.checkbox("Mostrar apenas pendentes", value=False, help="Em curso / Enviado fornecedor / A aguardar crédito")

    st.markdown("---")
    st.subheader("Exportar")
    export_fmt = st.radio("Formato", ["Excel", "CSV"], horizontal=True)
    export_btn = st.button("Exportar registos filtrados")

# =====================
# Secção: Registo / Edição
# =====================
st.subheader("Registar / Editar devolução")

session = SessionLocal()

m_col1, m_col2 = st.columns([2, 1])
with m_col1:
    modo = st.radio("Modo", ["Novo registo", "Editar existente"], horizontal=True)

edit_id = None
if modo == "Editar existente":
    ids = [r.id for r in session.query(Devolucao.id).all()]
    if ids:
        edit_id = st.selectbox("Escolha o ID a editar", ids)
    else:
        st.info("Não existem registos para editar.")

with st.form("frm_devolucao", clear_on_submit=(modo == "Novo registo")):
    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)
    c7, c8 = st.columns(2)

    if modo == "Editar existente" and edit_id:
        rec = session.query(Devolucao).get(edit_id)
    else:
        rec = None

    fornecedor = c1.text_input("Fornecedor*", value=(rec.fornecedor if rec else ""))
    email_fornecedor = c2.text_input("Email fornecedor", value=(rec.email_fornecedor if rec else ""))
    tipo = c3.selectbox("Tipo*", ["Troca", "Crédito"], index=(0 if (rec and rec.tipo=="Troca") else 1 if rec else 0))

    produto = st.text_area("Medicamento/Produto*", value=(rec.produto if rec else ""))
    motivo = st.text_area("Motivo da devolução*", value=(rec.motivo if rec else ""))

    quantidade = c1.text_input("Quantidade", value=(rec.quantidade if rec else ""))
    lote = c2.text_input("Lote", value=(rec.lote if rec else ""))
    validade = c3.date_input("Validade", value=(rec.validade if rec and rec.validade else None))

    nd_numero = c4.text_input("N.º Nota de Devolução", value=(rec.nd_numero if rec else ""))
    nd_data = c5.date_input("Data ND", value=(rec.nd_data if rec and rec.nd_data else None))
    estado = c6.selectbox("Estado", ["Em curso", "Enviado fornecedor", "A aguardar crédito", "Crédito recebido", "Fechado"], index=(
        ["Em curso", "Enviado fornecedor", "A aguardar crédito", "Crédito recebido", "Fechado"].index(rec.estado) if rec else 0
    ))

    data_envio_fornecedor = c4.date_input("Data envio fornecedor", value=(rec.data_envio_fornecedor if rec and rec.data_envio_fornecedor else None))
    data_transporte = c5.date_input("Data transporte", value=(rec.data_transporte if rec and rec.data_transporte else None))

    nc_numero = c6.text_input("N.º Nota de Crédito", value=(rec.nc_numero if rec else ""))
    nc_valor_str = c7.text_input("Valor NC (€)", value=(str(rec.nc_valor) if rec and rec.nc_valor is not None else ""))
    nc_data_rececao = c8.date_input("Data receção NC", value=(rec.nc_data_rececao if rec and rec.nc_data_rececao else None))

    comunicou_sfin = c7.checkbox("Comunicou SFIN?", value=(rec.comunicou_sfin if rec else False))
    data_comunicacao_sfin = c8.date_input("Data comunicação SFIN", value=(rec.data_comunicacao_sfin if rec and rec.data_comunicacao_sfin else None))

    observacoes = st.text_area("Observações", value=(rec.observacoes if rec else ""))

    up_files = st.file_uploader("Anexar documentos (e-mail, ND, NC)", type=["pdf","msg","eml","jpg","png","doc","docx"], accept_multiple_files=True)

    submitted = st.form_submit_button("Guardar")

if submitted:
    if not fornecedor or not produto or not motivo or not tipo:
        st.error("Preencha os campos obrigatórios marcados com *.")
    else:
        docs_paths_joined = save_uploaded_files(up_files) if up_files else None
        try:
            if modo == "Editar existente" and edit_id:
                rec = session.query(Devolucao).get(edit_id)
                if rec is None:
                    st.error("Registo não encontrado.")
                else:
                    rec.fornecedor = fornecedor
                    rec.email_fornecedor = email_fornecedor or None
                    rec.produto = produto
                    rec.motivo = motivo
                    rec.tipo = tipo
                    rec.quantidade = quantidade or None
                    rec.lote = lote or None
                    rec.validade = validade or None
                    rec.nd_numero = nd_numero or None
                    rec.nd_data = nd_data or None
                    rec.estado = estado
                    rec.data_envio_fornecedor = data_envio_fornecedor or None
                    rec.data_transporte = data_transporte or None
                    rec.nc_numero = nc_numero or None
                    rec.nc_valor = Decimal(nc_valor_str.replace(",", ".")) if nc_valor_str.strip() != "" else None
                    rec.nc_data_rececao = nc_data_rececao or None
                    rec.comunicou_sfin = bool(comunicou_sfin)
                    rec.data_comunicacao_sfin = data_comunicacao_sfin or None
                    rec.observacoes = observacoes or None
                    if docs_paths_joined:
                        rec.docs_paths = (rec.docs_paths + ";" if rec.docs_paths else "") + docs_paths_joined
                    session.commit()
                    st.success(f"Registo {edit_id} atualizado com sucesso.")
            else:
                novo = Devolucao(
                    fornecedor=fornecedor,
                    email_fornecedor=email_fornecedor or None,
                    produto=produto,
                    motivo=motivo,
                    tipo=tipo,
                    quantidade=quantidade or None,
                    lote=lote or None,
                    validade=validade or None,
                    nd_numero=nd_numero or None,
                    nd_data=nd_data or None,
                    estado=estado,
                    data_envio_fornecedor=data_envio_fornecedor or None,
                    data_transporte=data_transporte or None,
                    nc_numero=nc_numero or None,
                    nc_valor=Decimal(nc_valor_str.replace(",", ".")) if nc_valor_str.strip() != "" else None,
                    nc_data_rececao=nc_data_rececao or None,
                    comunicou_sfin=bool(comunicou_sfin),
                    data_comunicacao_sfin=data_comunicacao_sfin or None,
                    observacoes=observacoes or None,
                    docs_paths=docs_paths_joined,
                )
                session.add(novo)
                session.commit()
                st.success(f"Registo criado com ID {novo.id}.")
        except OperationalError as e:
            st.error(f"Erro de base de dados: {e}")
        except Exception as e:
            st.error(f"Erro ao guardar: {e}")

# =====================
# Secção: Lista e Indicadores
# =====================
st.subheader("Registos")

filtros = {
    "estado": estado,
    "tipo": tipo,
    "fornecedor": fornecedor_f,
    "pendentes_only": pendentes,
}

df = df_all(session, filtros)

# --- Robustez: garantir colunas necessárias para evitar KeyError ---
REQUIRED_COLS = [
    "Estado","Data receção NC","Data envio fornecedor","Data ND","Criado",
    "Motivo","Produto","ID","Fornecedor","N.º Nota Devolução"
]
for col in REQUIRED_COLS:
    if col not in df.columns:
        # datas vs texto
        if "Data" in col or col == "Criado":
            df[col] = pd.NaT
        else:
            df[col] = None

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
)

# Exportação
if export_btn:
    if df.empty:
        st.warning("Não há registos para exportar com os filtros atuais.")
    else:
        if export_fmt == "Excel":
            bio = io.BytesIO()
            with pd.ExcelWriter(bio, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Devolucoes", index=False)
            st.download_button("Descarregar Excel", data=bio.getvalue(), file_name="devolucoes.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("Descarregar CSV", data=csv, file_name="devolucoes.csv", mime="text/csv")

# =====================
# Secção: Alertas e verificação bimestral
# =====================
st.subheader("Alertas")

hoje = dt.date.today()

if df.empty:
    st.info("Sem registos para analisar alertas.")
else:
    # Pendentes há mais de 60 dias sem NC (só se coluna existir)
    if "Estado" in df.columns and "Data receção NC" in df.columns:
        pendentes_sem_nc = df[(df["Estado"].isin(["Em curso", "Enviado fornecedor", "A aguardar crédito"])) & (df["Data receção NC"].isna())]
        if not pendentes_sem_nc.empty:
            def dias_abertos(row):
                base = row.get("Data envio fornecedor") or row.get("Data ND") or (row.get("Criado").date() if isinstance(row.get("Criado"), pd.Timestamp) else None)
                # fallback: hoje
                if base is None:
                    return 0
                if isinstance(base, pd.Timestamp):
                    base = base.date()
                return (hoje - base).days
            pendentes_sem_nc = pendentes_sem_nc.copy()
            pendentes_sem_nc["Dias abertos"] = pendentes_sem_nc.apply(dias_abertos, axis=1)
            criticos = pendentes_sem_nc[pendentes_sem_nc["Dias abertos"] > 60]
            if not criticos.empty:
                st.warning("Há devoluções pendentes há mais de 60 dias sem Nota de Crédito.")
                cols_show = [c for c in ["ID","Fornecedor","N.º Nota Devolução","Data ND","Data envio fornecedor","Dias abertos","Motivo","Produto"] if c in criticos.columns]
                st.dataframe(criticos[cols_show], use_container_width=True)
        else:
            st.info("Sem pendentes sem NC no momento.")
    else:
        st.info("Colunas necessárias para alertas não encontradas (Estado / Data receção NC).")

# =====================
# Secção: Modelos de e-mail
st.subheader("Modelos de e-mail")

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**Fornecedor – Pedido de aceitação de devolução**")
    fornecedor_nome = st.text_input("Fornecedor (nome no e-mail)", key="em_fornecedor")
    corpo1 = f"""
Exmos. Senhores {fornecedor_nome or '[Fornecedor]'},

Serve o presente para solicitar a devolução do(s) seguinte(s) medicamento(s)/produto(s):
- Produto: [Produto]
- Lote: [Lote]
- Validade: [Validade]
- Quantidade: [Quantidade]
- Motivo: [Motivo]
- Tipo de devolução: [Troca/Crédito]

Aguardo a vossa confirmação para avançarmos com o envio/levantamento.

Com os melhores cumprimentos,
Serviços Farmacêuticos – ULSLA
"""
    st.code(corpo1)

with col_b:
    st.markdown("**SFIN – Notas de Crédito Pendentes (até 5.º dia útil)**")
    lista_nd = ", ".join(df[df["Estado"].isin(["Enviado fornecedor","A aguardar crédito","Em curso"])]["N.º Nota Devolução"].dropna().astype(str).tolist()) or "[lista de ND]"
    corpo2 = f"""
Assunto: Notas de Crédito Pendentes

Exmos. Senhores,

Serve a presente para informar que se encontram pendentes as Notas de Crédito relativas às seguintes Notas de Devolução: {lista_nd}.
Solicita-se verificação e regularização junto dos fornecedores.

Cumprimentos,
Serviços Farmacêuticos – ULSLA
"""
    st.code(corpo2)

# Rodapé simples
st.caption("© ULSLA – Fluxo de Devoluções (SF/SFIN). Guardar ficheiros em data/docs. Variáveis DEVOLUCOES_DB e DEVOLUCOES_DOCS_DIR podem ser usadas para personalizar caminhos.")
