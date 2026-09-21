"""Juntar Excel e CSV — ULSLA | Importação e exportação em formato PT-PT.
Dependências: streamlit, pandas, openpyxl, xlrd, xlsxwriter, rarfile.
Para ficheiros RAR, rarfile pode necessitar de unrar/unar/bsdtar no servidor.
"""

import csv
import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import rarfile
import streamlit as st

EXTENSOES_EXCEL = {".xlsx", ".xlsm", ".xls"}
EXTENSOES_SUPORTADAS = EXTENSOES_EXCEL | {".csv"}
SEPARADORES = {"Automático (Portugal)": None, "Ponto e vírgula (; )": ";", "Vírgula (, )": ",", "Tabulação": "\t", "Barra vertical (| )": "|"}


def normalizar_nome_coluna(valor):
    import unicodedata
    nome = unicodedata.normalize("NFKD", str(valor).replace("\ufeff", "").replace("\xa0", " "))
    nome = "".join(c for c in nome if not unicodedata.combining(c)).lower().strip()
    nome = re.sub(r"[^a-z0-9]+", " ", nome)
    return re.sub(r"\s+", " ", nome).strip()


def normalizar_documento(valor):
    if pd.isna(valor):
        return ""
    texto = str(valor).strip()
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    return texto.upper()


def sugerir_coluna_documento(colunas):
    candidatos = {"n documento", "numero documento", "numero de documento", "num documento", "documento"}
    for c in colunas:
        if normalizar_nome_coluna(c) in candidatos:
            return c
    return next((c for c in colunas if "documento" in normalizar_nome_coluna(c)), colunas[0] if colunas else None)


def coluna_identificador(coluna):
    """Nunca transformar identificadores e referências em números."""
    nome = normalizar_nome_coluna(coluna)
    tokens = set(nome.split())
    protegidos = {
        "documento", "doc", "nif", "niss", "nipc", "nutente", "utente", "codigo", "cod",
        "conta", "iban", "referencia", "ref", "serie", "numero", "num", "id", "ean",
        "upc", "telefone", "telemovel", "postal", "cc", "artigo", "fatura", "factura",
        "fornecedor", "cliente", "processo", "pedido", "contrato", "centro", "rubrica",
    }
    return bool(tokens & protegidos) or nome in {"n", "n o", "nr"}


def parece_data(valor):
    if pd.isna(valor):
        return False
    texto = str(valor).strip()
    return bool(re.match(r"^(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})(?:[ T].*)?$", texto))


def detetar_colunas_data(df):
    resultado = []
    for coluna in df.columns:
        nome = normalizar_nome_coluna(coluna)
        valores = [str(x).strip() for x in df[coluna].head(300) if not pd.isna(x) and str(x).strip()]
        proporcao = sum(parece_data(x) for x in valores) / len(valores) if valores else 0
        if nome == "data" or nome.startswith("data ") or nome.endswith(" data") or nome.startswith("date ") or nome == "date" or proporcao >= 0.8:
            resultado.append(coluna)
    return resultado


def converter_numero(valor):
    """Converte números PT: 1.234,56; -1 234,56; (1.234,56); 12,5; 1234."""
    if pd.isna(valor) or str(valor).strip() == "":
        return None
    texto = str(valor).strip()
    negativo_parenteses = texto.startswith("(") and texto.endswith(")")
    if negativo_parenteses:
        texto = texto[1:-1].strip()
    texto = re.sub(r"\bEUR\b|€", "", texto, flags=re.I)
    texto = re.sub(r"[\s\u00a0\u202f]", "", texto)
    if not re.fullmatch(r"[+-]?[\d.,]+", texto):
        return None
    if "," in texto and "." in texto:
        # PT 1.234,56 ou, se necessário, EN 1,234.56
        if texto.rfind(",") > texto.rfind("."):
            if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d+", texto):
                return None
            texto = texto.replace(".", "").replace(",", ".")
        else:
            if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+", texto):
                return None
            texto = texto.replace(",", "")
    elif "," in texto:
        if not re.fullmatch(r"[+-]?\d+(?:,\d+)?", texto):
            return None
        texto = texto.replace(",", ".")
    elif "." in texto:
        if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", texto):
            texto = texto.replace(".", "")  # Em PT, 1.234 é mil duzentos e trinta e quatro
        elif not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", texto):
            return None
    try:
        numero = float(texto)
        return -abs(numero) if negativo_parenteses else numero
    except ValueError:
        return None


