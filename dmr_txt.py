from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from typing import Any
import re

import pandas as pd


# =========================================================
# CONFIGURAÇÃO DMR TXT - POSIÇÕES FIXAS
# =========================================================
#
# Baseado nas posições indicadas por ti:
#
# Linha 006:
# - NIF: colunas 10 a 18
# - Categoria rendimento: colunas 53 a 54
# - Rendimento: começa no sinal da coluna 38 e vai até à coluna 52
# - IRS: começa no sinal da coluna 58 e termina antes do sinal seguinte,
#        usando 58 a 71
#
# Em Python:
# - coluna 1 => índice 0
# - fim exclusivo
#
# Logo:
# - NIF        10-18 => [9:18]
# - CATEGORIA  53-54 => [52:54]
# - RENDIMENTO 38-52 => [37:52]
# - IRS        58-71 => [57:71]
# =========================================================

DMR_TIPO_REGISTO = slice(0, 3)
DMR_NIF = slice(9, 18)
DMR_REND = slice(37, 52)
DMR_CAT = slice(52, 54)
DMR_IRS = slice(57, 71)

REGISTO_DETALHE = "006"
CATEGORIA_ACEITE = "A "   # A + espaço
CATEGORIA_EXCLUIDA_PREFIX = "A2"  # A21, A22, etc. ficam excluídas por não serem "A "

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


# =========================================================
# MODELOS
# =========================================================

@dataclass
class DMRRecord:
    line_index: int
    original_line: str
    nif: str
    categoria: str
    rendimento: Decimal
    irs: Decimal

    def is_categoria_a_valida(self) -> bool:
        return self.categoria == CATEGORIA_ACEITE


# =========================================================
# UTILITÁRIOS DECIMAL / TEXTO
# =========================================================

