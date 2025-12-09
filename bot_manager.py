import sqlite3
import os
import asyncio
import time
import socket
from urllib.parse import urlparse
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError, TimedOut
from telegram.request import HTTPXRequest
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
    """Verifica conexión a Internet antes de arrancar."""
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
    """Captura errores globales."""
    try:
        raise context.error
    except (NetworkError, TimedOut):
        log.warning("⚠️ Error de red/timeout con Telegram. El bot reintentará automáticamente.")
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
# --- FUNCIONES AUXILIARES ---
# ==========================================================

async def show_single_product(context: ContextTypes.DEFAULT_TYPE, chat_id, product_id):
    """
    Función reutilizable para mostrar la tarjeta de UN solo producto.
    """
    conn = database.get_db_conn()
    cursor = conn.cursor()

    query = """
    SELECT
        P.id, P.nombre, P.precio_objetivo, P.status, P.precio_mas_bajo, P.url,
        (SELECT H.precio FROM HistorialPrecios H
         WHERE H.producto_id = P.id
         ORDER BY H.fecha DESC
         LIMIT 1) AS ultimo_precio
    FROM Productos P
    WHERE P.id = ?
    """
    cursor.execute(query, (product_id,))
    prod = cursor.fetchone()
    conn.close()

    if not prod:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ No se encontraron datos para el ID {product_id}.")
        return

    pid, nombre, objetivo, status, precio_mas_bajo, url, ultimo_precio = prod

    nombre_str = nombre if nombre else "(Pendiente de rastrear)"
    objetivo_str = f"S/ {objetivo}" if objetivo else "No fijado"
    precio_str = f"S/ {ultimo_precio}" if ultimo_precio else "Aún no trackeado"
    precio_mas_bajo_str = f"S/ {precio_mas_bajo}" if precio_mas_bajo else "N/A"
    status_str = status.capitalize() if status else "Ninguno"

    status_icon = "🟢" if status == "disponible" else "🔴" if status == "no disponible" else "⚪"

    message = (
        f"📦 *{nombre_str}*\n"
        f"🆔 *ID:* {pid}\n"
        f"{status_icon} *Status:* {status_str}\n\n"
        f"💰 *Precio Actual:* {precio_str}\n"
        f"📉 *Mínimo Histórico:* {precio_mas_bajo_str}\n"
        f"🎯 *Meta:* {objetivo_str}"
    )

    keyboard = [
        [
            InlineKeyboardButton("🎯 Fijar Meta", callback_data=f"set_{pid}"),
            InlineKeyboardButton("🗑 Eliminar", callback_data=f"del_{pid}")
        ],
        [
            InlineKeyboardButton("🔄 Actualizar", callback_data=f"update_{pid}"),
            InlineKeyboardButton("🔗 Ver Producto", url=url)
        ]
    ]

    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=markup, parse_mode='Markdown')


# ==========================================================
# --- Comandos del Bot ---
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Soy tu bot de seguimiento de precios.\n"
        "Usa /lista para ver productos.\n"
        "Usa /agregar <URL> para añadir uno nuevo.\n"
        "Usa /actualizar para forzar revisión masiva."
    )


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("Comando /lista recibido.")

    try:
        conn = database.get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM Productos")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("No hay productos en la base de datos.")
            return

        await update.message.reply_text(f"--- 📦 LISTA DE {len(rows)} PRODUCTOS ---")

        for row in rows:
            await show_single_product(context, update.effective_chat.id, row[0])
            await asyncio.sleep(0.2)

    except Exception as e:
        log.error(f"Error en /lista: {e}")
        await update.message.reply_text("Ocurrió un error al obtener la lista.")


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

        await update.message.reply_text(f"✅ Producto añadido (ID: {product_id}). Procesando...")

        await asyncio.to_thread(scraper_engine.track_single_product, product_id)

        await update.message.reply_text("✅ Proceso finalizado. Aquí tienes el resultado:")
        await show_single_product(context, update.effective_chat.id, product_id)

    except sqlite3.IntegrityError:
        await update.message.reply_text("Error: URL ya registrada.")
    except Exception as e:
        log.error(f"Error en /agregar: {e}", exc_info=True)
        await update.message.reply_text("Error interno.")
    finally:
        conn.close()


async def update_all_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fuerza el tracking de todos los productos.
    """
    log.info("Comando /actualizar recibido.")
    count = scraper_engine.get_product_count()
    if count == 0:
        await update.message.reply_text("No hay productos.")
        return

    total_seconds = count * (scraper_engine.SCRAPING_WAIT_TIME + scraper_engine.POST_SCRAPE_SLEEP)
    minutes = total_seconds // 60

    await update.message.reply_text(
        f"Actualizando {count} productos.\nEstimado: ~{minutes} min.\nTe avisaré al terminar."
    )

    # --- CORRECCIÓN AQUÍ: Llamamos a track_all_products sin argumentos ---
    await asyncio.to_thread(scraper_engine.track_all_products)

    await update.message.reply_text("✅ Actualización masiva completa.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    data = query.data
    if data == "cancel_delete":
        await query.edit_message_text("Operación cancelada.")
        return

    if data.startswith("del_confirm_"):
        try:
            product_id = int(data.split('_')[2])
            conn = database.get_db_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Productos WHERE id = ?", (product_id,))
            conn.commit()
            conn.close()
            await query.edit_message_text(f"🗑 Producto ID {product_id} eliminado.")
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
            [InlineKeyboardButton("❌ SÍ, Eliminar definitivamente", callback_data=f"del_confirm_{product_id}")],
            [InlineKeyboardButton("Cancelar", callback_data="cancel_delete")]
        ])
        await query.message.reply_text(f"⚠️ ¿Estás seguro de eliminar el ID {product_id}?", reply_markup=keyboard)

    elif action == "set":
        context.user_data['product_id_to_set'] = product_id
        await query.message.reply_text(f"🎯 Ingresa el nuevo precio META para el ID {product_id}:")
        return STATE_SET_TARGET

    elif action == "update":
        await query.message.reply_text(f"⏳ Actualizando ID {product_id}...")
        await asyncio.to_thread(scraper_engine.track_single_product, product_id)
        await show_single_product(context, update.effective_chat.id, product_id)


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

        await update.message.reply_text(f"✅ Meta actualizada.")
        await show_single_product(context, update.effective_chat.id, product_id)

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
    await update.message.reply_text("Operación cancelada.")
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

    log.info("Iniciando el bot...")
    user_filter = filters.User(user_id=int(CHAT_ID))

    # Timeouts aumentados
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