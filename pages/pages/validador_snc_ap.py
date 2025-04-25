# pages/validador_snc_ap.py

import streamlit as st
import pandas as pd
import os
from collections import Counter
from datetime import datetime

# Cabeçalhos esperados
CABECALHOS = [
    'Conta', 'Data Contab.', 'Data Doc.', 'Nº Lancamento', 'Entidade', 'Designação',
    'Tipo', 'Nº Documento', 'Serie', 'Ano', 'Debito', 'Credito', 'Acumulado',
    'D/C', 'R/D', 'Observações', 'Doc. Regul', 'Cl. Funcional', 'Fonte Finan.',
    'Programa', 'Medida', 'Projeto', 'Regionalização', 'Atividade', 'Natureza',
    'Cl. Orgânica', 'Mes', 'Departamento', 'DOCID', 'Ordem', 'Subtipo', 'NIF',
    'Código Parceira', 'Código Intragrupo', 'Utiliz Criação',
    'Utiliz Ult Alteração', 'Data Ult Alteração'
]

ORG_POR_FONTE = {
    '368': '108904000', '31H': '108904000', '483': '108904000', '488': '108904000',
    '511': '101904000', '513': '101904000', '521': '101904000', '522': '101904000',
    '541': '101904000', '724': '101904000',
}

st.set_page_config(
    page_title="Validador SNC-AP",
    layout="wide"
)
st.title("🛡️ Validador de Lançamentos SNC-AP")

st.markdown(
    "Carrega até **5 ficheiros CSV** gerados pelo SNC-AP "
    "para validares regras de fonte, rubrica, DOCID, etc."
)

uploaded = st.file_uploader(
    "Selecione os ficheiros CSV (até 5)", 
    type="csv", 
    accept_multiple_files=True
)

if uploaded:
    progresso = st.progress(0)
    log = []
    resumo_erros = Counter()
    total_linhas = 0
    total_files = len(uploaded)

    # Funções auxiliares
    def extrair_rubrica(conta: str) -> str:
        partes = str(conta).split(".")
        return ".".join(partes[1:]) if len(partes) > 1 else ""

    def validar_linha(idx, row):
        erros = []
        rd = str(row['R/D']).strip()
        fonte = str(row['Fonte Finan.']).strip()
        org   = str(row['Cl. Orgânica']).strip()
        programa = str(row['Programa']).strip()
        medida   = str(row['Medida']).strip()
        projeto  = row['Projeto']
        atividade = str(row['Atividade']).strip()
        funcional = str(row['Cl. Funcional']).strip()
        conta     = str(row['Conta']).strip()
        entidade  = str(row['Entidade']).strip()

        # regra por fonte/orgânica
        if fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
            erros.append(f"Linha {idx}: Cl. Orgânica deveria ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

        # regras R/D
        if rd == 'R':
            if entidade == '971010' and fonte != '511':
                erros.append(f"Linha {idx}: Entidade 971010 requer fonte 511")
            if programa != "'011":
                erros.append(f"Linha {idx}: Programa deve ser '011")
            if fonte not in ['483','31H','488'] and medida != "'022":
                erros.append(f"Linha {idx}: Medida deve ser '022' (exceto fontes 483,31H,488)")
            if entidade == '971007' and fonte != '541':
                erros.append(f"Linha {idx}: Entidade 971007 requer fonte 541")

        elif rd == 'D':
            if fonte not in ['483','31H','488'] and medida != "'022":
                erros.append(f"Linha {idx}: Medida deve ser '022' (exceto fontes 483,31H,488)")
            if org == '101904000':
                if pd.notna(projeto) and str(projeto).strip():
                    if atividade != '000':
                        erros.append(f"Linha {idx}: Projeto preenchido → Atividade deve ser 000")
                else:
                    if atividade != '130':
                        erros.append(f"Linha {idx}: Projeto vazio → Atividade deve ser 130")
            if org == '108904000':
                if atividade != '000' or not (pd.notna(projeto) and str(projeto).strip()):
                    erros.append(f"Linha {idx}: Cl. Orgânica 108904000 → Atividade=000 e Projeto preenchido")
            if funcional != "'0730":
                erros.append(f"Linha {idx}: Cl. Funcional deve ser '0730")
        return erros

    def validar_documentos_co(df_in):
        errs = []
        df_co = df_in[df_in['Tipo'] == 'CO']
        for docid, grupo in df_co.groupby('DOCID'):
            debs = grupo[grupo['Conta'].astype(str).str.startswith(('0281','0282'))]
            creds = grupo[grupo['Conta'].astype(str).str.startswith('0272')]
            rubs_d = {extrair_rubrica(c) for c in debs['Conta']}
            for _, ln in creds.iterrows():
                rub = extrair_rubrica(ln['Conta'])
                if rub not in rubs_d:
                    errs.append(f"DOCID {docid}: sem débito para rubrica {rub}")
        return errs

    # Processar cada ficheiro
    for idx_file, ficheiro in enumerate(uploaded, start=1):
        df = None
        nome = ficheiro.name
        try:
            df = pd.read_csv(
                ficheiro,
                sep=';',
                encoding='ISO-8859-1',
                header=9,
                names=CABECALHOS,
                dtype=str,
                low_memory=False
            )
            log.append(f"✔️ Lido {nome} ({len(df)} linhas).")
        except Exception as e:
            log.append(f"❌ Erro a ler {nome}: {e}")
            continue

        # filtrar "Saldo Inicial"
        df = df[~df['Data Contab.'].astype(str).str.contains("Saldo Inicial", na=False)]
        total_linhas += len(df)

        # Validar linhas
        erros_linha = []
        for i, row in df.iterrows():
            msgs = validar_linha(i, row)
            for m in msgs:
                resumo_erros[m] += 1
            erros_linha += msgs

        # Validar documentos CO
        msgs_co = validar_documentos_co(df)
        for m in msgs_co:
            resumo_erros[m] += 1
        erros_linha += msgs_co

        # Se houve erros, gerar excel de erros
        if erros_linha:
            # extrair índices corretos
            indices = []
            for m in erros_linha:
                if m.startswith("Linha"):
                    # "Linha 3: ..." → ["Linha 3", "..."] → "Linha 3" → split()[1] = "3"
                    numero = m.split(":", 1)[0].split()[1]
                    indices.append(int(numero))
            df_err = df.loc[indices].copy()
            df_err['Erro'] = erros_linha
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_out = f"{nome.rstrip('.csv')}_erros_{timestamp}.xlsx"
            df_err.to_excel(nome_out, index=False)
            log.append(f"⚠️ {nome}: {len(erros_linha)} erro(s); gerado {nome_out}")
        else:
            log.append(f"✅ {nome}: nenhum erro encontrado.")

        progresso.progress(idx_file / total_files)

    # Mostrar log e resumo
    st.subheader("📋 Log de processamento")
    st.text("\n".join(log))

    st.subheader("📊 Resumo de Erros")
    if resumo_erros:
        df_resumo = pd.DataFrame(
            resumo_erros.items(), columns=['Regra', 'Ocorrências']
        ).sort_values('Ocorrências', ascending=False)
        st.table(df_resumo)
    st.write(f"Total de linhas validadas: {total_linhas}")

else:
    st.info("Carrega até 5 ficheiros CSV usando o uploader acima.")
