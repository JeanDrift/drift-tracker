import time
import sqlite3
import datetime
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import telegram

# --- Importar módulos del proyecto ---
from scrapers import mercadolibre_scraper
from scrapers import lacuracao_scraper
import database  # <-- ¡NUEVA IMPORTACIÓN!

# --- Cargar .env ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Constantes ---
LOCK_FILE = database.BASE_DIR / "tracker.lock"  # Archivo de bloqueo
SCRAPING_WAIT_TIME = 7  # Segundos de espera
POST_SCRAPE_SLEEP = 30  # Segundos entre cada producto

SCRAPER_DISPATCH = {
    "MercadoLibre": mercadolibre_scraper.parse,
    "LaCuracao": lacuracao_scraper.parse,
}

# --- Inicialización de Telegram ---
bot_telegram = None
if TELEGRAM_TOKEN:
    try:
        bot_telegram = telegram.Bot(token=TELEGRAM_TOKEN)
        print("[Engine] Bot de Telegram inicializado.")
    except Exception as e:
        print(f"[Engine] Error inicializando el bot de Telegram: {e}")
else:
    print("[Engine] ADVERTENCIA: TELEGRAM_TOKEN no encontrado.")


# --- Funciones de Notificación (Async) ---
async def _async_send_message(bot, chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        print("[Engine] Notificación de Telegram enviada.")
    except Exception as e:
        print(f"[Engine] Error al enviar notificación (async): {e}")


def send_telegram_notification(message):
    if not bot_telegram:
        print(f"[Engine] Notificación (simulada): {message}")
        return
    try:
        asyncio.run(_async_send_message(bot_telegram, CHAT_ID, message))
    except Exception as e:
        print(f"[Engine] Error general en send_telegram_notification: {e}")


# --- Funciones de Base de Datos (Ahora usan database.py) ---
def update_product_name(producto_id, nombre):
    conn = database.get_db_conn()  # <-- OPTIMIZADO
    conn.execute("UPDATE Productos SET nombre = ? WHERE id = ?", (nombre, producto_id))
    conn.commit()
    conn.close()


def save_price(producto_id, precio):
    conn = database.get_db_conn()  # <-- OPTIMIZADO
    fecha_iso = datetime.datetime.now().isoformat()
    conn.execute("INSERT INTO HistorialPrecios (producto_id, precio, fecha) VALUES (?, ?, ?)",
                 (producto_id, precio, fecha_iso))
    conn.commit()
    conn.close()
    print(f"[Engine] Nuevo precio guardado: S/ {precio}")


def update_product_status(producto_id, status):
    if not status or status == 'ninguno':
        return
    conn = database.get_db_conn()  # <-- OPTIMIZADO
    conn.execute("UPDATE Productos SET status = ? WHERE id = ?", (status, producto_id))
    conn.commit()
    conn.close()
    print(f"[Engine] Status actualizado a: {status}")


def check_and_notify(producto_id, nombre_producto, precio_actual, producto_url, nuevo_status):
    """Comprueba el precio y envía notificaciones."""
    conn = database.get_db_conn()
    cursor = conn.cursor()

    # 1. Obtener datos de alerta del producto
    cursor.execute("""
        SELECT precio_inicial, precio_objetivo, notificacion_objetivo_enviada, precio_mas_bajo
        FROM Productos WHERE id = ?
    """, (producto_id,))
    datos = cursor.fetchone()

    # --- ¡FIX DE ROBUSTEZ! ---
    # Si la BD está ocupada o el ID no se encuentra, salimos de forma segura.
    if not datos:
        print(f"[Engine] ERROR: No se pudieron leer los datos del producto ID {producto_id} para notificar.")
        conn.close()
        return
    # --- FIN DEL FIX ---

    precio_inicial, precio_objetivo, notificacion_enviada, precio_mas_bajo = datos

    # 2. Obtener precio anterior
    cursor.execute("SELECT precio FROM HistorialPrecios WHERE producto_id = ? ORDER BY fecha DESC LIMIT 2",
                   (producto_id,))
    precios = cursor.fetchall()
    precio_anterior = None
    if len(precios) > 1:
        # El precio [0] es el actual (que acabamos de guardar), el [1] es el anterior
        precio_anterior = precios[1][0]

        # 3. Lógica de Precio Inicial (Solo se ejecuta una vez)
    if precio_inicial is None:
        cursor.execute("UPDATE Productos SET precio_inicial = ? WHERE id = ?", (precio_actual, producto_id))
        conn.commit()
        print(f"[Engine] Se guardó el precio inicial: S/ {precio_actual}")

    # 4. Lógica de Precio Más Bajo (NUEVO)
    if precio_mas_bajo is None or precio_actual < precio_mas_bajo:
        precio_mas_bajo = precio_actual
        cursor.execute("UPDATE Productos SET precio_mas_bajo = ? WHERE id = ?", (precio_mas_bajo, producto_id))
        conn.commit()
        print(f"[Engine] ¡Nuevo precio más bajo registrado: S/ {precio_mas_bajo}!")

    # Formatear para notificación (evitar 'None')
    precio_mas_bajo_str = f"S/ {precio_mas_bajo}" if precio_mas_bajo else "N/A"
    status_str = nuevo_status.capitalize() if nuevo_status else "Ninguno"

    # 5. Lógica de Notificaciones

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
    elif precio_anterior is not None and precio_actual < precio_anterior:
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


# --- Funciones de Scraping (El "Motor") ---

def _get_page_html(url):
    """Función interna de Selenium."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)
        print(f"[Engine] Abriendo: {url}...")
        driver.get(url)
        print(f"[Engine] Esperando {SCRAPING_WAIT_TIME} segundos...")
        time.sleep(SCRAPING_WAIT_TIME)
        page_html = driver.page_source
        print("[Engine] Página cargada y HTML obtenido.")
        return page_html
    except Exception as e:
        print(f"[Engine] Error al obtener la página: {e}")
        return None
    finally:
        if driver:
            driver.quit()
            print("[Engine] Navegador cerrado.")


def _scrape_and_save(product_id, producto_url, tienda):
    """
    Función interna que hace el trabajo para un producto.
    Devuelve True si tuvo éxito, False si falló.
    """
    print(f"\n---[ Procesando Producto ID: {product_id} (Tienda: {tienda}) ]---")

    if tienda not in SCRAPER_DISPATCH:
        print(f"ERROR: No se encontró un scraper para la tienda '{tienda}'.")
        return False

    html_content = _get_page_html(producto_url)
    if not html_content:
        print(f"ERROR: No se pudo obtener el HTML para el producto ID {product_id}.")
        return False

    try:
        parser_func = SCRAPER_DISPATCH[tienda]
        titulo, precio, status = parser_func(html_content)
    except Exception as e:
        print(f"CRÍTICO: El scraper '{tienda}' falló con una excepción: {e}")
        titulo, precio, status = None, None, None

    if titulo and precio:
        save_price(product_id, precio)
        update_product_name(product_id, titulo)
        update_product_status(product_id, status)
        check_and_notify(product_id, titulo, precio, producto_url, status)
        print("--- Producto procesado exitosamente ---")
        return True
    else:
        print(f"--- ERROR: No se pudo extraer título o precio del producto ID {product_id} ---")
        return False


# --- Funciones Públicas (Para llamar desde otros scripts) ---

def track_single_product(product_id):
    """
    Rastrea un solo producto basándose en su ID.
    Usado por el bot para /agregar y el botón /actualizar.
    """
    print(f"[Engine] Solicitud de tracking para UN solo producto: ID {product_id}")
    conn = database.get_db_conn()  # <-- OPTIMIZADO
    cursor = conn.cursor()
    cursor.execute("SELECT url, tienda FROM Productos WHERE id = ?", (product_id,))
    producto = cursor.fetchone()
    conn.close()

    if producto:
        url, tienda = producto
        _scrape_and_save(product_id, url, tienda)
    else:
        print(f"[Engine] ERROR: No se encontró el producto ID {product_id} para el tracking individual.")


def get_product_count():
    """Devuelve cuántos productos hay en la BD."""
    conn = database.get_db_conn()  # <-- OPTIMIZADO
    count = conn.execute("SELECT COUNT(*) FROM Productos").fetchone()[0]
    conn.close()
    return count


def track_all_products():
    """
    Rastrea TODOS los productos en la base de datos.
    Usa un archivo de bloqueo para evitar ejecuciones simultáneas.
    """
    print("[Engine] Solicitud de tracking para TODOS los productos...")

    producto_id = None

    if LOCK_FILE.exists():
        print("[Engine] ERROR: Ya hay un proceso de tracking en ejecución. Omitiendo.")
        return

    try:
        LOCK_FILE.touch()
        print("[Engine] Archivo de bloqueo creado. Iniciando scrape...")

        conn = database.get_db_conn()  # <-- OPTIMIZADO
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, tienda FROM Productos")
        productos = cursor.fetchall()
        conn.close()

        if not productos:
            print("[Engine] No hay productos en la BD para revisar.")
            return

        print(f"[Engine] Se van a revisar {len(productos)} producto(s).")

        for producto in productos:
            producto_id, producto_url, tienda = producto
            _scrape_and_save(producto_id, producto_url, tienda)

            print(f"\n[Engine] Esperando {POST_SCRAPE_SLEEP} segundos...")
            time.sleep(POST_SCRAPE_SLEEP)

        print("\n---[ TRACKING COMPLETO ]---")

    except Exception as e:
        print(f"[Engine] Ocurrió un error fatal durante track_all_products: {e}")

    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
            print("[Engine] Archivo de bloqueo eliminado. Proceso terminado.")