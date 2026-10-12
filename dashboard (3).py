import streamlit as st
import pandas as pd
import plotly.express as px
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import glob
import os
import time
import tempfile
from fpdf import FPDF

st.set_page_config(page_title="Monitoreo Energético EPET N°3", page_icon="⚡", layout="wide")

st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background-color: rgba(34, 197, 94, 0.08);
        border-left: 4px solid #22c55e;
        padding: 12px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

if "contado" not in st.session_state:
    try:
        with open("contador_visitas.txt", "r") as f:
            contador_visitas = int(f.read().strip())
    except FileNotFoundError:
        contador_visitas = 0
    contador_visitas += 1
    with open("contador_visitas.txt", "w") as f:
        f.write(str(contador_visitas))
    st.session_state["contado"] = True
    st.session_state["contador_visitas"] = contador_visitas
else:
    contador_visitas = st.session_state["contador_visitas"]

with st.sidebar:
    st.title("⚡ EDUCATIC 2026")
    st.caption("EPET N°3 · Monitoreo Energético")
    st.markdown("---")
    st.metric("👀 Visitas al dashboard", contador_visitas)
    st.markdown("---")
    archivos_subidos = st.file_uploader("Cargar CSV (sistema 1.0 o 2.0)", type="csv", accept_multiple_files=True)
    st.caption("Si no cargás nada, se usan los datos guardados en la página.")

# ---------------------------------------------------------------------
# Datos: sistema 1.0 (luz, temperatura, humedad, corriente) y
# sistema 2.0 (capturar_datos_v2.py: temp_aula, calefactor, ventana, PIR, gas...)
# ---------------------------------------------------------------------
FACTOR_CO2 = 0.22   # kg CO2/kWh · CAMMESA, Resumen Anual 2025 (emisiones unitarias de la oferta total)
COLS_V2 = {"temp_aula", "hum_aula", "i_enchufe", "p_enchufe", "calef_on", "ventana_abierta", "ocupada", "gas"}


def leer_csv(fuente):
    d = pd.read_csv(fuente, on_bad_lines="skip")
    d.columns = [c.strip() for c in d.columns]
    return d


def a_formato_v1(d):
    return pd.DataFrame({"fecha_hora": d["fecha_hora"], "luz": d["luz"], "temperatura": d["temp_aula"],
                         "humedad": d["hum_aula"], "corriente": d["i_enchufe"]})


datasets = {}      # nombre -> DataFrame en formato 1.0 (para las pestañas generales)
datos_v2 = []      # DataFrames del sistema 2.0 (para la pestaña Aula y calefacción)
if os.path.exists("datos_sala_informatica.csv"):
    datasets["Sala de informática · agosto (sistema 1.0)"] = leer_csv("datos_sala_informatica.csv")
fuentes = [(os.path.basename(p), p) for p in sorted(glob.glob("datos_*.csv")) if os.path.basename(p) != "datos_sala_informatica.csv"]
fuentes += [(f.name, f) for f in (archivos_subidos or [])]
for nombre, fuente in fuentes:
    try:
        d = leer_csv(fuente)
    except Exception:
        continue
    if COLS_V2.issubset(d.columns):
        d["archivo"] = nombre
        if "ubic" not in d.columns:
            d["ubic"] = nombre
        datos_v2.append(d)
        datasets[f"{nombre} (sistema 2.0)"] = a_formato_v1(d)
    elif {"fecha_hora", "luz", "temperatura", "humedad", "corriente"}.issubset(d.columns):
        datasets[nombre] = d

if not datasets:
    st.error("No hay datos para mostrar. Cargá un CSV en la barra lateral.")
    st.stop()

with st.sidebar:
    nombres = list(datasets.keys())
    elegido = st.selectbox("📂 Jornada para el análisis general", nombres,
                           index=len(nombres) - 1 if archivos_subidos else 0)
    st.markdown("---")
    auto_refresh = st.checkbox("🔄 Modo demo en vivo (actualiza cada 5s)")

# --- Carga y limpieza ---
df = datasets[elegido].copy()
df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
for columna in ["luz", "temperatura", "humedad", "corriente"]:
    df[columna] = pd.to_numeric(df[columna], errors="coerce")

total_bruto = len(df)
df = df.dropna()
tras_dropna = len(df)

filas_antes = len(df)
df = df[(df["temperatura"] > 15) & (df["temperatura"] < 40)]
df = df[(df["humedad"] > 15) & (df["humedad"] < 100)]
filas_filtradas = filas_antes - len(df)

df["potencia_watts"] = df["corriente"].abs() * 220
df["hora"] = df["fecha_hora"].dt.hour
df = df.reset_index(drop=True)
horas_totales = (df["fecha_hora"].max() - df["fecha_hora"].min()).total_seconds() / 3600

# --- Detección de sesiones de uso de la pava (agrupando picos cercanos) ---
umbral_pava = 1000
tiempos_altos = df.loc[df["potencia_watts"] > umbral_pava, "fecha_hora"].reset_index(drop=True)

sesiones = []
if len(tiempos_altos) > 0:
    inicio = tiempos_altos.iloc[0]
    anterior = tiempos_altos.iloc[0]
    for t in tiempos_altos.iloc[1:]:
        if (t - anterior).total_seconds() > 150:  # más de 2.5 min de diferencia = nueva sesión
            sesiones.append((inicio, anterior))
            inicio = t
        anterior = t
    sesiones.append((inicio, anterior))

picos_eventos = []
for inicio, fin in sesiones:
    ventana = df[(df["fecha_hora"] >= inicio) & (df["fecha_hora"] <= fin + pd.Timedelta(seconds=5))]
    if len(ventana) > 0:
        picos_eventos.append(ventana.loc[ventana["potencia_watts"].idxmax()])

tiempo_pava_seg = (df["potencia_watts"] > umbral_pava).sum()

# --- Luz vs potencia ---
umbral_luz = df["luz"].median()
umbral_potencia = df["potencia_watts"].median()
posible_desperdicio = df[(df["luz"] > umbral_luz) & (df["potencia_watts"] > umbral_potencia)]
porcentaje_desperdicio = 100 * len(posible_desperdicio) / len(df)
correlacion_luz_potencia = df["luz"].corr(df["potencia_watts"])

