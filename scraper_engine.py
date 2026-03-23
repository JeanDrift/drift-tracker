import time
import sqlite3
import datetime
import os
import json
import urllib.request
import asyncio
import random
import re
from pathlib import Path
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import telegram
import logging
from threading import Lock

# --- Importar módulos del proyecto ---
from scrapers import mercadolibre_scraper
from scrapers import lacuracao_scraper
from scrapers import lg_scraper
from scrapers import memorik_scraper
import database
import log_setup

# --- Configurar Logger ---
log = log_setup.setup_logging('scraper_engine')
logging.getLogger('WDM').setLevel(logging.ERROR)
os.environ['WDM_LOG_LEVEL'] = '0'

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

LOCK_FILE = database.BASE_DIR / "tracker.lock"
DRIVER_INSTALL_LOCK = Lock()

SCRAPER_DISPATCH = {
    "MercadoLibre": mercadolibre_scraper.parse,
    "LaCuracao": lacuracao_scraper.parse,
    "LG": lg_scraper.parse,
    "MemoryKings": memorik_scraper.parse
}

# --- Helper de Moneda ---
def get_currency_symbol(tienda):
    return "$" if tienda == "MemoryKings" else "S/"


def send_telegram_notification(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            pass
    except Exception as e:
        log.error(f"Error en notificación HTTP: {e}")


def save_price(producto_id, precio):
    with database.db_pool.get_conn() as conn:
        fecha_iso = datetime.datetime.now().isoformat()
        conn.execute("INSERT INTO HistorialPrecios (producto_id, precio, fecha) VALUES (?, ?, ?)",
                     (producto_id, precio, fecha_iso))
        conn.commit()


def check_and_notify(producto_id, nombre_producto, precio_actual, producto_url, nuevo_status, tienda):
    with database.db_pool.get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT precio_inicial, precio_objetivo, notificacion_objetivo_enviada, precio_mas_bajo FROM Productos WHERE id = ?",
            (producto_id,))
        datos = cursor.fetchone()
        if not datos: return

        p_ini, p_obj, notif_env, p_min = datos
        cursor.execute("SELECT precio FROM HistorialPrecios WHERE producto_id = ? ORDER BY fecha DESC LIMIT 2",
                       (producto_id,))
        precios = cursor.fetchall()
        p_ant = precios[1][0] if len(precios) > 1 else None

        if p_min is None or precio_actual < p_min:
            p_min = precio_actual
            conn.execute("UPDATE Productos SET precio_mas_bajo = ? WHERE id = ?", (p_min, producto_id))
            conn.commit()

        sym = get_currency_symbol(tienda)
        status_str = nuevo_status.capitalize() if nuevo_status else "Ninguno"

        if p_obj and precio_actual <= p_obj and not notif_env:
            mensaje = f"🎯 **¡META ALCANZADA!** 🎯\n\n*{nombre_producto}*\nStatus: {status_str}\nPrecio: **{sym} {precio_actual}**\n[Ver Producto]({producto_url})"
            send_telegram_notification(mensaje)
            conn.execute("UPDATE Productos SET notificacion_objetivo_enviada = 1 WHERE id = ?", (producto_id,))
            conn.commit()
        elif p_ant and precio_actual < p_ant:
            mensaje = f"📉 **¡BAJÓ DE PRECIO!**\n\n*{nombre_producto}*\nPrecio: **{sym} {precio_actual}**\nAntes: {sym} {p_ant}\n[Ver]({producto_url})"
            send_telegram_notification(mensaje)


def create_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument(
        f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    try:
        with DRIVER_INSTALL_LOCK:
            service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)
    except Exception as e:
        log.error(f"Error driver: {e}");
        return None


def _scrape_and_save(p_id, p_url, p_tienda, driver):
    if p_tienda not in SCRAPER_DISPATCH: return False
    try:
        driver.get(p_url)
        titulo, precio, status = SCRAPER_DISPATCH[p_tienda](driver)
        if titulo and precio:
            save_price(p_id, precio)
            with database.db_pool.get_conn() as conn:
                conn.execute("UPDATE Productos SET nombre = ?, status = ? WHERE id = ?", (titulo, status, p_id))
                conn.commit()
            check_and_notify(p_id, titulo, precio, p_url, status, p_tienda)
            return True
        elif status:
            with database.db_pool.get_conn() as conn:
                conn.execute("UPDATE Productos SET status = ? WHERE id = ?", (status, p_id))
                conn.commit()
            return True
    except Exception as e:
        log.error(f"Error Scrape ID {p_id}: {e}")
    return False


# --- FUNCIONES REQUERIDAS POR BOT_MANAGER ---
def get_product_count():
    with database.db_pool.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM Productos").fetchone()[0]


def track_single_product(product_id):
    with database.db_pool.get_conn() as conn:
        prod = conn.execute("SELECT id, url, tienda FROM Productos WHERE id = ?", (product_id,)).fetchone()
    if not prod: return
    driver = create_driver()
    if driver:
        _scrape_and_save(prod[0], prod[1], prod[2], driver)
        driver.quit()


async def track_all_products():
    if LOCK_FILE.exists(): return
    try:
        LOCK_FILE.touch()
        with database.db_pool.get_conn() as conn:
            prods = conn.execute("SELECT id, url, tienda FROM Productos").fetchall()
        if not prods: return

        # Agrupar por tienda para optimizar driver
        queues = {}
        for p in prods: queues.setdefault(p[2], []).append(p)

        async def process_store(name, p_list):
            driver = await asyncio.to_thread(create_driver)
            if not driver: return
            for p in p_list:
                await asyncio.to_thread(_scrape_and_save, p[0], p[1], p[2], driver)
                await asyncio.sleep(random.uniform(5, 10))
            driver.quit()

        await asyncio.gather(*(process_store(s, pl) for s, pl in queues.items()))
    finally:
        if LOCK_FILE.exists(): LOCK_FILE.unlink()