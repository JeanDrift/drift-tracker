import time
import sqlite3
import datetime
import os       # <-- ¡NUEVA IMPORTACIÓN!
from dotenv import load_dotenv # <-- ¡NUEVA IMPORTACIÓN!
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import telegram
import asyncio

# --- Cargar variables de entorno ---
# Esto lee tu archivo .env y carga las variables
load_dotenv()

# --- Importamos nuestros scrapers ---
from scrapers import mercadolibre_scraper
from scrapers import lacuracao_scraper

# ==========================================================
# --- CONFIGURACIÓN DE TELEGRAM (AHORA DESDE .env) ---
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


# ... (El resto de tu código: _async_send_message, send_telegram_notification, setup_database, etc. ...
# ... NO CAMBIA NADA MÁS ABAJO) ...


# --- 2. CREAMOS UNA FUNCIÓN ASYNC DE AYUDA ---
async def _async_send_message(bot, chat_id, message):
    """
    Función de ayuda asíncrona que realmente envía el mensaje.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=message)
        print("Notificación de Telegram enviada.")
    except Exception as e:
        print(f"Error al enviar notificación de Telegram (async): {e}")


# --- 3. MODIFICAMOS LA FUNCIÓN ORIGINAL ---
def send_telegram_notification(message):
    """
    Envía un mensaje de texto a tu chat de Telegram.
    (Ahora usa asyncio.run() para llamar a la función async).
    """
    if not bot_telegram:
        print(f"Notificación (simulada): {message}")
        return

    # asyncio.run() ejecuta la función async de forma síncrona
    try:
        asyncio.run(_async_send_message(bot_telegram, CHAT_ID, message))
    except RuntimeError as e:
        # Esto maneja errores si asyncio ya se está ejecutando (poco probable aquí)
        print(f"Error de runtime con asyncio: {e}")
    except Exception as e:
        print(f"Error general en send_telegram_notification: {e}")


# --- Funciones de Base de Datos (Sin cambios) ---

def setup_database():
    """Crea las tablas en la base de datos si no existen."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL UNIQUE,
        nombre TEXT,
        tienda TEXT,
        precio_inicial REAL,
        precio_objetivo REAL
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS HistorialPrecios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER,
        precio REAL,
        fecha DATETIME,
        FOREIGN KEY (producto_id) REFERENCES Productos (id)
    )
    ''')
    conn.commit()
    conn.close()
    print(f"Base de datos '{DB_NAME}' configurada con nuevas columnas.")


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


# --- Lógica de Notificación (Sin cambios) ---

def check_and_notify(producto_id, nombre_producto, precio_actual):
    """
    Comprueba el precio actual contra la BD y envía notificaciones
    según las reglas definidas por el usuario.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT precio_inicial, precio_objetivo FROM Productos WHERE id = ?", (producto_id,))
    datos_alerta = cursor.fetchone()

    if not datos_alerta:
        conn.close()
        return

    precio_inicial, precio_objetivo = datos_alerta

    if precio_inicial is None:
        cursor.execute("UPDATE Productos SET precio_inicial = ? WHERE id = ?", (precio_actual, producto_id))
        conn.commit()
        print(f"Se guardó el precio inicial: S/ {precio_actual}")
        send_telegram_notification(
            f"📈 Nuevo seguimiento\n\nProducto: {nombre_producto}\nPrecio inicial: S/ {precio_actual}"
        )
    else:
        if precio_actual < precio_inicial:
            mensaje = (
                f"🚨 ¡BAJÓ DE PRECIO INICIAL! 🚨\n\n"
                f"Producto: {nombre_producto}\n"
                f"Precio Anterior (Inicial): S/ {precio_inicial}\n"
                f"Precio Nuevo: S/ {precio_actual}\n"
                f"¡Ahorro de S/ {precio_inicial - precio_actual:.2f}!"
            )
            send_telegram_notification(mensaje)

    if precio_objetivo is not None:
        if precio_actual <= precio_objetivo:
            mensaje = (
                f"🎯 ¡PRECIO OBJETIVO ALCANZADO! 🎯\n\n"
                f"Producto: {nombre_producto}\n"
                f"Precio Objetivo: S/ {precio_objetivo}\n"
                f"Precio Nuevo: S/ {precio_actual}\n"
                f"¡CORRE!"
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


# --- Bloque Principal (Sin cambios) ---
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
            check_and_notify(producto_id, titulo, precio)
            print("--- Producto procesado exitosamente ---")
        else:
            print(f"--- ERROR: No se pudo extraer título o precio del producto ID {producto_id} ---")

        print("\nEsperando 30 segundos antes de la siguiente solicitud...")
        time.sleep(30)

    print("\n---[ TRACKING COMPLETO ]---")