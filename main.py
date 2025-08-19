import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date, time as dtime, timedelta
import pytz
import plotly.express as px
import time
from typing import Optional, Dict

# ======================== CONFIG ========================
SUPABASE_URL = "https://qjoomrgjitlzgmdhteuz.supabase.co"
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqb29tcmdqaXRsemdtZGh0ZXV6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTE4MjQzNjcsImV4cCI6MjA2NzQwMDM2N30.GM5Zh8w7n42ZHvBC_DjWFrKUziH0pE6TOydsXk3rp8U"
HEADERS = {"apikey": API_KEY, "Authorization": f"Bearer {API_KEY}"}
TZ_BR = pytz.timezone("America/Sao_Paulo")

# >>>>>>>>>>>>>>>>>> HORÁRIO INICIAL DO INTERVALO (mude aqui) <<<<<<<<<<<<<<<<<<
# Use None para pegar o dia inteiro; ou "HH:MM", ex.: "17:00"
TIME_INICIO_STR: Optional[str] = None # ex.: "17:00" ou None

# ======================== LIMITES (oxi1/oxi2/co1/co2 removidos) ========================
LIMITES = {
    "cc1": {"min": 1000, "max": 3000, "unit": "[mA]"},
    "cc2": {"min": 1000, "max": 3000, "unit": "[mA]"},
    "cc3": {"min": 1000, "max": 3000, "unit": "[mA]"},
    "cc4": {"min": 1000, "max": 3000, "unit": "[mA]"},
    "orp": {"min": 600, "max": 900, "unit": "[mV]"},
}

# Limites para os gráficos da tabela readings
READING_LIMITS: Dict[str, Dict[str, float]] = {
    "tensao_v":  {"min": 200, "max": 250, "unit": "[V]"},
    "corrente_a":{"min": 1,   "max": 3,   "unit": "[A]"},
    "potencia_w":{"min": 300, "max": 400,  "unit": "[W]"},
}

# ======================== HELPERS ========================
def parse_hhmm(s: Optional[str]) -> Optional[dtime]:
    if not s:
        return None
    try:
        h, m = (int(p) for p in s.strip().split(":")[:2])
        return dtime(hour=h, minute=m)
    except Exception:
        return None

TIME_INICIO: Optional[dtime] = parse_hhmm(TIME_INICIO_STR)

def iso_z(dt_utc: datetime) -> str:
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

def day_range_utc(selected_date: date, start_time: Optional[dtime]):
    """
    Retorna (inicio_utc, fim_utc) para a data selecionada.
    - inicio = 00:00 local OU start_time local, se fornecido.
    - fim    = 00:00 do dia seguinte (local).
    """
    start_local = TZ_BR.localize(
        datetime.combine(selected_date, start_time if start_time else dtime.min)
    )
    next_local = TZ_BR.localize(datetime.combine(selected_date + timedelta(days=1), dtime.min))
    return start_local.astimezone(pytz.UTC), next_local.astimezone(pytz.UTC)

def request_supabase(table: str, params_list):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    return requests.get(url, headers=HEADERS, params=params_list)

def get_table_by_date(table_name: str, ts_col: str, selected_date: date,
                      start_time: Optional[dtime]) -> pd.DataFrame:
    start_utc, next_utc = day_range_utc(selected_date, start_time)
    params = [
        ("select", "*"),
        (ts_col, f"gte.{iso_z(start_utc)}"),
        (ts_col, f"lt.{iso_z(next_utc)}"),
        ("order", f"{ts_col}.asc"),
    ]
    resp = request_supabase(table_name, params)
    if resp.status_code != 200:
        st.error(f"[{table_name}] Erro {resp.status_code}: {resp.text}")
        return pd.DataFrame()
    return pd.DataFrame(resp.json())

def to_local_datetime(series) -> pd.Series:
    s = pd.to_datetime(series, utc=True, errors="coerce")
    return s.dt.tz_convert(TZ_BR)

def norm_psa(v) -> str:
    s = str(v).strip().lower()
    if s in ("p1", "psa1", "psa 1", "psa-1"): return "psa1"
    if s in ("p2", "psa2", "psa 2", "psa-2"): return "psa2"
    return s or "desconhecido"

