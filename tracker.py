import time
import re  # Importamos la librería de expresiones regulares para limpiar el precio
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


def get_page_html(url):
    """
    Usa Selenium para abrir una URL, esperar a que cargue,
    y devolver el HTML de la página.
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

        # Aumentamos la espera a 7 segundos. Mercado Libre es lento
        # y a veces necesita más tiempo para cargar el precio.
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


def parse_product_data(html):
    """
    Usa BeautifulSoup para analizar el HTML y extraer los datos clave.
    (Versión 3: Prioriza el precio de descuento y, si no existe,
    busca el precio normal).
    """
    if html is None:
        print("No hay HTML para analizar.")
        return

    print("\n--- Iniciando Análisis (Lógica de Descuento Priorizada) ---")
    soup = BeautifulSoup(html, 'html.parser')

    # --- 1. Extraer el Título (sigue igual) ---
    try:
        title_element = soup.find('h1', class_='ui-pdp-title')
        if title_element:
            product_title = title_element.get_text().strip()
            print(f"TÍTULO ENCONTRADO: {product_title}")
        else:
            print("ERROR: No se pudo encontrar el TÍTULO. (Clase 'ui-pdp-title' cambió)")

    except Exception as e:
        print(f"Error al procesar el título: {e}")

    # --- 2. Extraer el Precio (NUEVA LÓGICA DE PRIORIDAD) ---
    try:
        product_price = None
        price_element = None  # Variable para guardar el tag del precio

        # --- Prioridad 1: Buscar el precio con descuento ---
        # Buscamos el contenedor '...__second-line' que identificaste
        discount_container = soup.find('div', class_='ui-pdp-price__second-line')

        if discount_container:
            # Si encontramos el contenedor de descuento, buscamos la fracción DENTRO de él
            price_element = discount_container.find('span', class_='andes-money-amount__fraction')
            if price_element:
                print("Info: Precio de DESCUENTO ('second-line') encontrado.")

        # --- Prioridad 2: Buscar el precio normal (si no se encontró el de descuento) ---
        if not price_element:
            # Si price_element sigue vacío (no hubo 'second-line' o no tenía fracción)
            # buscamos el contenedor '...__part__container' que identificaste
            normal_container = soup.find('div', class_='ui-pdp-price__part__container')

            if normal_container:
                # Buscamos la fracción DENTRO de este contenedor normal
                price_element = normal_container.find('span', class_='andes-money-amount__fraction')
                if price_element:
                    print("Info: Precio NORMAL ('part__container') encontrado.")

        # --- Procesamiento Final ---
        # Si, después de ambas búsquedas, 'price_element' tiene algo:
        if price_element:
            price_text = price_element.get_text().strip()
            price_cleaned = re.sub(r'[^\d]', '', price_text)
            product_price = int(price_cleaned)
            print(f"PRECIO FINAL ENCONTRADO: S/ {product_price}")
        else:
            # Si no se encontró ni el de descuento ni el normal
            print("ERROR: No se pudo encontrar ningún selector de precio válido.")

    except Exception as e:
        print(f"Error al procesar el precio: {e}")

    print("--- Análisis Terminado ---")


# --- Bloque Principal para Ejecutar ---
if __name__ == "__main__":
    # ¡Tu URL!
    PRODUCT_URL = "https://www.mercadolibre.com.pe/logitech-m170-negro/p/MPE15144095#polycard_client=recommendations_home_navigation-related-recommendations&reco_backend=recomm_platform_exp_com_org_rfa&wid=MPE832211988&reco_client=home_navigation-related-recommendations&reco_item_pos=3&reco_backend_type=function&reco_id=b1250a9e-c3a8-4dee-9090-2e1ccd4961b0&sid=recos&c_id=/home/navigation-related-recommendations/element&c_uid=8c4d0f6a-18e1-4f4f-934d-0f7eb117b553"

    # 1. Obtenemos el HTML
    html_content = get_page_html(PRODUCT_URL)

    # (Opcional: guardar el HTML para revisarlo si falla)
    # if html_content:
    #     with open("pagina_debug.html", "w", encoding="utf-8") as f:
    #         f.write(html_content)
    #     print("HTML guardado en 'pagina_debug.html' para revisión.")

    # 2. Analizamos el HTML
    parse_product_data(html_content)