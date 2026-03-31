import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd


# =========================================================
# POSIÇÕES FIXAS DA DMR TXT (1-based, conforme indicado)
# =========================================================
# NIF: colunas 10-18
# Categoria rendimento: colunas 53-54  -> tem de ser "A "
# Rendimento: começa no sinal da coluna 38 e termina antes da coluna 53
# IRS: começa no sinal da coluna 58 e termina antes do sinal da coluna 73

DMR_NIF_START = 10
DMR_NIF_END = 19

DMR_CAT_START = 53
DMR_CAT_END = 55

DMR_REND_START = 38
DMR_REND_END = 53

DMR_IRS_START = 58
DMR_IRS_END = 73


# =========================================================
# UTILITÁRIOS NUMÉRICOS
# =========================================================
def decimal_2(v):
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_decimal_pt(value):
    if value is None:
        return Decimal("0.00")

    if isinstance(value, Decimal):
        return decimal_2(value)

    if isinstance(value, (int, float)):
        return decimal_2(str(value))

    s = str(value).strip()
    if s == "":
        return Decimal("0.00")

    # remove espaços
    s = s.replace(" ", "")

    # formato PT: 1.234,56
    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        # se vier "1234.56", mantém
        pass

    try:
        return decimal_2(Decimal(s))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor numérico inválido: {value}")


