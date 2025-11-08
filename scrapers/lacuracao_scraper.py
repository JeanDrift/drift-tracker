import re
from bs4 import BeautifulSoup


def parse(html):
    """
    Analiza el HTML de una página de producto de La Curacao.
    (Versión 2: Usa 'itemprop' para máxima fiabilidad).
    """
    if html is None:
        print("No hay HTML para analizar.")
        return None, None

    print("\n--- [Scraper: LaCuracao V2] Iniciando Análisis ---")
    soup = BeautifulSoup(html, 'html.parser')

    product_title = None
    product_price = None

    # --- 1. Extraer el Título (Nueva Lógica) ---
    try:
        # Buscamos por 'itemprop="name"', que es más fiable que una clase CSS
        title_element = soup.find('span', itemprop='name')

        if title_element:
            product_title = title_element.get_text().strip()
            print(f"TÍTULO ENCONTRADO: {product_title}")
        else:
            print("ERROR: No se pudo encontrar el TÍTULO (Selector 'span[itemprop=name]' no encontrado).")

    except Exception as e:
        print(f"Error al procesar el título: {e}")

    # --- 2. Extraer el Precio (Lógica ÓPTIMA) ---
    try:
        # Esta es la forma óptima que descubriste.
        # Buscamos la etiqueta <meta> que contiene el precio limpio.
        price_element = soup.find('meta', itemprop='price')

        if price_element and price_element.get('content'):
            # Obtenemos el valor del atributo 'content', que es "2949"
            price_text = price_element.get('content')
            print(f"Info: 'content' de meta-tag encontrado: '{price_text}'")

            # Convertimos a float (por si trae decimales "2949.00")
            # y luego a int para guardarlo limpio
            product_price = int(float(price_text))
            print(f"PRECIO FINAL ENCONTRADO: S/ {product_price}")

        else:
            # Fallback (Plan B) por si quitan el meta-tag:
            # Buscamos el 'data-price-amount' que también viste
            print("Info: No se encontró 'meta[itemprop=price]'. Buscando 'data-price-amount'...")
            price_span = soup.find('span', {'data-price-amount': True})  # Busca un span que TENGA ese atributo
            if price_span:
                price_text = price_span['data-price-amount']  # "2949"
                print(f"Info: 'data-price-amount' encontrado: '{price_text}'")
                product_price = int(float(price_text))
                print(f"PRECIO FINAL (Fallback) ENCONTRADO: S/ {product_price}")
            else:
                print("ERROR: No se pudo encontrar el PRECIO (Fallaron 'meta[itemprop=price]' y 'data-price-amount').")

    except Exception as e:
        print(f"Error al procesar el precio: {e}")

    print("--- [Scraper: LaCuracao V2] Análisis Terminado ---")
    return product_title, product_price