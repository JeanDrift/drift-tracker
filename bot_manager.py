import sqlite3
import os
import asyncio
import time
import socket
from urllib.parse import urlparse
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError, TimedOut, BadRequest
from telegram.request import HTTPXRequest  # <-- IMPORTANTE PARA TIMEOUTS
from telegram.ext import (
    Application, CommandHandler, ContextTypes, filters,
    CallbackQueryHandler, ConversationHandler, MessageHandler
)
import logging

# --- Importar módulos del proyecto ---
import scraper_engine
import database
import log_setup

# --- Configurar Logger ---
log = log_setup.setup_logging('bot_manager')

# --- Cargar variables de entorno ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Estados para la conversación ---
(STATE_SET_TARGET) = range(1)


# ==========================================================
# --- Funciones de Resiliencia ---
# ==========================================================

def wait_for_internet():
    """Verifica conexión a Internet (DNS Google) antes de arrancar."""
    log.info("Verificando conectividad a Internet...")
    while True:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=5)
            log.info("¡Conexión a Internet detectada!")
            return
        except OSError:
            log.warning("No hay conexión a Internet. Reintentando en 30s...")
            time.sleep(30)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Captura errores globales para evitar que el bot muera."""
    try:
        raise context.error
    except (NetworkError, TimedOut):
        log.warning("⚠️ Error de red/timeout con Telegram. El bot reintentará automáticamente.")
        # No hacemos nada, dejamos que el polling lo intente de nuevo
    except Exception as e:
        log.error(f"🔥 Excepción no controlada: {e}", exc_info=True)


# ==========================================================
# --- Lógica de Tienda ---
# ==========================================================
def detect_store(url):
    domain = urlparse(url).netloc.lower()
    if 'mercadolibre' in domain: return 'MercadoLibre'
    if 'lacuracao' in domain: return 'LaCuracao'
    if 'falabella' in domain: return 'Falabella'
    if 'ripley' in domain: return 'Ripley'
    return None


# ==========================================================
# --- Comandos del Bot ---
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Soy tu bot de seguimiento de precios.\n"
        "Usa /lista para ver productos.\n"
        "Usa /agregar <URL> para añadir uno nuevo.\n"
        "Usa /actualizar para forzar revisión."
    )


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("Comando /lista recibido.")
    try:
        conn = database.get_db_conn()
        cursor = conn.cursor()
        query = """
        SELECT
            P.id, P.nombre, P.precio_objetivo, P.status, P.precio_mas_bajo,
            (SELECT H.precio FROM HistorialPrecios H
             WHERE H.producto_id = P.id
             ORDER BY H.fecha DESC
             LIMIT 1) AS ultimo_precio
        FROM Productos P
        """
        cursor.execute(query)
        productos = cursor.fetchall()
        conn.close()

        if not productos:
            await update.message.reply_text("No hay productos en la base de datos.")
            return

        await update.message.reply_text("--- 📦 TUS PRODUCTOS ---")

        for prod in productos:
            id, nombre, objetivo, status, precio_mas_bajo, ultimo_precio = prod

            nombre_str = nombre if nombre else "(Pendiente...)"
            objetivo_str = f"S/ {objetivo}" if objetivo else "No fijado"
            precio_str = f"S/ {ultimo_precio}" if ultimo_precio else "N/A"
            precio_mas_bajo_str = f"S/ {precio_mas_bajo}" if precio_mas_bajo else "N/A"
            status_str = status.capitalize() if status else "Ninguno"

            message = (
                f"*{nombre_str}*\n"
                f"*ID:* {id} | *Status:* {status_str}\n"
                f"*Precio Actual:* {precio_str}\n"
                f"*Precio Más Bajo:* {precio_mas_bajo_str}\n"
                f"*Meta:* {objetivo_str}"
            )

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Fijar Meta", callback_data=f"set_{id}"),
                    InlineKeyboardButton("Eliminar", callback_data=f"del_{id}")
                ],
                [
                    InlineKeyboardButton("🕑 Actualizar Este Item", callback_data=f"update_{id}")
                ]
            ])

            # Enviamos el mensaje. Si falla por timeout, el try/except lo atrapa.
            await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')

    except (TimedOut, NetworkError):
        log.warning("Timeout al enviar la lista. La conexión es inestable.")
        # Intentamos avisar al usuario si es posible
        try:
            await update.message.reply_text("⚠️ La red está lenta, no pude enviar la lista completa.")
        except:
            pass


async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info(f"Comando /agregar recibido con args: {context.args}")
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usa /agregar <URL_COMPLETA>")
        return

    url = context.args[0].strip()
    tienda = detect_store(url)
    if not tienda:
        await update.message.reply_text("Tienda no reconocida.")
        return

    conn = database.get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO Productos (url, tienda, status, notificacion_objetivo_enviada) VALUES (?, ?, 'ninguno', 0)",
            (url, tienda)
        )
        conn.commit()
        product_id = cursor.lastrowid

        await update.message.reply_text(f"✅ Producto añadido (ID: {product_id}). Iniciando tracking...")

        await asyncio.to_thread(scraper_engine.track_single_product, product_id)

        await update.message.reply_text(f"¡Tracking inicial completado!")

    except sqlite3.IntegrityError:
        await update.message.reply_text("Error: URL ya registrada.")
    except Exception as e:
        log.error(f"Error en /agregar: {e}", exc_info=True)
        await update.message.reply_text("Error interno.")
    finally:
        conn.close()


async def update_all_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("Comando /actualizar recibido.")
    count = scraper_engine.get_product_count()
    if count == 0:
        await update.message.reply_text("No hay productos.")
        return

    total_seconds = count * (scraper_engine.SCRAPING_WAIT_TIME + scraper_engine.POST_SCRAPE_SLEEP)
    minutes = total_seconds // 60

    await update.message.reply_text(
        f"Actualizando {count} productos.\nEstimado: ~{minutes} min."
    )
    await asyncio.to_thread(scraper_engine.track_all_products)
    await update.message.reply_text("✅ Actualización completa.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass  # Si falla el answer por red, seguimos

    data = query.data
    if data == "cancel_delete":
        await query.edit_message_text("Cancelado.")
        return

    if data.startswith("del_confirm_"):
        try:
            product_id = int(data.split('_')[2])
            conn = database.get_db_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Productos WHERE id = ?", (product_id,))
            conn.commit()
            conn.close()
            await query.edit_message_text(f"ID {product_id} eliminado.")
        except Exception as e:
            log.error(f"Error eliminando: {e}")
        return

    try:
        action, product_id_str = data.split('_')
        product_id = int(product_id_str)
    except:
        return

    if action == "del":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("SÍ, Eliminar", callback_data=f"del_confirm_{product_id}")],
            [InlineKeyboardButton("Cancelar", callback_data="cancel_delete")]
        ])
        await query.edit_message_text(f"¿Eliminar ID {product_id}?", reply_markup=keyboard)

    elif action == "set":
        context.user_data['product_id_to_set'] = product_id
        await query.message.reply_text(f"Ingresa precio objetivo para ID {product_id}:")
        return STATE_SET_TARGET

    elif action == "update":
        await query.message.reply_text(f"Actualizando ID {product_id}...")
        await asyncio.to_thread(scraper_engine.track_single_product, product_id)
        await query.message.reply_text("¡Actualizado!")


async def receive_target_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_price = float(update.message.text)
        product_id = context.user_data['product_id_to_set']
        conn = database.get_db_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE Productos SET precio_objetivo = ?, notificacion_objetivo_enviada = 0 WHERE id = ?",
            (new_price, product_id)
        )
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Objetivo para ID {product_id}: S/ {new_price}")
    except ValueError:
        await update.message.reply_text("Debe ser un número.")
        return STATE_SET_TARGET
    except Exception as e:
        log.error(f"Error setting price: {e}")
    finally:
        context.user_data.clear()
        return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END


# ==========================================================
# --- Función Principal ---
# ==========================================================

def main():
    wait_for_internet()
    database.setup_database()

    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.critical("Faltan credenciales en .env")
        return

    log.info("Iniciando el bot con Timeouts Aumentados...")
    user_filter = filters.User(user_id=int(CHAT_ID))

    # --- AUMENTAR TIMEOUTS AQUÍ ---
    # Esto le da al bot más paciencia con tu internet lento
    request = HTTPXRequest(connection_pool_size=8, connect_timeout=60, read_timeout=60)

    application = Application.builder().token(TELEGRAM_TOKEN).request(request).build()

    application.add_error_handler(error_handler)

    set_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^set_')],
        states={STATE_SET_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target_price)]},
        fallbacks=[CommandHandler('cancelar', cancel_conversation)]
    )
    application.add_handler(set_price_conv)

    application.add_handler(CommandHandler("start", start, filters=user_filter))
    application.add_handler(CommandHandler("lista", list_products, filters=user_filter))
    application.add_handler(CommandHandler("agregar", add_product, filters=user_filter))
    application.add_handler(CommandHandler("actualizar", update_all_products, filters=user_filter))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^(del_|cancel_delete|update_)'))

    log.info("Bot escuchando...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            log.critical(f"Caída del bot: {e}. Reiniciando en 60s...", exc_info=True)
            time.sleep(60)