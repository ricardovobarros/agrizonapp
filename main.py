import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import pytz
import plotly.express as px

# ======================== CONFIG SUPABASE ========================
SUPABASE_URL = "https://qjoomrgjitlzgmdhteuz.supabase.co"
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqb29tcmdqaXRsemdtZGh0ZXV6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTE4MjQzNjcsImV4cCI6MjA2NzQwMDM2N30.GM5Zh8w7n42ZHvBC_DjWFrKUziH0pE6TOydsXk3rp8U"
TABLE_NAME = "agrizon"

HEADERS = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}"
}

# ======================== LIMITES E UNIDADES ========================
LIMITES = {
    'cc1': {'min': 1, 'max': 3, 'unit': '[A]'},
    'cc2': {'min': 1, 'max': 3, 'unit': '[A]'},
    'cc3': {'min': 1, 'max': 3, 'unit': '[A]'},
    'cc4': {'min': 1, 'max': 3, 'unit': '[A]'},
    'co1': {'min': 1.3, 'max': 2, 'unit': '[A]'},
    'co2': {'min': 1.3, 'max': 2, 'unit': '[A]'},
    'oxi1': {'min': 60, 'max': 95.5, 'unit': '[%]'},
    'oxi2': {'min': 60, 'max': 95.5, 'unit': '[%]'},
    'orp': {'min': 600, 'max': 900, 'unit': '[mV]'},
}

# ======================== FUNÇÃO DE CONSULTA ========================
def get_today_data():
    tz_br = pytz.timezone('America/Sao_Paulo')
    now_br = datetime.now(tz_br)

    start_day = now_br.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end_day = now_br.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

    query = (
        f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
        f"?select=*"
        f"&timestemp=gte.{start_day}"
        f"&timestemp=lte.{end_day}"
        f"&order=timestemp.asc"
    )

    response = requests.get(query, headers=HEADERS)

    if response.status_code != 200:
        st.error(f"Erro {response.status_code}: {response.text}")
        return pd.DataFrame()

    return pd.DataFrame(response.json())

# ======================== CONFIG DA PÁGINA ========================
st.set_page_config(page_title="Agrizon Dashboard", layout="wide")
st.title("🌱⚛️ Agrizon Dashboard")
st.write(f'📅 Leituras do Dia {datetime.now().date()}')

REFRESH_INTERVAL = 30  # segundos
st.write(f"🔄 Atualizando automaticamente a cada {REFRESH_INTERVAL} segundos.")

# Atualização automática sem perder estado
count = st.experimental_memo(lambda: 0)
st_autorefresh = st.experimental_rerun
st_autorefresh()

# ======================== DADOS DO DIA ========================
df = get_today_data()

if df.empty:
    st.warning("Nenhum dado encontrado hoje.")
else:
    df['timestemp'] = pd.to_datetime(df['timestemp'])
    df['Hora'] = df['timestemp'].dt.strftime('%H:%M:%S')

    st.subheader("📋 Log de Warnings")
    log_df = df[['timestemp', 'warning']].dropna()
    log_df = log_df[log_df['warning'].str.strip() != ""]
    log_df['timestemp'] = log_df['timestemp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    log_text = "\n".join(f"[{row['timestemp']}] - {row['warning']}" for _, row in log_df.iterrows())
    st.text_area(" ", log_text, height=200, disabled=True)

    # Gráficos
    for col, config in reversed(list(LIMITES.items())):
        if col in df.columns:
            unit = config['unit']
            fig = px.line(df, x='Hora', y=col, title=f"{col.upper()} - {unit}", markers=True)
            fig.add_hline(y=config['min'], line_dash="dot", line_color="lightblue",
                          annotation_text=f"Min: {config['min']} {unit}", annotation_position="bottom left")
            fig.add_hline(y=config['max'], line_dash="dot", line_color="red",
                          annotation_text=f"Max: {config['max']} {unit}", annotation_position="top left")
            fig.update_layout(xaxis_title="Hora", yaxis_title=f"{col.upper()} {unit}", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

# ======================== CONTROLE DE DISPOSITIVOS ========================
st.title("Controle de Dispositivos")

# Inicializa session_state
for key in ["PSA1", "PSA2", "Camara1", "Camara2", "Camara3", "Camara4"]:
    if key not in st.session_state:
        st.session_state[key] = False

# Renderiza toggles
st.session_state["PSA1"] = st.toggle("PSA 1", value=st.session_state["PSA1"])
st.session_state["PSA2"] = st.toggle("PSA 2", value=st.session_state["PSA2"])
st.session_state["Camara1"] = st.toggle("Câmara 1", value=st.session_state["Camara1"])
st.session_state["Camara2"] = st.toggle("Câmara 2", value=st.session_state["Camara2"])
st.session_state["Camara3"] = st.toggle("Câmara 3", value=st.session_state["Camara3"])
st.session_state["Camara4"] = st.toggle("Câmara 4", value=st.session_state["Camara4"])

estado = {k: v for k, v in st.session_state.items() if k in ["PSA1", "PSA2", "Camara1", "Camara2", "Camara3", "Camara4"]}
ip_esp32 = "192.168.15.41"

if st.button("Atualizar Dispositivos"):
    try:
        r = requests.post(f"http://{ip_esp32}/controle", json=estado, timeout=5)
        if r.status_code == 200:
            st.success("✅ Comando enviado com sucesso!")
        else:
            st.error(f"Erro no ESP32: {r.status_code}")
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
