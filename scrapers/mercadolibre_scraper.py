import re
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def parse(driver):
    """
    Analiza la página de MercadoLibre usando Selenium y WebDriverWait.
    Devuelve (titulo, precio, status).
    """
    print("\n--- [Scraper: MercadoLibre V3 (Smart Wait)] Iniciando Análisis ---")
    
    try:
        # Esperar inteligentemente a que cargue el título (elemento clave)
        # Máximo 10 segundos
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "ui-pdp-title"))
        )
        print("Elemento clave encontrado. Procesando HTML...")
    except Exception as e:
        print(f"Timeout esperando carga de página: {e}")
        return None, None, "ninguno"

    # Obtenemos el HTML ya cargado
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    product_title = None
    product_price = None
    # Por defecto, asumimos "no disponible" según tu lógica
    product_status = "no disponible"

    # --- 1. Extraer el Título ---
    try:
        title_element = soup.find('h1', class_='ui-pdp-title')
        if title_element:
            product_title = title_element.get_text().strip()
            print(f"TÍTULO ENCONTRADO: {product_title}")
        else:
            print("ERROR: No se pudo encontrar el TÍTULO.")
    except Exception as e:
        print(f"Error al procesar el título: {e}")

    # --- 2. Extraer el Precio ---
    try:
        price_element = None
        discount_container = soup.find('div', class_='ui-pdp-price__second-line')
        if discount_container:
            price_element = discount_container.find('span', class_='andes-money-amount__fraction')
            if price_element:
                print("Info: Precio de DESCUENTO encontrado.")

        if not price_element:
            normal_container = soup.find('div', class_='ui-pdp-price__part__container')
            if normal_container:
                price_element = normal_container.find('span', class_='andes-money-amount__fraction')
                if price_element:
                    print("Info: Precio NORMAL encontrado.")

        if price_element:
            price_text = price_element.get_text().strip()
            price_cleaned = re.sub(r'[^\d]', '', price_text)
            product_price = int(price_cleaned)
            print(f"PRECIO FINAL ENCONTRADO: S/ {product_price}")
        else:
            print("ERROR: No se pudo encontrar ningún selector de precio válido.")
    except Exception as e:
        print(f"Error al procesar el precio: {e}")

    # --- 3. Extraer el Status (NUEVO) ---
    try:
        # Caso 1: Hay varias unidades (ej: "+10 disponibles")
        stock_span = soup.find('button', class_='andes-button andes-spinner__icon-base ui-pdp-action--primary andes-button--loud')

        if stock_span and "Comprar ahora" in stock_span.get_text():
            product_status = "disponible"
            print("STATUS ENCONTRADO: Disponible (Stock múltiple)")

        else:
            # Si no se encuentra ninguno de los dos, se queda como "no disponible"
            print("STATUS ENCONTRADO: No Disponible (No se encontraron selectores de stock)")

    except Exception as e:
        print(f"Error al procesar el status: {e}")
        # En caso de error, es más seguro asumir "no disponible"
        product_status = "no disponible"

    print("--- [Scraper: MercadoLibre V3] Análisis Terminado ---")

    # Devolver los 3 valores
    return product_title, product_price, product_status