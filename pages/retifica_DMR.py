from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

import pandas as pd
import streamlit as st


# ===================== POSIÇÕES CORRETAS DMR TXT =====================
# Python usa posições 0-based e fim exclusivo.

POS_NIF_INI = 10
POS_NIF_FIM = 19

POS_REND_INI = 39
POS_REND_FIM = 53

POS_CAT_INI = 53
POS_CAT_FIM = 56

POS_IRS_INI = 59
POS_IRS_FIM = 72


# ===================== FUNÇÕES =====================

def descobrir_folhas_excel(excel_file):
    excel_file.seek(0)
    return pd.ExcelFile(excel_file).sheet_names


def decimal_seguro(valor) -> Decimal:
    if pd.isna(valor):
        return Decimal("0")

    texto = str(valor).strip()

    if texto == "":
        return Decimal("0")

    if texto.lower() in {"valor", "irs", "rendimento", "nif"}:
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
        raise ValueError(
            f"Campo numérico inválido no TXT: {raw!r} nas posições {ini + 1}-{fim}"
        )

    return Decimal(sinal) * (Decimal(raw) / Decimal("100"))


def formatar_decimal_txt(valor: Decimal, tamanho: int, com_sinal: bool = True) -> str:
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    sinal = "+"
    if valor < 0:
        sinal = "-"
        valor = abs(valor)

    valor_centimos = int(valor * 100)

    if com_sinal:
        return sinal + str(valor_centimos).zfill(tamanho - 1)

    return str(valor_centimos).zfill(tamanho)


def substituir_intervalo(linha: str, ini: int, fim: int, novo: str) -> str:
    tamanho = fim - ini

    if len(novo) != tamanho:
        raise ValueError(
            f"Novo valor com tamanho errado. Esperado {tamanho}, obtido {len(novo)}: {novo}"
        )

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

        nif = linha[POS_NIF_INI:POS_NIF_FIM].strip()
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
                "linha": linha,
                "nif": nif.zfill(9),
                "categoria": categoria.strip(),
                "rendimento": rendimento,
                "irs": irs,
            }
        )

    return linhas, linhas_006


