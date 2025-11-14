import time
import scraper_engine  # <-- ¡Importamos nuestro nuevo motor!
import database        # <-- ¡Importamos nuestro gestor de BD!

HOURS_BETWEEN_RUNS = 1  # Correrá cada 1 hora


if __name__ == "__main__":
    # 1. Asegurar que la BD exista al arrancar
    database.setup_database()

    print(f"[Tracker] Iniciando bucle principal. Se ejecutará cada {HOURS_BETWEEN_RUNS} hora(s).")
    while True:
        try:
            # 2. Llamar al motor para que haga all el trabajo
            scraper_engine.track_all_products()

            # 3. Dormir hasta el próximo ciclo
            sleep_seconds = HOURS_BETWEEN_RUNS * 60 * 60
            print(f"[Tracker] Ciclo completado. Durmiendo por {sleep_seconds} segundos...")
            time.sleep(sleep_seconds)

        except Exception as e:
            print(f"[Tracker] Error en el bucle principal: {e}")
            print("[Tracker] Esperando 5 minutos antes de reintentar...")
            time.sleep(300)