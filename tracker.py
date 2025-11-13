import time
import sqlite3
import datetime
import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import telegram
import asyncio

# --- Cargar variables de entorno ---
load_dotenv()

# --- Importamos nuestros scrapers ---
from scrapers import mercadolibre_scraper
from scrapers import lacuracao_scraper

# ==========================================================
# --- CONFIGURACIÓN DE TELEGRAM (DESDE .env) ---
# ==========================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# ==========================================================

# --- Constantes ---
DB_NAME = "precios.db"

SCRAPER_DISPATCH = {
    "MercadoLibre": mercadolibre_scraper.parse,
    "LaCuracao": lacuracao_scraper.parse,
}

# --- Funciones de Telegram ---
bot_telegram = None
if TELEGRAM_TOKEN:
    try:
        bot_telegram = telegram.Bot(token=TELEGRAM_TOKEN)
        print("Bot de Telegram inicializado correctamente.")
    except Exception as e:
        print(f"Error inicializando el bot de Telegram: {e}")
else:
    print("ADVERTENCIA: TELEGRAM_TOKEN no encontrado en .env. No se enviarán notificaciones.")


async def _async_send_message(bot, chat_id, message):
    try:
        # Usamos parse_mode='Markdown' para los links y negritas
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        print("Notificación de Telegram enviada.")
    except Exception as e:
        print(f"Error al enviar notificación de Telegram (async): {e}")


def send_telegram_notification(message):
    if not bot_telegram:
        print(f"Notificación (simulada): {message}")
        return
    try:
        asyncio.run(_async_send_message(bot_telegram, CHAT_ID, message))
    except Exception as e:
        print(f"Error general en send_telegram_notification: {e}")


# --- Funciones de Base de Datos (ACTUALIZADAS) ---

def setup_database():
    """Crea las tablas en la base de datos si no existen."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL UNIQUE,
        nombre TEXT,
        tienda TEXT,
        precio_inicial REAL,
        precio_objetivo REAL,
        notificacion_objetivo_enviada BOOLEAN DEFAULT 0,
        status TEXT DEFAULT 'ninguno',  -- NUEVA COLUMNA
        precio_mas_bajo REAL            -- NUEVA COLUMNA
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS HistorialPrecios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER,
        precio REAL,
        fecha DATETIME,
        FOREIGN KEY (producto_id) REFERENCES Productos (id) ON DELETE CASCADE
    )
    ''')
    conn.commit()
    conn.close()
    print(f"Base de datos '{DB_NAME}' configurada con columnas 'status' y 'precio_mas_bajo'.")


def get_all_products_to_track():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, tienda FROM Productos")
    productos = cursor.fetchall()
    conn.close()
    return productos


def update_product_name(producto_id, nombre):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE Productos SET nombre = ? WHERE id = ?", (nombre, producto_id))
    conn.commit()
    conn.close()


def save_price(producto_id, precio):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    fecha_actual_iso = datetime.datetime.now().isoformat()
    cursor.execute("INSERT INTO HistorialPrecios (producto_id, precio, fecha) VALUES (?, ?, ?)",
                   (producto_id, precio, fecha_actual_iso))
    conn.commit()
    conn.close()
    print(f"Nuevo precio guardado: S/ {precio}")


# --- Nueva Lógica de Notificación (REESCRITA) ---

def check_and_notify(producto_id, nombre_producto, precio_actual, producto_url):
    """
    Comprueba el precio y envía notificaciones según las nuevas reglas.
    Actualiza el precio más bajo.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Obtener todos los datos del producto
    cursor.execute("""
        SELECT precio_inicial, precio_objetivo, notificacion_objetivo_enviada, precio_mas_bajo, status 
        FROM Productos WHERE id = ?
    """, (producto_id,))
    datos = cursor.fetchone()
    if not datos:
        conn.close()
        return

    precio_inicial, precio_objetivo, notificacion_enviada, precio_mas_bajo, status = datos

    # 2. Obtener precio anterior
    cursor.execute("SELECT precio FROM HistorialPrecios WHERE producto_id = ? ORDER BY fecha DESC LIMIT 2",
                   (producto_id,))
    precios = cursor.fetchall()
    precio_anterior = None
    if len(precios) > 1:
        precio_anterior = precios[1][0]

        # 3. Lógica de Precio Inicial (Solo se ejecuta una vez)
    if precio_inicial is None:
        cursor.execute("UPDATE Productos SET precio_inicial = ? WHERE id = ?", (precio_actual, producto_id))
        conn.commit()
        print(f"Se guardó el precio inicial: S/ {precio_actual}")

    # 4. Lógica de Precio Más Bajo (NUEVO)
    if precio_mas_bajo is None or precio_actual < precio_mas_bajo:
        precio_mas_bajo = precio_actual  # Actualizar la variable local para las notificaciones
        cursor.execute("UPDATE Productos SET precio_mas_bajo = ? WHERE id = ?", (precio_mas_bajo, producto_id))
        conn.commit()
        print(f"¡Nuevo precio más bajo registrado: S/ {precio_mas_bajo}!")

    # Formatear para notificación (evitar 'None')
    precio_mas_bajo_str = f"S/ {precio_mas_bajo}" if precio_mas_bajo else "N/A"
    status_str = status.capitalize() if status else "Ninguno"

    # 5. Lógica de Notificaciones

    # Trigger 1: Notificación ESPECIAL de Precio Objetivo
    if precio_objetivo is not None and precio_actual <= precio_objetivo:
        if not notificacion_enviada:
            mensaje = (
                f"🎯 **¡PRECIO OBJETIVO ALCANZADO!** 🎯\n\n"
                f"Producto: *{nombre_producto}*\n"
                f"Status: *{status_str}*\n\n"
                f"Precio Objetivo: S/ {precio_objetivo}\n"
                f"**Precio Nuevo: S/ {precio_actual}**\n"
                f"Precio Más Bajo: {precio_mas_bajo_str}\n\n"
                f"[Ver Producto]({producto_url})"
            )
            send_telegram_notification(mensaje)
            cursor.execute("UPDATE Productos SET notificacion_objetivo_enviada = 1 WHERE id = ?", (producto_id,))
            conn.commit()
        else:
            print("Info: Precio objetivo alcanzado, pero ya se notificó.")

    # Trigger 2: Notificación de CUALQUIER bajada de precio
    elif precio_anterior is not None and precio_actual < precio_anterior:
        # Se usa 'elif' para no enviar spam (la notificación de objetivo es prioritaria)
        mensaje = (
            f"📉 **¡Bajó de precio!**\n\n"
            f"Producto: *{nombre_producto}*\n"
            f"Status: *{status_str}*\n\n"
            f"Precio Anterior: S/ {precio_anterior}\n"
            f"**Precio Nuevo: S/ {precio_actual}**\n"
            f"Precio Más Bajo: {precio_mas_bajo_str}\n\n"
            f"[Ver Producto]({producto_url})"
        )
        send_telegram_notification(mensaje)

    conn.close()