def converter_data(valor):
    if pd.isna(valor) or str(valor).strip() == "":
        return None
    try:
        if isinstance(valor, (datetime, pd.Timestamp)):
            return valor.to_pydatetime() if isinstance(valor, pd.Timestamp) else valor
        texto = str(valor).strip()
        if not parece_data(texto):
            return None
        dt = pd.to_datetime(texto, errors="coerce", dayfirst=not bool(re.match(r"^\d{4}[-/]", texto)))
        if pd.isna(dt):
            return None
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.tz_localize(None)
        return dt.to_pydatetime() if isinstance(dt, pd.Timestamp) else dt
    except (ValueError, TypeError, OverflowError):
        return None


def detetar_colunas_monetarias(df):
    tokens_moeda = {"valor", "montante", "debito", "credito", "saldo", "total", "preco", "importe", "liquido", "iliquido", "custo", "euro", "euros"}
    return [c for c in df.columns if not coluna_identificador(c) and bool(set(normalizar_nome_coluna(c).split()) & tokens_moeda)]


def detetar_colunas_numericas(df, colunas_data=None, colunas_monetarias=None):
    """Deteta quantidades e montantes sem converter NIF, números de documento ou códigos."""
    colunas_data = set(colunas_data or [])
    colunas_monetarias = set(colunas_monetarias or [])
    resultado = []
    for coluna in df.columns:
        if coluna in colunas_data or coluna in colunas_monetarias or coluna_identificador(coluna):
            continue
        valores = [v for v in df[coluna].head(300) if not pd.isna(v) and str(v).strip()]
        if not valores:
            continue
        # Colunas com nomes textuais mantêm-se texto, mesmo que uma linha contenha um número.
        nome = normalizar_nome_coluna(coluna)
        if set(nome.split()) & {"nome", "descricao", "observacoes", "morada", "entidade", "tipo", "estado", "localidade", "designacao"}:
            continue
        validos = sum(converter_numero(v) is not None for v in valores)
        if validos / len(valores) >= 0.95:
            resultado.append(coluna)
    return resultado


def formatar_data_ou_original(valor):
    convertido = converter_data(valor)
    return convertido if convertido is not None else ("" if pd.isna(valor) else valor)


def formatar_numero_ou_original(valor):
    convertido = converter_numero(valor)
    return convertido if convertido is not None else ("" if pd.isna(valor) else valor)


def preparar_formatos(df, colunas_data, colunas_monetarias, colunas_numericas=None):
    resultado = df.copy().astype(object)
    for coluna in colunas_data:
        if coluna in resultado:
            resultado[coluna] = [formatar_data_ou_original(v) for v in resultado[coluna]]
    for coluna in set(colunas_monetarias or []) | set(colunas_numericas or []):
        if coluna in resultado and coluna not in colunas_data and not coluna_identificador(coluna):
            resultado[coluna] = [formatar_numero_ou_original(v) for v in resultado[coluna]]
    return resultado


def limpar_tabela(df):
    if df.empty:
        return df
    df = df.replace("", pd.NA).dropna(how="all").fillna("")
    df.columns = [str(c).replace("\ufeff", "").replace("\xa0", " ").strip() for c in df.columns]
    return df


def ler_excel_bytes(conteudo, nome_ficheiro, todas_as_folhas=False):
    extensao = Path(nome_ficheiro).suffix.lower()
    if extensao not in EXTENSOES_EXCEL:
        return []
    engine = "xlrd" if extensao == ".xls" else "openpyxl"
    folhas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, dtype=str, keep_default_na=False, engine=engine)
    blocos = []
    for indice, (folha, df) in enumerate(folhas.items()):
        if indice and not todas_as_folhas:
            break
        df = limpar_tabela(df)
        if not df.empty:
            df.attrs["origem_folha"] = folha
            blocos.append(df)
    return blocos


def descodificar_csv(conteudo):
    if conteudo.startswith((b"\xff\xfe", b"\xfe\xff")):
        return conteudo.decode("utf-16"), "UTF-16"
    if conteudo.startswith(b"\xef\xbb\xbf"):
        return conteudo.decode("utf-8-sig"), "UTF-8 BOM"
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return conteudo.decode(encoding), encoding.upper()
        except UnicodeDecodeError:
            pass
    raise ValueError("Não foi possível identificar a codificação do CSV")


