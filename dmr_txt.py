from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Tuple, Optional

import pandas as pd


# ============================================================
# POSIÇÕES FIXAS DA LINHA 006 DA DMR TXT
# Baseadas nas colunas indicadas pelo utilizador:
#
# NIF: colunas 10 a 18
# Rendimento: colunas 38 a 52 (inclui sinal + ou -)
# Categoria: colunas 53 e 54
# IRS: colunas 58 a 72 (inclui sinal + ou -)
#
# Em Python, slice [inicio:fim] usa fim exclusivo.
# ============================================================

LINHA_006_PREFIX = "006"

POS_NIF_INI = 9      # coluna 10
POS_NIF_FIM = 18     # coluna 18 inclusive -> slice [9:18]

POS_REND_INI = 38    # coluna 38
POS_REND_FIM = 52    # coluna 51 inclusive -> slice [37:52]

POS_CAT_INI = 53     # coluna 53
POS_CAT_FIM = 55     # colunas 53-54 -> slice [52:54]

POS_IRS_INI = 58     # coluna 58
POS_IRS_FIM = 71     # coluna 72 inclusive -> slice [57:72]

# Campo seguinte ao IRS normalmente começa no sinal seguinte.
# Mantemos uma referência útil para reconstrução/validação visual.
POS_DEPOIS_IRS = 72  # próxima coluna após IRS


# ============================================================
# EXCEL PENDENTES
# Esperado:
# Coluna A -> NIF
# Coluna C -> Valor (negativo)
# Coluna D -> IRS (negativo)
# ============================================================

EXCEL_COL_NIF = 0
EXCEL_COL_VALOR = 2
EXCEL_COL_IRS = 3


def q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalizar_nif(valor) -> str:
    s = "" if valor is None else str(valor).strip()
    s = re.sub(r"\D", "", s)
    if not s:
        return ""
    return s.zfill(9)[-9:]


def parse_decimal_pt(valor) -> Decimal:
    """
    Converte valores vindos do Excel/PT:
    - 100,05
    - -100,05
    - 100.05
    - 100
    - células vazias -> 0
    """
    if valor is None:
        return Decimal("0.00")

    if isinstance(valor, Decimal):
        return q2(valor)

    # pandas pode dar int/float
    if isinstance(valor, (int, float)):
        try:
            return q2(Decimal(str(valor)))
        except Exception:
            return Decimal("0.00")

    s = str(valor).strip()
    if s == "" or s.lower() == "nan":
        return Decimal("0.00")

    s = s.replace(" ", "")
    s = s.replace(".", "") if ("," in s and "." in s) else s
    s = s.replace(",", ".")

    if s in {"+", "-", ""}:
        return Decimal("0.00")

    try:
        return q2(Decimal(s))
    except InvalidOperation:
        raise ValueError(f"Valor decimal inválido: {valor!r}")


def parse_campo_dmr(campo: str) -> Decimal:
    """
    Lê um campo numérico da DMR TXT com sinal incluído.
    Exemplos:
    +00000000064387 -> 643.87
    -00000000064387 -> -643.87
    +00000000000000 -> 0.00
    """
    campo = (campo or "").rstrip()

    if not campo:
        return Decimal("0.00")

    primeiro = campo[0]
    if primeiro not in {"+", "-"}:
        raise ValueError(f"Campo sem sinal +/-: [{campo}]")

    sinal = -1 if primeiro == "-" else 1
    numero = campo[1:].strip()

    if numero == "":
        return Decimal("0.00")

    if not numero.isdigit():
        raise ValueError(f"Campo com caracteres inválidos: [{campo}]")

    valor = Decimal(int(numero)) / Decimal("100")
    return q2(valor * sinal)


def format_campo_dmr(valor: Decimal, largura: int) -> str:
    """
    Converte Decimal para o formato DMR com sinal e centésimos.
    largura inclui o sinal.
    Ex.: largura=15 -> +00000000064387
    """
    valor = q2(valor)
    sinal = "+" if valor >= 0 else "-"
    absoluto = abs(valor)

    centimos = int((absoluto * 100).to_integral_value(rounding=ROUND_HALF_UP))
    digitos = str(centimos).zfill(largura - 1)

    if len(digitos) > (largura - 1):
        raise ValueError(
            f"Valor {valor} não cabe num campo de largura {largura}."
        )

    return sinal + digitos


