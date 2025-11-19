import time
import asyncio
import scraper_engine
import database
import log_setup

# --- Configurar Logger ---
log = log_setup.setup_logging('tracker')

HOURS_BETWEEN_RUNS = 1

if __name__ == "__main__":
    try:
        database.setup_database()
    except Exception as e:
        log.critical(f"No se pudo inicializar la base de datos: {e}", exc_info=True)
        exit(1)

    log.info("Iniciando servicio de Tracker en segundo plano...")

    while True:
        try:
            log.info("--- Iniciando ciclo de rastreo ---")
            
            # Ejecutar el tracking asíncrono
            asyncio.run(scraper_engine.track_all_products())
            
            log.info("--- Ciclo finalizado ---")

            # Dormir
            sleep_seconds = HOURS_BETWEEN_RUNS * 60 * 60
            log.info(f"Durmiendo por {sleep_seconds} segundos hasta el próximo ciclo...")
            time.sleep(sleep_seconds)

        except Exception as e:
            log.error(f"Error en el bucle principal: {e}", exc_info=True)
            log.warning("Esperando 5 minutos antes de reintentar...")
            time.sleep(300)