def detetar_separador_csv(texto):
    """Privilegia ; quando este gera colunas coerentes: evita confundir vírgulas decimais."""
    linhas = [linha for linha in texto.splitlines() if linha.strip()][:31]
    if not linhas:
        return ";"
    resultados = []
    for sep in (";", "\t", "|", ","):
        try:
            registos = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=sep, strict=True))
            if not registos:
                continue
            cabecalho = len(registos[0])
            if cabecalho <= 1:
                continue
            consistencia = sum(len(r) == cabecalho for r in registos[1:]) / max(1, len(registos) - 1)
            # Mais consistência, depois preferência PT (';'), depois número de colunas.
            preferencia = 1 if sep == ";" else 0
            resultados.append(((consistencia, preferencia, cabecalho), sep))
        except csv.Error:
            continue
    if not resultados:
        return ";"
    return max(resultados)[1]


def ler_csv_bytes(conteudo, nome_ficheiro, separador="Automático"):
    if not conteudo:
        return []
    texto, codificacao = descodificar_csv(conteudo)
    texto = texto.lstrip("\ufeff")
    primeira_linha = next((l.strip() for l in texto.splitlines() if l.strip()), "")
    declaracao = primeira_linha[4:] if primeira_linha.lower().startswith("sep=") else None
    if declaracao is not None:
        partes = texto.splitlines(keepends=True)
        inicio = next((i for i, linha in enumerate(partes) if linha.strip()), None)
        texto = "".join(partes[inicio + 1:]) if inicio is not None else ""
    if not texto.strip():
        return []
    escolhido = None if separador in ("Automático", "Automático (Portugal)") else separador
    if escolhido == "Tabulação":
        escolhido = "\t"
    delimitador = escolhido or (declaracao if declaracao in (";", ",", "\t", "|") else detetar_separador_csv(texto))
    df = pd.read_csv(
        io.StringIO(texto), sep=delimitador, dtype=str, keep_default_na=False,
        skip_blank_lines=True, on_bad_lines="error", engine="python",
    )
    df = limpar_tabela(df)
    if df.empty:
        return []
    if len(df.columns) == 1 and not escolhido:
        raise ValueError("O CSV ficou com uma única coluna. Escolha manualmente o separador na aplicação.")
    df.attrs["separador"] = delimitador
    df.attrs["codificacao"] = codificacao
    return [df]


def ler_ficheiro_bytes(conteudo, nome_ficheiro, todas_as_folhas=False, separador="Automático"):
    extensao = Path(nome_ficheiro).suffix.lower()
    if extensao == ".csv":
        return ler_csv_bytes(conteudo, nome_ficheiro, separador)
    if extensao in EXTENSOES_EXCEL:
        return ler_excel_bytes(conteudo, nome_ficheiro, todas_as_folhas)
    return []


def extrair_excels_zip(conteudo):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        return [(info.filename, arquivo.read(info)) for info in arquivo.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() in EXTENSOES_SUPORTADAS
                and not Path(info.filename).name.startswith("~$")]


def extrair_excels_rar(conteudo):
    with rarfile.RarFile(io.BytesIO(conteudo)) as arquivo:
        return [(info.filename, arquivo.read(info)) for info in arquivo.infolist()
                if not info.isdir() and Path(info.filename).suffix.lower() in EXTENSOES_SUPORTADAS
                and not Path(info.filename).name.startswith("~$")]


def recolher_ficheiros(uploaded_files):
    encontrados, erros = [], []
    for ficheiro in uploaded_files:
        nome, dados = ficheiro.name, ficheiro.getvalue()
        extensao = Path(nome).suffix.lower()
        try:
            if extensao in EXTENSOES_SUPORTADAS:
                encontrados.append((nome, dados))
            elif extensao in (".zip", ".rar"):
                internos = extrair_excels_zip(dados) if extensao == ".zip" else extrair_excels_rar(dados)
                if not internos:
                    erros.append(f"{nome}: arquivo sem Excel ou CSV suportado.")
                encontrados.extend((f"{nome} → {interno}", conteudo) for interno, conteudo in internos)
        except Exception as exc:
            erros.append(f"{nome}: {exc}")
    return encontrados, erros


def nome_ficheiro_real(nome_origem):
    return nome_origem.split(" → ", 1)[-1]


