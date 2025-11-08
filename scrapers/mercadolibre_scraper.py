import re
from bs4 import BeautifulSoup


def parse(html):
    """
    Analiza el HTML de una página de producto de MercadoLibre.
    Devuelve (titulo, precio) o (None, None) si falla.
    """
    if html is None:
        print("No hay HTML para analizar.")
        return None, None

    print("\n--- [Scraper: MercadoLibre] Iniciando Análisis ---")
    soup = BeautifulSoup(html, 'html.parser')

    product_title = None
    product_price = None

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

    print("--- [Scraper: MercadoLibre] Análisis Terminado ---")
    return product_title, product_price