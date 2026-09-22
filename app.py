import os
import streamlit as st

st.set_page_config(
    page_title="Hub Financeiro ULSLA",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

LOCAL_MODE = os.getenv("ULSLA_LOCAL_MODE", "0") == "1"

st.markdown(
    """
    <style>
      .stApp { background: #f5f7fb; }
      .block-container { max-width: 1500px; padding-top: 1.6rem; padding-bottom: 3rem; }
      [data-testid="stSidebar"] { border-right: 1px solid #e4e9f1; }
      .hero {
        padding: 2rem 2.2rem;
        border-radius: 22px;
        background: linear-gradient(135deg, #15365f 0%, #1f5f91 58%, #3187b7 100%);
        color: white;
        box-shadow: 0 14px 35px rgba(21,54,95,.15);
        margin-bottom: 1.25rem;
      }
      .hero h1 { margin: 0 0 .35rem 0; font-size: 2.15rem; line-height: 1.15; }
      .hero p { margin: 0; opacity: .92; font-size: 1.02rem; }
      .status {
        display: inline-block;
        margin-top: 1rem;
        padding: .38rem .7rem;
        border-radius: 999px;
        background: rgba(255,255,255,.16);
        border: 1px solid rgba(255,255,255,.30);
        font-size: .88rem;
        font-weight: 600;
      }
      .section-title {
        font-weight: 750;
        font-size: 1.24rem;
        color: #183451;
        margin: .6rem 0 .15rem 0;
      }
      .section-subtitle {
        color: #66758a;
        margin-bottom: .55rem;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        background: white;
        border: 1px solid #e6eaf0 !important;
        border-radius: 16px !important;
        box-shadow: 0 5px 18px rgba(22,44,70,.045);
      }
      div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #c9d8e8 !important;
        box-shadow: 0 8px 24px rgba(22,44,70,.075);
      }
      .tool-title { font-size: 1.03rem; font-weight: 720; color: #183451; margin-bottom: .2rem; }
      .tool-desc { color: #65758a; font-size: .91rem; min-height: 2.75rem; margin-bottom: .4rem; }
      .footer { color: #77869a; font-size: .84rem; text-align: center; padding-top: 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

modo = "Modo local — independente do Streamlit Cloud" if LOCAL_MODE else "Modo web / Streamlit"
st.markdown(
    f"""
    <div class="hero">
      <h1>Hub Financeiro ULSLA</h1>
      <p>Ferramentas locais para processamento, conversão, reconciliação e validação financeira.</p>
      <span class="status">● {modo}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

m1, m2, m3 = st.columns(3)
m1.metric("Ferramentas disponíveis", "16")
m2.metric("Execução", "Local" if LOCAL_MODE else "Web")
m3.metric("Âmbito", "Financeiro · SNC-AP")

st.sidebar.markdown("## 🏥 Hub Financeiro")
if LOCAL_MODE:
    st.sidebar.success("Execução local ativa")
    st.sidebar.caption("A aplicação está a correr apenas neste computador.")
else:
    st.sidebar.info("Execução web")
st.sidebar.markdown(
    """
    **Navegação**
    
    Pode usar o menu automático acima ou escolher uma ferramenta nos cartões da página inicial.
    """
)
st.sidebar.divider()
st.sidebar.caption("ULSLA · Serviços Financeiros e Patrimoniais")


def tool_card(path: str, icon: str, title: str, description: str):
    with st.container(border=True):
        st.markdown(f'<div class="tool-title">{icon} {title}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="tool-desc">{description}</div>', unsafe_allow_html=True)
        st.page_link(path, label="Abrir ferramenta", icon="➡️", use_container_width=True)


def section(title: str, subtitle: str, tools: list[tuple[str, str, str, str]]):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-subtitle">{subtitle}</div>', unsafe_allow_html=True)
    for i in range(0, len(tools), 3):
        cols = st.columns(3)
        for col, tool in zip(cols, tools[i:i + 3]):
            with col:
                tool_card(*tool)


section(
    "Contabilidade e SNC-AP",
    "Validação, reconciliação e transformação de ficheiros contabilísticos.",
    [
        ("pages/validador_snc_ap.py", "🛡️", "Validador SNC-AP", "Valida lançamentos, classificadores e regras contabilísticas."),
        ("pages/Balancete_BA.py", "📊", "Balancete BA", "Valida registos BA04, cabimentos, compromissos, obrigações e pagamentos."),
        ("pages/Retificar_DTAS.py", "🧩", "Retificar DTAS", "Corrige XML DTAS com base no balancete BA de referência."),
        ("pages/Confere_ATIVOS.py", "🏷️", "Contabilidade × Ativos", "Reconcilia o balancete SICC com o registo patrimonial de ativos."),
        ("pages/Converte_CM.py", "📄", "Gerar ficheiro CM", "Converte INFOCB para o formato CM pronto para tratamento contabilístico."),
        ("pages/conversor_centros_custo.py", "🧭", "Centros de Custo", "Converte e harmoniza centros de custo mantendo o formato dos ficheiros."),
    ],
)

section(
    "Faturação, Notas de Crédito e Fornecedores",
    "Ferramentas de apoio ao processamento de documentos de fornecedores e faturação.",
    [
        ("pages/Faturas_para_P2.py", "🧾", "Faturas para P2", "Extrai informação de faturas PDF e prepara a importação no SICC."),
        ("pages/Criar_NC_CSV.py", "📝", "Criar NC CSV", "Converte o ficheiro original em notas de crédito para importação."),
        ("pages/NC_PDF_Manager-Farmacia.py", "💊", "NC Farmácia por PDF", "Atualiza o ficheiro de notas de crédito APIFARMA/PAYBACK a partir dos PDFs."),
        ("pages/PAYBACK_APIFARMA_NC.py", "💳", "PAYBACK APIFARMA", "Converte notas de crédito Excel/CSV para o formato contabilístico."),
        ("pages/converte_FD_migrantes.py", "🌍", "FD Migrantes", "Corrige rubricas específicas nos ficheiros de faturação de migrantes."),
    ],
)

section(
    "Recursos Humanos e Fiscal",
    "Conversão e retificação de ficheiros relacionados com vencimentos e declarações.",
    [
        ("pages/converte_ficheiro_vencimentos_app.py", "👥", "Ficheiro de Vencimentos", "Importa o ficheiro de vencimentos e gera Excel formatado."),
        ("pages/retifica_DMR.py", "🧮", "Retificar DMR", "Retifica o TXT da DMR com base em pendentes disponibilizados em Excel."),
    ],
)

section(
    "Dados e Ferramentas de Apoio",
    "Utilitários transversais para preparação, consolidação e transformação de dados.",
    [
        ("pages/criadorRA.py", "💶", "Receita Alheia", "Gera ficheiros de Receita Alheia com validação das entidades."),
        ("pages/Juntar_Excel.py", "📚", "Juntar Excel", "Consolida vários ficheiros Excel e remove documentos duplicados."),
        ("pages/mapeamentos_CCM.py", "🏥", "CCF / CCMSNS", "Processa ZIPs MCDT/Termas e, em Windows local, automatiza emails CCMSNS, reclamações e arquivo."),
    ],
)

st.divider()
st.markdown(
    '<div class="footer">Hub Financeiro ULSLA · versão local preparada para funcionamento independente do serviço Streamlit Cloud</div>',
    unsafe_allow_html=True,
)
