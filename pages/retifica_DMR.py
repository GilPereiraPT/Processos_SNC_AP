import io
import os
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Retificação DMR", page_icon="📄", layout="wide")


# =========================================================
# CONFIG
# =========================================================

DEFAULT_ENCODING_CSV = "utf-8-sig"
ESTADOS_FINAIS_OK = ["Alterado", "Não encontrado", "Ignorado"]
TIPOS_EXCEL_SUPORTADOS = [".xlsx", ".xls", ".csv"]
TIPOS_DMR_SUPORTADOS = [".xlsx", ".xls", ".csv"]


# =========================================================
# UTILITÁRIOS
# =========================================================

def normalizar_texto(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def normalizar_nif(v):
    s = normalizar_texto(v)
    s = "".join(ch for ch in s if ch.isdigit())
    return s


def excel_col_letter_to_index(letter):
    """
    Converte letra Excel (A, B, C, AA) para índice 0-based.
    """
    letter = normalizar_texto(letter).upper()
    if not letter:
        raise ValueError("Letra de coluna inválida.")

    total = 0
    for ch in letter:
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"Letra de coluna inválida: {letter}")
        total = total * 26 + (ord(ch) - ord("A") + 1)
    return total - 1


def maybe_get_column_by_excel_letter(df, excel_letter_or_name):
    """
    Se o valor existir como nome da coluna, usa-o.
    Caso contrário, tenta interpretá-lo como letra Excel.
    """
    s = normalizar_texto(excel_letter_or_name)
    if s in df.columns:
        return s

    try:
        idx = excel_col_letter_to_index(s)
        if idx < 0 or idx >= len(df.columns):
            raise ValueError
        return df.columns[idx]
    except Exception:
        raise ValueError(f"Não foi possível resolver a coluna '{excel_letter_or_name}'.")


def parse_decimal_pt(value):
    """
    Aceita números PT:
    - 100,05
    - 1.234,56
    - -100,00
    - (100,00)
    Também lida com float/int já lidos pelo pandas.
    """
    if pd.isna(value):
        return Decimal("0")

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    s = str(value).strip()

    if s == "":
        return Decimal("0")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    s = s.replace(" ", "")
    s = s.replace("\u00A0", "")

    # remove separador de milhar e troca decimal PT
    # ex: 1.234,56 -> 1234.56
    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        # pode vir já em formato internacional
        pass

    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Valor numérico inválido: {value}")

    if negative:
        d = -d

    return d


def decimal_to_pt_str(d):
    """
    Formata Decimal em PT: 1234.56 -> 1.234,56
    """
    if d is None:
        return ""

    d = Decimal(d).quantize(Decimal("0.01"))
    s = f"{d:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def decimal_to_float(d):
    return float(Decimal(d))


def ler_ficheiro_tabular(uploaded_file, sheet_name=None):
    """
    Lê CSV ou Excel para DataFrame.
    """
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        # tenta UTF-8-SIG; se falhar, Latin-1
        uploaded_file.seek(0)
        try:
            return pd.read_csv(uploaded_file, dtype=object, encoding="utf-8-sig")
        except Exception:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, dtype=object, encoding="latin1", sep=None, engine="python")

    if name.endswith(".xlsx") or name.endswith(".xls"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, sheet_name=sheet_name, dtype=object)

    raise ValueError(f"Formato não suportado: {uploaded_file.name}")


def listar_sheets_excel(uploaded_file):
    name = uploaded_file.name.lower()
    if not (name.endswith(".xlsx") or name.endswith(".xls")):
        return []

    uploaded_file.seek(0)
    xls = pd.ExcelFile(uploaded_file)
    return xls.sheet_names


def garantir_coluna(df, col_name, default=""):
    if col_name not in df.columns:
        df[col_name] = default
    return df


def criar_bytes_excel(dfs_by_sheet):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dfs_by_sheet.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    output.seek(0)
    return output.getvalue()


def criar_zip_ficheiros(files_dict):
    """
    files_dict = {filename: bytes}
    """
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files_dict.items():
            zf.writestr(filename, content)
    mem.seek(0)
    return mem.getvalue()


# =========================================================
# LÓGICA DE NEGÓCIO
# =========================================================

def encontrar_linhas_nif_categoria_a(
    dmr_df,
    col_nif_dmr,
    col_tipo_dmr,
    nif,
    excluir_tipos=None,
):
    """
    Procura linhas do NIF cuja coluna de tipo/código comece por A
    e não esteja na lista de exclusão.
    """
    excluir_tipos = set((excluir_tipos or []))

    mask_nif = dmr_df[col_nif_dmr].astype(str).map(normalizar_nif) == nif
    tipos = dmr_df[col_tipo_dmr].astype(str).map(lambda x: normalizar_texto(x).upper())

    mask_categoria_a = tipos.str.startswith("A", na=False)
    mask_excluir = tipos.isin({t.upper() for t in excluir_tipos})

    res = dmr_df[mask_nif & mask_categoria_a & (~mask_excluir)].copy()
    return res


