import sqlite3
from urllib.parse import urlparse
import database  # <-- ¡NUEVA IMPORTACIÓN!


def detect_store(url):
    domain = urlparse(url).netloc.lower()
    if 'mercadolibre' in domain: return 'MercadoLibre'
    if 'lacuracao' in domain: return 'LaCuracao'
    if 'falabella' in domain: return 'Falabella'
    if 'ripley' in domain: return 'Ripley'
    return None


def add_new_product():
    # 1. Asegurar que la BD exista
    database.setup_database()

    print("---[ Añadir Nuevo Producto al Tracker ]---")
    url = input("Pega la URL completa del producto: ").strip()
    if not url:
        print("Error: La URL no puede estar vacía.")
        return

    tienda = detect_store(url)
    if not tienda:
        print(f"No se pudo detectar la tienda para: {url}")
        tienda = input("Por favor, ingresa el nombre de la tienda (ej. MercadoLibre): ").strip()
    else:
        print(f"Tienda detectada: {tienda}")

    if not tienda:
        print("Error: La tienda no puede estar vacía.")
        return

    precio_objetivo_input = input("Ingresa un precio objetivo (opcional, ej: 2500): ").strip()
    precio_objetivo = None
    try:
        if precio_objetivo_input:
            precio_objetivo = float(precio_objetivo_input)
    except ValueError:
        print("Precio objetivo no válido, se guardará sin precio objetivo.")

    conn = database.get_db_conn()  # <-- OPTIMIZADO
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO Productos (url, nombre, tienda, precio_inicial, precio_objetivo) VALUES (?, ?, ?, ?, ?)",
            (url, None, tienda, None, precio_objetivo)
        )
        conn.commit()
        print(f"\n¡Éxito! Producto añadido.")
        print("El bot de Telegram o el tracker lo procesarán pronto.")

    except sqlite3.IntegrityError:
        print("\nError: Esta URL ya existe en la base de datos.")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    add_new_product()