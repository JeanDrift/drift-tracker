import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Directorio base del proyecto
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"

# Asegurarse de que el directorio de logs exista
LOG_DIR.mkdir(exist_ok=True)


def setup_logging(script_name: str):
    """
    Configura un logger centralizado que escribe en archivos rotativos.
    """
    # 1. Crear el nombre del archivo de log
    log_file = LOG_DIR / f"{script_name}.log"

    # 2. Definir el formato del log
    # (timestamp) [NIVEL] [NombreScript] Mensaje
    log_format = logging.Formatter(
        '%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 3. Configurar el "Rotating File Handler"
    # Creará hasta 5 archivos de log de 5MB cada uno.
    # Cuando 'script.log' se llena, lo renombra a 'script.log.1', etc.
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding='utf-8'
    )
    handler.setFormatter(log_format)

    # 4. Configurar el logger
    logger = logging.getLogger(script_name)
    logger.setLevel(logging.INFO)
    
    # EVITAR DOBLE LOGGING: No propagar al root logger
    logger.propagate = False

    # Evitar que se añadan múltiples handlers si se importa varias veces
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(handler)

    # 5. (Opcional) Añadir un handler para que también imprima en la consola
    # Esto es útil para depurar. Puedes comentarlo en producción.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # 6. Redirigir todos los 'print' y 'errores' a este logger
    # Esto captura errores de librerías (como 'database is locked')
    # Nota: basicConfig configura el ROOT logger. Si propagate fuera True, saldría doble.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s',
        handlers=[handler, console_handler]
    )

    return logger