def ler_pendentes_excel(excel_file, sheet_name=None):
    excel_file.seek(0)

    df = pd.read_excel(
        excel_file,
        sheet_name=sheet_name,
        header=0,
    )

    df.columns = [str(c).strip() for c in df.columns]

    colunas_necessarias = ["NIF", "Rendimento", "Valor", "IRS"]
    em_falta = [c for c in colunas_necessarias if c not in df.columns]

    if em_falta:
        raise ValueError(
            "O Excel não tem as colunas esperadas. "
            f"Faltam: {', '.join(em_falta)}. "
            "O ficheiro deve ter: NIF, Rendimento, Valor, IRS."
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
    pendentes_out["Estado"] = ""
    pendentes_out["Rendimento DMR Antes"] = ""
    pendentes_out["Rendimento DMR Depois"] = ""
    pendentes_out["IRS DMR Antes"] = ""
    pendentes_out["IRS DMR Depois"] = ""
    pendentes_out["Categoria DMR"] = ""

    mapa_dmr = {}

    for item in linhas_006:
        mapa_dmr.setdefault(item["nif"], []).append(item)

    for i, row in pendentes_df.iterrows():
        nif = str(row["NIF"]).strip().zfill(9)
        valor_excel = row["Valor_Decimal"]
        irs_excel = row["IRS_Decimal"]

        if nif not in mapa_dmr:
            estado = "NIF não encontrado na DMR com categoria A válida"

            resultados.append(
                {
                    "NIF": nif,
                    "Estado": estado,
                    "Valor Excel": valor_excel,
                    "IRS Excel": irs_excel,
                }
            )

            pendentes_out.at[i, "Estado"] = estado
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

        novo_rendimento_txt = formatar_decimal_txt(
            rendimento_depois,
            POS_REND_FIM - POS_REND_INI,
            com_sinal=True,
        )

        novo_irs_txt = formatar_decimal_txt(
            irs_depois,
            POS_IRS_FIM - POS_IRS_INI,
            com_sinal=True,
        )

        linha = substituir_intervalo(
            linha,
            POS_REND_INI,
            POS_REND_FIM,
            novo_rendimento_txt,
        )

        linha = substituir_intervalo(
            linha,
            POS_IRS_INI,
            POS_IRS_FIM,
            novo_irs_txt,
        )

        linhas_corrigidas[idx] = linha

        estado = "Corrigido"

        resultados.append(
            {
                "NIF": nif,
                "Estado": estado,
                "Categoria DMR": item["categoria"],
                "Valor Excel": valor_excel,
                "IRS Excel": irs_excel,
                "Rendimento Antes": rendimento_antes,
                "Rendimento Depois": rendimento_depois,
                "IRS Antes": irs_antes,
                "IRS Depois": irs_depois,
            }
        )

        pendentes_out.at[i, "Estado"] = estado
        pendentes_out.at[i, "Rendimento DMR Antes"] = rendimento_antes
        pendentes_out.at[i, "Rendimento DMR Depois"] = rendimento_depois
        pendentes_out.at[i, "IRS DMR Antes"] = irs_antes
        pendentes_out.at[i, "IRS DMR Depois"] = irs_depois
        pendentes_out.at[i, "Categoria DMR"] = item["categoria"]

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

st.info(
    "Carregue o ficheiro TXT da DMR e o Excel com pendentes. "
    "Depois clique em Processar ficheiros."
)

with st.expander("Posições usadas no TXT da DMR", expanded=True):
    st.markdown(
        f"""
- **NIF**: posições `{POS_NIF_INI}:{POS_NIF_FIM}`
- **Rendimento**: posições `{POS_REND_INI}:{POS_REND_FIM}`
- **Categoria**: posições `{POS_CAT_INI}:{POS_CAT_FIM}`
- **IRS**: posições `{POS_IRS_INI}:{POS_IRS_FIM}`

Exemplo validado:
- `00000000314719` → `3147,19`
- `0000000067600` → `676,00`

Regras:
- Só são consideradas linhas começadas por `006`.
- A categoria tem de começar por `A`.
- A categoria `A21` é excluída.
- Os valores do Excel já vêm negativos.
- O valor do Excel é somado ao valor da DMR, reduzindo rendimento e IRS.
- O novo rendimento e o novo IRS nunca ficam negativos.
"""
    )

st.subheader("1. Carregar ficheiros")

col1, col2 = st.columns(2)

with col1:
    dmr_file = st.file_uploader(
        "Carregue aqui o ficheiro TXT da DMR",
        type=["txt"],
    )

with col2:
    excel_file = st.file_uploader(
        "Carregue aqui o ficheiro Excel com pendentes",
        type=["xlsx", "xls"],
    )

sheet_name = None

if excel_file is not None:
    try:
        folhas = descobrir_folhas_excel(excel_file)

        if folhas:
            sheet_name = st.selectbox(
                "Escolha a folha do Excel",
                options=folhas,
                index=0,
            )

    except Exception as e:
        st.warning(f"Não foi possível listar as folhas do Excel: {e}")

st.subheader("2. Processar")

if st.button("Processar ficheiros", type="primary"):
    try:
        if dmr_file is None:
            st.error("Tem de carregar o ficheiro TXT da DMR.")
            st.stop()

        if excel_file is None:
            st.error("Tem de carregar o ficheiro Excel com pendentes.")
            st.stop()

        with st.spinner("A processar ficheiros..."):
            linhas_originais, linhas_006 = ler_dmr_txt(dmr_file)

            pendentes_df = ler_pendentes_excel(
                excel_file,
                sheet_name=sheet_name,
            )

            resultados_df, pendentes_out, dmr_corrigida_txt = aplicar_retificacoes(
                linhas_originais,
                linhas_006,
                pendentes_df,
            )

        st.success("Processamento concluído.")

        total_pendentes = len(pendentes_out)
        total_corrigidos = 0
        total_erro = 0

        if not resultados_df.empty and "Estado" in resultados_df.columns:
            total_corrigidos = int((resultados_df["Estado"] == "Corrigido").sum())
            total_erro = int((resultados_df["Estado"] != "Corrigido").sum())

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Linhas no Excel", total_pendentes)
        m2.metric("Linhas 006 categoria A válida", len(linhas_006))
        m3.metric("Corrigidas", total_corrigidos)
        m4.metric("Com erro / validação", total_erro)

        st.subheader("Resumo das alterações")

        if resultados_df.empty:
            st.info("Não foram encontrados registos para apresentar.")
        else:
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
                label="Descarregar DMR corrigida TXT",
                data=dmr_bytes,
                file_name="DMR_corrigida.txt",
                mime="text/plain",
            )

        with dl2:
            st.download_button(
                label="Descarregar Excel atualizado",
                data=excel_bytes,
                file_name="pendentes_atualizado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"Erro ao processar ficheiros: {e}")