# --- Temperatura mañana/tarde ---
manana_mask = df["hora"] < 13
temp_manana = df[manana_mask]["temperatura"].mean()
temp_tarde = df[~manana_mask]["temperatura"].mean()

# --- Energía y ambiente ---
factor_co2 = FACTOR_CO2
energia_kwh = (df["potencia_watts"].mean() / 1000) * horas_totales
co2_kg = energia_kwh * factor_co2
co2_mensual = co2_kg * 20

def calcular_eficiencia(pct):
    if pct < 5:
        return "A", "#1a9641", "Excelente"
    elif pct < 10:
        return "B", "#a6d96a", "Bueno"
    elif pct < 20:
        return "C", "#ffffbf", "Regular"
    elif pct < 30:
        return "D", "#fdae61", "Mejorable"
    else:
        return "E", "#d7191c", "Ineficiente"

letra, color_letra, etiqueta_letra = calcular_eficiencia(porcentaje_desperdicio)

# --- Traducir CO2 a algo mas relatable ---
def co2_a_relatable(co2_kg):
    arbol_kg_anio = 21  # kg de CO2 que absorbe un arbol promedio por año
    km_por_kg = 1 / 0.192  # km recorridos en auto promedio por kg de CO2
    dias_arbol = (co2_kg / arbol_kg_anio) * 365
    km_auto = co2_kg * km_por_kg
    return dias_arbol, km_auto

# ======================================================================
# ENCABEZADO
# ======================================================================
st.title("⚡ Relevamiento energético: hacia un uso eficiente de la energía")
st.caption(f"EPET N°3 Neuquén · Finalista EDUCATIC 2026 · Mostrando: {elegido}")
if filas_filtradas > 0:
    st.caption(f"ℹ️ Se filtraron {filas_filtradas} lecturas puntuales inválidas (glitches del sensor DHT22).")

col_kpis, col_sello = st.columns([4, 1])
with col_kpis:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💡 Luz promedio", f"{df['luz'].mean():.0f}")
    c2.metric("🌡️ Temperatura", f"{df['temperatura'].mean():.1f} °C")
    c3.metric("💧 Humedad", f"{df['humedad'].mean():.1f} %")
    c4.metric("🔌 Potencia", f"{df['potencia_watts'].mean():.1f} W")
    c5.metric("📊 Registros", f"{len(df):,}")
with col_sello:
    st.markdown(f"""
    <div style="background-color:{color_letra}; border-radius:10px; padding:8px; text-align:center;">
        <div style="font-size:11px; color:#1a1a1a; font-weight:bold;">EFICIENCIA</div>
        <div style="font-size:32px; font-weight:bold; color:#1a1a1a; line-height:1;">{letra}</div>
        <div style="font-size:10px; color:#1a1a1a;">{etiqueta_letra}</div>
    </div>
    """, unsafe_allow_html=True)

tab1, tab_v2, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["📈 Gráficos", "🔥 Aula y calefacción", "🔍 Patrones de consumo", "📝 Informe completo", "📋 Datos", "ℹ️ Proyecto", "🎮 Simulador", "🏠 Para vos"])

