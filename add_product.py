import sqlite3
from urllib.parse import urlparse  # Importamos el analizador de URLs

DB_NAME = "precios.db"


def detect_store(url):
    """
    Analiza la URL para detectar el nombre de la tienda.
    """
    domain = urlparse(url).netloc.lower()

    if 'mercadolibre' in domain:
        return 'MercadoLibre'
    if 'lacuracao' in domain:
        return 'LaCuracao'
    if 'falabella' in domain:
        return 'Falabella'
    if 'ripley' in domain:
        return 'Ripley'

    # Si no la conocemos, devolvemos None
    return None


def add_new_product():
    """
    Pide al usuario una URL, detecta la tienda y la añade a la BD.
    """

    print("---[ Añadir Nuevo Producto al Tracker ]---")

    # 1. Pedir URL
    url = input("Pega la URL completa del producto: ").strip()
    if not url:
        print("Error: La URL no puede estar vacía.")
        return

    # 2. Detectar Tienda
    tienda = detect_store(url)

    if not tienda:
        print(f"No se pudo detectar la tienda para: {url}")
        tienda = input("Por favor, ingresa el nombre de la tienda (ej. MercadoLibre): ").strip()
    else:
        print(f"Tienda detectada: {tienda}")

    if not tienda:
        print("Error: La tienda no puede estar vacía.")
        return

    # 3. Conectarse a la BD
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO Productos (url, nombre, tienda) VALUES (?, ?, ?)",
                       (url, None, tienda))
        conn.commit()
        print(f"\n¡Éxito! Producto añadido.")
        print(f"URL: {url}")
        print(f"Tienda: {tienda}")

    except sqlite3.IntegrityError:
        print("\nError: Esta URL ya existe en la base de datos.")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    add_new_product()