@dataclass
class LinhaDMR:
    idx: int
    original: str
    nif: str
    categoria: str
    rendimento: Decimal
    irs: Decimal

    def atualizar(self, novo_rendimento: Decimal, novo_irs: Decimal) -> str:
        linha = self.original

        rend_fmt = format_campo_dmr(
            novo_rendimento, POS_REND_FIM - POS_REND_INI
        )
        irs_fmt = format_campo_dmr(
            novo_irs, POS_IRS_FIM - POS_IRS_INI
        )

        nova = (
            linha[:POS_REND_INI]
            + rend_fmt
            + linha[POS_REND_FIM:POS_IRS_INI]
            + irs_fmt
            + linha[POS_IRS_FIM:]
        )
        return nova


def ler_dmr_txt(uploaded_file) -> Tuple[List[str], List[LinhaDMR]]:
    """
    Lê o TXT da DMR e devolve:
    - lista das linhas originais
    - lista das linhas 006 parseadas
    """
    if uploaded_file is None:
        raise ValueError("Ficheiro DMR não fornecido.")

    raw = uploaded_file.read()
    if isinstance(raw, str):
        texto = raw
    else:
        # tentar utf-8 e fallback latin-1
        try:
            texto = raw.decode("utf-8")
        except Exception:
            texto = raw.decode("latin-1")

    linhas = texto.splitlines()
    linhas_006: List[LinhaDMR] = []

    for idx, linha in enumerate(linhas):
        if not linha.startswith(LINHA_006_PREFIX):
            continue

        # garantir comprimento mínimo
        if len(linha) < POS_IRS_FIM:
            continue

        nif = normalizar_nif(linha[POS_NIF_INI:POS_NIF_FIM])
        categoria = linha[POS_CAT_INI:POS_CAT_FIM]
        rendimento_raw = linha[POS_REND_INI:POS_REND_FIM]
        irs_raw = linha[POS_IRS_INI:POS_IRS_FIM]

        rendimento = parse_campo_dmr(rendimento_raw)
        irs = parse_campo_dmr(irs_raw)

        linhas_006.append(
            LinhaDMR(
                idx=idx,
                original=linha,
                nif=nif,
                categoria=categoria,
                rendimento=rendimento,
                irs=irs,
            )
        )

    return linhas, linhas_006


def descobrir_folhas_excel(uploaded_file) -> List[str]:
    uploaded_file.seek(0)
    xls = pd.ExcelFile(uploaded_file)
    folhas = list(xls.sheet_names)
    uploaded_file.seek(0)
    return folhas


def ler_pendentes_excel(uploaded_file, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """
    Lê o Excel de pendentes.
    Esperado:
    A = NIF
    C = Valor
    D = IRS
    """
    if uploaded_file is None:
        raise ValueError("Ficheiro Excel não fornecido.")

    uploaded_file.seek(0)

    # Sem header para garantir que A,C,D são sempre 0,2,3
    df = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=None, dtype=object)

    # Se vier dict (quando sheet_name=None e múltiplas folhas), usar a primeira
    if isinstance(df, dict):
        primeira_folha = next(iter(df))
        df = df[primeira_folha]

    if df is None or df.empty:
        raise ValueError("O Excel está vazio ou não foi possível lê-lo.")

    cols = list(df.columns)
    max_col = max(EXCEL_COL_NIF, EXCEL_COL_VALOR, EXCEL_COL_IRS)
    if len(cols) <= max_col:
        raise ValueError(
            "O Excel não tem colunas suficientes. Esperado: A=NIF, C=Valor, D=IRS."
        )

    out = pd.DataFrame()
    out["NIF"] = df.iloc[:, EXCEL_COL_NIF].apply(normalizar_nif)
    out["Valor"] = df.iloc[:, EXCEL_COL_VALOR].apply(parse_decimal_pt)
    out["IRS"] = df.iloc[:, EXCEL_COL_IRS].apply(parse_decimal_pt)

    # guardar linha de origem do Excel para referência
    out["Linha_Excel"] = range(1, len(out) + 1)

    # remover linhas sem NIF
    out = out[out["NIF"] != ""].copy()

    return out.reset_index(drop=True)


def aplicar_retificacoes(
    linhas_originais: List[str],
    linhas_006: List[LinhaDMR],
    pendentes_df: pd.DataFrame,
):
    """
    Regras:
    - procurar no TXT linha 006 com:
      - mesmo NIF
      - categoria "A " (A21 não serve)
    - somar o valor negativo do Excel ao valor positivo da DMR para reduzir
    - somar o IRS negativo do Excel ao IRS da DMR para reduzir
    - o resultado nunca pode ficar negativo
    """

    dmr_por_nif = {}
    for rec in linhas_006:
        if rec.categoria == "A ":
            dmr_por_nif.setdefault(rec.nif, []).append(rec)

    novas_linhas = list(linhas_originais)
    resultados = []

    for _, row in pendentes_df.iterrows():
        nif = row["NIF"]
        valor_ajuste = q2(row["Valor"])
        irs_ajuste = q2(row["IRS"])
        linha_excel = int(row["Linha_Excel"])

        candidatos = dmr_por_nif.get(nif, [])

        if not candidatos:
            resultados.append(
                {
                    "Linha_Excel": linha_excel,
                    "NIF": nif,
                    "Valor_Pendente": valor_ajuste,
                    "IRS_Pendente": irs_ajuste,
                    "Estado": "Sem linha categoria A na DMR",
                    "Linha_DMR": None,
                    "Categoria": None,
                    "Rendimento_Original": None,
                    "IRS_Original": None,
                    "Novo_Rendimento": None,
                    "Novo_IRS": None,
                }
            )
            continue

        # regra: usar a primeira linha A encontrada desse NIF
        rec = candidatos[0]

        novo_rendimento = q2(rec.rendimento + valor_ajuste)
        novo_irs = q2(rec.irs + irs_ajuste)

        if novo_rendimento < 0:
            resultados.append(
                {
                    "Linha_Excel": linha_excel,
                    "NIF": nif,
                    "Valor_Pendente": valor_ajuste,
                    "IRS_Pendente": irs_ajuste,
                    "Estado": "Rendimento insuficiente na DMR",
                    "Linha_DMR": rec.idx + 1,
                    "Categoria": rec.categoria,
                    "Rendimento_Original": rec.rendimento,
                    "IRS_Original": rec.irs,
                    "Novo_Rendimento": None,
                    "Novo_IRS": None,
                }
            )
            continue

        if novo_irs < 0:
            resultados.append(
                {
                    "Linha_Excel": linha_excel,
                    "NIF": nif,
                    "Valor_Pendente": valor_ajuste,
                    "IRS_Pendente": irs_ajuste,
                    "Estado": "IRS insuficiente na DMR",
                    "Linha_DMR": rec.idx + 1,
                    "Categoria": rec.categoria,
                    "Rendimento_Original": rec.rendimento,
                    "IRS_Original": rec.irs,
                    "Novo_Rendimento": None,
                    "Novo_IRS": None,
                }
            )
            continue

        nova_linha = rec.atualizar(novo_rendimento, novo_irs)
        novas_linhas[rec.idx] = nova_linha

        # atualizar também o objeto para evitar conflitos caso o mesmo NIF apareça várias vezes
        rec.original = nova_linha
        rec.rendimento = novo_rendimento
        rec.irs = novo_irs

        resultados.append(
            {
                "Linha_Excel": linha_excel,
                "NIF": nif,
                "Valor_Pendente": valor_ajuste,
                "IRS_Pendente": irs_ajuste,
                "Estado": "Corrigido",
                "Linha_DMR": rec.idx + 1,
                "Categoria": rec.categoria,
                "Rendimento_Original": q2(rec.rendimento - valor_ajuste),
                "IRS_Original": q2(rec.irs - irs_ajuste),
                "Novo_Rendimento": novo_rendimento,
                "Novo_IRS": novo_irs,
            }
        )

    resultados_df = pd.DataFrame(resultados)

    pendentes_out = pendentes_df.copy()
    if not resultados_df.empty:
        pendentes_out = pendentes_out.merge(
            resultados_df[["Linha_Excel", "Estado", "Linha_DMR", "Categoria",
                           "Rendimento_Original", "IRS_Original",
                           "Novo_Rendimento", "Novo_IRS"]],
            on="Linha_Excel",
            how="left",
        )

    dmr_corrigida_txt = "\n".join(novas_linhas)

    return resultados_df, pendentes_out, dmr_corrigida_txt


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Pendentes Atualizado") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    output.seek(0)
    return output.getvalue()
