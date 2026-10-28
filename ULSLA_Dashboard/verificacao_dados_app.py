"""Controlo transversal independente das aplicações de análise."""
from pathlib import Path
import streamlit as st
from ulsla_branding import hero
from verificacao_dados import render

st.set_page_config(page_title='ULSLA | Verificação de Dados',page_icon='📋',layout='wide')
hero('ULSLA | Verificação de Dados','Todos os dados em falta, por período e por módulo.','XML · Extratos contabilísticos · Analítica · Reporte e ficheiros de apoio')
render(Path(__file__).resolve().parent,key='global_verificacao')
