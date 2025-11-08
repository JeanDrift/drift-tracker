import time
import sqlite3
import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --- Importamos nuestros scrapers ---
from scrapers import mercadolibre_scraper

# (Aquí añadiremos más, ej: from scrapers import lacuracao_scraper)


# --- Constantes ---
DB_NAME = "precios.db"

# --- El "Despachador" ---
# Un diccionario que mapea el nombre de la tienda (de la BD)
# con la función 'parse' del scraper correcto.
SCRAPER_DISPATCH = {
    "MercadoLibre": mercadolibre_scraper.parse,
    # "LaCuracao": lacuracao_scraper.parse, # <-- Así añadiremos futuras tiendas
}


# --- Funciones de Base de Datos (Actualizadas) ---

def setup_database():
    """Crea las tablas en la base de datos si no existen."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL UNIQUE,
        nombre TEXT,
        tienda TEXT
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
    print(f"Base de datos '{DB_NAME}' configurada.")


def get_all_products_to_track():
    """
    Obtiene todos los productos de la tabla Productos.
    Devuelve una lista de tuplas (id, url, tienda).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # ¡Importante! Ahora también seleccionamos la 'tienda'
    cursor.execute("SELECT id, url, tienda FROM Productos")
    productos = cursor.fetchall()
    conn.close()
    return productos


def update_product_name(producto_id, nombre):
    """Actualiza el nombre de un producto en la BD."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE Productos SET nombre = ? WHERE id = ?", (nombre, producto_id))
    conn.commit()
    conn.close()


def save_price(producto_id, precio):
    """Guarda un nuevo registro de precio en el historial."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    fecha_actual_obj = datetime.datetime.now()
    fecha_actual_iso = fecha_actual_obj.isoformat()

    cursor.execute("INSERT INTO HistorialPrecios (producto_id, precio, fecha) VALUES (?, ?, ?)",
                   (producto_id, precio, fecha_actual_iso))
    conn.commit()
    conn.close()
    print(f"Nuevo precio guardado: S/ {precio} en {fecha_actual_obj.strftime('%Y-%m-%d %H:%M')}")


# --- Función Genérica de Scraping (Selenium) ---

def get_page_html(url):
    """
    """
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


# --- Bloque Principal (El Gerente) ---
if __name__ == "__main__":

    print("---[ INICIANDO TRACKER DE PRECIOS ]---")

    setup_database()

    productos_a_revisar = get_all_products_to_track()

    if not productos_a_revisar:
        print("No hay productos en la base de datos para revisar.")
        print("Usa 'python add_product.py' para añadir uno.")
        exit()

    print(f"Se van a revisar {len(productos_a_revisar)} producto(s).")

    for producto in productos_a_revisar:
        producto_id, producto_url, tienda = producto  # ¡Ahora tenemos la tienda!

        print(f"\n---[ Procesando Producto ID: {producto_id} (Tienda: {tienda}) ]---")

        # 1. Verificar si tenemos un scraper para esta tienda
        if tienda not in SCRAPER_DISPATCH:
            print(f"ERROR: No se encontró un scraper para la tienda '{tienda}'. Omitiendo.")
            continue  # Salta al siguiente producto del bucle

        # 2. Obtener el HTML (genérico)
        html_content = get_page_html(producto_url)

        if not html_content:
            print(f"ERROR: No se pudo obtener el HTML para el producto ID {producto_id}. Omitiendo.")
            continue

        # 3. Llamar al scraper ESPECÍFICO
        try:
            # Obtenemos la función de parseo correcta desde el diccionario
            parser_func = SCRAPER_DISPATCH[tienda]

            # Llamamos a esa función (ej. mercadolibre_scraper.parse(html))
            titulo, precio = parser_func(html_content)

        except Exception as e:
            print(f"CRÍTICO: El scraper '{tienda}' falló con una excepción: {e}")
            titulo, precio = None, None

        # 4. Guardar en la Base de Datos
        if titulo and precio:
            save_price(producto_id, precio)
            update_product_name(producto_id, titulo)
            print("--- Producto procesado exitosamente ---")
        else:
            print(f"--- ERROR: No se pudo extraer título o precio del producto ID {producto_id} ---")

        print("\nEsperando 30 segundos antes de la siguiente solicitud...")
        time.sleep(30)
