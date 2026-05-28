import os
import platform
from pathlib import Path
import streamlit as st

st.write("Sistema:", platform.system())
st.write("Utilizador:", os.getlogin())
st.write("Pasta atual:", os.getcwd())

teste = Path(r"C:\Temp\Notas de Crédito\Payback")

st.write("Existe?", teste.exists())
st.write("É pasta?", teste.is_dir())

try:
    st.write("Conteúdo:")
    st.write(os.listdir(teste)[:20])
except Exception as e:
    st.error(e)
