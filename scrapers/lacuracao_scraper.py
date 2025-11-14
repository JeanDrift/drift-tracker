import re
from bs4 import BeautifulSoup


def parse(html):
    """
    Analiza el HTML de una página de producto de La Curacao.
    (Versión 3: Añade scraping de status).
    Devuelve (titulo, precio, status).
    """
    if html is None:
        print("No hay HTML para analizar.")
        return None, None, "ninguno"  # Devolver 3 valores

    print("\n--- [Scraper: LaCuracao V3] Iniciando Análisis ---")
    soup = BeautifulSoup(html, 'html.parser')

    product_title = None
    product_price = None
    product_status = "ninguno"  # Status por defecto

    # --- 1. Extraer el Título ---
    try:
        title_element = soup.find('span', itemprop='name')
        if title_element:
            product_title = title_element.get_text().strip()
            print(f"TÍTULO ENCONTRADO: {product_title}")
        else:
            print("ERROR: No se pudo encontrar el TÍTULO (Selector 'span[itemprop=name]' no encontrado).")
    except Exception as e:
        print(f"Error al procesar el título: {e}")

    # --- 2. Extraer el Precio ---
    try:
        price_element = soup.find('meta', itemprop='price')
        if price_element and price_element.get('content'):
            price_text = price_element.get('content')
            print(f"Info: 'content' de meta-tag encontrado: '{price_text}'")
            product_price = int(float(price_text))
        else:
            print("Info: No se encontró 'meta[itemprop=price]'. Buscando 'data-price-amount'...")
            price_span = soup.find('span', {'data-price-amount': True})
            if price_span:
                price_text = price_span['data-price-amount']
                print(f"Info: 'data-price-amount' encontrado: '{price_text}'")
                product_price = int(float(price_text))
            else:
                print("ERROR: No se pudo encontrar el PRECIO (Fallaron 'meta[itemprop=price]' y 'data-price-amount').")

        if product_price:
            print(f"PRECIO FINAL ENCONTRADO: S/ {product_price}")

    except Exception as e:
        print(f"Error al procesar el precio: {e}")

    # --- 3. Extraer el Status (NUEVO) ---
    try:
        # Buscamos el div con clase 'stock'
        stock_div = soup.find('div', class_='stock')

        if stock_div:
            # Obtenemos la lista de clases del div
            class_list = stock_div.get('class', [])

            if 'available' in class_list:
                product_status = "disponible"
                print("STATUS ENCONTRADO: Disponible")
            elif 'unavailable' in class_list:
                product_status = "no disponible"
                print("STATUS ENCONTRADO: No Disponible")
            else:
                # Si encontramos el div pero no la clase, usamos el texto
                status_text = stock_div.get_text().strip().lower()
                if "no" in status_text:
                    product_status = "no disponible"
                    print(f"STATUS (por texto) ENCONTRADO: No Disponible")
                else:
                    print("Info: Se encontró 'div.stock' pero sin clases/texto claros.")
        else:
            print("ERROR: No se pudo encontrar el 'div.stock' del status.")

    except Exception as e:
        print(f"Error al procesar el status: {e}")

    print("--- [Scraper: LaCuracao V3] Análisis Terminado ---")

    # Devolver los 3 valores
    return product_title, product_price, product_status