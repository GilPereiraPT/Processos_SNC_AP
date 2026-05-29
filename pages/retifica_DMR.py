from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
import pandas as pd


# posições 0-based no TXT
POS_NIF_INI = 18
POS_NIF_FIM = 27

POS_REND_INI = 65
POS_REND_FIM = 76

POS_CAT_INI = 62
POS_CAT_FIM = 64

POS_IRS_INI = 76
POS_IRS_FIM = 87


def descobrir_folhas_excel(excel_file):
    excel_file.seek(0)
    return pd.ExcelFile(excel_file).sheet_names


def decimal_seguro(valor, campo="valor") -> Decimal:
    if pd.isna(valor):
        return Decimal("0")

    texto = str(valor).strip()

    if texto == "":
        return Decimal("0")

    # protege contra cabeçalhos tratados como dados
    if texto.lower() in ["valor", "irs", "rendimento", "nif"]:
        raise ValueError(f"Valor decimal inválido: {texto!r}")

    texto = texto.replace("€", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")

    try:
        return Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"Valor decimal inválido: {texto!r}")


def formatar_decimal_txt(valor: Decimal, tamanho: int) -> str:
    valor = max(valor, Decimal("0"))
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    inteiro = int(valor * 100)
    return str(inteiro).zfill(tamanho)


def ler_valor_txt(linha: str, ini: int, fim: int) -> Decimal:
    raw = linha[ini:fim].strip()
    if raw == "":
        return Decimal("0")
    return Decimal(raw) / Decimal("100")


def substituir_intervalo(linha: str, ini: int, fim: int, novo: str) -> str:
    return linha[:ini] + novo + linha[fim:]


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
        if linha.startswith("006"):
            categoria = linha[POS_CAT_INI:POS_CAT_FIM]
            if categoria == "A ":
                linhas_006.append(
                    {
                        "idx": idx,
                        "linha": linha,
                        "nif": linha[POS_NIF_INI:POS_NIF_FIM].strip(),
                        "categoria": categoria,
                        "rendimento": ler_valor_txt(linha, POS_REND_INI, POS_REND_FIM),
                        "irs": ler_valor_txt(linha, POS_IRS_INI, POS_IRS_FIM),
                    }
                )

    return linhas, linhas_006


def ler_pendentes_excel(excel_file, sheet_name=None):
    excel_file.seek(0)

    df = pd.read_excel(
        excel_file,
        sheet_name=sheet_name,
        header=0,
        dtype={"NIF": str},
    )

    df.columns = [str(c).strip() for c in df.columns]

    colunas_necessarias = ["NIF", "Rendimento", "Valor", "IRS"]
    em_falta = [c for c in colunas_necessarias if c not in df.columns]

    if em_falta:
        raise ValueError(
            "O Excel não tem as colunas esperadas. "
            f"Faltam: {', '.join(em_falta)}. "
            "Esperado: NIF, Rendimento, Valor, IRS."
        )

    df = df.copy()

    # remove linhas totalmente vazias
    df = df.dropna(how="all")

    # protege contra cabeçalhos repetidos no meio do ficheiro
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

    df["Categoria"] = df["Rendimento"].astype(str).str.strip()

    # só categoria A; A21 é excluído
    df = df[df["Categoria"].str.upper() == "A"]
    df = df[df["Categoria"].str.upper() != "A21"]

    df["Valor_Decimal"] = df["Valor"].apply(lambda x: decimal_seguro(x, "Valor"))
    df["IRS_Decimal"] = df["IRS"].apply(lambda x: decimal_seguro(x, "IRS"))

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

    mapa_dmr = {}
    for item in linhas_006:
        mapa_dmr.setdefault(item["nif"], []).append(item)

    for i, row in pendentes_df.iterrows():
        nif = str(row["NIF"]).zfill(9)
        valor_excel = row["Valor_Decimal"]
        irs_excel = row["IRS_Decimal"]

        if nif not in mapa_dmr:
            estado = "NIF não encontrado na DMR categoria A"
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
        )

        novo_irs_txt = formatar_decimal_txt(
            irs_depois,
            POS_IRS_FIM - POS_IRS_INI,
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

    resultados_df = pd.DataFrame(resultados)

    # remove colunas técnicas do Excel final
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
