import streamlit as st
st.set_page_config(page_title="Ferramenta Integrada", page_icon="🛠️", layout="wide")
st.title("🛠️ Ferramenta Integrada: Receita Alheia + Validador SNC-AP")
st.write("Utiliza o menu à esquerda ou os atalhos abaixo:")

cols = st.columns(3)
with cols[0]:
    st.page_link("pages/3_🔁_Converte_CM.py", label="Converte CM", icon="🔁")
    st.page_link("pages/2_🧭_Conversor_Centros_Custo.py", label="Conversor Centros Custo", icon="🧭")
with cols[1]:
    st.page_link("pages/7_✅_Validador_SNC_AP.py", label="Validador SNC-AP", icon="✅")
    st.page_link("pages/1_📊_Balancete_BA.py", label="Balancete BA", icon="📊")
with cols[2]:
    st.page_link("pages/5_🧾_Criador_RA.py", label="Criador RA", icon="🧾")
    st.page_link("pages/6_💳_Ifthenpay_Pagamentos.py", label="Ifthenpay Pagamentos", icon="💳")
