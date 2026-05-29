from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

import pandas as pd
import streamlit as st


POS_NIF_INI = 10
POS_NIF_FIM = 19

POS_REND_INI = 39
POS_REND_FIM = 53

POS_CAT_INI = 53
POS_CAT_FIM = 56

POS_IRS_INI = 59
POS_IRS_FIM = 72


def descobrir_folhas_excel(excel_file):
    excel_file.seek(0)
    return pd.ExcelFile(excel_file).sheet_names


def decimal_seguro(valor) -> Decimal:
    if pd.isna(valor):
        return Decimal("0")

    texto = str(valor).strip()

    if texto == "" or texto.lower() in {"valor", "irs", "rendimento", "nif"}:
        return Decimal("0")

    texto = texto.replace("€", "").replace(" ", "")

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"Valor decimal inválido: {valor!r}")


def ler_valor_txt(linha: str, ini: int, fim: int) -> Decimal:
    raw = linha[ini:fim].strip()

    if raw == "":
        return Decimal("0")

    sinal = 1

    if raw.startswith("+"):
        raw = raw[1:]
    elif raw.startswith("-"):
        sinal = -1
        raw = raw[1:]

    if not raw.isdigit():
        raise ValueError(f"Campo numérico inválido no TXT: {raw!r}")

    return Decimal(sinal) * (Decimal(raw) / Decimal("100"))


def formatar_decimal_txt(valor: Decimal, tamanho: int) -> str:
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    sinal = "+"
    if valor < 0:
        sinal = "-"
        valor = abs(valor)

    return sinal + str(int(valor * 100)).zfill(tamanho - 1)


def substituir_intervalo(linha: str, ini: int, fim: int, novo: str) -> str:
    if len(novo) != fim - ini:
        raise ValueError(f"Novo valor com tamanho errado: {novo}")

    return linha[:ini] + novo + linha[fim:]


def categoria_valida(categoria: str) -> bool:
    categoria = str(categoria).strip().upper()
    return categoria.startswith("A") and categoria != "A21"


def ler_dmr_txt(dmr_file):
    dmr_file.seek(0)
    conteudo = dmr_file.read()

    if isinstance(conteudo, bytes):
        try:
            texto = conteudo.decode("utf-8")
        except UnicodeDecodeError:
            texto = conteudo.decode("latin-1")
    else:
        texto = conteudo

    linhas = texto.splitlines()
    linhas_006 = []

    for idx, linha in enumerate(linhas):
        if not linha.startswith("006"):
            continue

        if len(linha) < POS_IRS_FIM:
            continue

        nif = linha[POS_NIF_INI:POS_NIF_FIM].strip().zfill(9)
        categoria = linha[POS_CAT_INI:POS_CAT_FIM]

        if not categoria_valida(categoria):
            continue

        try:
            rendimento = ler_valor_txt(linha, POS_REND_INI, POS_REND_FIM)
            irs = ler_valor_txt(linha, POS_IRS_INI, POS_IRS_FIM)
        except Exception:
            continue

        linhas_006.append(
            {
                "idx": idx,
                "nif": nif,
                "categoria": categoria.strip(),
                "rendimento": rendimento,
                "irs": irs,
            }
        )

    return linhas, linhas_006


def ler_pendentes_excel(excel_file, sheet_name=None):
    excel_file.seek(0)

    df = pd.read_excel(excel_file, sheet_name=sheet_name, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    colunas_necessarias = ["NIF", "Rendimento", "Valor", "IRS"]
    em_falta = [c for c in colunas_necessarias if c not in df.columns]

    if em_falta:
        raise ValueError(
            f"O Excel não tem as colunas esperadas. Faltam: {', '.join(em_falta)}"
        )

    df = df.dropna(how="all").copy()

    df = df[df["NIF"].astype(str).str.strip().str.lower() != "nif"]
    df = df[df["Valor"].astype(str).str.strip().str.lower() != "valor"]
    df = df[df["IRS"].astype(str).str.strip().str.lower() != "irs"]

    df["NIF"] = (
        df["NIF"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .str.zfill(9)
    )

    df["Categoria"] = df["Rendimento"].astype(str).str.strip().str.upper()
    df = df[df["Categoria"].apply(categoria_valida)]

    df["Valor_Decimal"] = df["Valor"].apply(decimal_seguro)
    df["IRS_Decimal"] = df["IRS"].apply(decimal_seguro)

    return df.reset_index(drop=True)


def aplicar_retificacoes(linhas_originais, linhas_006, pendentes_df):
    linhas_corrigidas = list(linhas_originais)
    resultados = []

    pendentes_out = pendentes_df.copy()

    pendentes_out["Estado"] = pd.Series(dtype="object")
    pendentes_out["Rendimento DMR Antes"] = pd.Series(dtype="object")
    pendentes_out["Rendimento DMR Depois"] = pd.Series(dtype="object")
    pendentes_out["IRS DMR Antes"] = pd.Series(dtype="object")
    pendentes_out["IRS DMR Depois"] = pd.Series(dtype="object")
    pendentes_out["Categoria DMR"] = pd.Series(dtype="object")

    mapa_dmr = {}
    for item in linhas_006:
        mapa_dmr.setdefault(item["nif"], []).append(item)

    for i, row in pendentes_df.iterrows():
        nif = str(row["NIF"]).strip().zfill(9)
        valor_excel = row["Valor_Decimal"]
        irs_excel = row["IRS_Decimal"]

        if nif not in mapa_dmr:
            estado = "NIF não encontrado na DMR com categoria A válida"
            pendentes_out.at[i, "Estado"] = estado

            resultados.append(
                {
                    "NIF": nif,
                    "Estado": estado,
                    "Valor Excel": str(valor_excel),
                    "IRS Excel": str(irs_excel),
                }
            )
            continue

        item = mapa_dmr[nif][0]
        idx = item["idx"]
        linha = linhas_corrigidas[idx]

        rendimento_antes = ler_valor_txt(linha, POS_REND_INI, POS_REND_FIM)
        irs_antes = ler_valor_txt(linha, POS_IRS_INI, POS_IRS_FIM)

        rendimento_depois = rendimento_antes + valor_excel
        irs_depois = irs_antes + irs_excel

        if rendimento_depois < 0:
            rendimento_depois = Decimal("0")

        if irs_depois < 0:
            irs_depois = Decimal("0")

        linha = substituir_intervalo(
            linha,
            POS_REND_INI,
            POS_REND_FIM,
            formatar_decimal_txt(rendimento_depois, POS_REND_FIM - POS_REND_INI),
        )

        linha = substituir_intervalo(
            linha,
            POS_IRS_INI,
            POS_IRS_FIM,
            formatar_decimal_txt(irs_depois, POS_IRS_FIM - POS_IRS_INI),
        )

        linhas_corrigidas[idx] = linha

        estado = "Corrigido"

        pendentes_out.at[i, "Estado"] = estado
        pendentes_out.at[i, "Rendimento DMR Antes"] = str(rendimento_antes)
        pendentes_out.at[i, "Rendimento DMR Depois"] = str(rendimento_depois)
        pendentes_out.at[i, "IRS DMR Antes"] = str(irs_antes)
        pendentes_out.at[i, "IRS DMR Depois"] = str(irs_depois)
        pendentes_out.at[i, "Categoria DMR"] = item["categoria"]

        resultados.append(
            {
                "NIF": nif,
                "Estado": estado,
                "Categoria DMR": item["categoria"],
                "Valor Excel": str(valor_excel),
                "IRS Excel": str(irs_excel),
                "Rendimento Antes": str(rendimento_antes),
                "Rendimento Depois": str(rendimento_depois),
                "IRS Antes": str(irs_antes),
                "IRS Depois": str(irs_depois),
            }
        )

    resultados_df = pd.DataFrame(resultados)

    for col in ["Valor_Decimal", "IRS_Decimal", "Categoria"]:
        if col in pendentes_out.columns:
            pendentes_out = pendentes_out.drop(columns=[col])

    dmr_corrigida_txt = "\n".join(linhas_corrigidas)

    return resultados_df, pendentes_out, dmr_corrigida_txt


def dataframe_to_excel_bytes(df):
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Pendentes Atualizado")

    output.seek(0)
    return output.getvalue()


# ===================== STREAMLIT =====================

st.set_page_config(page_title="Retificar DMR TXT", layout="wide")

st.title("Retificação de DMR em TXT")

st.info("Carregue o ficheiro TXT da DMR e o Excel com pendentes.")

with st.expander("Posições usadas no TXT da DMR", expanded=True):
    st.markdown(
        f"""
- **NIF**: `{POS_NIF_INI}:{POS_NIF_FIM}`
- **Rendimento**: `{POS_REND_INI}:{POS_REND_FIM}`
- **Categoria**: `{POS_CAT_INI}:{POS_CAT_FIM}`
- **IRS**: `{POS_IRS_INI}:{POS_IRS_FIM}`

Regras:
- Só são consideradas linhas começadas por `006`.
- A categoria tem de começar por `A`.
- A categoria `A21` é excluída.
- Os valores do Excel já vêm negativos.
- O novo rendimento e o novo IRS nunca ficam negativos.
"""
    )

col1, col2 = st.columns(2)

with col1:
    dmr_file = st.file_uploader("Ficheiro TXT da DMR", type=["txt"])

with col2:
    excel_file = st.file_uploader("Excel com pendentes", type=["xlsx", "xls"])

sheet_name = None

if excel_file is not None:
    try:
        folhas = descobrir_folhas_excel(excel_file)
        if folhas:
            sheet_name = st.selectbox("Folha do Excel", options=folhas, index=0)
    except Exception as e:
        st.warning(f"Não foi possível listar as folhas do Excel: {e}")

if st.button("Processar ficheiros", type="primary"):
    try:
        if dmr_file is None:
            st.error("Tem de carregar o ficheiro TXT da DMR.")
            st.stop()

        if excel_file is None:
            st.error("Tem de carregar o Excel com pendentes.")
            st.stop()

        with st.spinner("A processar..."):
            linhas_originais, linhas_006 = ler_dmr_txt(dmr_file)
            pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name)

            resultados_df, pendentes_out, dmr_corrigida_txt = aplicar_retificacoes(
                linhas_originais,
                linhas_006,
                pendentes_df,
            )

        st.success("Processamento concluído.")

        total_corrigidos = int((resultados_df["Estado"] == "Corrigido").sum()) if not resultados_df.empty else 0
        total_erro = int((resultados_df["Estado"] != "Corrigido").sum()) if not resultados_df.empty else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Linhas no Excel", len(pendentes_out))
        m2.metric("Linhas DMR válidas", len(linhas_006))
        m3.metric("Corrigidas", total_corrigidos)
        m4.metric("Com erro", total_erro)

        st.subheader("Resumo das alterações")
        st.dataframe(resultados_df, use_container_width=True)

        st.subheader("Excel atualizado")
        st.dataframe(pendentes_out, use_container_width=True)

        st.subheader("Pré-visualização da DMR corrigida")
        preview = "\n".join(dmr_corrigida_txt.splitlines()[:50])
        st.text_area("Primeiras 50 linhas", preview, height=400)

        excel_bytes = dataframe_to_excel_bytes(pendentes_out)
        dmr_bytes = dmr_corrigida_txt.encode("latin-1", errors="replace")

        dl1, dl2 = st.columns(2)

        with dl1:
            st.download_button(
                "Descarregar DMR corrigida TXT",
                data=dmr_bytes,
                file_name="DMR_corrigida.txt",
                mime="text/plain",
            )

        with dl2:
            st.download_button(
                "Descarregar Excel atualizado",
                data=excel_bytes,
                file_name="pendentes_atualizado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"Erro ao processar ficheiros: {e}")