# ======================================================================
# TAB 1 - GRAFICOS
# ======================================================================
with tab1:
    for col, nombre, color in [("luz", "Luz ambiente", "#f59e0b"),
                                 ("temperatura", "Temperatura (°C)", "#ef4444"),
                                 ("humedad", "Humedad (%)", "#3b82f6")]:
        fig = px.line(df, x="fecha_hora", y=col, title=nombre)
        fig.update_traces(line_color=color)
        fig.update_layout(height=280, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    fig_pot = px.line(df, x="fecha_hora", y="potencia_watts", title="Potencia (W)")
    fig_pot.update_traces(line_color="#22c55e")
    fig_pot.update_layout(height=320, margin=dict(t=40, b=20))
    for i, pico in enumerate(picos_eventos):
        fig_pot.add_annotation(
            x=pico["fecha_hora"], y=pico["potencia_watts"],
            text="🫖 Pava" if i == 0 else "🫖",
            showarrow=True, arrowhead=2, arrowcolor="#854f0b",
            font=dict(size=11, color="#854f0b"), ay=-35
        )
    st.plotly_chart(fig_pot, use_container_width=True)
    if picos_eventos:
        st.caption(f"📍 Se detectaron {len(picos_eventos)} sesiones de uso de la pava eléctrica durante la jornada (agrupando picos cercanos del termostato).")

    st.markdown("**Consumo promedio por hora del día**")
    consumo_por_hora = df.groupby("hora")["potencia_watts"].mean().reset_index()
    fig_hora = px.bar(consumo_por_hora, x="hora", y="potencia_watts",
                       labels={"hora": "Hora del día", "potencia_watts": "Potencia promedio (W)"})
    fig_hora.update_traces(marker_color="#8b5cf6")
    fig_hora.update_layout(height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_hora, use_container_width=True)

# ======================================================================
# TAB V2 - AULA Y CALEFACCION (sistema 2.0)
# ======================================================================
with tab_v2:
    st.subheader("🔥 Sistema 2.0: energía, calefacción y aire del aula")
    st.caption("Sensores nuevos: sonda en el calefactor (DS18B20), sensor magnético de ventana, sensor de presencia (PIR), "
               "sensor de humo/gas (MQ-2), DHT22, LDR y ACS712 en el enchufe de un aparato.")

    if not datos_v2:
        st.info("Todavía no hay datos del sistema 2.0 cargados en la página. "
                "Podés cargar un archivo `datos_<lugar>_<fecha>.csv` desde la barra lateral.")
    else:
        TEMP_MAX = 21.0   # Secretaría de Energía: 18-21 °C en invierno
        kcal_h = st.number_input("Potencia del calefactor (kcal/h, de la chapita)", value=3000, step=100,
                                 help="Se usa para estimar el gas consumido. Cambialo por el valor de la chapita del calefactor medido.")
        PCI_GAS = 9300    # kcal/m³, poder calorífico aproximado del gas natural
        CO2_GAS = 2.0     # kg CO2 por m³ de gas natural (aproximado)

        v2 = pd.concat(datos_v2, ignore_index=True)
        num = [c for c in v2.columns if c not in ("fecha_hora", "ubic", "archivo")]
        v2[num] = v2[num].apply(pd.to_numeric, errors="coerce")
        v2["fecha_hora"] = pd.to_datetime(v2["fecha_hora"], errors="coerce")
        v2 = v2.dropna(subset=["fecha_hora", "t_s"]).sort_values(["archivo", "t_s"])
        dt = v2.groupby("archivo")["t_s"].diff().fillna(1).clip(lower=0)
        dt[dt > 10] = 0          # huecos largos = Arduino desconectado
        v2["dt"] = dt

        def resumen_lugar(g):
            minutos = lambda cond: g.loc[cond, "dt"].sum() / 60
            h_calef = g.loc[g["calef_on"] == 1, "dt"].sum() / 3600
            kwh = (g["p_enchufe"].fillna(0) * g["dt"]).sum() / 3.6e6
            m3 = kcal_h / PCI_GAS * h_calef
            return pd.Series({
                "Horas medidas": g["dt"].sum() / 3600,
                "Energía del aparato (kWh)": kwh,
                "CO₂ electricidad (kg)": kwh * FACTOR_CO2,
                "Horas de calefactor": h_calef,
                "Gas estimado (m³)": m3,
                "CO₂ gas (kg, aprox.)": m3 * CO2_GAS,
                "Min. calefactor + ventana abierta": minutos((g["calef_on"] == 1) & (g["ventana_abierta"] == 1)),
                f"Min. con calefactor y más de {TEMP_MAX:.0f} °C": minutos((g["calef_on"] == 1) & (g["temp_aula"] > TEMP_MAX)),
                "Min. con consumo y aula vacía": minutos((g["ocupada"] == 0) & (g["p_enchufe"] > 0)),
                "Alarmas de humo/gas (lecturas)": int((g["alarma_gas"] == 1).sum()) if "alarma_gas" in g else 0,
            })

        tabla = v2.groupby("ubic").apply(resumen_lugar)
        st.markdown("**Resumen por lugar**")
        st.dataframe(tabla.T.style.format("{:.2f}"), use_container_width=True)
        st.caption(f"Electricidad: {FACTOR_CO2} kg CO₂/kWh (CAMMESA, Resumen Anual 2025). Gas: estimado con la potencia "
                   f"del calefactor, {PCI_GAS} kcal/m³ y ~{CO2_GAS} kg CO₂/m³ (valores aproximados). "
                   f"Temperatura recomendada en invierno: 18 a 21 °C (Secretaría de Energía).")

        lugar = st.selectbox("📍 Ver el detalle de un lugar", list(tabla.index))
        d = v2[v2["ubic"] == lugar]
        r = tabla.loc[lugar]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("🔥🪟 Calefactor + ventana", f"{r['Min. calefactor + ventana abierta']:.0f} min")
        k2.metric("🌡️ Sobrecalefacción", f"{r[f'Min. con calefactor y más de {TEMP_MAX:.0f} °C']:.0f} min")
        k3.metric("🔌 Consumo con aula vacía", f"{r['Min. con consumo y aula vacía']:.0f} min")
        k4.metric("🌍 CO₂ total estimado", f"{r['CO₂ electricidad (kg)'] + r['CO₂ gas (kg, aprox.)']:.2f} kg")

        fig_t = px.line(d, x="fecha_hora", y=["temp_aula", "t_calef"],
                        labels={"value": "°C", "fecha_hora": "", "variable": ""},
                        title="Temperatura del aula y del calefactor")
        fig_t.add_hline(y=TEMP_MAX, line_dash="dash", line_color="#C62828", annotation_text="21 °C")
        fig_t.update_layout(height=320, margin=dict(t=40, b=20))
        st.plotly_chart(fig_t, use_container_width=True)

        estados = d[["fecha_hora", "calef_on", "ventana_abierta", "ocupada"]].rename(columns={
            "calef_on": "Calefactor prendido", "ventana_abierta": "Ventana abierta", "ocupada": "Aula ocupada"})
        estados = estados.melt("fecha_hora", var_name="Estado", value_name="on")
        fig_e = px.area(estados, x="fecha_hora", y="on", facet_row="Estado", color="Estado",
                        color_discrete_sequence=["#EF6C00", "#1976D2", "#2E7D32"], line_shape="hv",
                        title="¿Cuándo estuvo prendido el calefactor, abierta la ventana y ocupada el aula?")
        fig_e.update_yaxes(visible=False)
        fig_e.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        fig_e.update_layout(height=360, showlegend=False, margin=dict(t=50, b=20))
        st.plotly_chart(fig_e, use_container_width=True)

        g1, g2 = st.columns(2)
        fig_p = px.line(d, x="fecha_hora", y="p_enchufe", title="Potencia del aparato medido (W)",
                        labels={"p_enchufe": "W", "fecha_hora": ""})
        fig_p.update_traces(line_color="#2E75B6")
        fig_p.update_layout(height=280, margin=dict(t=40, b=20))
        g1.plotly_chart(fig_p, use_container_width=True)
        fig_g = px.line(d, x="fecha_hora", y="gas", title="Sensor de humo / gas (MQ-2)",
                        labels={"gas": "lectura", "fecha_hora": ""})
        fig_g.update_traces(line_color="#C62828")
        fig_g.update_layout(height=280, margin=dict(t=40, b=20))
        g2.plotly_chart(fig_g, use_container_width=True)

        if "p_panel" in d and d["p_panel"].fillna(0).max() > 0:
            wh = (d["p_panel"].clip(lower=0) * d["dt"]).sum() / 3600
            st.metric("☀️ Energía generada por el panel solar", f"{wh:.1f} Wh",
                      help=f"CO₂ evitado: {wh / 1000 * FACTOR_CO2 * 1000:.1f} g")

# ======================================================================
# TAB 2 - PATRONES
# ======================================================================
with tab2:
    st.subheader("¿Se usa luz artificial cuando ya hay suficiente luz natural?")
    fig_corr = px.scatter(df, x="luz", y="potencia_watts",
                           labels={"luz": "Nivel de luz natural", "potencia_watts": "Potencia consumida (W)"},
                           color="potencia_watts", color_continuous_scale="RdYlGn_r")
    st.plotly_chart(fig_corr, use_container_width=True)

    st.info(f"📐 Correlación estadística entre luz y potencia: **{correlacion_luz_potencia:.3f}** (un valor cercano a 0 indica que no hay relación real entre ambas variables).")

    if abs(correlacion_luz_potencia) < 0.15:
        st.success(f"✅ No se detectó una relación significativa entre la luz natural disponible y el consumo eléctrico. El {porcentaje_desperdicio:.0f}% de coincidencia entre umbrales altos parece responder al azar, no a un patrón real de desperdicio de iluminación.")
    elif porcentaje_desperdicio > 15:
        st.warning(f"⚠️ En el **{porcentaje_desperdicio:.0f}%** de las mediciones hubo buena luz natural Y alto consumo eléctrico al mismo tiempo — posible uso innecesario de iluminación artificial.")
    else:
        st.success(f"✅ Solo el **{porcentaje_desperdicio:.0f}%** de las mediciones muestra ese patrón — no parece haber un desperdicio significativo de luz artificial.")

# ======================================================================
# TAB 3 - INFORME COMPLETO + PDF
# ======================================================================
with tab3:
    st.subheader("📝 Resumen automático de la jornada")

    pico_idx = df["potencia_watts"].idxmax()
    pico_potencia = df.loc[pico_idx, "potencia_watts"]
    pico_hora = df.loc[pico_idx, "fecha_hora"]

    resumen = (
        f"Durante las {horas_totales:.1f} horas registradas "
        f"({df['fecha_hora'].min().strftime('%H:%M')} a {df['fecha_hora'].max().strftime('%H:%M')}), "
        f"el mayor consumo eléctrico se detectó a las {pico_hora.strftime('%H:%M:%S')}, "
        f"con un pico de {pico_potencia:.0f} W. Se detectaron {len(picos_eventos)} sesiones de uso de la pava eléctrica "
        f"durante la jornada, representando en total unos {tiempo_pava_seg/60:.1f} minutos de uso real ({100*tiempo_pava_seg/len(df):.1f}% del tiempo). "
        f"La temperatura subió de un promedio de {temp_manana:.1f}°C en el turno mañana a {temp_tarde:.1f}°C en el turno tarde. "
        f"No se encontró una correlación relevante entre la luz natural y el consumo eléctrico (r={correlacion_luz_potencia:.3f}). "
        f"El sello de eficiencia energética calculado para esta jornada es {letra} ({etiqueta_letra})."
    )
    st.markdown(resumen)

    st.subheader("🌱 Impacto ambiental estimado")
    e1, e2, e3 = st.columns(3)
    e1.metric("Energía del día", f"{energia_kwh:.2f} kWh")
    e2.metric("CO₂ equivalente evitable", f"{co2_kg:.2f} kg")
    e3.metric("Proyección mensual (20 días)", f"{co2_mensual:.1f} kg CO₂")
    dias_arbol_dia, km_auto_dia = co2_a_relatable(co2_kg)
    dias_arbol_mes, km_auto_mes = co2_a_relatable(co2_mensual)
    st.caption(f"🌳 Eso equivale a lo que absorbe un árbol en **{dias_arbol_dia:.0f} días**, o a manejar un auto **{km_auto_dia:.1f} km**. Proyectado al mes: **{dias_arbol_mes:.0f} días de un árbol**, o **{km_auto_mes:.0f} km en auto**.")
    st.caption(f"Cálculo con el factor de emisión de la red argentina: {FACTOR_CO2} kg CO₂/kWh (CAMMESA, Resumen Anual 2025). Estimación, no medición directa de emisiones.")

    st.markdown("---")
    st.subheader("📄 Descargar informe completo en PDF")
    st.caption("Genera un informe técnico detallado con metodología, estadísticas, gráficos y conclusiones — listo para anexar al trabajo escrito.")

    def ascii_safe(txt):
        return txt.encode("latin-1", "replace").decode("latin-1")

    def generar_pdf_completo():
        # --- generar grafico embebido ---
        fig, axs = plt.subplots(4, 1, figsize=(9, 9), sharex=True)
        for ax, col, nombre, color in [
            (axs[0], "luz", "Luz ambiente", "#f59e0b"),
            (axs[1], "temperatura", "Temperatura (°C)", "#ef4444"),
            (axs[2], "humedad", "Humedad (%)", "#3b82f6"),
            (axs[3], "potencia_watts", "Potencia (W)", "#22c55e"),
        ]:
            ax.plot(df["fecha_hora"], df[col], color=color, linewidth=0.7)
            ax.set_ylabel(nombre, fontsize=8)
            ax.tick_params(labelsize=7)
        plt.tight_layout()
        tmp_chart = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        plt.savefig(tmp_chart.name, dpi=140)
        plt.close(fig)

        fig2, ax2 = plt.subplots(figsize=(9, 3))
        consumo_por_hora.plot(x="hora", y="potencia_watts", kind="bar", ax=ax2, color="#8b5cf6", legend=False)
        ax2.set_ylabel("Potencia prom. (W)", fontsize=8)
        ax2.set_xlabel("Hora del día", fontsize=8)
        ax2.tick_params(labelsize=7)
        plt.tight_layout()
        tmp_hora = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        plt.savefig(tmp_hora.name, dpi=140)
        plt.close(fig2)

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        # --- Portada ---
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 20)
        pdf.ln(15)
        pdf.cell(0, 12, "Informe de Relevamiento Energetico", ln=True, align="C")
        pdf.set_font("Helvetica", "", 13)
        pdf.cell(0, 9, "Sistema de Monitoreo con Arduino - EPET N3", ln=True, align="C")
        pdf.cell(0, 9, "Proyecto EDUCATIC 2026", ln=True, align="C")
        pdf.ln(10)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"Fecha del relevamiento: {df['fecha_hora'].min().strftime('%d/%m/%Y')}", ln=True, align="C")
        pdf.cell(0, 7, f"Horario: {df['fecha_hora'].min().strftime('%H:%M')} a {df['fecha_hora'].max().strftime('%H:%M')} ({horas_totales:.1f} horas)", ln=True, align="C")
        pdf.cell(0, 7, ascii_safe(f"Datos: {elegido}"), ln=True, align="C")

        # --- 1. Metodologia ---
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "1. Metodologia", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            "El sistema utiliza un microcontrolador Arduino Uno conectado a tres sensores: un LDR "
            "(fotoresistencia) para medir luz ambiente mediante un divisor de voltaje, un DHT22 para "
            "temperatura y humedad, y un ACS712 para corriente electrica mediante efecto Hall, "
            "intercalado en el cableado de un artefacto real (pava electrica). Los datos se capturaron "
            "con un script en Python (pyserial) cada segundo, calculando la corriente mediante el metodo "
            "RMS sobre 500 muestras para representar correctamente la naturaleza alterna de la senal electrica."
        ))
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "1.1 Cobertura de los datos", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            f"Se registraron {total_bruto:,} lecturas brutas. Tras eliminar valores faltantes y filtrar "
            f"lecturas fisicamente imposibles (glitches puntuales de comunicacion del sensor DHT22, "
            f"caracteristicos por su duracion de 1-2 segundos), quedaron {len(df):,} registros validos "
            f"({100*len(df)/total_bruto:.1f}% de los datos originales), suficientes para un analisis representativo."
        ))

        # --- 2. Estadisticas generales ---
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "2. Estadisticas generales", ln=True)
        pdf.set_font("Helvetica", "B", 10)
        col_w = [45, 30, 30, 30, 35]
        headers = ["Variable", "Promedio", "Minimo", "Maximo", "Desv. Est."]
        for w, h in zip(col_w, headers):
            pdf.cell(w, 8, h, border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 10)
        filas_tabla = [
            ("Luz (unid. sensor)", df["luz"].mean(), df["luz"].min(), df["luz"].max(), df["luz"].std()),
            ("Temperatura (C)", df["temperatura"].mean(), df["temperatura"].min(), df["temperatura"].max(), df["temperatura"].std()),
            ("Humedad (%)", df["humedad"].mean(), df["humedad"].min(), df["humedad"].max(), df["humedad"].std()),
            ("Corriente (A)", df["corriente"].mean(), df["corriente"].min(), df["corriente"].max(), df["corriente"].std()),
            ("Potencia (W)", df["potencia_watts"].mean(), df["potencia_watts"].min(), df["potencia_watts"].max(), df["potencia_watts"].std()),
        ]
        for nombre, prom, mn, mx, std in filas_tabla:
            pdf.cell(col_w[0], 8, ascii_safe(nombre), border=1)
            pdf.cell(col_w[1], 8, f"{prom:.2f}", border=1, align="C")
            pdf.cell(col_w[2], 8, f"{mn:.2f}", border=1, align="C")
            pdf.cell(col_w[3], 8, f"{mx:.2f}", border=1, align="C")
            pdf.cell(col_w[4], 8, f"{std:.2f}", border=1, align="C")
            pdf.ln()

        # --- 3. Grafico general ---
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "3. Evolucion temporal de las variables", ln=True)
        pdf.image(tmp_chart.name, w=180)

        # --- 4. Patron horario ---
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "4. Patron de consumo por hora del dia", ln=True)
        pdf.image(tmp_hora.name, w=180)
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            "El grafico muestra el consumo promedio de potencia agrupado por hora. Los picos se asocian "
            "a momentos puntuales de uso de la pava electrica durante los recreos, mientras que el resto "
            "del tiempo el consumo se mantiene bajo y estable, correspondiente al modo de espera de las "
            "computadoras del aula."
        ))

        # --- 5. Uso de la pava ---
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "5. Deteccion de uso de cargas de alto consumo", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            f"Se identificaron {len(picos_eventos)} sesiones de uso de la pava electrica (agrupando picos "
            f"cercanos correspondientes al ciclado normal del termostato dentro de una misma sesion), "
            f"totalizando aproximadamente {tiempo_pava_seg/60:.1f} minutos de uso real, equivalentes al "
            f"{100*tiempo_pava_seg/len(df):.1f}% del tiempo total registrado. El pico maximo de consumo "
            f"detectado fue de {pico_potencia:.0f} W a las {pico_hora.strftime('%H:%M:%S')}hs."
        ))

        # --- 6. Luz vs consumo ---
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "6. Relacion entre luz natural y consumo electrico", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            f"Se calculo el coeficiente de correlacion entre el nivel de luz natural y la potencia "
            f"consumida, obteniendo un valor de {correlacion_luz_potencia:.3f}. Este resultado, cercano a "
            f"cero, indica que no existe una relacion lineal significativa entre ambas variables en el "
            f"periodo relevado. Esto sugiere que el uso de iluminacion artificial y otros consumos del "
            f"aula responden principalmente a factores horarios y de actividad academica, mas que a la "
            f"disponibilidad de luz solar."
        ))

        # --- 7. Temperatura ---
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "7. Evolucion de la temperatura ambiente", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            f"La temperatura promedio paso de {temp_manana:.1f}C durante el turno manana (antes de las "
            f"13hs) a {temp_tarde:.1f}C durante el turno tarde, un incremento de {temp_tarde-temp_manana:.1f}C "
            f"consistente con el calentamiento natural de un aula ocupada a lo largo de la jornada."
        ))

        # --- 8. Ambiental ---
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "8. Balance energetico y ambiental estimado", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            f"La energia total consumida durante la jornada relevada fue de {energia_kwh:.3f} kWh. "
            f"Utilizando el factor de emision de la red argentina de {factor_co2} kg de CO2 por kWh "
            f"(CAMMESA, Resumen Anual 2025), esto equivale a {co2_kg:.3f} kg de CO2 evitables si dicha "
            f"energia se generara mediante el panel solar del sistema en lugar de la red convencional. "
            f"Proyectado a 20 dias habiles de clase, representaria aproximadamente {co2_mensual:.1f} kg de CO2 al mes."
        ))

        # --- 9. Conclusiones ---
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "9. Conclusiones", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, ascii_safe(
            f"El aula de informatica presenta un consumo base bajo y estable, con picos puntuales y breves "
            f"asociados al uso de artefactos de alto consumo (pava electrica). No se encontro evidencia de "
            f"desperdicio de iluminacion artificial vinculado a la disponibilidad de luz natural en el "
            f"periodo relevado. El sistema de monitoreo desarrollado demostro ser capaz de capturar, "
            f"procesar y visualizar datos reales de consumo energetico de forma automatica y continua, "
            f"cumpliendo el objetivo general del proyecto. Sello de eficiencia energetica calculado: {letra} ({etiqueta_letra})."
        ))

        return bytes(pdf.output())

    pdf_bytes = generar_pdf_completo()
    st.download_button("⬇️ Descargar informe completo (PDF)", data=pdf_bytes,
                        file_name="informe_relevamiento_energetico.pdf", mime="application/pdf")

# ======================================================================
# TAB 4 - DATOS
# ======================================================================
with tab4:
    st.dataframe(df, use_container_width=True, height=400)
    st.download_button("⬇️ Descargar datos procesados", df.to_csv(index=False), "datos_procesados.csv")

# ======================================================================
# TAB 5 - PROYECTO
# ======================================================================
with tab5:
    st.markdown("""
    ### Relevamiento energético. Hacia un uso eficiente de la energía
    **EPET N°3 · Neuquén** — Proyecto finalista de **EDUCATIC 2026**
    (instancia provincial: 15 y 16 de octubre, Centro de Convenciones Domuyo).

    **Equipo:** Josías Sospasa, Ximena Gómez y Tomás Pérez, estudiantes de la orientación en Energías.
    **Docentes:** Cristian Vega y Darío Delvas.

    #### ¿Por qué empezamos?
    Hace unos años, en la sala de informática de la escuela se prendieron fuego computadoras.
    Nos preguntamos qué pasa adentro de las aulas: cuánta energía se usa, cuánta se desperdicia
    y en qué condiciones están el aire y la temperatura.

    #### ¿Por qué importa? Energía y cambio climático
    - En Argentina, la **energía** genera cerca de **la mitad** de los gases de efecto invernadero (Inventario Nacional de GEI).
    - El país se propuso ser **carbono neutral en 2050** (Estrategia de Largo Plazo).
    - Cada kWh de la red emite en promedio **0,22 kg de CO₂** (CAMMESA, 2025).
    - El **Artículo 12 del Acuerdo de París** pide educación y concientización sobre el clima: este proyecto lo hacen estudiantes.

    #### Etapa 1 · agosto 2026 (sistema 1.0)
    Arduino Uno con LDR (luz), DHT22 (temperatura y humedad) y ACS712 (corriente).
    Relevamos la sala de informática: **más de 22.000 mediciones** en casi 7 horas,
    **13 usos de la pava eléctrica** detectados y una suba de temperatura de unos 2 °C durante la jornada.

    #### Etapa 2 · octubre 2026 (sistema 2.0)
    Sumamos sensores para medir **la calefacción y el aire**, no solo la electricidad:
    """)
    st.table(pd.DataFrame([
        ["DHT22", "Temperatura y humedad del aula"],
        ["LDR", "Luz del ambiente"],
        ["ACS712 20 A", "Corriente y potencia de un aparato enchufado"],
        ["DS18B20 (sonda)", "Temperatura del calefactor: si está prendido o no"],
        ["Sensor magnético", "Si la ventana está abierta o cerrada"],
        ["PIR HC-SR501", "Si hay personas en el aula"],
        ["MQ-2", "Humo o gas en el aire (alarma)"],
        ["Sensor de tensión + ACS712 5 A", "Energía del panel solar (próxima etapa)"],
    ], columns=["Sensor", "Qué mide"]))
    st.markdown("""
    Con Python cruzamos los datos y detectamos situaciones de desperdicio:
    **calefactor prendido con la ventana abierta**, **aula sobrecalefaccionada** (más de 21 °C)
    y **consumo con el aula vacía** (ver la pestaña 🔥 *Aula y calefacción*).

    #### Fuentes
    - CAMMESA, Resumen Anual 2025 — factor de emisión de la red.
    - Secretaría de Energía — guía de uso eficiente: 18 a 21 °C en invierno; cada grado menos ahorra entre 10 y 20 %; ventilar 5 a 10 minutos.
    - Inventario Nacional de Gases de Efecto Invernadero de Argentina.
    - Acuerdo de París, Artículo 12.
    """)

# ======================================================================
# TAB 6 - SIMULADOR INTERACTIVO
# ======================================================================
with tab6:
    st.subheader("🎮 Simulador: ¿Qué pasaría si...?")
    st.caption("Ajustá los parámetros de un aula y descubrí cuánto se podría ahorrar con control automático de iluminación basado en luz natural (como el sensor LDR de este proyecto).")

    col_sliders, col_resultado = st.columns([1, 1])

    with col_sliders:
        st.markdown("**Parámetros del aula**")
        horas = st.slider("Horas de iluminación por día", 2, 10, 6)
        cantidad = st.slider("Cantidad de luminarias", 5, 40, 15)
        potencia_led = st.slider("Potencia por luminaria (W)", 10, 60, 36)
        dias_anio = st.slider("Días de uso al año (ciclo lectivo)", 100, 220, 180)
        st.markdown("---")
        ahorro_pct = st.slider(
            "Ahorro estimado con sensores de luz automáticos (%)",
            0, 50, 22,
            help="Basado en la práctica de 'daylight harvesting': apagar o atenuar luces artificiales cuando el sensor LDR detecta suficiente luz natural."
        )
        precio_kwh = st.number_input("Precio del kWh ($ARS, opcional para estimar $)", value=150.0, step=10.0)

    consumo_kwh_anio = (cantidad * potencia_led * horas * dias_anio) / 1000
    ahorro_kwh_anio = consumo_kwh_anio * (ahorro_pct / 100)
    consumo_optimizado = consumo_kwh_anio - ahorro_kwh_anio
    ahorro_pesos = ahorro_kwh_anio * precio_kwh
    co2_evitado_sim = ahorro_kwh_anio * factor_co2

    with col_resultado:
        st.markdown("**Resultado estimado**")
        st.metric("🔌 Consumo actual estimado", f"{consumo_kwh_anio:,.0f} kWh/año")
        st.metric("💡 Ahorro potencial", f"{ahorro_kwh_anio:,.0f} kWh/año", delta=f"-{ahorro_pct}%")
        st.metric("✅ Consumo optimizado", f"{consumo_optimizado:,.0f} kWh/año")
        st.markdown("---")
        st.metric("💰 Ahorro estimado en pesos", f"${ahorro_pesos:,.0f} ARS/año")
        st.metric("🌱 CO₂ evitado estimado", f"{co2_evitado_sim:,.0f} kg/año")
        dias_arbol_sim, km_auto_sim = co2_a_relatable(co2_evitado_sim)
        st.caption(f"🌳 Equivale a lo que absorbe un árbol en {dias_arbol_sim:.0f} días, o manejar {km_auto_sim:.0f} km en auto.")

    st.info(
        "ℹ️ El % de ahorro es un valor orientativo y ajustable, inspirado en el hallazgo real de este "
        "proyecto sobre la relación entre luz natural y consumo eléctrico. No representa una medición "
        "directa, sino una proyección para explorar distintos escenarios."
    )

