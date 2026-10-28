from __future__ import annotations
import streamlit as st
from ulsla_branding import hero
from ulsla_launcher import config, available, ready, start_module

st.set_page_config(page_title='ULSLA | Plataforma Financeira', page_icon='🏥', layout='wide')
cfg = config()
hero(cfg.get('titulo','ULSLA | Plataforma Financeira'), cfg.get('subtitulo',''),
     'Portal institucional · módulos independentes · dados locais preservados')
st.caption('As aplicações não são todas carregadas no portal. Pode iniciar cada módulo apenas quando precisar.')

modules = cfg.get('modulos', [])
cols = st.columns(2)
for i, mod in enumerate(modules):
    with cols[i % 2]:
        with st.container(border=True):
            st.subheader(f"{mod.get('icone','')} {mod['nome']}")
            st.write(mod.get('descricao',''))
            port = int(mod['porta'])
            url = f'http://127.0.0.1:{port}'
            online = ready(port)
            if online:
                st.success(f'Ativo · porta {port}')
                st.link_button('Abrir módulo', url, use_container_width=True)
            elif available(port):
                st.warning(f'A porta {port} está ocupada, mas não responde como Streamlit.')
                st.caption('Verifique a configuração da porta ou feche o programa que a está a usar.')
            else:
                st.caption(f'Parado · porta {port}')
                if st.button('Iniciar módulo', key=f"start_{i}", use_container_width=True, type='primary'):
                    with st.spinner(f"A iniciar {mod['nome']}..."):
                        ok, message = start_module(mod['script'], port, wait=12)
                    if ok:
                        st.rerun()
                    else:
                        st.error(message)

st.divider()
a, b = st.columns([4,1])
with a:
    st.caption('Os módulos são iniciados no teu computador. O endereço 127.0.0.1 nunca funciona se o processo Streamlit correspondente estiver desligado.')
with b:
    if st.button('Atualizar estados', use_container_width=True):
        st.rerun()
