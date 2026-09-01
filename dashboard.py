import streamlit as st
import pandas as pd
import plotly.express as px
import time
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

# --- Contador de visitas (una vez por sesión/visitante) ---
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
    archivo = st.file_uploader("Cargar un CSV distinto", type="csv")
    st.caption("Si no cargás nada, se usa datos_sala_informatica.csv")
    st.markdown("---")
    auto_refresh = st.checkbox("🔄 Modo demo en vivo (actualiza cada 5s)")

df = pd.read_csv(archivo) if archivo is not None else pd.read_csv("datos_sala_informatica.csv")
df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
for columna in ["luz", "temperatura", "humedad", "corriente"]:
    df[columna] = pd.to_numeric(df[columna], errors="coerce")
df = df.dropna()

filas_antes = len(df)
df = df[(df["temperatura"] > 15) & (df["temperatura"] < 40)]
df = df[(df["humedad"] > 15) & (df["humedad"] < 100)]
filas_filtradas = filas_antes - len(df)

df["potencia_watts"] = df["corriente"].abs() * 220
df["hora"] = df["fecha_hora"].dt.hour
df = df.reset_index(drop=True)

umbral_pava = 1000
por_encima = df["potencia_watts"] > umbral_pava
inicios_evento = por_encima & ~por_encima.shift(1, fill_value=False)
picos_eventos = []
for idx in df[inicios_evento].index:
    fin_ventana = df.loc[idx, "fecha_hora"] + pd.Timedelta(seconds=60)
    ventana = df[(df["fecha_hora"] >= df.loc[idx, "fecha_hora"]) & (df["fecha_hora"] <= fin_ventana)]
    if len(ventana) > 0:
        picos_eventos.append(ventana.loc[ventana["potencia_watts"].idxmax()])

umbral_luz = df["luz"].median()
umbral_potencia = df["potencia_watts"].median()
posible_desperdicio = df[(df["luz"] > umbral_luz) & (df["potencia_watts"] > umbral_potencia)]
porcentaje_desperdicio = 100 * len(posible_desperdicio) / len(df)

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

st.title("⚡ Sistema de Monitoreo Energético")
st.caption("Diagnóstico de consumo eléctrico escolar · Proyecto EDUCATIC 2026")
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

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Gráficos", "🔍 Patrones de consumo", "📝 Resumen y ambiente", "📋 Datos", "ℹ️ Proyecto"])

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
        st.caption(f"📍 Se detectaron {len(picos_eventos)} usos de la pava eléctrica durante la jornada (picos > {umbral_pava}W).")

    st.markdown("**Consumo promedio por hora del día**")
    consumo_por_hora = df.groupby("hora")["potencia_watts"].mean().reset_index()
    fig_hora = px.bar(consumo_por_hora, x="hora", y="potencia_watts",
                       labels={"hora": "Hora del día", "potencia_watts": "Potencia promedio (W)"})
    fig_hora.update_traces(marker_color="#8b5cf6")
    fig_hora.update_layout(height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_hora, use_container_width=True)

with tab2:
    st.subheader("¿Se usa luz artificial cuando ya hay suficiente luz natural?")
    fig_corr = px.scatter(df, x="luz", y="potencia_watts",
                           labels={"luz": "Nivel de luz natural", "potencia_watts": "Potencia consumida (W)"},
                           color="potencia_watts", color_continuous_scale="RdYlGn_r")
    st.plotly_chart(fig_corr, use_container_width=True)

    if porcentaje_desperdicio > 15:
        st.warning(f"⚠️ En el **{porcentaje_desperdicio:.0f}%** de las mediciones hubo buena luz natural Y alto consumo eléctrico al mismo tiempo — posible uso innecesario de iluminación artificial.")
    else:
        st.success(f"✅ Solo el **{porcentaje_desperdicio:.0f}%** de las mediciones muestra ese patrón — no parece haber un desperdicio significativo de luz artificial.")

