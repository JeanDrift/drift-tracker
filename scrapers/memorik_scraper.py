import re
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def parse(driver):
    """
    Analiza la página de Memory Kings.
    Extrae el precio en DÓLARES y verifica stock en el texto.
    """
    print("\n--- [Scraper: Memory Kings] Iniciando Análisis ---")

    try:
        # 1. Esperar a que el título (h1.h1) sea visible
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.h1"))
        )
    except Exception as e:
        print(f"Error: No se detectó la carga de Memory Kings: {e}")
        return None, None, "ninguno"

    # Captura del HTML
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    product_title = None
    product_price = None
    product_status = "no disponible"

    try:
        # A. Título
        title_el = soup.find('h1', class_='h1')
        if title_el:
            product_title = title_el.get_text().strip()
            print(f"TÍTULO: {product_title}")

        # B. Precio (Foco en Dólares $)
        price_div = soup.find('div', class_='price')
        if price_div:
            price_text = price_div.get_text().strip()
            # Regex para capturar el número que sigue al símbolo $
            # Busca: símbolo $, opcional espacio, y luego números con comas o puntos
            match_usd = re.search(r'\$\s*([\d,.]+)', price_text)
            if match_usd:
                raw_val = match_usd.group(1).replace(',', '')
                product_price = float(raw_val)
                print(f"PRECIO (USD): $ {product_price}")

        # C. Disponibilidad / Stock
        # Buscamos todos los divs con la clase 'body-text'
        body_texts = soup.find_all('div', class_='body-text')
        stock_container = None
        
        # Iteramos sobre ellos para encontrar el que tiene "Stock:"
        for div in body_texts:
            if "Stock:" in div.get_text():
                stock_container = div
                break

        if stock_container:
            # Buscamos el <strong> dentro de ese contenedor
            stock_val_el = stock_container.find('strong')
            if stock_val_el:
                stock_text = stock_val_el.get_text().strip().lower()
                print(f"INFO STOCK: {stock_text}")

                textos_numeros = ["uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"]
                numeros_en_texto = [int(s) for s in re.findall(r'\d+', stock_text)]

                # Si el texto contiene "> 10", cualquier número mayor a 0, o los números escritos en letras
                if ">" in stock_text and "10" in stock_text:
                    product_status = "disponible"
                elif any(num > 0 for num in numeros_en_texto):
                    product_status = "disponible"
                elif any(palabra in stock_text.split() for palabra in textos_numeros):
                    product_status = "disponible"
                else:
                    product_status = "no disponible"
        else:
            print("STATUS: No Disponible (No se encontró información de stock)")
            product_status = "no disponible"

    except Exception as e:
        print(f"Error procesando Memory Kings: {e}")

    print("--- [Scraper: Memory Kings] Análisis Terminado ---")
    return product_title, product_price, product_status