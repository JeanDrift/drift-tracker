import re
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def parse(driver):
    """
    Versión Proactiva: Espera dinámicamente a que el botón de compra pierda la clase 'hidden'.
    """
    print("\n--- [Scraper: LG Store V8] Iniciando Análisis ---")

    try:
        # 1. Manejo de Cookies
        try:
            cookie_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            cookie_btn.click()
            print("Info: Cookies aceptadas.")
            time.sleep(3)  # Espera crítica para la recarga de página
        except:
            pass

        # 2. ESPERA INTELIGENTE POR EL BOTÓN DE COMPRA
        # En lugar de solo esperar al título, esperamos a que aparezca
        # CUALQUIERA de los dos botones principales de acción.
        print("Esperando validación de stock en el DOM...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".buy-now-button, .stock-alert-button"))
        )

        # Damos un pequeño margen para que los scripts de LG terminen de alternar la clase 'hidden'
        time.sleep(2)

    except Exception as e:
        print(f"Error: No se detectaron botones de compra o alerta: {e}")
        return None, None, "ninguno"

    # Captura del HTML después de la espera dinámica
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    product_title = None
    product_price = None
    product_status = "no disponible"

    try:
        # A. Extracción de Título
        title_el = soup.select_one('h2.pdp-title.font-family-headline')
        product_title = title_el.get_text().strip() if title_el else "Desconocido"

        # B. Extracción de Precio (Lógica estándar)
        price_div = soup.find('div', class_='price-top')
        if price_div:
            target_span = price_div.find('span', string=re.compile(r'S/'))
            if not target_span:
                spans = price_div.find_all('span')
                for s in spans:
                    if "S/" in s.get_text():
                        target_span = s;
                        break
            if target_span:
                product_price = int(float(re.sub(r'[^\d.]', '', target_span.get_text())))

        # C. LÓGICA DE STATUS REFORZADA (Identificando por ID o clase exacta)
        # Usamos selectores CSS para ser más precisos con las clases múltiples
        buy_now = soup.select_one('a.buy-now-button')
        stock_alert = soup.select_one('a.stock-alert-button')

        def check_hidden(el):
            if not el: return True
            return 'hidden' in el.get('class', [])

        # Prioridad absoluta: Si el botón 'Comprar ahora' NO tiene la clase 'hidden', hay stock.
        if buy_now and not check_hidden(buy_now):
            product_status = "disponible"
            print("STATUS: Disponible (Botón 'Comprar ahora' visible en el DOM)")

        # Si el de compra está oculto pero el de alerta está visible, no hay stock.
        elif stock_alert and not check_hidden(stock_alert):
            product_status = "no disponible"
            print("STATUS: No disponible (Botón 'Recibe alerta' visible en el DOM)")

        # Caso de seguridad: Si ambos existen pero la lógica falla, comparamos clases
        else:
            if buy_now and 'hidden' not in buy_now.get('class', []):
                product_status = "disponible"
            else:
                product_status = "no disponible"

    except Exception as e:
        print(f"Error procesando disponibilidad: {e}")

    return product_title, product_price, product_status