def q2(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def normalizar_nif(valor: Any) -> str:
    s = "" if valor is None else str(valor)
    s = re.sub(r"\D", "", s)
    if not s:
        return ""
    return s.zfill(9)[-9:]


def parse_decimal_pt(valor: Any) -> Decimal:
    """
    Converte valores vindos do Excel/PT:
    - 100,05
    - -100,05
    - 100.05
    - 1.234,56
    - vazio => 0
    """
    if valor is None:
        return ZERO

    if isinstance(valor, Decimal):
        return q2(valor)

    if isinstance(valor, (int, float)):
        return q2(Decimal(str(valor)))

    s = str(valor).strip()
    if s == "":
        return ZERO

    s = s.replace(" ", "")

    # formato PT tipo 1.234,56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return q2(Decimal(s))
    except (InvalidOperation, ValueError):
        return ZERO


def decimal_to_pt_str(v: Decimal) -> str:
    v = q2(v)
    s = f"{v:.2f}"
    return s.replace(".", ",")


def campo_txt_para_decimal(txt: str) -> Decimal:
    """
    Campo com sinal e 2 casas decimais implícitas.
    Exemplos:
    +00000000064387 -> 643.87
    -00000000010005 -> -100.05
    +00000000000000 -> 0.00
    """
    s = (txt or "").rstrip("\r\n")
    s = s.strip()

    if not s:
        return ZERO

    sinal = 1
    if s[0] == "-":
        sinal = -1
        s_num = s[1:]
    elif s[0] == "+":
        s_num = s[1:]
    else:
        s_num = s

    s_num = s_num.strip()
    s_num = s_num.lstrip("0")

    if s_num == "":
        return ZERO

    if len(s_num) == 1:
        s_num = "0" + s_num

    euros = s_num[:-2] or "0"
    cents = s_num[-2:]

    valor = Decimal(f"{int(euros)}.{cents}")
    if sinal < 0:
        valor = -valor

    return q2(valor)


def decimal_para_campo_txt(valor: Decimal, largura_total: int) -> str:
    """
    Converte Decimal para campo DMR com sinal e casas implícitas.
    largura_total inclui o sinal.
    Exemplo largura_total=15 => +00000000064387
    """
    valor = q2(valor)
    sinal = "+" if valor >= 0 else "-"
    absoluto = abs(valor)

    centimos = int((absoluto * 100).to_integral_value(rounding=ROUND_HALF_UP))
    digits_len = largura_total - 1
    return f"{sinal}{centimos:0{digits_len}d}"


# =========================================================
# LEITURA DMR TXT
# =========================================================

def split_lines_preserve(text: str) -> list[str]:
    """
    Divide preservando o terminador de linha quando existir.
    """
    if not text:
        return []
    return text.splitlines(True)


def read_text_file_any_encoding(uploaded_file: Any) -> str:
    """
    Lê TXT/bytes tentando decodificações comuns.
    """
    raw = uploaded_file.read()
    if isinstance(raw, str):
        return raw

    encodings = ["utf-8", "cp1252", "latin-1", "iso-8859-1"]
    for enc in encodings:
        try:
            return raw.decode(enc)
        except Exception:
            pass

    return raw.decode("latin-1", errors="replace")


def parse_dmr_line_006(line: str, line_index: int) -> DMRRecord | None:
    """
    Lê uma linha 006 usando posições fixas.
    """
    base = line.rstrip("\r\n")

    if len(base) < 71:
        return None

    if base[DMR_TIPO_REGISTO] != REGISTO_DETALHE:
        return None

    nif = base[DMR_NIF].strip()
    categoria = base[DMR_CAT]
    rendimento = campo_txt_para_decimal(base[DMR_REND])
    irs = campo_txt_para_decimal(base[DMR_IRS])

    return DMRRecord(
        line_index=line_index,
        original_line=line,
        nif=nif,
        categoria=categoria,
        rendimento=rendimento,
        irs=irs,
    )


def parse_dmr_records(dmr_text: str) -> tuple[list[str], list[DMRRecord]]:
    """
    Devolve:
    - lista de linhas originais
    - lista de registos 006 interpretados
    """
    lines = split_lines_preserve(dmr_text)
    records: list[DMRRecord] = []

    for idx, line in enumerate(lines):
        rec = parse_dmr_line_006(line, idx)
        if rec is not None:
            records.append(rec)

    return lines, records


# =========================================================
# LEITURA EXCEL PENDENTES
# =========================================================

def escolher_folha_excel(excel_file: Any, sheet_name: str | None = None) -> str:
    """
    Escolhe a folha a ler.
    """
    excel_file.seek(0)
    xls = pd.ExcelFile(excel_file)

    if sheet_name and sheet_name in xls.sheet_names:
        return sheet_name

    if xls.sheet_names:
        return xls.sheet_names[0]

    raise ValueError("O ficheiro Excel não contém folhas.")


def ler_pendentes_excel(excel_file: Any, sheet_name: str | None = None) -> pd.DataFrame:
    """
    Lê o Excel de pendentes e normaliza as colunas esperadas:

    Esperado:
    - Coluna A: NIF
    - Coluna C: Valor
    - Coluna D: IRS

    Pode haver cabeçalhos variados; a leitura é feita por posição.
    """
    excel_file.seek(0)
    folha = escolher_folha_excel(excel_file, sheet_name)

    excel_file.seek(0)
    df = pd.read_excel(excel_file, sheet_name=folha, header=0)

    # Se vier como dict por algum motivo
    if isinstance(df, dict):
        if folha in df:
            df = df[folha]
        else:
            df = next(iter(df.values()))

    if not hasattr(df, "columns"):
        raise ValueError("Não foi possível ler a folha Excel corretamente.")

    if df.shape[1] < 4:
        raise ValueError(
            "O Excel tem menos de 4 colunas. É necessário pelo menos: A=NIF, C=Valor, D=IRS."
        )

    # Trabalhar por posição:
    # A -> índice 0
    # C -> índice 2
    # D -> índice 3
    out = pd.DataFrame()
    out["NIF"] = df.iloc[:, 0].apply(normalizar_nif)
    out["Valor"] = df.iloc[:, 2].apply(parse_decimal_pt)
    out["IRS"] = df.iloc[:, 3].apply(parse_decimal_pt)

    # Guardar nº da linha original do Excel (2 = primeira linha após cabeçalho)
    out["LinhaExcel"] = range(2, len(out) + 2)

    # Remover linhas vazias
    out = out[(out["NIF"] != "")].copy()

    # Só interessam linhas com alteração real
    out = out[
        (out["Valor"].apply(lambda x: x != ZERO)) |
        (out["IRS"].apply(lambda x: x != ZERO))
    ].copy()

    out.reset_index(drop=True, inplace=True)

    # Colunas auxiliares para resultado
    out["Estado"] = ""
    out["Mensagem"] = ""
    out["LinhaDMR"] = ""
    out["CategoriaDMR"] = ""
    out["RendimentoDMR_Original"] = ""
    out["IRSDMR_Original"] = ""
    out["RendimentoDMR_Novo"] = ""
    out["IRSDMR_Novo"] = ""

    return out


# =========================================================
# ESCRITA EM LINHA DMR
# =========================================================

def replace_slice(text: str, sl: slice, new_value: str) -> str:
    base = text.rstrip("\r\n")
    ending = text[len(base):]

    start = sl.start or 0
    stop = sl.stop if sl.stop is not None else len(base)

    if len(new_value) != (stop - start):
        raise ValueError("O novo valor não tem o comprimento esperado para a fatia.")

    novo = base[:start] + new_value + base[stop:]
    return novo + ending


def atualizar_linha_dmr(original_line: str, novo_rendimento: Decimal, novo_irs: Decimal) -> str:
    """
    Atualiza apenas os campos de rendimento e IRS,
    mantendo todo o restante conteúdo da linha.
    """
    base = original_line.rstrip("\r\n")

    rendimento_txt = decimal_para_campo_txt(novo_rendimento, DMR_REND.stop - DMR_REND.start)
    irs_txt = decimal_para_campo_txt(novo_irs, DMR_IRS.stop - DMR_IRS.start)

    line = original_line
    line = replace_slice(line, DMR_REND, rendimento_txt)
    line = replace_slice(line, DMR_IRS, irs_txt)
    return line


# =========================================================
# PROCESSAMENTO PRINCIPAL
# =========================================================

def aplicar_pendentes_na_dmr(dmr_text: str, pendentes_df: pd.DataFrame) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """
    Regras:
    - procurar por NIF na DMR
    - considerar apenas linhas 006 com categoria exatamente "A "
    - o Excel já traz os valores a negativo
    - o novo valor DMR = valor_original + valor_excel
      (ex.: 300 + (-100) = 200)
    - nunca pode ficar negativo
    - idem para IRS
    """
    lines, records = parse_dmr_records(dmr_text)

    # Índice por NIF, só categoria A válida
    por_nif: dict[str, list[DMRRecord]] = {}
    for rec in records:
        if rec.is_categoria_a_valida():
            por_nif.setdefault(rec.nif, []).append(rec)

    pendentes_out = pendentes_df.copy()

    resumo_rows: list[dict[str, Any]] = []
    linhas_alteradas = 0

    for idx, row in pendentes_out.iterrows():
        nif = normalizar_nif(row.get("NIF"))
        valor_excel = parse_decimal_pt(row.get("Valor"))
        irs_excel = parse_decimal_pt(row.get("IRS"))

        candidatos = por_nif.get(nif, [])

        if not candidatos:
            pendentes_out.at[idx, "Estado"] = "Sem correspondência"
            pendentes_out.at[idx, "Mensagem"] = "Não foi encontrada linha 006 com categoria 'A ' para este NIF."
            continue

        # Regra prática:
        # aplicar à primeira linha A encontrada para o NIF.
        rec = candidatos[0]

        rendimento_original = rec.rendimento
        irs_original = rec.irs

        rendimento_novo = q2(rendimento_original + valor_excel)
        irs_novo = q2(irs_original + irs_excel)

        erros: list[str] = []

        if rendimento_novo < ZERO:
            erros.append(
                f"Rendimento insuficiente na DMR ({decimal_to_pt_str(rendimento_original)}) "
                f"para absorver {decimal_to_pt_str(valor_excel)}."
            )

        if irs_novo < ZERO:
            erros.append(
                f"IRS insuficiente na DMR ({decimal_to_pt_str(irs_original)}) "
                f"para absorver {decimal_to_pt_str(irs_excel)}."
            )

        if erros:
            pendentes_out.at[idx, "Estado"] = "Erro"
            pendentes_out.at[idx, "Mensagem"] = " ".join(erros)
            pendentes_out.at[idx, "LinhaDMR"] = rec.line_index + 1
            pendentes_out.at[idx, "CategoriaDMR"] = rec.categoria
            pendentes_out.at[idx, "RendimentoDMR_Original"] = decimal_to_pt_str(rendimento_original)
            pendentes_out.at[idx, "IRSDMR_Original"] = decimal_to_pt_str(irs_original)
            pendentes_out.at[idx, "RendimentoDMR_Novo"] = decimal_to_pt_str(rendimento_novo)
            pendentes_out.at[idx, "IRSDMR_Novo"] = decimal_to_pt_str(irs_novo)
            continue

        # Atualizar linha DMR
        nova_linha = atualizar_linha_dmr(lines[rec.line_index], rendimento_novo, irs_novo)
        lines[rec.line_index] = nova_linha
        linhas_alteradas += 1

        # Atualizar também o registo em memória para permitir operações seguintes no mesmo NIF
        rec.rendimento = rendimento_novo
        rec.irs = irs_novo
        rec.original_line = nova_linha

        pendentes_out.at[idx, "Estado"] = "Atualizado"
        pendentes_out.at[idx, "Mensagem"] = "Linha DMR atualizada com sucesso."
        pendentes_out.at[idx, "LinhaDMR"] = rec.line_index + 1
        pendentes_out.at[idx, "CategoriaDMR"] = rec.categoria
        pendentes_out.at[idx, "RendimentoDMR_Original"] = decimal_to_pt_str(rendimento_original)
        pendentes_out.at[idx, "IRSDMR_Original"] = decimal_to_pt_str(irs_original)
        pendentes_out.at[idx, "RendimentoDMR_Novo"] = decimal_to_pt_str(rendimento_novo)
        pendentes_out.at[idx, "IRSDMR_Novo"] = decimal_to_pt_str(irs_novo)

        resumo_rows.append(
            {
                "LinhaExcel": row.get("LinhaExcel", ""),
                "NIF": nif,
                "LinhaDMR": rec.line_index + 1,
                "Categoria": rec.categoria,
                "ValorExcel": decimal_to_pt_str(valor_excel),
                "IRSExcel": decimal_to_pt_str(irs_excel),
                "RendimentoOriginal": decimal_to_pt_str(rendimento_original),
                "IRSOriginal": decimal_to_pt_str(irs_original),
                "RendimentoNovo": decimal_to_pt_str(rendimento_novo),
                "IRSNovo": decimal_to_pt_str(irs_novo),
            }
        )

    dmr_corrigida = "".join(lines)

    resumo_df = pd.DataFrame(resumo_rows)
    if resumo_df.empty:
        resumo_df = pd.DataFrame(
            columns=[
                "LinhaExcel", "NIF", "LinhaDMR", "Categoria", "ValorExcel", "IRSExcel",
                "RendimentoOriginal", "IRSOriginal", "RendimentoNovo", "IRSNovo"
            ]
        )

    return dmr_corrigida, pendentes_out, resumo_df


# =========================================================
# EXPORTAÇÕES
# =========================================================

def pendentes_to_excel_bytes(df: pd.DataFrame) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Pendentes Atualizados")
    bio.seek(0)
    return bio.read()


def resumo_to_excel_bytes(df: pd.DataFrame) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resumo")
    bio.seek(0)
    return bio.read()


def texto_para_bytes_utf8(texto: str) -> bytes:
    return texto.encode("utf-8")


# =========================================================
# FUNÇÃO DE CONVENIÊNCIA PARA A PÁGINA
# =========================================================

def processar_dmr_e_excel(
    dmr_file: Any,
    excel_file: Any,
    sheet_name: str | None = None,
) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """
    Lê:
    - DMR em TXT
    - Excel de pendentes

    Devolve:
    - texto DMR corrigido
    - dataframe pendentes atualizado
    - dataframe resumo
    """
    dmr_file.seek(0)
    dmr_text = read_text_file_any_encoding(dmr_file)

    excel_file.seek(0)
    pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name)

    dmr_corrigida, pendentes_out, resumo_df = aplicar_pendentes_na_dmr(dmr_text, pendentes_df)

    return dmr_corrigida, pendentes_out, resumo_df