def processar_retificacao(
    dmr_df,
    pendentes_df,
    *,
    col_nif_dmr,
    col_tipo_dmr,
    col_valor_dmr,
    col_irs_dmr,
    col_nif_pend,
    col_valor_pend,
    col_irs_pend,
    excluir_tipos=None,
):
    """
    Regras:
    - NIF do Excel pendente procura linha DMR do mesmo NIF com categoria A
    - A21 não serve, se estiver em excluir_tipos
    - valor e IRS do Excel já estão negativos
    - o novo valor = valor_dmr + valor_excel
    - o novo IRS = irs_dmr + irs_excel
    - nunca pode ficar negativo
    """
    excluir_tipos = excluir_tipos or []

    dmr_out = dmr_df.copy()
    pend_out = pendentes_df.copy()

    garantir_coluna(pend_out, "Estado", "")
    garantir_coluna(pend_out, "Mensagem", "")
    garantir_coluna(pend_out, "Linha_DMR", "")
    garantir_coluna(pend_out, "Tipo_Rendimento_DMR", "")
    garantir_coluna(pend_out, "Valor_DMR_Original", "")
    garantir_coluna(pend_out, "IRS_DMR_Original", "")
    garantir_coluna(pend_out, "Valor_DMR_Novo", "")
    garantir_coluna(pend_out, "IRS_DMR_Novo", "")

    log_rows = []

    alterados = 0
    nao_encontrados = 0
    ignorados = 0
    com_erro = 0

    for idx_p, row_p in pend_out.iterrows():
        try:
            nif = normalizar_nif(row_p[col_nif_pend])
            valor_ajuste = parse_decimal_pt(row_p[col_valor_pend])
            irs_ajuste = parse_decimal_pt(row_p[col_irs_pend])

            if nif == "":
                pend_out.at[idx_p, "Estado"] = "Ignorado"
                pend_out.at[idx_p, "Mensagem"] = "NIF vazio."
                ignorados += 1
                continue

            candidatos = encontrar_linhas_nif_categoria_a(
                dmr_out,
                col_nif_dmr=col_nif_dmr,
                col_tipo_dmr=col_tipo_dmr,
                nif=nif,
                excluir_tipos=excluir_tipos,
            )

            if candidatos.empty:
                pend_out.at[idx_p, "Estado"] = "Não encontrado"
                pend_out.at[idx_p, "Mensagem"] = "NIF sem linha elegível de categoria A na DMR."
                nao_encontrados += 1
                continue

            # Se houver várias linhas, tenta escolher a primeira com saldo suficiente
            linha_escolhida = None
            msg_validacao = ""

            for idx_d, row_d in candidatos.iterrows():
                valor_dmr = parse_decimal_pt(row_d[col_valor_dmr])
                irs_dmr = parse_decimal_pt(row_d[col_irs_dmr])

                novo_valor = valor_dmr + valor_ajuste
                novo_irs = irs_dmr + irs_ajuste

                if novo_valor < 0:
                    msg_validacao = (
                        f"Valor insuficiente na DMR. Atual={decimal_to_pt_str(valor_dmr)}, "
                        f"ajuste={decimal_to_pt_str(valor_ajuste)}, novo={decimal_to_pt_str(novo_valor)}."
                    )
                    continue

                if novo_irs < 0:
                    msg_validacao = (
                        f"IRS insuficiente na DMR. Atual={decimal_to_pt_str(irs_dmr)}, "
                        f"ajuste={decimal_to_pt_str(irs_ajuste)}, novo={decimal_to_pt_str(novo_irs)}."
                    )
                    continue

                linha_escolhida = (idx_d, row_d, valor_dmr, irs_dmr, novo_valor, novo_irs)
                break

            if linha_escolhida is None:
                pend_out.at[idx_p, "Estado"] = "Erro"
                pend_out.at[idx_p, "Mensagem"] = msg_validacao or "Sem linha DMR com saldo suficiente."
                com_erro += 1
                continue

            idx_d, row_d, valor_dmr, irs_dmr, novo_valor, novo_irs = linha_escolhida

            dmr_out.at[idx_d, col_valor_dmr] = decimal_to_float(novo_valor)
            dmr_out.at[idx_d, col_irs_dmr] = decimal_to_float(novo_irs)

            pend_out.at[idx_p, "Estado"] = "Alterado"
            pend_out.at[idx_p, "Mensagem"] = "DMR atualizada com sucesso."
            pend_out.at[idx_p, "Linha_DMR"] = int(idx_d) + 2  # +2 considerando header Excel
            pend_out.at[idx_p, "Tipo_Rendimento_DMR"] = normalizar_texto(row_d[col_tipo_dmr])
            pend_out.at[idx_p, "Valor_DMR_Original"] = decimal_to_float(valor_dmr)
            pend_out.at[idx_p, "IRS_DMR_Original"] = decimal_to_float(irs_dmr)
            pend_out.at[idx_p, "Valor_DMR_Novo"] = decimal_to_float(novo_valor)
            pend_out.at[idx_p, "IRS_DMR_Novo"] = decimal_to_float(novo_irs)

            log_rows.append({
                "Linha_Pendente": int(idx_p) + 2,
                "NIF": nif,
                "Linha_DMR": int(idx_d) + 2,
                "Tipo_Rendimento": normalizar_texto(row_d[col_tipo_dmr]),
                "Valor_DMR_Original": decimal_to_float(valor_dmr),
                "Valor_Ajuste": decimal_to_float(valor_ajuste),
                "Valor_DMR_Novo": decimal_to_float(novo_valor),
                "IRS_DMR_Original": decimal_to_float(irs_dmr),
                "IRS_Ajuste": decimal_to_float(irs_ajuste),
                "IRS_DMR_Novo": decimal_to_float(novo_irs),
                "Estado": "Alterado",
            })

            alterados += 1

        except Exception as e:
            pend_out.at[idx_p, "Estado"] = "Erro"
            pend_out.at[idx_p, "Mensagem"] = str(e)
            com_erro += 1

    resumo = {
        "Pendentes lidos": len(pend_out),
        "Alterados": alterados,
        "Não encontrados": nao_encontrados,
        "Ignorados": ignorados,
        "Com erro / validação": com_erro,
    }

    log_df = pd.DataFrame(log_rows)

    return dmr_out, pend_out, log_df, resumo