with tab3:
    st.subheader("📝 Resumen automático de la jornada")

    pico_idx = df["potencia_watts"].idxmax()
    pico_potencia = df.loc[pico_idx, "potencia_watts"]
    pico_hora = df.loc[pico_idx, "fecha_hora"]
    horas_totales = (df["fecha_hora"].max() - df["fecha_hora"].min()).total_seconds() / 3600

    resumen = (
        f"Durante las {horas_totales:.1f} horas registradas "
        f"({df['fecha_hora'].min().strftime('%H:%M')} a {df['fecha_hora'].max().strftime('%H:%M')}), "
        f"el mayor consumo eléctrico se detectó a las {pico_hora.strftime('%H:%M:%S')}, "
        f"con un pico de {pico_potencia:.0f} W. Se detectaron {len(picos_eventos)} usos de la pava eléctrica "
        f"durante la jornada. La temperatura varió entre {df['temperatura'].min():.1f}°C y {df['temperatura'].max():.1f}°C, "
        f"mientras que la humedad se mantuvo mayormente estable entre {df['humedad'].quantile(0.05):.0f}% y "
        f"{df['humedad'].quantile(0.95):.0f}%. El sello de eficiencia energética calculado para esta jornada es {letra} ({etiqueta_letra})."
    )
    st.markdown(resumen)

    st.subheader("🌱 Impacto ambiental estimado")
    factor_co2 = 0.4
    energia_kwh = (df["potencia_watts"].mean() / 1000) * horas_totales
    co2_kg = energia_kwh * factor_co2
    co2_mensual = co2_kg * 20

    e1, e2, e3 = st.columns(3)
    e1.metric("Energía del día", f"{energia_kwh:.2f} kWh")
    e2.metric("CO₂ equivalente evitable", f"{co2_kg:.2f} kg")
    e3.metric("Proyección mensual (20 días)", f"{co2_mensual:.1f} kg CO₂")
    st.caption("Cálculo orientativo con factor promedio de 0.4 kg CO₂/kWh para la red argentina. Estimación ilustrativa, no medición directa de emisiones.")

    st.markdown("---")
    st.subheader("📄 Descargar resumen en PDF")

    def generar_pdf():
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "Monitoreo Energetico - EPET N3", ln=True, align="C")
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, "Proyecto EDUCATIC 2026", ln=True, align="C")
        pdf.ln(8)

        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, f"Sello de eficiencia energetica: {letra} ({etiqueta_letra})", ln=True)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Indicadores principales", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"- Luz promedio: {df['luz'].mean():.0f}", ln=True)
        pdf.cell(0, 7, f"- Temperatura promedio: {df['temperatura'].mean():.1f} C", ln=True)
        pdf.cell(0, 7, f"- Humedad promedio: {df['humedad'].mean():.1f} %", ln=True)
        pdf.cell(0, 7, f"- Potencia promedio: {df['potencia_watts'].mean():.1f} W", ln=True)
        pdf.cell(0, 7, f"- Registros analizados: {len(df):,}", ln=True)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Resumen de la jornada", ln=True)
        pdf.set_font("Helvetica", "", 11)
        resumen_ascii = resumen.encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 7, resumen_ascii)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Impacto ambiental estimado", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"- Energia del dia: {energia_kwh:.2f} kWh", ln=True)
        pdf.cell(0, 7, f"- CO2 equivalente evitable: {co2_kg:.2f} kg", ln=True)
        pdf.cell(0, 7, f"- Proyeccion mensual (20 dias): {co2_mensual:.1f} kg CO2", ln=True)

        return bytes(pdf.output())

    pdf_bytes = generar_pdf()
    st.download_button("⬇️ Descargar PDF del resumen", data=pdf_bytes,
                        file_name="resumen_monitoreo_energetico.pdf", mime="application/pdf")

with tab4:
    st.dataframe(df, use_container_width=True, height=400)
    st.download_button("⬇️ Descargar datos procesados", df.to_csv(index=False), "datos_procesados.csv")

with tab5:
    st.markdown("""
    ### Objetivo del proyecto
    Diagnosticar el consumo energético de la institución mediante un sistema de monitoreo con Arduino,
    identificando patrones de consumo innecesario y proponiendo medidas de optimización.

    **Sensores utilizados:** LDR (luz), DHT22 (temperatura y humedad), ACS712 (corriente eléctrica)
    **Alimentación:** panel solar con batería de respaldo
    """)

if auto_refresh:
    time.sleep(5)
    st.rerun()