def decimal_to_field(value: Decimal, width: int) -> str:
    """
    Converte Decimal para formato DMR com sinal e 2 casas implícitas.
    Ex.: 643.87 -> +00000000064387  (width=15)
    """
    value = decimal_2(value)
    sign = "+" if value >= 0 else "-"
    cents = int((abs(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    digits_width = width - 1
    return f"{sign}{cents:0{digits_width}d}"


def field_to_decimal(field: str) -> Decimal:
    """
    Converte campo DMR com sinal e 2 casas implícitas.
    Ex.: +00000000064387 -> 643.87
    """
    s = (field or "").strip()
    if not s:
        return Decimal("0.00")

    sign = 1
    if s[0] == "-":
        sign = -1
        s = s[1:]
    elif s[0] == "+":
        s = s[1:]

    s = s.strip()
    s = s.lstrip("0")

    if s == "":
        return Decimal("0.00")

    cents = Decimal(s) / Decimal("100")
    return decimal_2(cents * sign)


# =========================================================
# LEITURA / NORMALIZAÇÃO EXCEL
# =========================================================
def normalizar_nif(valor):
    s = str(valor).strip()
    s = re.sub(r"\D", "", s)
    return s


def encontrar_coluna(cols, candidatos):
    normalizadas = {str(c).strip().lower(): c for c in cols}
    for cand in candidatos:
        c = normalizadas.get(cand.strip().lower())
        if c is not None:
            return c
    return None


def ler_pendentes_excel(excel_file, sheet_name=None):
    xls = pd.ExcelFile(excel_file)
    folha = sheet_name if sheet_name in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=folha)

    if not isinstance(df, pd.DataFrame):
        raise ValueError("Não foi possível ler a folha do Excel como tabela.")

    if df.empty:
        raise ValueError("A folha Excel está vazia.")

    cols = list(df.columns)

    # Procura flexível, mas se não encontrar usa as posições A/C/D
    col_nif = encontrar_coluna(cols, ["NIF", "Nif", "nif", "Contribuinte"])
    col_valor = encontrar_coluna(cols, ["Valor", "VALOR", "valor"])
    col_irs = encontrar_coluna(cols, ["IRS", "irs", "Retenção", "Retencao"])

    if col_nif is None and len(cols) >= 1:
        col_nif = cols[0]
    if col_valor is None and len(cols) >= 3:
        col_valor = cols[2]
    if col_irs is None and len(cols) >= 4:
        col_irs = cols[3]

    if col_nif is None or col_valor is None or col_irs is None:
        raise ValueError(
            "Não foi possível identificar as colunas necessárias no Excel. "
            "É esperado: coluna A=NIF, coluna C=Valor, coluna D=IRS."
        )

    out = df.copy()

    out["NIF"] = out[col_nif].apply(normalizar_nif)
    out["Valor"] = out[col_valor].apply(parse_decimal_pt)
    out["IRS"] = out[col_irs].apply(parse_decimal_pt)

    out["Estado"] = ""
    out["Mensagem"] = ""
    out["Linha_DMR"] = ""
    out["Categoria_DMR"] = ""
    out["Rendimento_Original_DMR"] = ""
    out["IRS_Original_DMR"] = ""
    out["Rendimento_Novo_DMR"] = ""
    out["IRS_Novo_DMR"] = ""

    return out


# =========================================================
# DMR TXT
# =========================================================
def ler_dmr_txt(file_obj):
    raw = file_obj.read()
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        text = str(raw)

    # preserva linhas
    linhas = text.splitlines()
    return linhas


def extrair_nif_linha_006(linha):
    return linha[DMR_NIF_START:DMR_NIF_END].strip()


def extrair_categoria_linha_006(linha):
    return linha[DMR_CAT_START:DMR_CAT_END]


def extrair_rendimento_linha_006(linha):
    return field_to_decimal(linha[DMR_REND_START:DMR_REND_END])


def extrair_irs_linha_006(linha):
    return field_to_decimal(linha[DMR_IRS_START:DMR_IRS_END])


def atualizar_campo_fixo(linha, start, end, novo_valor_decimal):
    width = end - start
    novo_campo = decimal_to_field(novo_valor_decimal, width)
    if len(novo_campo) != width:
        raise ValueError(
            f"Campo reconstruído com tamanho inválido: esperado {width}, obtido {len(novo_campo)}."
        )
    return linha[:start] + novo_campo + linha[end:]


def atualizar_linha_006(linha, novo_rendimento, novo_irs):
    linha2 = atualizar_campo_fixo(linha, DMR_REND_START, DMR_REND_END, novo_rendimento)
    linha2 = atualizar_campo_fixo(linha2, DMR_IRS_START, DMR_IRS_END, novo_irs)
    return linha2


def indexar_linhas_006(linhas):
    """
    Indexa linhas 006 elegíveis:
    - registo começa por 006
    - categoria exatamente "A "
    """
    idx = {}
    for i, linha in enumerate(linhas):
        if not linha.startswith("006"):
            continue

        if len(linha) < max(DMR_IRS_END, DMR_CAT_END):
            continue

        nif = extrair_nif_linha_006(linha)
        categoria = extrair_categoria_linha_006(linha)

        if categoria != "A ":
            continue

        idx.setdefault(nif, []).append(i)

    return idx


# =========================================================
# PROCESSAMENTO
# =========================================================
def processar_dmr_e_excel(dmr_file, excel_file, sheet_name=None):
    linhas = ler_dmr_txt(dmr_file)
    pendentes = ler_pendentes_excel(excel_file, sheet_name=sheet_name)
    idx_por_nif = indexar_linhas_006(linhas)

    resumo = []

    for r in pendentes.index:
        nif = pendentes.at[r, "NIF"]
        valor_excel = pendentes.at[r, "Valor"]
        irs_excel = pendentes.at[r, "IRS"]

        # Os valores no Excel já vêm negativos.
        # Ex.: -100 -> somar à DMR (diminuindo 100)
        if not nif:
            pendentes.at[r, "Estado"] = "Erro"
            pendentes.at[r, "Mensagem"] = "NIF vazio."
            continue

        if nif not in idx_por_nif:
            pendentes.at[r, "Estado"] = "Não encontrado"
            pendentes.at[r, "Mensagem"] = "NIF sem linha 006 com categoria 'A '."
            continue

        candidatos = idx_por_nif[nif]
        aplicado = False
        ultima_msg = ""

        for linha_idx in candidatos:
            linha = linhas[linha_idx]

            rendimento_atual = extrair_rendimento_linha_006(linha)
            irs_atual = extrair_irs_linha_006(linha)

            novo_rendimento = decimal_2(rendimento_atual + valor_excel)
            novo_irs = decimal_2(irs_atual + irs_excel)

            # Não pode ficar negativo
            if novo_rendimento < 0:
                ultima_msg = (
                    f"Rendimento insuficiente na linha {linha_idx + 1}: "
                    f"{rendimento_atual} + ({valor_excel}) < 0."
                )
                continue

            if novo_irs < 0:
                ultima_msg = (
                    f"IRS insuficiente na linha {linha_idx + 1}: "
                    f"{irs_atual} + ({irs_excel}) < 0."
                )
                continue

            nova_linha = atualizar_linha_006(linha, novo_rendimento, novo_irs)
            linhas[linha_idx] = nova_linha

            pendentes.at[r, "Estado"] = "Atualizado"
            pendentes.at[r, "Mensagem"] = "Linha DMR atualizada com sucesso."
            pendentes.at[r, "Linha_DMR"] = linha_idx + 1
            pendentes.at[r, "Categoria_DMR"] = extrair_categoria_linha_006(linha)
            pendentes.at[r, "Rendimento_Original_DMR"] = float(rendimento_atual)
            pendentes.at[r, "IRS_Original_DMR"] = float(irs_atual)
            pendentes.at[r, "Rendimento_Novo_DMR"] = float(novo_rendimento)
            pendentes.at[r, "IRS_Novo_DMR"] = float(novo_irs)

            resumo.append(
                {
                    "Linha_DMR": linha_idx + 1,
                    "NIF": nif,
                    "Categoria": "A ",
                    "Rendimento_Original": float(rendimento_atual),
                    "Valor_Excel": float(valor_excel),
                    "Rendimento_Novo": float(novo_rendimento),
                    "IRS_Original": float(irs_atual),
                    "IRS_Excel": float(irs_excel),
                    "IRS_Novo": float(novo_irs),
                }
            )

            aplicado = True
            break

        if not aplicado:
            pendentes.at[r, "Estado"] = "Erro"
            pendentes.at[r, "Mensagem"] = ultima_msg or "Nenhuma linha elegível conseguiu absorver a redução."

    dmr_corrigida = "\n".join(linhas)
    resumo_df = pd.DataFrame(resumo)

    if resumo_df.empty:
        resumo_df = pd.DataFrame(
            columns=[
                "Linha_DMR",
                "NIF",
                "Categoria",
                "Rendimento_Original",
                "Valor_Excel",
                "Rendimento_Novo",
                "IRS_Original",
                "IRS_Excel",
                "IRS_Novo",
            ]
        )

    return dmr_corrigida, pendentes, resumo_df


# =========================================================
# EXPORTAÇÕES
# =========================================================
def pendentes_to_excel_bytes(df):
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Pendentes")
    bio.seek(0)
    return bio.getvalue()


def resumo_to_excel_bytes(df):
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resumo")
    bio.seek(0)
    return bio.getvalue()


def texto_para_bytes_utf8(texto):
    return texto.encode("utf-8")
