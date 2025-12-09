import sqlite3
from pathlib import Path
import logging
import queue
from contextlib import contextmanager

# Configurar un logger para este módulo
log = logging.getLogger(__name__)

# --- Constantes Centralizadas de la Base de Datos ---
DB_NAME = "precios.db"
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / DB_NAME
DB_TIMEOUT = 60  # Timeout alto para evitar bloqueos en cargas pesadas


class SQLiteConnectionPool:
    """
    Gestiona un pool de conexiones para SQLite.
    Permite que múltiples hilos soliciten conexiones sin bloquear el archivo
    indefinidamente, controlando la concurrencia.
    """

    def __init__(self, db_path, max_connections=10):
        self.db_path = db_path
        # Usamos una cola para limitar la concurrencia
        self.slots = queue.Queue(maxsize=max_connections)
        for _ in range(max_connections):
            self.slots.put(None)

    @contextmanager
    def get_conn(self):
        """
        Context manager para obtener una conexión del pool.
        Uso:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()
                ...
        """
        token = self.slots.get(timeout=120)  # Espera máx 2 mins por un slot libre
        conn = None
        try:
            # En SQLite es mejor crear conexiones nuevas por hilo que compartir objetos
            conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
        except Exception as e:
            log.error(f"Error de BD en el pool: {e}")
            raise e
        finally:
            if conn:
                conn.close()
            self.slots.put(token)  # Liberar el slot


# --- INSTANCIA GLOBAL DEL POOL ---
# Esta es la variable que scraper_engine.py estaba buscando y no encontraba
db_pool = SQLiteConnectionPool(DB_PATH)


def setup_database():
    """
    Configura la BD. Esta función crea las tablas si no existen.
    """
    if log.hasHandlers():
        log.info("Asegurando que la base de datos exista y esté actualizada...")
    else:
        print("[Database] Asegurando que la base de datos exista...")

    # Usamos una conexión directa para el setup
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")

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

    if log.hasHandlers():
        log.info(f"Base de datos '{DB_NAME}' lista y optimizada (WAL).")


def get_db_conn():
    """
    Establece conexión directa con la BD.
    Mantenida para compatibilidad con bot_manager.py y funciones simples.
    """
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn