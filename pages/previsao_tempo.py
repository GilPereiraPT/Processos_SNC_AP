# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import altair as alt
import requests
from datetime import datetime

# Configuração da página
st.set_page_config(
    page_title="Meteorologia: Santo André",
    page_icon="🌊",
    layout="wide",
)

# --- FUNÇÃO PARA OBTER DADOS REAIS (Open-Meteo) ---
@st.cache_data
def load_weather_data():
    # Coordenadas de Vila Nova de Santo André
    lat, lon = 38.05, -8.79
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2023-01-01&end_date=2024-12-31&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max&timezone=Europe%2FLisbon"
    
    response = requests.get(url).json()
    daily = response["daily"]
    
    df = pd.DataFrame({
        "date": pd.to_datetime(daily["time"]),
        "temp_max": daily["temperature_2m_max"],
        "temp_min": daily["temperature_2m_min"],
        "precipitation": daily["precipitation_sum"],
        "wind": daily["wind_speed_10m_max"]
    })
    return df

try:
    full_df = load_weather_data()
except Exception as e:
    st.error("Não foi possível carregar os dados meteorológicos.")
    st.stop()

# --- INTERFACE ---
st.title("🌊 Meteorologia em Vila Nova de Santo André")
st.markdown(f"Dados históricos reais obtidos para a região do Litoral Alentejano.")

st.divider()

# --- MÉTRICAS COMPARATIVAS (2024 vs 2023) ---
st.header("Resumo Anual: 2024")

df_2024 = full_df[full_df["date"].dt.year == 2024]
df_2023 = full_df[full_df["date"].dt.year == 2023]

col1, col2, col3, col4 = st.columns(4)

def delta_val(val24, val23):
    return f"{val24 - val23:.1f}"

with col1:
    max_24 = df_2024["temp_max"].max()
    st.metric("Máxima Absoluta", f"{max_24:.1f}°C", delta=f"{max_24 - df_2023['temp_max'].max():.1f}°C")

with col2:
    min_24 = df_2024["temp_min"].min()
    st.metric("Mínima Absoluta", f"{min_24:.1f}°C", delta=f"{min_24 - df_2023['temp_min'].min():.1f}°C")

with col3:
    prec_24 = df_2024["precipitation"].sum()
    st.metric("Precipitação Total", f"{prec_24:.0f} mm", delta=f"{prec_24 - df_2023['precipitation'].sum():.0f} mm")

with col4:
    wind_24 = df_2024["wind"].max()
    st.metric("Vento Máximo", f"{wind_24:.1f} km/h", delta=f"{wind_24 - df_2023['wind'].max():.1f} km/h")

st.divider()

# --- COMPARAÇÃO INTERATIVA ---
st.header("Análise Temporal")

years = full_df["date"].dt.year.unique()
selected_years = st.pills("Selecione os anos", years, default=years, selection_mode="multi")

if not selected_years:
    st.warning("Selecione pelo menos um ano para visualizar os gráficos.")
else:
    df_filtered = full_df[full_df["date"].dt.year.isin(selected_years)]

    tab1, tab2 = st.tabs(["🌡️ Temperatura", "🌧️ Precipitação & Vento"])

    with tab1:
        chart_temp = alt.Chart(df_filtered).mark_area(opacity=0.3).encode(
            x=alt.X("date:T", timeUnit="monthdate", title="Meses"),
            y=alt.Y("temp_max:Q", title="Temperatura (°C)"),
            y2="temp_min:Q",
            color=alt.Color("date:N", timeUnit="year", title="Ano"),
            tooltip=["date", "temp_max", "temp_min"]
        ).properties(height=400).interactive()
        
        st.altair_chart(chart_temp, use_container_width=True)

    with tab2:
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("Precipitação Acumulada")
            chart_prec = alt.Chart(df_filtered).mark_bar().encode(
                x=alt.X("date:T", timeUnit="month", title="Mês"),
                y=alt.Y("precipitation:Q", aggregate="sum", title="Soma mm"),
                color="date:N",
                xOffset="date:N"
            )
            st.altair_chart(chart_prec, use_container_width=True)
            
        with c2:
            st.subheader("Velocidade do Vento")
            chart_wind = alt.Chart(df_filtered).mark_line().encode(
                x=alt.X("date:T", timeUnit="monthdate"),
                y=alt.Y("wind:Q", title="km/h"),
                color="date:N"
            )
            st.altair_chart(chart_wind, use_container_width=True)

st.divider()
with st.expander("Ver Tabela de Dados"):
    st.dataframe(full_df, use_container_width=True)
