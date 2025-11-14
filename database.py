import sqlite3
from pathlib import Path

# --- Constantes Centralizadas de la Base de Datos ---
DB_NAME = "precios.db"
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / DB_NAME
DB_TIMEOUT = 15  # <-- ¡LA SOLUCIÓN! (Esperará hasta 15 segundos)


def setup_database():
    """
    Configura la BD. Esta función crea las tablas si no existen.
    Es 'idempotente' (se puede llamar de forma segura múltiples veces).
    """
    print("[Database] Asegurando que la base de datos exista y esté actualizada...")

    # Usar get_db_conn() para asegurar que el timeout se aplique también aquí
    conn = get_db_conn()
    cursor = conn.cursor()

    # Tabla de Productos
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL UNIQUE,
        nombre TEXT,
        tienda TEXT,
        precio_inicial REAL,
        precio_objetivo REAL,
        notificacion_objetivo_enviada BOOLEAN DEFAULT 0,
        status TEXT DEFAULT 'ninguno',
        precio_mas_bajo REAL
    )
    ''')
    # Tabla de Historial
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS HistorialPrecios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER,
        precio REAL,
        fecha DATETIME,
        FOREIGN KEY (producto_id) REFERENCES Productos (id) ON DELETE CASCADE
    )
    ''')
    conn.commit()
    conn.close()
    print(f"[Database] Base de datos '{DB_NAME}' lista.")


def get_db_conn():
    """
    Establece conexión con la BD, habilita foreign keys y
    configura un timeout para evitar errores de 'database is locked'.
    """
    # ¡LA SOLUCIÓN! Se añade el parámetro timeout
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn