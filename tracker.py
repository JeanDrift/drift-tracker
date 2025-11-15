import time
import scraper_engine
import database
import log_setup  # <-- ¡NUEVA IMPORTACIÓN!
import logging

# --- Configurar Logger ---
log = log_setup.setup_logging('tracker')

HOURS_BETWEEN_RUNS = 1

if __name__ == "__main__":
    # 1. Asegurar que la BD exista al arrancar
    try:
        database.setup_database()
    except Exception as e:
        log.critical(f"No se pudo inicializar la base de datos: {e}", exc_info=True)
        exit()  # Salir si no se puede crear la BD

    log.info(f"Iniciando bucle principal. Se ejecutará cada {HOURS_BETWEEN_RUNS} hora(s).")

    while True:
        try:
            # 2. Llamar al motor para que haga todo el trabajo
            scraper_engine.track_all_products()

            # 3. Dormir hasta el próximo ciclo
            sleep_seconds = HOURS_BETWEEN_RUNS * 60 * 60
            log.info(f"Ciclo completado. Durmiendo por {sleep_seconds} segundos...")
            time.sleep(sleep_seconds)

        except Exception as e:
            log.error(f"Error en el bucle principal: {e}", exc_info=True)
            log.warning("Esperando 5 minutos antes de reintentar...")
            time.sleep(300)