# --- Función Genérica de Scraping (Sin cambios) ---

def get_page_html(url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)
        print(f"Abriendo: {url}...")
        driver.get(url)
        print("Esperando 7 segundos a que cargue el contenido dinámico...")
        time.sleep(7)
        page_html = driver.page_source
        print("Página cargada y HTML obtenido.")
        return page_html
    except Exception as e:
        print(f"Error al obtener la página: {e}")
        return None
    finally:
        if driver:
            driver.quit()
            print("Navegador cerrado.")


# --- Bloque Principal (Sin cambios, solo pasa la URL) ---
if __name__ == "__main__":

    print("---[ INICIANDO TRACKER DE PRECIOS ]---")
    setup_database()

    productos_a_revisar = get_all_products_to_track()
    if not productos_a_revisar:
        print("No hay productos en la base de datos para revisar.")
        exit()

    print(f"Se van a revisar {len(productos_a_revisar)} producto(s).")

    for producto in productos_a_revisar:
        producto_id, producto_url, tienda = producto

        print(f"\n---[ Procesando Producto ID: {producto_id} (Tienda: {tienda}) ]---")

        if tienda not in SCRAPER_DISPATCH:
            print(f"ERROR: No se encontró un scraper para la tienda '{tienda}'.")
            continue

        html_content = get_page_html(producto_url)
        if not html_content:
            print(f"ERROR: No se pudo obtener el HTML para el producto ID {producto_id}.")
            continue

        try:
            parser_func = SCRAPER_DISPATCH[tienda]
            titulo, precio = parser_func(html_content)
        except Exception as e:
            print(f"CRÍTICO: El scraper '{tienda}' falló con una excepción: {e}")
            titulo, precio = None, None

        if titulo and precio:
            save_price(producto_id, precio)
            update_product_name(producto_id, titulo)
            # Pasamos la URL para incluirla en las notificaciones
            check_and_notify(producto_id, titulo, precio, producto_url)
            print("--- Producto procesado exitosamente ---")
        else:
            print(f"--- ERROR: No se pudo extraer título o precio del producto ID {producto_id} ---")

        print("\nEsperando 30 segundos antes de la siguiente solicitud...")
        time.sleep(30)

    print("\n---[ TRACKING COMPLETO ]---")