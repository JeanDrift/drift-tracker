import sqlite3
from pathlib import Path
import logging

# Configurar un logger para este módulo
log = logging.getLogger(__name__)

# --- Constantes Centralizadas de la Base de Datos ---
DB_NAME = "precios.db"
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / DB_NAME
DB_TIMEOUT = 15

def setup_database():
    """
    Configura la BD. Esta función crea las tablas si no existen.
    """
    log.info("Asegurando que la base de datos exista y esté actualizada...")
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

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
    log.info(f"Base de datos '{DB_NAME}' lista.")

def get_db_conn():
    """
    Establece conexión con la BD, habilita foreign keys y
    configura un timeout para evitar errores de 'database is locked'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn