from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parent
TOOLS = [
    ("Contabilidade e SNC-AP", "pages/validador_snc_ap.py", "🛡️", "Validador SNC-AP", "Validação de ficheiros SNC-AP"),
    ("Contabilidade e SNC-AP", "pages/Balancete_BA.py", "📊", "Balancete BA", "Conferência de balancetes"),
    ("Contabilidade e SNC-AP", "pages/Retificar_DTAS.py", "🧩", "Retificar DTAS", "Retificação de ficheiros DTAS"),
    ("Contabilidade e SNC-AP", "pages/Confere_ATIVOS.py", "🏷️", "Contabilidade e Ativos", "Conferência patrimonial"),
    ("Contabilidade e SNC-AP", "pages/Converte_CM.py", "📄", "Converter CM", "Conversão de ficheiros INFOCB"),
    ("Contabilidade e SNC-AP", "pages/conversor_centros_custo.py", "🧭", "Centros de Custo", "Harmonização de centros de custo"),
    ("Faturação e Fornecedores", "pages/Certidoes_SS_AT.py", "📋", "Certidões SS e AT", "Em desenvolvimento: Segurança Social e Autoridade Tributária"),
    ("Faturação e Fornecedores", "pages/Faturas_para_P2.py", "🧾", "Faturas para P2", "Preparação de faturas para SICC"),
    ("Faturação e Fornecedores", "pages/Criar_NC_CSV.py", "📝", "Criar NC CSV", "Conversão de notas de crédito"),
    ("Faturação e Fornecedores", "pages/NC_PDF_Manager-Farmacia.py", "💊", "NC Farmácia por PDF", "Tratamento de notas de crédito"),
    ("Faturação e Fornecedores", "pages/PAYBACK_APIFARMA_NC.py", "💳", "PAYBACK APIFARMA", "Tratamento contabilístico de payback"),
    ("Faturação e Fornecedores", "pages/converte_FD_migrantes.py", "🌍", "FD Migrantes", "Conversão de ficheiros de faturação"),
    ("Recursos Humanos e Fiscal", "pages/converte_ficheiro_vencimentos_app.py", "👥", "Vencimentos", "Preparação de mapas de vencimentos"),
    ("Recursos Humanos e Fiscal", "pages/retifica_DMR.py", "🧮", "Retificar DMR", "Retificação de ficheiros DMR"),
    ("Dados e Ferramentas de Apoio", "pages/criadorRA.py", "💶", "Receita Alheia", "Criação de ficheiros de receita alheia"),
    ("Dados e Ferramentas de Apoio", "pages/Juntar_Excel.py", "📚", "Juntar Excel", "Consolidação de ficheiros Excel"),
    ("Dados e Ferramentas de Apoio", "pages/mapeamentos_CCM.py", "🏥", "Mapeamentos CCM", "Consulta de mapeamentos"),
]

st.set_page_config(page_title="Processos Internos | ULSLA", page_icon="🏥", layout="wide")
st.markdown("""<style>
.stApp {background:#f5f7fb}
.block-container {max-width:1450px;padding-top:1.4rem}
[data-testid="stSidebar"] {border-right:1px solid #dce4ed}
</style>""", unsafe_allow_html=True)

def home():
    logo = ROOT / "logotipo ULSLA.png"
    if logo.exists():
        st.image(str(logo), width=250)
    st.title("Processos Internos")
    st.caption("ULSLA · Gestão Financeira e Patrimonial · Versão online")
    st.write("Selecione uma área funcional ou pesquise a ferramenta pretendida.")
    query = st.text_input("Pesquisar ferramentas", placeholder="Ex.: DMR, fornecedores, balancete")
    categories = list(dict.fromkeys(t[0] for t in TOOLS))
    category = st.selectbox("Área funcional", ["Todas as áreas"] + categories)
    selected = [t for t in TOOLS if (category == "Todas as áreas" or t[0] == category)
                and query.casefold() in " ".join(t[2:]+(t[0],)).casefold()]
    st.metric("Ferramentas disponíveis", len(TOOLS))
    if not selected:
        st.info("Não foram encontradas ferramentas.")
    for group in categories:
        entries = [t for t in selected if t[0] == group]
        if not entries:
            continue
        st.subheader(group)
        for start in range(0, len(entries), 3):
            cols = st.columns(3)
            for col, item in zip(cols, entries[start:start+3]):
                _, path, icon, title, description = item
                with col:
                    with st.container(border=True):
                        st.markdown(f"**{icon} {title}**")
                        st.caption(description)
                        st.page_link(path, label="Abrir ferramenta", icon="➡️", use_container_width=True)
    st.caption("Algumas funcionalidades requerem execução local e não estão disponíveis nesta versão.")

missing = [path for _, path, _, _, _ in TOOLS if not (ROOT / path).is_file()]
if missing:
    st.error("Páginas em falta: " + ", ".join(missing))
    st.stop()

navigation = {"Início": [st.Page(home, title="Página inicial", icon="🏠", default=True)]}
for group, path, icon, title, _ in TOOLS:
    navigation.setdefault(group, []).append(st.Page(path, title=title, icon=icon))
st.navigation(navigation, position="sidebar", expanded=True).run()
