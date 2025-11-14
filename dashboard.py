import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
from pathlib import Path
import database  # <-- ¡NUEVA IMPORTACIÓN!

# --- Configuración de la Página (¡Debe ser lo primero!) ---
st.set_page_config(page_title="Tracker de Precios", layout="wide")

# --- Constantes ---
ITEMS_PER_PAGE = 10  # Productos por página


# --- Carga de Datos (con caché) ---
@st.cache_data(ttl=600)
def load_data():
    """
    Carga todos los datos de la base de datos (con producto_id)
    y los devuelve como un DataFrame de Pandas.
    """
    print("Cargando datos desde la base de datos...")
    try:
        # ¡OPTIMIZADO! Usa la ruta centralizada
        conn = sqlite3.connect(database.DB_PATH)
        query = """
        SELECT
            P.id as producto_id, 
            P.nombre,
            P.tienda,
            H.precio,
            H.fecha
        FROM HistorialPrecios H
        JOIN Productos P ON H.producto_id = P.id
        ORDER BY H.fecha ASC
        """
        df = pd.read_sql(query, conn)
        conn.close()

        df['fecha'] = pd.to_datetime(df['fecha'], format='mixed')

        if 'nombre' in df.columns:
            df['producto_display'] = df['nombre'] + " (" + df['tienda'] + ")"

        return df
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        return pd.DataFrame()


# ==================================================================
# --- VISTA 1: PÁGINA DE DETALLE DE PRODUCTO ---
# ==================================================================
def show_detail_page(df, product_id):
    """
    Muestra la página de detalles (métricas y gráfico) para UN producto.
    """
    try:
        product_data = df[df['producto_id'] == product_id]

        if product_data.empty:
            st.warning("No se encontraron datos para este producto.")
            st.markdown("<a href='/' target='_self'>&larr; Volver a la lista</a>", unsafe_allow_html=True)
            return

        display_name = product_data.iloc[0]['producto_display']
        st.title(display_name)

        latest_price = product_data.iloc[-1]['precio']
        lowest_price = product_data['precio'].min()
        highest_price = product_data['precio'].max()
        avg_price = product_data['precio'].mean()

        st.header("Estadísticas Clave")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Precio Actual", f"S/ {latest_price:,.2f}")
        col2.metric("Precio Más Bajo", f"S/ {lowest_price:,.2f}")
        col3.metric("Precio Más Alto", f"S/ {highest_price:,.2f}")
        col4.metric("Precio Promedio", f"S/ {avg_price:,.2f}")

        st.header("Historial de Precios")
        fig = px.line(
            product_data,
            x='fecha',
            y='precio',
            title=f"Evolución del precio de {display_name}",
            markers=True
        )
        min_price = product_data['precio'].min()
        max_price = product_data['precio'].max()
        fig.update_yaxes(range=[min_price * 0.98, max_price * 1.02])
        st.plotly_chart(fig, use_container_width=True)

        st.header("Tabla de Historial")
        st.dataframe(product_data[['fecha', 'precio']].sort_values(by='fecha', ascending=False),
                     use_container_width=True)

        st.divider()
        st.markdown("<a href='/' target='_self'>&larr; Volver a la lista</a>", unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error al mostrar detalles: {e}")
        st.markdown("<a href='/' target='_self'>&larr; Volver a la lista</a>", unsafe_allow_html=True)


# ==================================================================
# --- VISTA 2: PÁGINA PRINCIPAL (LISTA DE PRODUCTOS) ---
# ==================================================================
def show_main_page(df):
    """
    Muestra la lista paginada de productos, cada uno con su gráfico.
    """
    st.title("📊 Dashboard de Historial de Precios")

    product_list = df.drop_duplicates(subset=['producto_id'])

    if product_list.empty:
        st.warning("No hay productos en la base de datos.")
        st.info("Ejecuta 'python tracker.py' para empezar a recolectar datos.")
        return

    total_products = len(product_list)
    total_pages = max(1, (total_products + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    pagination_container = st.container()
    with pagination_container:
        col1, col2 = st.columns([0.8, 0.2])
        col1.markdown(f"**Total de productos: {total_products}**")
        current_page = col2.number_input(
            f"Página (1-{total_pages})",
            min_value=1,
            max_value=total_pages,
            value=1,
            label_visibility="collapsed"
        )

    start_index = (current_page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    products_to_show = product_list.iloc[start_index:end_index]

    for _, product in products_to_show.iterrows():
        product_id = product['producto_id']
        display_name = product['producto_display']

        with st.container(border=True):
            st.markdown(
                f"## <a href='/?producto_id={product_id}' target='_self' style='text-decoration:none; color:inherit;'>{display_name}</a>",
                unsafe_allow_html=True
            )
            product_data = df[df['producto_id'] == product_id]

            if product_data.empty or product_data.shape[0] < 2:
                st.info("Este producto necesita al menos dos registros para mostrar un gráfico.")
            else:
                fig = px.line(
                    product_data,
                    x='fecha',
                    y='precio',
                    markers=True
                )
                min_price = product_data['precio'].min()
                max_price = product_data['precio'].max()
                fig.update_yaxes(range=[min_price * 0.98, max_price * 1.02])
                st.plotly_chart(fig, use_container_width=True)


# ==================================================================
# --- LÓGICA PRINCIPAL (ROUTER) ---
# ==================================================================

# 1. Asegurar que la BD exista
database.setup_database()

# 2. Cargar los datos
data = load_data()

# 3. Obtener parámetros de la URL
query_params = st.query_params

# 4. Decidir qué página mostrar
if "producto_id" in query_params:
    try:
        product_id = int(query_params.get("producto_id"))
        show_detail_page(data, product_id)
    except ValueError:
        st.error("ID de producto no válido.")
        st.markdown("<a href='/' target='_self'>&larr; Volver a la lista</a>", unsafe_allow_html=True)
else:
    show_main_page(data)