def filter_nonzero(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col not in df.columns:
        return df.iloc[0:0].copy()
    vals = pd.to_numeric(df[col], errors="coerce")
    mask = vals.ne(0) & vals.notna()
    out = df.loc[mask].copy()
    out[col] = vals[mask]
    return out

def cap_upper(df: pd.DataFrame, col: str, upper: Optional[float]) -> pd.DataFrame:
    """Aplica corte superior; se upper=None, não filtra."""
    if upper is None or col not in df.columns:
        return df.copy()
    vals = pd.to_numeric(df[col], errors="coerce")
    mask = vals.le(upper) & vals.notna()
    out = df.loc[mask].copy()
    out[col] = vals[mask]
    return out

def get_table_by_date_respecting_db_tz(
    table_name: str,
    ts_col: str,
    selected_date: date,
    start_time: Optional[dtime],
    db_tz_is_local: bool = True,     # << se True, manda -03:00; se False, manda UTC (Z)
    tz=TZ_BR
) -> pd.DataFrame:
    """
    Busca registros em [início, fim) considerando a *visão de tempo do banco*.
    - db_tz_is_local=True: assume que o banco/coluna é comparada em America/Sao_Paulo;
      envia strings com offset -03:00/-02:00 (conforme horário vigente).
    - db_tz_is_local=False: comportamento anterior (converte janela local para UTC e envia 'Z').
    """
    start_local, end_local = day_range_local(selected_date, start_time, tz)

    if db_tz_is_local:
        start_str = iso_with_offset(start_local)  # ex.: 2025-08-13T00:00:00-03:00
        end_str   = iso_with_offset(end_local)    # ex.: 2025-08-14T00:00:00-03:00
    else:
        start_str = iso_z(start_local.astimezone(pytz.UTC))  # ex.: ...Z
        end_str   = iso_z(end_local.astimezone(pytz.UTC))

    params = [
        ("select", "*"),
        (ts_col, f"gte.{start_str}"),
        (ts_col, f"lt.{end_str}"),
        ("order", f"{ts_col}.asc"),
    ]
    resp = request_supabase(table_name, params)
    if resp.status_code != 200:
        st.error(f"[{table_name}] Erro {resp.status_code}: {resp.text}")
        return pd.DataFrame()
    return pd.DataFrame(resp.json())

# ===== Helpers de fuso =====
def day_range_local(selected_date: date, start_time: Optional[dtime], tz=TZ_BR):
    """Retorna (inicio_local, fim_local) como datetimes *com timezone tz*."""
    start_local = tz.localize(datetime.combine(selected_date, start_time or dtime.min))
    next_local  = tz.localize(datetime.combine(selected_date + timedelta(days=1), dtime.min))
    return start_local, next_local

def iso_with_offset(dt_local: datetime) -> str:
    """Formata como RFC3339 com offset, ex.: 2025-08-13T00:00:00-03:00"""
    # garante sem micros para evitar ruído
    return dt_local.replace(microsecond=0).isoformat()

# ======================== APP ========================
st.set_page_config(page_title="Agrizon Dashboard", layout="wide")
st.title("🌱⚛️ Agrizon Dashboard")

selected_date = st.date_input("📅 Escolha a data", datetime.now().date())
REFRESH_INTERVAL = 30
inicio_txt = TIME_INICIO.strftime("%H:%M") if TIME_INICIO else "00:00 (dia inteiro)"
st.caption( f"Auto-refresh só quando a cada {REFRESH_INTERVAL} segundos se a data for hoje ({datetime.now().date()}).")

# ---------------- LEITURA TABELAS ----------------
st.subheader("⚡ Leituras  das CAMARAS (Correntes) e ORP (Tensao)")
# ---------------- LEITURA TABELAS ----------------
df = get_table_by_date_respecting_db_tz("agrizon",  "timestemp", selected_date, TIME_INICIO, db_tz_is_local=True)
df_read = get_table_by_date_respecting_db_tz("readings", "ts", selected_date, TIME_INICIO, db_tz_is_local=True)

# Cria ts_local ANTES de usar nos warnings
if not df.empty:
    df["ts_local"] = to_local_datetime(df["timestemp"])
if not df_read.empty:
    df_read["ts_local"] = to_local_datetime(df_read["ts"])

# ================== Warnings (independente de agrizon estar vazio) ==================
st.subheader("📋 Log de Warnings")

warnings_list = []

# warnings da tabela agrizon
if not df.empty and "warning" in df.columns:
    log_df = df[["ts_local", "warning"]].dropna(subset=["warning"])
    log_df = log_df[log_df["warning"].astype(str).str.strip() != ""]
    if not log_df.empty:
        warnings_list.append(log_df)

# warnings da tabela readings
if not df_read.empty and "warning" in df_read.columns:
    log_read_df = df_read[["ts_local", "warning"]].dropna(subset=["warning"])
    log_read_df = log_read_df[log_read_df["warning"].astype(str).str.strip() != ""]
    if not log_read_df.empty:
        warnings_list.append(log_read_df)

# concatena e exibe
if warnings_list:
    all_warnings = pd.concat(warnings_list, ignore_index=True).sort_values("ts_local")
    txt = "\n".join(f"[{t.strftime('%Y-%m-%d %H:%M:%S')}] - {w}"
                    for t, w in zip(all_warnings["ts_local"], all_warnings["warning"]))
    st.text_area("Warnings", txt, height=200, disabled=True)
else:
    st.text("Sem warnings para o período.")


for col, cfg in reversed(list(LIMITES.items())):
    if col in df.columns:
        df_plot = filter_nonzero(df, col)
        upper = 6000 if col != "orp" else None  # não corta ORP
        df_plot = cap_upper(df_plot, col, upper)
        if df_plot.empty:
            continue

        fig = px.line(df_plot, x="ts_local", y=col, title=f"{col.upper()} {cfg['unit']}", markers=True)
        fig.add_hline(y=cfg["min"], line_dash="dot", line_color="lightblue",
                      annotation_text=f"Min: {cfg['min']} {cfg['unit']}", annotation_position="bottom left")
        fig.add_hline(y=cfg["max"], line_dash="dot", line_color="red",
                      annotation_text=f"Max: {cfg['max']} {cfg['unit']}", annotation_position="top left")
        fig.update_layout(
            xaxis_title="Hora (HH:MM:SS)",
            yaxis_title=f"{col.upper()} {cfg['unit']}",
            hovermode="x unified",
            xaxis_tickformat="%H:%M:%S",
            xaxis_tickangle=-90
        )
        st.plotly_chart(fig, use_container_width=True)

# ---------------- READINGS (quebra por PSA; zeros removidos; limites) ----------------
st.subheader("⚡ Leituras dos PSAs: Tensão, Corrente e Potência")

if df_read.empty:
    st.info(f"Nenhum dado encontrado em 'leitura de psas' para {selected_date}.")
else:
    df_read["ts_local"] = to_local_datetime(df_read["ts"])
    df_read["psa_norm"] = df_read.get("psa", "dados").apply(norm_psa) if "psa" in df_read.columns else "dados"
    df_read = df_read.sort_values("ts_local")

    light_blue = "#ADD8E6"
    light_green = "#90EE90"
    color_map = {"psa1": light_blue, "psa2": light_green, "p1": light_blue, "p2": light_green, "dados": light_blue}

    def plot_readings_segmented_nonzero(y_col: str, title: str, y_label: str, limits: Optional[Dict[str, float]]):
        if y_col not in df_read.columns:
            return
        df_y = filter_nonzero(df_read, y_col)
        if df_y.empty:
            return

        # segmenta por mudanças de psa_norm (para não ligar blocos distintos)
        df_y = df_y.sort_values("ts_local")
        switch = (df_y["psa_norm"] != df_y["psa_norm"].shift()).astype(int)
        df_y["segment"] = switch.cumsum()
        df_y["line_group"] = df_y["psa_norm"] + "_seg" + df_y["segment"].astype(str)

        fig = px.line(
            df_y, x="ts_local", y=y_col,
            color="psa_norm",
            line_group="line_group",
            markers=True,
            color_discrete_map=color_map,
            category_orders={"psa_norm": ["psa1", "psa2"]},
            title=title
        )

        if limits is not None:
            fig.add_hline(y=limits["min"], line_dash="dot", line_color="lightblue",
                          annotation_text=f"Min: {limits['min']} {limits['unit']}", annotation_position="bottom left")
            fig.add_hline(y=limits["max"], line_dash="dot", line_color="red",
                          annotation_text=f"Max: {limits['max']} {limits['unit']}", annotation_position="top left")

        fig.update_layout(
            xaxis_title="Hora (HH:MM:SS)",
            yaxis_title=y_label,
            hovermode="x unified",
            xaxis_tickformat="%H:%M:%S",
            xaxis_tickangle=-90,
            legend_title_text="PSA"
        )
        st.plotly_chart(fig, use_container_width=True)


    plot_readings_segmented_nonzero("potencia_w", "Potência [W]",
                                    "Potência [W]", READING_LIMITS.get("potencia_w"))
    plot_readings_segmented_nonzero("tensao_v",  "Tensão [V]", "Tensão [V]",   READING_LIMITS.get("tensao_v"))
    plot_readings_segmented_nonzero("corrente_a","Corrente [A]", "Corrente [A]", READING_LIMITS.get("corrente_a"))


# ---------------- AUTOREFRESH somente para hoje ----------------
if selected_date == datetime.now().date():
    time.sleep(30)
    st.rerun()
