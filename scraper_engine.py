
import time
import sqlite3
import datetime
import os
import asyncio
import random
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
SCRAPING_WAIT_TIME = 7  # Tiempo base de espera (se puede reducir si usamos waits explícitos en el futuro)
POST_SCRAPE_SLEEP = 30  # Ya no se usa globalmente, sino dinámico por tienda

SCRAPER_DISPATCH = {
    "MercadoLibre": mercadolibre_scraper.parse,
    "LaCuracao": lacuracao_scraper.parse,
    "Falabella": None, # Placeholder
    "Ripley": None     # Placeholder
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
        # Creamos un loop temporal si no existe, o usamos el actual
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_send_message(bot_telegram, CHAT_ID, message))
        except RuntimeError:
            asyncio.run(_async_send_message(bot_telegram, CHAT_ID, message))
    except Exception as e:
        log.error(f"Error general en send_telegram_notification: {e}")


# --- Funciones de Base de Datos ---
def update_product_name(producto_id, nombre):
    with database.db_pool.get_conn() as conn:
        conn.execute("UPDATE Productos SET nombre = ? WHERE id = ?", (nombre, producto_id))
        conn.commit()


def save_price(producto_id, precio):
    with database.db_pool.get_conn() as conn:
        fecha_iso = datetime.datetime.now().isoformat()
        conn.execute("INSERT INTO HistorialPrecios (producto_id, precio, fecha) VALUES (?, ?, ?)",
                     (producto_id, precio, fecha_iso))
        conn.commit()
    log.info(f"Nuevo precio guardado: S/ {precio}")


def update_product_status(producto_id, status):
    if not status or status == 'ninguno':
        return
    with database.db_pool.get_conn() as conn:
        conn.execute("UPDATE Productos SET status = ? WHERE id = ?", (status, producto_id))
        conn.commit()
    log.info(f"Status actualizado a: {status}")


def check_and_notify(producto_id, nombre_producto, precio_actual, producto_url, nuevo_status):
    with database.db_pool.get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT precio_inicial, precio_objetivo, notificacion_objetivo_enviada, precio_mas_bajo
            FROM Productos WHERE id = ?
        """, (producto_id,))
        datos = cursor.fetchone()

        if not datos:
            log.error(f"No se pudieron leer los datos del producto ID {producto_id} para notificar.")
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


# --- Funciones de Scraping (El "Motor") ---

def create_driver():
    """Crea y retorna una nueva instancia de Chrome Driver."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-pipe")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

from threading import Lock

# ... (existing imports)

# --- Global Lock for Driver Installation ---
DRIVER_INSTALL_LOCK = Lock()

# ... (rest of code)

def create_driver():
    """Crea y retorna una nueva instancia de Chrome Driver."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-pipe")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    try:
        # Synchronize driver installation to avoid race conditions
        with DRIVER_INSTALL_LOCK:
            try:
                service = Service(ChromeDriverManager().install())
            except Exception as e:
                log.warning(f"Fallo al actualizar driver (red). Reintentando en 5s... Error: {e}")
                time.sleep(5)
                service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        log.error(f"Error fatal creando el driver: {e}")
        return None


def _navigate_to_product(url, driver):
    """Navega a la URL usando el driver existente."""
    try:
        log.info(f"Navegando a: {url}...")
        driver.get(url)
        # Ya no esperamos aquí. El scraper específico esperará lo que necesite.
        return True

    except Exception as e:
        log.error(f"Error al navegar a la página {url}: {e}")
        return False


def _scrape_and_save(p_id, p_url, p_tienda, driver):
    """Procesa un producto usando un driver específico."""
    log.info(f"---[ Procesando Producto ID: {p_id} (Tienda: {p_tienda}) ]---")

    if p_tienda not in SCRAPER_DISPATCH:
        log.error(f"ERROR: No se encontró un scraper para la tienda '{p_tienda}'.")
        return False
    
    parser_func = SCRAPER_DISPATCH[p_tienda]
    if parser_func is None:
        log.warning(f"Scraper para {p_tienda} aún no implementado.")
        return False

    if not _navigate_to_product(p_url, driver):
        log.error(f"ERROR: No se pudo navegar al producto ID {p_id}.")
        return False

    try:
        # AHORA PASAMOS EL DRIVER, NO EL HTML
        titulo, precio, status = parser_func(driver)
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
    elif status == "no disponible":
        # Caso especial: Producto no disponible (precio puede ser None)
        # El usuario solicitó explícitamente SOLO actualizar el status, sin tocar precio ni nombre.
        update_product_status(p_id, status)
        log.info(f"--- Producto ID {p_id} marcado como NO DISPONIBLE. (Precio/Nombre intactos) ---")
        return True
    else:
        log.error(f"--- ERROR: No se pudo extraer título o precio del producto ID {p_id} ---")
        return False


async def process_store_products(store_name, products):
    """
    Procesa una lista de productos de una misma tienda de forma SECUENCIAL.
    Se ejecuta en paralelo con otras tiendas.
    """
    log.info(f"[Worker: {store_name}] Iniciando. {len(products)} productos en cola.")
    
    # Crear driver dedicado para esta tienda
    driver = await asyncio.to_thread(create_driver)
    if not driver:
        log.error(f"[Worker: {store_name}] No se pudo crear el driver. Abortando.")
        return

    try:
        for i, prod in enumerate(products):
            p_id, p_url, p_tienda = prod
            
            # Procesar producto (bloqueante para este worker, pero ok porque es su propio hilo lógico)
            # Usamos to_thread para las operaciones de Selenium que son bloqueantes
            await asyncio.to_thread(_scrape_and_save, p_id, p_url, p_tienda, driver)
            
            # Si no es el último, esperar un tiempo aleatorio
            if i < len(products) - 1:
                wait_time = random.uniform(5, 15)
                log.info(f"[Worker: {store_name}] Esperando {wait_time:.1f}s antes del siguiente...")
                await asyncio.sleep(wait_time)
                
    except Exception as e:
        log.error(f"[Worker: {store_name}] Error en el ciclo: {e}", exc_info=True)
    finally:
        log.info(f"[Worker: {store_name}] Finalizado. Cerrando driver.")
        try:
            driver.quit()
        except:
            pass


# --- Funciones Públicas ---

def track_single_product(product_id):
    """Rastrea un solo producto (crea su propio driver efímero)."""
    log.info(f"Solicitud de tracking para UN solo producto: ID {product_id}")
    
    producto = None
    with database.db_pool.get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT url, tienda FROM Productos WHERE id = ?", (product_id,))
        producto = cursor.fetchone()

    if producto:
        url, tienda = producto
        driver = create_driver()
        if driver:
            try:
                _scrape_and_save(product_id, url, tienda, driver)
            finally:
                driver.quit()
    else:
        log.error(f"ERROR: No se encontró el producto ID {product_id} para el tracking individual.")


def get_product_count():
    with database.db_pool.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM Productos").fetchone()[0]
    return count


async def track_all_products():
    """
    Rastrea TODOS los productos usando paralelismo por tienda.
    """
    log.info("Solicitud de tracking para TODOS los productos (Modo Paralelo por Tienda)...")

    # --- LÓGICA DEL CANDADO ---
    if LOCK_FILE.exists():
        try:
            file_age = time.time() - LOCK_FILE.stat().st_mtime
            if file_age > 7200:
                log.warning(f"⚠️ Eliminando candado zombie ({int(file_age / 60)} mins).")
                LOCK_FILE.unlink()
            else:
                log.warning("Ya hay un proceso de tracking reciente. Omitiendo.")
                return False
        except Exception as e:
            if LOCK_FILE.exists(): LOCK_FILE.unlink()

    try:
        LOCK_FILE.touch()
        
        all_products = []
        with database.db_pool.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, url, tienda FROM Productos")
            all_products = cursor.fetchall()

        if not all_products:
            log.info("No hay productos en la BD.")
            return True

        # Agrupar por tienda
        store_queues = {}
        for prod in all_products:
            tienda = prod[2]
            if tienda not in store_queues:
                store_queues[tienda] = []
            store_queues[tienda].append(prod)

        log.info(f"Plan de ejecución: {len(store_queues)} tiendas detectadas.")

        # Crear tareas asíncronas (una por tienda)
        tasks = []
        for store_name, products in store_queues.items():
            tasks.append(process_store_products(store_name, products))

        # Ejecutar todas las tiendas en paralelo
        await asyncio.gather(*tasks)

        log.info("\n---[ TRACKING COMPLETO (PARALELO) ]---")
        return True

    except Exception as e:
        log.critical(f"Error fatal en track_all_products: {e}", exc_info=True)
        return False

    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
