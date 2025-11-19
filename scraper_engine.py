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
import logging

# --- Importar módulos del proyecto ---
from scrapers import mercadolibre_scraper
from scrapers import lacuracao_scraper
import database
import log_setup

# --- Configurar Logger ---
log = log_setup.setup_logging('scraper_engine')

# --- SILENCIAR LOGS DE WDM ---
logging.getLogger('WDM').setLevel(logging.ERROR)
os.environ['WDM_LOG_LEVEL'] = '0'

# --- Cargar .env ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Constantes ---
LOCK_FILE = database.BASE_DIR / "tracker.lock"
SCRAPING_WAIT_TIME = 7
POST_SCRAPE_SLEEP = 30

SCRAPER_DISPATCH = {
    "MercadoLibre": mercadolibre_scraper.parse,
    "LaCuracao": lacuracao_scraper.parse,
}

# --- Inicialización de Telegram ---
bot_telegram = None
if TELEGRAM_TOKEN:
    try:
        bot_telegram = telegram.Bot(token=TELEGRAM_TOKEN)
        log.info("Bot de Telegram inicializado.")
    except Exception as e:
        log.error(f"Error inicializando el bot de Telegram: {e}")
else:
    log.warning("TELEGRAM_TOKEN no encontrado.")


# --- Funciones de Notificación (Async) ---
async def _async_send_message(bot, chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        log.info("Notificación de Telegram enviada.")
    except Exception as e:
        log.error(f"Error al enviar notificación (async): {e}")


def send_telegram_notification(message):
    if not bot_telegram:
        log.warning(f"Notificación (simulada): {message}")
        return
    try:
        asyncio.run(_async_send_message(bot_telegram, CHAT_ID, message))
    except Exception as e:
        log.error(f"Error general en send_telegram_notification: {e}")


# --- Funciones de Base de Datos ---
def update_product_name(producto_id, nombre):
    conn = database.get_db_conn()
    conn.execute("UPDATE Productos SET nombre = ? WHERE id = ?", (nombre, producto_id))
    conn.commit()
    conn.close()


def save_price(producto_id, precio):
    conn = database.get_db_conn()
    fecha_iso = datetime.datetime.now().isoformat()
    conn.execute("INSERT INTO HistorialPrecios (producto_id, precio, fecha) VALUES (?, ?, ?)",
                 (producto_id, precio, fecha_iso))
    conn.commit()
    conn.close()
    log.info(f"Nuevo precio guardado: S/ {precio}")


def update_product_status(producto_id, status):
    if not status or status == 'ninguno':
        return
    conn = database.get_db_conn()
    conn.execute("UPDATE Productos SET status = ? WHERE id = ?", (status, producto_id))
    conn.commit()
    conn.close()
    log.info(f"Status actualizado a: {status}")


def check_and_notify(producto_id, nombre_producto, precio_actual, producto_url, nuevo_status):
    conn = database.get_db_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT precio_inicial, precio_objetivo, notificacion_objetivo_enviada, precio_mas_bajo
        FROM Productos WHERE id = ?
    """, (producto_id,))
    datos = cursor.fetchone()

    if not datos:
        log.error(f"No se pudieron leer los datos del producto ID {producto_id} para notificar.")
        conn.close()
        return

    precio_inicial, precio_objetivo, notificacion_enviada, precio_mas_bajo = datos

    cursor.execute("SELECT precio FROM HistorialPrecios WHERE producto_id = ? ORDER BY fecha DESC LIMIT 2",
                   (producto_id,))
    precios = cursor.fetchall()
    precio_anterior = None
    if len(precios) > 1:
        precio_anterior = precios[1][0]

    if precio_inicial is None:
        cursor.execute("UPDATE Productos SET precio_inicial = ? WHERE id = ?", (precio_actual, producto_id))
        conn.commit()
        log.info(f"Se guardó el precio inicial: S/ {precio_actual}")

    if precio_mas_bajo is None or precio_actual < precio_mas_bajo:
        precio_mas_bajo = precio_actual
        cursor.execute("UPDATE Productos SET precio_mas_bajo = ? WHERE id = ?", (precio_mas_bajo, producto_id))
        conn.commit()
        log.info(f"¡Nuevo precio más bajo registrado: S/ {precio_mas_bajo}!")

    precio_mas_bajo_str = f"S/ {precio_mas_bajo}" if precio_mas_bajo else "N/A"
    status_str = nuevo_status.capitalize() if nuevo_status else "Ninguno"

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
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-pipe")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = None
    try:
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            log.warning(f"Fallo al actualizar driver (red). Reintentando en 5s... Error: {e}")
            time.sleep(5)
            service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=options)

        log.info(f"Abriendo: {url}...")
        driver.get(url)

        log.info(f"Esperando {SCRAPING_WAIT_TIME} segundos...")
        time.sleep(SCRAPING_WAIT_TIME)

        page_html = driver.page_source
        log.info("Página cargada y HTML obtenido.")
        return page_html

    except Exception as e:
        log.error(f"Error al obtener la página: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
            log.info("Navegador cerrado.")


def _scrape_and_save(p_id, p_url, p_tienda):
    # Parámetros renombrados para evitar scope issues
    log.info(f"\n---[ Procesando Producto ID: {p_id} (Tienda: {p_tienda}) ]---")

    if p_tienda not in SCRAPER_DISPATCH:
        log.error(f"ERROR: No se encontró un scraper para la tienda '{p_tienda}'.")
        return False

    html_content = _get_page_html(p_url)
    if not html_content:
        log.error(f"ERROR: No se pudo obtener el HTML para el producto ID {p_id}.")
        return False

    try:
        parser_func = SCRAPER_DISPATCH[p_tienda]
        titulo, precio, status = parser_func(html_content)
    except Exception as e:
        log.critical(f"El scraper '{p_tienda}' falló con una excepción: {e}")
        titulo, precio, status = None, None, None

    if titulo and precio:
        save_price(p_id, precio)
        update_product_name(p_id, titulo)
        update_product_status(p_id, status)
        check_and_notify(p_id, titulo, precio, p_url, status)
        log.info("--- Producto procesado exitosamente ---")
        return True
    else:
        log.error(f"--- ERROR: No se pudo extraer título o precio del producto ID {p_id} ---")
        return False


# --- Funciones Públicas ---

def track_single_product(product_id):
    log.info(f"Solicitud de tracking para UN solo producto: ID {product_id}")
    conn = database.get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT url, tienda FROM Productos WHERE id = ?", (product_id,))
    producto = cursor.fetchone()
    conn.close()

    if producto:
        url, tienda = producto
        _scrape_and_save(product_id, url, tienda)
    else:
        log.error(f"ERROR: No se encontró el producto ID {product_id} para el tracking individual.")


def get_product_count():
    conn = database.get_db_conn()
    count = conn.execute("SELECT COUNT(*) FROM Productos").fetchone()[0]
    conn.close()
    return count


def track_all_products():
    """
    Rastrea TODOS los productos.
    Incluye lógica de recuperación ante archivos de bloqueo 'zombie'.
    """
    log.info("Solicitud de tracking para TODOS los productos...")

    # --- LÓGICA MEJORADA DEL CANDADO ---
    if LOCK_FILE.exists():
        # Verificar antigüedad del archivo
        try:
            file_age = time.time() - LOCK_FILE.stat().st_mtime
            # Si el archivo tiene más de 2 horas (7200 segundos), es un zombie de un corte de luz
            if file_age > 7200:
                log.warning(
                    f"⚠️ Archivo de bloqueo antiguo encontrado ({int(file_age / 60)} mins). Eliminando candado zombie.")
                LOCK_FILE.unlink()
            else:
                log.warning("Ya hay un proceso de tracking reciente en ejecución. Omitiendo este ciclo.")
                return False
        except Exception as e:
            log.error(f"Error verificando archivo de bloqueo: {e}. Forzando eliminación.")
            if LOCK_FILE.exists(): LOCK_FILE.unlink()

    try:
        LOCK_FILE.touch()
        log.info("Archivo de bloqueo creado. Iniciando scrape...")

        conn = database.get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, tienda FROM Productos")
        productos = cursor.fetchall()
        conn.close()

        if not productos:
            log.info("No hay productos en la BD para revisar.")
            return True

        log.info(f"Se van a revisar {len(productos)} producto(s).")

        for producto in productos:
            producto_id, producto_url, tienda = producto
            _scrape_and_save(producto_id, producto_url, tienda)
            log.info(f"Esperando {POST_SCRAPE_SLEEP} segundos...")
            time.sleep(POST_SCRAPE_SLEEP)

        log.info("\n---[ TRACKING COMPLETO ]---")
        return True

    except Exception as e:
        log.critical(f"Ocurrió un error fatal durante track_all_products: {e}", exc_info=True)
        return False

    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
            log.info("Archivo de bloqueo eliminado. Proceso terminado.")