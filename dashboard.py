import streamlit as st
import pandas as pd
import plotly.express as px
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
    archivo = st.file_uploader("Cargar un CSV distinto", type="csv")
    st.caption("Si no cargás nada, se usa datos_sala_informatica.csv")
    st.markdown("---")
    auto_refresh = st.checkbox("🔄 Modo demo en vivo (actualiza cada 5s)")

# --- Carga y limpieza ---
df = pd.read_csv(archivo) if archivo is not None else pd.read_csv("datos_sala_informatica.csv")
df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
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
factor_co2 = 0.4
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

# ======================================================================
# ENCABEZADO
# ======================================================================
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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📈 Gráficos", "🔍 Patrones de consumo", "📝 Informe completo", "📋 Datos", "ℹ️ Proyecto", "🎮 Simulador"])

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
    st.caption("Cálculo orientativo con factor promedio de 0.4 kg CO₂/kWh para la red argentina. Estimación ilustrativa, no medición directa de emisiones.")

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
        pdf.cell(0, 7, "Lugar: Aula de Informatica", ln=True, align="C")

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
            f"Utilizando un factor de emision orientativo de {factor_co2} kg de CO2 por kWh (promedio de "
            f"la matriz electrica argentina), esto equivale a {co2_kg:.3f} kg de CO2 evitables si dicha "
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
    ### Objetivo del proyecto
    Diagnosticar el consumo energético de la institución mediante un sistema de monitoreo con Arduino,
    identificando patrones de consumo innecesario y proponiendo medidas de optimización.

    **Sensores utilizados:** LDR (luz), DHT22 (temperatura y humedad), ACS712 (corriente eléctrica)
    **Alimentación:** panel solar con batería de respaldo
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

    st.info(
        "ℹ️ El % de ahorro es un valor orientativo y ajustable, inspirado en el hallazgo real de este "
        "proyecto sobre la relación entre luz natural y consumo eléctrico. No representa una medición "
        "directa, sino una proyección para explorar distintos escenarios."
    )

if auto_refresh:
    time.sleep(5)
    st.rerun()