# ======================================================================
# TAB 7 - PARA EL PUBLICO GENERAL
# ======================================================================
with tab7:
    st.subheader("🏠 ¿Cuánto gastás vos en tu casa?")
    st.caption("Tildá los aparatos que tenés en tu casa y mirá cuánto consumen por mes, sin necesidad de saber nada de electricidad.")

    aparatos_hogar = {
        "🧊 Heladera": 108,
        "❄️ Aire acondicionado": 180,
        "📺 TV": 12,
        "💻 Computadora": 18,
        "🧺 Lavarropas": 7.5,
        "🍕 Microondas": 6,
        "🫖 Pava eléctrica": 11.25,
        "👕 Plancha de ropa": 9,
        "🌀 Ventilador": 5.4,
        "💡 Iluminación (5 focos LED)": 7.5,
        "📱 Cargador de celular": 0.45,
    }

    seleccionados = []
    cols_check = st.columns(3)
    for i, (nombre, kwh_mes) in enumerate(aparatos_hogar.items()):
        with cols_check[i % 3]:
            if st.checkbox(nombre, key=f"aparato_{i}"):
                seleccionados.append((nombre, kwh_mes))

    total_kwh_mes = sum(k for _, k in seleccionados)
    precio_kwh_casa = st.number_input("Precio del kWh en tu zona ($ARS)", value=150.0, step=10.0, key="precio_casa")
    total_pesos_mes = total_kwh_mes * precio_kwh_casa

    st.markdown("---")
    r1, r2 = st.columns(2)
    r1.metric("⚡ Tu consumo estimado", f"{total_kwh_mes:.1f} kWh/mes")
    r2.metric("💰 Tu gasto estimado", f"${total_pesos_mes:,.0f} ARS/mes")
    st.caption("Valores orientativos basados en horas de uso típicas de cada aparato en un hogar promedio.")

    st.markdown("---")
    st.subheader("🎮 Elegí un juego")
    st.caption("Si sacás el puntaje perfecto en cualquiera, mostranos la pantalla... ¡hay una sorpresa esperándote! 🎁")

    import random

    def render_quiz(key_prefix, preguntas, premio_msg):
        """preguntas: lista de (prompt, [opciones], indice_correcto, explicacion)"""
        ronda_key = f"{key_prefix}_ronda"
        score_key = f"{key_prefix}_score"
        orden_key = f"{key_prefix}_orden"
        respondido_key = f"{key_prefix}_respondido"
        terminado_key = f"{key_prefix}_terminado"
        correcto_key = f"{key_prefix}_correcto"
        total = len(preguntas)

        def iniciar():
            orden = list(range(total))
            random.shuffle(orden)
            st.session_state[orden_key] = orden
            st.session_state[ronda_key] = 0
            st.session_state[score_key] = 0
            st.session_state[respondido_key] = False
            st.session_state[terminado_key] = False

        if ronda_key not in st.session_state:
            iniciar()

        if not st.session_state[terminado_key]:
            idx = st.session_state[orden_key][st.session_state[ronda_key]]
            prompt, opciones, correcta_idx, explicacion = preguntas[idx]

            st.markdown(f"**Pregunta {st.session_state[ronda_key] + 1} de {total}** — Puntaje: {st.session_state[score_key]}/{total}")
            st.progress(st.session_state[ronda_key] / total)
            st.markdown(f"#### {prompt}")

            cols = st.columns(len(opciones))
            clickeado = None
            for i, (col, opcion) in enumerate(zip(cols, opciones)):
                with col:
                    if st.button(opcion, use_container_width=True,
                                 disabled=st.session_state[respondido_key],
                                 key=f"{key_prefix}_btn_{st.session_state[ronda_key]}_{i}"):
                        clickeado = i

            if clickeado is not None and not st.session_state[respondido_key]:
                st.session_state[respondido_key] = True
                correcto = (clickeado == correcta_idx)
                st.session_state[correcto_key] = correcto
                if correcto:
                    st.session_state[score_key] += 1
                st.rerun()

            if st.session_state[respondido_key]:
                if st.session_state[correcto_key]:
                    st.success(f"🎉 ¡Correcto! {explicacion}")
                else:
                    st.error(f"❌ La respuesta correcta era **{opciones[correcta_idx]}**. {explicacion}")
                texto_boton = "Siguiente ➡️" if st.session_state[ronda_key] < total - 1 else "Ver resultado 🏁"
                if st.button(texto_boton, key=f"{key_prefix}_next_{st.session_state[ronda_key]}"):
                    st.session_state[ronda_key] += 1
                    st.session_state[respondido_key] = False
                    if st.session_state[ronda_key] >= total:
                        st.session_state[terminado_key] = True
                    st.rerun()
        else:
            score = st.session_state[score_key]
            st.markdown(f"## Resultado final: {score}/{total}")
            if score == total:
                st.balloons()
                st.success(premio_msg)
            elif score >= total - 1:
                st.info(f"¡Muy bien! {score}/{total}. Te faltó una nomás — ¿probamos de nuevo?")
            else:
                st.warning(f"Sacaste {score}/{total}. ¡Animate a probar otra vez!")
            if st.button("🔄 Jugar de nuevo", key=f"{key_prefix}_reset"):
                iniciar()
                st.rerun()

    PREGUNTAS_CUAL_GASTA_MAS = [
        ("¿Cuál de estos dos consume más potencia?", ["🧊 Heladera", "❄️ Aire acondicionado"], 1, "❄️ Aire acondicionado usa ~1500W, la 🧊 Heladera usa ~150W."),
        ("¿Cuál de estos dos consume más potencia?", ["💇 Secador de pelo", "🫖 Pava eléctrica"], 1, "🫖 Pava eléctrica usa ~1500W, el 💇 Secador de pelo ~1200W."),
        ("¿Cuál de estos dos consume más potencia?", ["🍕 Microondas", "👕 Plancha de ropa"], 1, "👕 Plancha ~1200W, 🍕 Microondas ~1000W."),
        ("¿Cuál de estos dos consume más potencia?", ["💻 Computadora de escritorio", "🌀 Ventilador"], 0, "💻 Computadora ~200W, 🌀 Ventilador ~60W."),
        ("¿Cuál de estos dos consume más potencia?", ["📱 Cargador de celular", "💡 Lamparita LED"], 1, "💡 Lamparita LED ~10W, 📱 Cargador de celular vacío ~5W."),
    ]

    PREGUNTAS_MITOS = [
        ("Dejar el cargador de celular enchufado sin el celular gasta mucha energía", ["Verdadero", "Falso"], 1, "Un cargador vacío consume menos de 0.5W, prácticamente nada."),
        ("Bajar la persiana en verano ayuda a gastar menos aire acondicionado", ["Verdadero", "Falso"], 0, "Menos sol entrando significa menos calor que el aire tiene que compensar."),
        ("Las heladeras viejas gastan más que las nuevas", ["Verdadero", "Falso"], 0, "La eficiencia energética de los electrodomésticos mejoró muchísimo en las últimas décadas."),
        ("Dejar la computadora en modo suspensión gasta lo mismo que apagada", ["Verdadero", "Falso"], 1, "La suspensión consume bastante menos que estar prendida, aunque no es exactamente cero."),
        ("Los aparatos con una lucecita 'standby' prendida no consumen nada", ["Verdadero", "Falso"], 1, "Ese consumo fantasma existe de verdad, se lo conoce como 'standby power'."),
        ("Un aire acondicionado consume más al arrancar que mientras ya está enfriando", ["Verdadero", "Falso"], 0, "El pico de arranque del compresor es mayor que el consumo en régimen estable — lo mismo que vimos con la pava."),
    ]

    PREGUNTAS_RANGO = [
        ("🧊 ¿Cuánto consume una heladera hogareña?", ["10-50W", "100-200W", "1000-2000W"], 1, "Ronda los 150W en funcionamiento normal."),
        ("❄️ ¿Cuánto consume un aire acondicionado split mediano?", ["100-300W", "500-900W", "1200-2500W"], 2, "Suele estar cerca de los 1500W."),
        ("💻 ¿Cuánto consume una notebook?", ["30-90W", "200-400W", "800-1200W"], 0, "Las notebooks son bastante eficientes, entre 30 y 90W."),
        ("📶 ¿Cuánto consume un router wifi?", ["5-15W", "50-100W", "300-500W"], 0, "Muy poco, entre 5 y 15W, por eso queda prendido todo el día sin problema."),
        ("🍕 ¿Cuánto consume un microondas?", ["100-300W", "700-1200W", "2000-3000W"], 1, "Ronda los 1000W mientras calienta."),
        ("👕 ¿Cuánto consume una plancha de ropa?", ["200-500W", "600-900W", "1000-1800W"], 2, "Suele estar entre 1000 y 1800W."),
    ]

    PREGUNTAS_TECNICA = [
        ("¿Cómo mide la corriente el sensor ACS712, sin tocar el cable eléctricamente?", ["Contando electrones", "Detectando el campo magnético (efecto Hall)", "Midiendo la temperatura del cable"], 1, "Cualquier cable con corriente genera un campo magnético, y el ACS712 lo detecta sin contacto eléctrico directo."),
        ("¿Por qué el LDR necesita una resistencia extra junto a él?", ["Para que no se rompa", "Porque el Arduino solo puede leer voltaje, no resistencia", "Es solo decorativo"], 1, "Se arma un divisor de voltaje para convertir el cambio de resistencia del LDR en un voltaje que el Arduino sí puede leer."),
        ("¿Qué significa que el cálculo de corriente use 'RMS'?", ["Un tipo de cable", "Un promedio especial para señales que oscilan, como la corriente alterna", "El nombre del sensor"], 1, "La corriente alterna cambia de dirección 50 veces por segundo; RMS resume bien toda esa onda en un solo número."),
        ("¿Por qué el cable de tierra (verde-amarillo) nunca se corta?", ["Porque es el más caro", "Es una medida de seguridad, no forma parte del circuito normal", "Porque es decorativo"], 1, "La tierra descarga fallas eléctricas a modo de protección; cortarla elimina esa seguridad."),
        ("¿Qué mide el sensor DHT22 en este proyecto?", ["Solo temperatura", "Temperatura y humedad", "Corriente eléctrica"], 1, "El DHT22 manda ambos datos por un solo cable de señal."),
        ("¿Para qué sirve el panel solar en este proyecto?", ["Para que se vea más lindo", "Para alimentar el sistema de forma autónoma y con energía limpia", "Para medir la luz"], 1, "Permite que el nodo de medición funcione sin depender de un enchufe, alineado con el eje de energías limpias del proyecto."),
    ]

    juego_elegido = st.selectbox(
        "¿Qué querés jugar?",
        ["⚡🆚⚡ ¿Cuál gasta más?", "🤔 Verdadero o Falso: mitos de ahorro", "🎯 Adiviná el rango", "🔧 Trivia técnica de los sensores"]
    )

    st.markdown("")
    if juego_elegido == "⚡🆚⚡ ¿Cuál gasta más?":
        render_quiz("quiz1", PREGUNTAS_CUAL_GASTA_MAS, "🎁 ¡PERFECTO! Mostrale esta pantalla a alguien del stand... tenemos algo para vos.")
    elif juego_elegido == "🤔 Verdadero o Falso: mitos de ahorro":
        render_quiz("quiz2", PREGUNTAS_MITOS, "🎁 ¡PERFECTO! Desarmaste todos los mitos. Mostrale esta pantalla a alguien del stand.")
    elif juego_elegido == "🎯 Adiviná el rango":
        render_quiz("quiz3", PREGUNTAS_RANGO, "🎁 ¡PERFECTO! Tenés un ojo clínico para los watts. Mostrale esta pantalla a alguien del stand.")
    else:
        render_quiz("quiz4", PREGUNTAS_TECNICA, "🎁 ¡PERFECTO! Sabés tanto como nosotros del proyecto. Mostrale esta pantalla a alguien del stand.")

if auto_refresh:
    time.sleep(5)
    st.rerun()
