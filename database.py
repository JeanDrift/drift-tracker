import sqlite3
from pathlib import Path
import logging

# Configurar un logger para este módulo
log = logging.getLogger(__name__)

# --- Constantes Centralizadas de la Base de Datos ---
DB_NAME = "precios.db"
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from queue import Queue, Empty
import logging

# Directorio base
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "precios.db"
DB_TIMEOUT = 10  # Segundos

log = logging.getLogger('database')

class DatabasePool:
    def __init__(self, db_path, max_connections=5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = Queue(maxsize=max_connections)
        self._initialize_pool()

    def _create_connection(self):
        """Crea una nueva conexión configurada."""
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging para mejor concurrencia
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _initialize_pool(self):
        """Llena el pool con conexiones iniciales."""
        for _ in range(self.max_connections):
            self.pool.put(self._create_connection())

    @contextmanager
    def get_conn(self):
        """
        Context manager para obtener una conexión del pool.
        Uso:
        with db_pool.get_conn() as conn:
            cursor = conn.cursor()
            ...
        """
        conn = None
        try:
            conn = self.pool.get(timeout=DB_TIMEOUT)
            yield conn
        except Empty:
            log.error("Timeout esperando conexión disponible en el pool.")
            raise Exception("Database pool exhausted")
        except Exception as e:
            log.error(f"Error de base de datos: {e}")
            raise
        finally:
            if conn:
                self.pool.put(conn)

    def close_all(self):
        """Cierra todas las conexiones del pool (al apagar la app)."""
        while not self.pool.empty():
            try:
                conn = self.pool.get_nowait()
                conn.close()
            except:
                pass

# Instancia global del pool
db_pool = DatabasePool(DB_PATH)

def setup_database():
    """Crea la tabla si no existe (usando el pool)."""
    with db_pool.get_conn() as conn:
        cursor = conn.cursor()
        
        # Tabla Productos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                nombre TEXT,
                precio_objetivo REAL,
                precio_inicial REAL,
                precio_mas_bajo REAL,
                notificacion_objetivo_enviada BOOLEAN DEFAULT 0,
                tienda TEXT,
                status TEXT DEFAULT 'ninguno'
            )
        """)

        # Tabla HistorialPrecios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS HistorialPrecios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id INTEGER,
                precio REAL,
                fecha TEXT,
                FOREIGN KEY(producto_id) REFERENCES Productos(id)
            )
        """)
        conn.commit()
    
    log.info("Base de datos 'precios.db' lista (WAL mode).")

# Wrapper para compatibilidad (aunque se recomienda usar db_pool.get_conn)
def get_db_conn():
    """
    DEPRECATED: Usar db_pool.get_conn() en su lugar.
    Retorna una conexión nueva (no del pool) para casos legacy.
    """
    return sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)