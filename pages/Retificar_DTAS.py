import copy
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET

import streamlit as st

TWOPLACES = Decimal("0.01")


def D(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    text = str(value).strip()
    if text == "":
        return Decimal("0.00")
    return Decimal(text)


def fmt_dec(value: Decimal) -> str:
    return str(value.quantize(TWOPLACES, rounding=ROUND_HALF_UP))


def get_child_text(parent, tag: str, required: bool = True):
    child = parent.find(tag)
    if child is None:
        if required:
            raise ValueError(f"Tag em falta: {tag}")
        return None
    return child.text


def set_child_decimal(parent, tag: str, value: Decimal):
    child = parent.find(tag)
    if child is None:
        raise ValueError(f"Tag em falta para atualização: {tag}")
    child.text = fmt_dec(value)


def get_root_tag_from_bytes(file_bytes: bytes) -> str:
    try:
        root = ET.fromstring(file_bytes)
        return root.tag
    except Exception as exc:
        raise ValueError(f"XML inválido: {exc}") from exc


def validate_ba_xml(file_bytes: bytes):
    root_tag = get_root_tag_from_bytes(file_bytes)
    if root_tag != "BA":
        raise ValueError(f"O ficheiro BA tem uma raiz inválida: <{root_tag}>. Esperado: <BA>.")


def validate_dtas_xml(file_bytes: bytes):
    root_tag = get_root_tag_from_bytes(file_bytes)
    if root_tag != "DTAS":
        raise ValueError(f"O ficheiro DTAS tem uma raiz inválida: <{root_tag}>. Esperado: <DTAS>.")


def sum_ba04_for_account(root: ET.Element, conta_local: str, side: str) -> Decimal:
    total = Decimal("0.00")
    found_any = False

    for registo in root.findall("./Registos/Registo"):
        conta = get_child_text(registo, "ContaLocal", required=False)
        if conta != conta_local:
            continue

        for detalhe in registo.findall("./DetalheResumo"):
            saldos = get_child_text(detalhe, "SaldosEMovimentos", required=False)
            if saldos != "BA04":
                continue

            found_any = True
            valor_txt = get_child_text(detalhe, "Credito" if side == "credito" else "Debito")
            total += D(valor_txt)

    if not found_any:
        raise ValueError(f"Não foram encontrados registos BA04 para a conta {conta_local} ({side}).")

    return total.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def find_resumo_macro(root: ET.Element, macro_rubrica: str):
    for node in root.findall("./Resumo/ResumoMacroRubrica"):
        if get_child_text(node, "MacroRubrica", required=False) == macro_rubrica:
            return node
    raise ValueError(f"ResumoMacroRubrica não encontrado: {macro_rubrica}")


def find_resumo_rubrica_agregadora(root: ET.Element, rubrica_agregadora: str):
    for node in root.findall("./Resumo/ResumoRubricaAgregadora"):
        if get_child_text(node, "RubricaAgregadora", required=False) == rubrica_agregadora:
            return node
    raise ValueError(f"ResumoRubricaAgregadora não encontrada: {rubrica_agregadora}")


def find_registo_by_rubrica(root: ET.Element, rubrica: str):
    for node in root.findall("./Registos/Registo"):
        if get_child_text(node, "Rubrica", required=False) == rubrica:
            return node
    raise ValueError(f"Registo não encontrado para a rubrica: {rubrica}")


def read_current_total_curto_prazo(root: ET.Element):
    dtas1 = find_resumo_macro(root, "DTAS1")
    dtas2 = find_resumo_macro(root, "DTAS2")

    q2 = D(get_child_text(dtas1, "TotalDividaPorNaturezaDespesaCurtoPrazo"))
    q3 = D(get_child_text(dtas2, "TotalDividaPorNaturezaDespesaCurtoPrazo"))
    total = (q2 + q3).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return total, q2, q3


def apply_adjustment(dtas_root: ET.Element, adjustment: Decimal):
    output_root = copy.deepcopy(dtas_root)

    dtas1 = find_resumo_macro(output_root, "DTAS1")
    dtas15 = find_resumo_rubrica_agregadora(output_root, "DTAS15")
    dtas151 = find_registo_by_rubrica(output_root, "DTAS151")

    # I2
    current = D(get_child_text(dtas1, "TotalDividaVincendaCurtoPrazo"))
    set_child_decimal(dtas1, "TotalDividaVincendaCurtoPrazo", current + adjustment)

    # Q2 / S2
    current = D(get_child_text(dtas1, "TotalDividaPorNaturezaDespesaCurtoPrazo"))
    new_total_dtas1 = current + adjustment
    set_child_decimal(dtas1, "TotalDividaPorNaturezaDespesaCurtoPrazo", new_total_dtas1)
    set_child_decimal(dtas1, "TotalGeralDividaPorNaturezaDespesa", new_total_dtas1)

    # W8 / AE8 / AG8
    current = D(get_child_text(dtas15, "TotalDividaVincendaCurtoPrazo"))
    set_child_decimal(dtas15, "TotalDividaVincendaCurtoPrazo", current + adjustment)

    current = D(get_child_text(dtas15, "TotalDividaPorNaturezaDespesaCurtoPrazo"))
    new_total_dtas15 = current + adjustment
    set_child_decimal(dtas15, "TotalDividaPorNaturezaDespesaCurtoPrazo", new_total_dtas15)
    set_child_decimal(dtas15, "TotalGeralDividaPorNaturezaDespesa", new_total_dtas15)

    # AL26 / AT26 / AV26
    current = D(get_child_text(dtas151, "DividaVincendaCurtoPrazo"))
    set_child_decimal(dtas151, "DividaVincendaCurtoPrazo", current + adjustment)

    current = D(get_child_text(dtas151, "TotalDividaPorNaturezaDespesaCurtoPrazo"))
    new_total_dtas151 = current + adjustment
    set_child_decimal(dtas151, "TotalDividaPorNaturezaDespesaCurtoPrazo", new_total_dtas151)
    set_child_decimal(dtas151, "TotalDividaPorNaturezaDespesa", new_total_dtas151)

    return output_root


def process_xmls(ba_bytes: bytes, dtas_bytes: bytes):
    validate_ba_xml(ba_bytes)
    validate_dtas_xml(dtas_bytes)

    ba_tree = ET.ElementTree(ET.fromstring(ba_bytes))
    dtas_tree = ET.ElementTree(ET.fromstring(dtas_bytes))

    ba_root = ba_tree.getroot()
    dtas_root = dtas_tree.getroot()

    saldo_0271_credor = sum_ba04_for_account(ba_root, "02.7.1", "credito")
    saldo_0272_devedor = sum_ba04_for_account(ba_root, "02.7.2", "debito")
    valor_correto = (saldo_0271_credor - saldo_0272_devedor).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    total_curto_prazo, q2, q3 = read_current_total_curto_prazo(dtas_root)
    ajuste = (valor_correto - total_curto_prazo).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    updated_root = apply_adjustment(dtas_root, ajuste)
    output_xml = ET.tostring(updated_root, encoding="utf-8", xml_declaration=True)

    details = {
        "saldo_0271_credor": saldo_0271_credor,
        "saldo_0272_devedor": saldo_0272_devedor,
        "valor_correto": valor_correto,
        "q2": q2,
        "q3": q3,
        "total_curto_prazo_atual": total_curto_prazo,
        "ajuste": ajuste,
    }

    return output_xml, details


def main():
    st.set_page_config(page_title="Retificação XML BA / DTAS", layout="wide")

    st.title("Retificação XML BA / DTAS")
    st.caption(
        "Carregue o XML BA (referência) e o XML DTAS (a corrigir). "
        "A aplicação usa BA04, calcula 02.7.1 crédito - 02.7.2 débito, "
        "compara com Q2 + Q3 do DTAS e devolve o XML retificado."
    )

    with st.expander("Regras aplicadas", expanded=False):
        st.markdown(
            """
- Usa apenas os valores `BA04` do ficheiro BA.
- Calcula o valor correto como:
  - **crédito da conta 02.7.1**
  - menos **débito da conta 02.7.2**
- No ficheiro DTAS, lê o total atual da dívida a curto prazo como:
  - `DTAS1 > TotalDividaPorNaturezaDespesaCurtoPrazo`
  - `DTAS2 > TotalDividaPorNaturezaDespesaCurtoPrazo`
  - ou seja, **Q2 + Q3**
- O ajuste é a diferença entre o valor correto e esse total atual.
- O ajuste é aplicado apenas nestes campos:
  - `DTAS1`
    - `TotalDividaVincendaCurtoPrazo`
    - `TotalDividaPorNaturezaDespesaCurtoPrazo`
    - `TotalGeralDividaPorNaturezaDespesa`
  - `DTAS15`
    - `TotalDividaVincendaCurtoPrazo`
    - `TotalDividaPorNaturezaDespesaCurtoPrazo`
    - `TotalGeralDividaPorNaturezaDespesa`
  - `DTAS151`
    - `DividaVincendaCurtoPrazo`
    - `TotalDividaPorNaturezaDespesaCurtoPrazo`
    - `TotalDividaPorNaturezaDespesa`
            """
        )

    col1, col2 = st.columns(2)

    with col1:
        ba_file = st.file_uploader(
            "XML BA (referência)",
            type=["xml", "XML"],
            key="ba_xml",
            help="Carregue o ficheiro BA em formato XML.",
        )

    with col2:
        dtas_file = st.file_uploader(
            "XML DTAS (a retificar)",
            type=["xml", "XML"],
            key="dtas_xml",
            help="Carregue o ficheiro DTAS em formato XML.",
        )

    if ba_file is not None:
        try:
            validate_ba_xml(ba_file.getvalue())
            st.success("Ficheiro BA válido.")
        except Exception as exc:
            st.error(f"Erro no ficheiro BA: {exc}")

    if dtas_file is not None:
        try:
            validate_dtas_xml(dtas_file.getvalue())
            st.success("Ficheiro DTAS válido.")
        except Exception as exc:
            st.error(f"Erro no ficheiro DTAS: {exc}")

    if ba_file and dtas_file:
        if st.button("Processar ficheiros", type="primary"):
            try:
                output_xml, details = process_xmls(ba_file.getvalue(), dtas_file.getvalue())

                st.success("Ficheiro retificado com sucesso.")

                c1, c2, c3 = st.columns(3)
                c1.metric("0271 credor (BA04)", fmt_dec(details["saldo_0271_credor"]))
                c2.metric("0272 devedor (BA04)", fmt_dec(details["saldo_0272_devedor"]))
                c3.metric("Valor correto", fmt_dec(details["valor_correto"]))

                c4, c5, c6 = st.columns(3)
                c4.metric("Q2", fmt_dec(details["q2"]))
                c5.metric("Q3", fmt_dec(details["q3"]))
                c6.metric("Q2 + Q3", fmt_dec(details["total_curto_prazo_atual"]))

                st.metric("Ajuste aplicado", fmt_dec(details["ajuste"]))

                original_name = dtas_file.name.rsplit(".", 1)[0]
                download_name = f"{original_name}_retificado.xml"

                st.download_button(
                    label="Descarregar XML retificado",
                    data=output_xml,
                    file_name=download_name,
                    mime="application/xml",
                )

                with st.expander("Pré-visualização do XML retificado"):
                    st.code(output_xml.decode("utf-8"), language="xml")

            except Exception as exc:
                st.error(f"Erro ao processar os ficheiros: {exc}")


if __name__ == "__main__":
    main()