def alinhar_colunas(blocos):
    """Usa a primeira grafia de cada cabeçalho, sem misturar colunas de nomes diferentes."""
    nomes = {}
    resultado = []
    for df in blocos:
        conversao = {}
        usadas = set()
        for nome in df.columns:
            chave = normalizar_nome_coluna(nome)
            destino = nomes.setdefault(chave, nome) if chave else nome
            if destino not in usadas:
                conversao[nome] = destino
                usadas.add(destino)
        resultado.append(df.rename(columns=conversao))
    return resultado


def criar_excel(df, colunas_data=None, colunas_monetarias=None, colunas_numericas=None):
    datas = colunas_data or []
    moedas = colunas_monetarias or []
    numericas = colunas_numericas or []
    saida = preparar_formatos(df, datas, moedas, numericas)
    if len(saida) > 1048575:
        raise ValueError("O Excel permite até 1.048.575 linhas de dados por folha. Divida os ficheiros.")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy",
                        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
        saida.to_excel(writer, sheet_name="Consolidado", index=False, na_rep="")
        wb, ws = writer.book, writer.sheets["Consolidado"]
        cabecalho = wb.add_format({"bold": True, "border": 1, "bg_color": "#17365D", "font_color": "#FFFFFF", "text_wrap": True, "valign": "top"})
        formato_data = wb.add_format({"num_format": "dd/mm/yyyy"})
        formato_moeda = wb.add_format({"num_format": '#,##0.00 "€"'})
        formato_numero = wb.add_format({"num_format": "#,##0.########"})
        formato_texto = wb.add_format({"num_format": "@"})
        for indice, coluna in enumerate(saida.columns):
            ws.write(0, indice, coluna, cabecalho)
            amostra = saida[coluna].head(500).tolist()
            largura = min(44, max(12, len(str(coluna)) + 2, *(min(42, len(str(v)) + 2) for v in amostra)))
            formato = (formato_data if coluna in datas else formato_moeda if coluna in moedas
                       else formato_numero if coluna in numericas else formato_texto if coluna_identificador(coluna) else None)
            ws.set_column(indice, indice, largura, formato)
        ws.freeze_panes(1, 0)
        ws.set_row(0, 30)
        if len(saida.columns):
            ws.autofilter(0, 0, max(len(saida), 1), len(saida.columns) - 1)
    return output.getvalue()


def criar_csv(df, colunas_data=None, colunas_monetarias=None, colunas_numericas=None):
    saida = preparar_formatos(df, colunas_data or [], colunas_monetarias or [], colunas_numericas or [])
    for c in colunas_data or []:
        if c in saida:
            saida[c] = saida[c].map(lambda v: v.strftime("%d/%m/%Y") if isinstance(v, (pd.Timestamp, datetime)) else v)
    for c in set(colunas_monetarias or []) | set(colunas_numericas or []):
        if c in saida and c not in (colunas_data or []):
            saida[c] = saida[c].map(lambda v: format(v, ".2f").replace(".", ",") if isinstance(v, (int, float)) and c in (colunas_monetarias or []) else str(v).replace(".", ",") if isinstance(v, (int, float)) else v)
    return saida.to_csv(index=False, sep=";", lineterminator="\n").encode("utf-8-sig")


