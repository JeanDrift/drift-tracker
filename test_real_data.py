import asyncio
import scraper_engine
import log_setup
import logging

# Force console logging to see output
logging.getLogger().setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.getLogger().addHandler(handler)

async def main():
    print("--- Starting Real Data Test ---")
    try:
        await scraper_engine.track_all_products()
    except Exception as e:
        print(f"ERROR: {e}")
    print("--- Test Finished ---")

if __name__ == "__main__":
    asyncio.run(main())
