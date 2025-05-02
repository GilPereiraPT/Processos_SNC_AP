import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Validador Balancete BA", layout="wide")
st.title("📊 Validador de Balancete BA - SNC-AP")
st.markdown("Validação automática de cabimentos, compromissos, obrigações e pagamentos a negativo (BA04).")

def extrair_dados(xml_content):
    root = ET.fromstring(xml_content)
    registos = []

    for reg in root.findall(".//Registo"):
        base = {
            'ID_Registo': reg.findtext("ID_Registo"),
            'ContaLocal': reg.findtext("ContaLocal"),
            'SaldosEMovimentos3': '',
            'Debito4': '',
        }

        detalhes = reg.findall("DetalheResumo")
        for det in detalhes:
            if det.findtext("SaldosEMovimentos") == "BA04":
                base['SaldosEMovimentos3'] = "BA04"
                base['Debito4'] = float(det.findtext("Debito") or 0.0)
                break

        if base['SaldosEMovimentos3'] == "BA04":
            for child in reg:
                if child.tag not in base:
                    base[child.tag] = child.text
            registos.append(base)

    return pd.DataFrame(registos)

def aplicar_regras(df):
    erros = []

    def regista_erro(row, motivo):
        linha = row.to_dict()
        linha["Erro"] = motivo
        erros.append(linha)

    for _, row in df.iterrows():
        conta = row['ContaLocal']
        debito = float(row.get('Debito4', 0.0))

        if conta.startswith("02.5.1.") and debito != 0:
            regista_erro(row, "Cabimento com débito diferente de zero")
        elif conta.startswith("02.6.1.") and debito != 0:
            regista_erro(row, "Compromisso com débito diferente de zero")
        elif conta.startswith("02.7.1.") and debito != 0:
            regista_erro(row, "Obrigação com débito diferente de zero")
        elif (conta.startswith("02.8.1") or conta.startswith("02.8.2")) and debito != 0:
            regista_erro(row, "Pagamento a negativo com débito diferente de zero")

    return pd.DataFrame(erros)

def converter_para_excel(df):
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer

uploaded_file = st.file_uploader("Carregar ficheiro XML do balancete BA", type=["xml"])

if uploaded_file is not None:
    xml_content = uploaded_file.read()
    df = extrair_dados(xml_content)
    erros_df = aplicar_regras(df)

    if not erros_df.empty:
        st.subheader("❗Erros encontrados")
        st.dataframe(erros_df, use_container_width=True)

        excel_buffer = converter_para_excel(erros_df)
        st.download_button(
            label="📥 Download do Excel com erros",
            data=excel_buffer,
            file_name="erros_validacao_balancete.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.success("Nenhum erro encontrado! ✅")