def main():
    st.set_page_config(page_title="Juntar Excel e CSV — ULSLA (PT)", page_icon="📚", layout="wide")
    st.title("📚 Juntar Excel e CSV — Formato Portugal")
    st.markdown("Os CSV são **interpretados como tabelas**, com cada campo na sua célula. O Excel final contém **datas e números reais**, prontos para somar, filtrar e ordenar. Documentos e códigos continuam texto.")
    ficheiros = st.file_uploader("Selecione Excel, CSV, ZIP ou RAR", type=["xlsx", "xlsm", "xls", "csv", "zip", "rar"], accept_multiple_files=True)
    if not ficheiros:
        return
    todas_folhas = st.checkbox("Juntar todas as folhas de cada Excel", value=False)
    modo = st.selectbox("Separador dos CSV", list(SEPARADORES), index=0, help="Automático (Portugal) dá prioridade ao ;, mas reconhece outros separadores quando necessário.")
    separador = SEPARADORES[modo] or "Automático"
    entradas, erros = recolher_ficheiros(ficheiros)
    blocos, controlo = [], []
    for origem, dados in entradas:
        nome = nome_ficheiro_real(origem)
        try:
            partes = ler_ficheiro_bytes(dados, nome, todas_folhas, separador)
            if not partes:
                erros.append(f"{origem}: sem linhas para consolidar.")
                continue
            blocos.extend(partes)
            for df in partes:
                controlo.append({"Ficheiro": origem, "Separador CSV": repr(df.attrs.get("separador", "—")), "Codificação": df.attrs.get("codificacao", "—"), "Colunas": len(df.columns), "Linhas": len(df)})
        except Exception as exc:
            erros.append(f"{origem}: {exc}")
    for erro in erros:
        st.warning(erro)
    if not blocos:
        return
    with st.expander("Verificar se cada CSV ficou nas colunas certas", expanded=True):
        st.dataframe(pd.DataFrame(controlo), use_container_width=True, hide_index=True)
        for i, df in enumerate(blocos):
            st.caption(f"{i+1}. {controlo[i]['Ficheiro']} — {len(df.columns)} colunas")
            st.dataframe(df.head(3), use_container_width=True, hide_index=True)
    total = pd.concat(alinhar_colunas(blocos), ignore_index=True, sort=False).fillna("")
    st.subheader("Tipos de dados — Portugal")
    datas_sugeridas = detetar_colunas_data(total)
    moedas_sugeridas = [c for c in detetar_colunas_monetarias(total) if c not in datas_sugeridas]
    c1, c2, c3 = st.columns(3)
    with c1:
        datas = st.multiselect("Datas (dd/mm/aaaa)", list(total.columns), default=datas_sugeridas)
    with c2:
        moedas = st.multiselect("Montantes (€)", [c for c in total if c not in datas and not coluna_identificador(c)], default=[c for c in moedas_sugeridas if c not in datas])
    with c3:
        disponiveis = [c for c in total if c not in datas and c not in moedas and not coluna_identificador(c)]
        numeros = st.multiselect("Outros números (quantidades, taxas…)", disponiveis,
                                default=[c for c in detetar_colunas_numericas(total, datas, moedas) if c in disponiveis])
    st.subheader("Duplicados")
    remover = st.checkbox("Remover números de documento repetidos", value=False)
    consolidado = total.copy()
    retiradas = 0
    if remover:
        colunas = list(total.columns)
        documento = st.selectbox("Coluna do documento", colunas, index=colunas.index(sugerir_coluna_documento(colunas)))
        manter = st.radio("Manter", ["Primeira ocorrência", "Última ocorrência"], horizontal=True)
        excluir_vazios = st.checkbox("Excluir linhas sem número de documento", value=False)
        chave = total[documento].map(normalizar_documento)
        com = total.loc[chave.ne("")]
        sem = total.loc[chave.eq("")]
        com = com.loc[~chave.loc[com.index].duplicated(keep="first" if manter.startswith("Primeira") else "last")]
        consolidado = com if excluir_vazios else pd.concat([com, sem]).sort_index(kind="stable")
        consolidado = consolidado.reset_index(drop=True)
        retiradas = len(total) - len(consolidado)
    st.subheader("Resultado")
    c1, c2, c3 = st.columns(3)
    c1.metric("Ficheiros processados", len(controlo))
    c2.metric("Linhas finais", f"{len(consolidado):,}".replace(",", "."))
    c3.metric("Linhas removidas", retiradas)
    with st.expander("Pré-visualização do consolidado"):
        st.dataframe(preparar_formatos(consolidado.head(200), datas, moedas, numeros), use_container_width=True, hide_index=True)
    try:
        excel_final = criar_excel(consolidado, datas, moedas, numeros)
        csv_final = criar_csv(consolidado, datas, moedas, numeros)
        a, b = st.columns(2)
        with a:
            st.download_button("⬇️ Descarregar Excel consolidado PT", excel_final, "Excel_CSV_Consolidado_PT.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
        with b:
            st.download_button("⬇️ Descarregar CSV consolidado PT", csv_final, "Excel_CSV_Consolidado_PT.csv", "text/csv", use_container_width=True)
    except Exception as exc:
        st.error(f"Não foi possível gerar os ficheiros: {exc}")
    st.caption("Excel: valores numéricos e datas como tipos reais; CSV: UTF-8 BOM, separador ; e vírgula decimal. O aspeto do separador decimal no Excel respeita as definições regionais do computador.")


if __name__ == "__main__":
    main()