# =========================================================
# UI
# =========================================================

st.title("Retificação de DMR")
st.caption("Submeta a DMR e o ficheiro com situações pendentes para gerar uma DMR corrigida, o Excel atualizado e um resumo das alterações.")

with st.expander("Regras aplicadas", expanded=False):
    st.markdown(
        """
- É usado o **NIF** do ficheiro de pendentes.
- Procura-se na **DMR** uma linha do mesmo NIF com **categoria A**.
- Tipos excluídos, como **A21**, podem ser definidos.
- O **Valor** e o **IRS** do ficheiro de pendentes já podem vir a negativo.
- O novo cálculo é:
  - **Novo Valor DMR = Valor DMR + Valor pendente**
  - **Novo IRS DMR = IRS DMR + IRS pendente**
- Os novos valores da DMR **não podem ficar negativos**.
"""
    )

col_up1, col_up2 = st.columns(2)

with col_up1:
    dmr_file = st.file_uploader("Ficheiro DMR", type=[x.replace(".", "") for x in TIPOS_DMR_SUPORTADOS], key="dmr")

with col_up2:
    pend_file = st.file_uploader("Ficheiro de pendentes", type=[x.replace(".", "") for x in TIPOS_EXCEL_SUPORTADOS], key="pend")


if dmr_file and pend_file:
    st.divider()

    # Sheets
    dmr_sheets = listar_sheets_excel(dmr_file)
    pend_sheets = listar_sheets_excel(pend_file)

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        dmr_sheet = st.selectbox("Folha da DMR", options=dmr_sheets if dmr_sheets else [None], index=0)
    with col_s2:
        pend_sheet = st.selectbox("Folha dos pendentes", options=pend_sheets if pend_sheets else [None], index=0)

    try:
        dmr_df = ler_ficheiro_tabular(dmr_file, sheet_name=dmr_sheet)
        pend_df = ler_ficheiro_tabular(pend_file, sheet_name=pend_sheet)
    except Exception as e:
        st.error(f"Erro ao ler os ficheiros: {e}")
        st.stop()

    st.subheader("Pré-visualização")

    tab_prev1, tab_prev2 = st.tabs(["DMR", "Pendentes"])
    with tab_prev1:
        st.dataframe(dmr_df.head(20), use_container_width=True)
    with tab_prev2:
        st.dataframe(pend_df.head(20), use_container_width=True)

    st.subheader("Mapeamento de colunas")

    dmr_cols = list(dmr_df.columns)
    pend_cols = list(pend_df.columns)

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**DMR**")
        col_nif_dmr = st.selectbox("Coluna NIF (DMR)", dmr_cols, index=0 if dmr_cols else None)
        col_tipo_dmr = st.selectbox("Coluna Tipo/Código rendimento (DMR)", dmr_cols, index=min(1, len(dmr_cols)-1) if dmr_cols else None)
        col_valor_dmr = st.selectbox("Coluna Valor rendimento (DMR)", dmr_cols, index=min(2, len(dmr_cols)-1) if dmr_cols else None)
        col_irs_dmr = st.selectbox("Coluna IRS (DMR)", dmr_cols, index=min(3, len(dmr_cols)-1) if dmr_cols else None)

    with c2:
        st.markdown("**Pendentes**")
        col_nif_pend = st.selectbox("Coluna NIF (Pendentes)", pend_cols, index=0 if pend_cols else None)
        col_valor_pend = st.selectbox("Coluna Valor (Pendentes)", pend_cols, index=min(2, len(pend_cols)-1) if pend_cols else None)
        col_irs_pend = st.selectbox("Coluna IRS (Pendentes)", pend_cols, index=min(3, len(pend_cols)-1) if pend_cols else None)

    st.subheader("Opções")

    excluir_tipos_raw = st.text_input(
        "Tipos a excluir da DMR",
        value="A21",
        help="Separar por vírgulas. Ex.: A21, A30"
    )
    excluir_tipos = [x.strip().upper() for x in excluir_tipos_raw.split(",") if x.strip()]

    if st.button("Processar retificação", type="primary"):
        try:
            dmr_out, pendentes_out, log_df, resumo = processar_retificacao(
                dmr_df=dmr_df,
                pendentes_df=pend_df,
                col_nif_dmr=col_nif_dmr,
                col_tipo_dmr=col_tipo_dmr,
                col_valor_dmr=col_valor_dmr,
                col_irs_dmr=col_irs_dmr,
                col_nif_pend=col_nif_pend,
                col_valor_pend=col_valor_pend,
                col_irs_pend=col_irs_pend,
                excluir_tipos=excluir_tipos,
            )

            st.success("Processamento concluído.")

            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                st.metric("Pendentes lidos", resumo["Pendentes lidos"])

            with col2:
                st.metric("Alterados", resumo["Alterados"])

            with col3:
                st.metric("Não encontrados", resumo["Não encontrados"])

            with col4:
                st.metric("Ignorados", resumo["Ignorados"])

            with col5:
                st.metric("Com erro / validação", resumo["Com erro / validação"])

            tab1, tab2, tab3 = st.tabs(["Pendentes atualizados", "DMR corrigida", "Log"])

            with tab1:
                st.dataframe(pendentes_out, use_container_width=True)

            with tab2:
                st.dataframe(dmr_out, use_container_width=True)

            with tab3:
                if log_df.empty:
                    st.info("Não existem alterações registadas.")
                else:
                    st.dataframe(log_df, use_container_width=True)

            # Preparar downloads
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            dmr_bytes = criar_bytes_excel({"DMR_Corrigida": dmr_out})
            pend_bytes = criar_bytes_excel({"Pendentes_Atualizados": pendentes_out})
            log_bytes = criar_bytes_excel({"Log_Alteracoes": log_df if not log_df.empty else pd.DataFrame([{"Info": "Sem alterações"}])})
            resumo_bytes = criar_bytes_excel({"Resumo": pd.DataFrame([resumo])})

            zip_bytes = criar_zip_ficheiros({
                f"DMR_corrigida_{timestamp}.xlsx": dmr_bytes,
                f"Pendentes_atualizados_{timestamp}.xlsx": pend_bytes,
                f"Log_alteracoes_{timestamp}.xlsx": log_bytes,
                f"Resumo_{timestamp}.xlsx": resumo_bytes,
            })

            st.subheader("Downloads")

            d1, d2, d3, d4, d5 = st.columns(5)

            with d1:
                st.download_button(
                    "Descarregar DMR corrigida",
                    data=dmr_bytes,
                    file_name=f"DMR_corrigida_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            with d2:
                st.download_button(
                    "Descarregar pendentes",
                    data=pend_bytes,
                    file_name=f"Pendentes_atualizados_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            with d3:
                st.download_button(
                    "Descarregar log",
                    data=log_bytes,
                    file_name=f"Log_alteracoes_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            with d4:
                st.download_button(
                    "Descarregar resumo",
                    data=resumo_bytes,
                    file_name=f"Resumo_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            with d5:
                st.download_button(
                    "Descarregar ZIP completo",
                    data=zip_bytes,
                    file_name=f"retificacao_dmr_{timestamp}.zip",
                    mime="application/zip",
                )

        except Exception as e:
            st.error(f"Erro ao processar ficheiros: {e}")
else:
    st.info("Carregue os dois ficheiros para continuar.")
