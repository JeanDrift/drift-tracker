import sqlite3
import os
import asyncio
import time  # <-- Importamos time
from urllib.parse import urlparse
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError  # <-- Importamos el error de red
from telegram.ext import (
    Application, CommandHandler, ContextTypes, filters,
    CallbackQueryHandler, ConversationHandler, MessageHandler
)

# --- Importar módulos del proyecto ---
import scraper_engine
import database

# --- Cargar variables de entorno ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Estados para la conversación ---
(STATE_SET_TARGET) = range(1)


# ==========================================================
# --- Lógica de Tienda ---
# (Esta sección no cambia)
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
# (Todas las funciones async: start, list_products, add_product,
# update_all_products, button_handler, receive_target_price,
# cancel_conversation... NO CAMBIAN EN ABSOLUTO)
# ...
# ... (Pega aquí todas tus funciones async sin cambios) ...
# ...
# ==========================================================
# (Asegúrate de pegar todas las funciones desde 'start'
# hasta 'cancel_conversation' aquí)
# ==========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Soy tu bot de seguimiento de precios.\n"
        "Usa /lista para ver y gestionar tus productos.\n"
        "Usa /agregar <URL> para agregar un nuevo producto.\n"
        "Usa /actualizar para forzar el tracking de todos los productos."
    )


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[Bot] Comando /lista recibido.")
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
        await update.message.reply_text("No hay productos en la base de datos. Usa /agregar <URL> para empezar.")
        return

    await update.message.reply_text("--- 📦 TUS PRODUCTOS ---")

    for prod in productos:
        id, nombre, objetivo, status, precio_mas_bajo, ultimo_precio = prod

        nombre_str = nombre if nombre else "(Pendiente de rastrear)"
        objetivo_str = f"S/ {objetivo}" if objetivo else "No fijado"
        precio_str = f"S/ {ultimo_precio}" if ultimo_precio else "Aún no trackeado"
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

        await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')


async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[Bot] Comando /agregar recibido con args: {context.args}")

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Error: Formato incorrecto.\n"
            "Usa /agregar <URL_COMPLETA_DEL_PRODUCTO>"
        )
        return

    url = context.args[0].strip()
    tienda = detect_store(url)

    if not tienda:
        await update.message.reply_text("Error: Tienda no reconocida o URL no válida.")
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

        await update.message.reply_text(
            f"¡Éxito! ✅\n"
            f"Producto añadido (ID: {product_id})...\n"
            f"Iniciando primer tracking en segundo plano. Te avisaré al terminar."
        )

        await asyncio.to_thread(scraper_engine.track_single_product, product_id)

        await update.message.reply_text(f"¡Primer tracking para ID {product_id} completado!")

    except sqlite3.IntegrityError:
        await update.message.reply_text("Error: Esta URL ya está siendo rastreada.")
    except Exception as e:
        print(f"[Bot] Error en /agregar: {e}")
        await update.message.reply_text(f"Ocurrió un error inesperado: {e}")
    finally:
        conn.close()


async def update_all_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fuerza el tracking de todos los productos."""
    print("[Bot] Comando /actualizar recibido.")

    count = scraper_engine.get_product_count()
    if count == 0:
        await update.message.reply_text("No hay productos para actualizar.")
        return

    total_seconds = count * (scraper_engine.SCRAPING_WAIT_TIME + scraper_engine.POST_SCRAPE_SLEEP)
    minutes = total_seconds // 60

    await update.message.reply_text(
        f"Iniciando actualización de *{count}* producto(s).\n"
        f"Tiempo estimado: *~{minutes} minutos* ({total_seconds} segundos).\n\n"
        "El bot seguirá respondiendo. Te avisaré cuando termine.",
        parse_mode='Markdown'
    )

    await asyncio.to_thread(scraper_engine.track_all_products)
    await update.message.reply_text("✅ ¡Actualización de todos los productos completada!")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las pulsaciones de los botones (Callbacks)."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "cancel_delete":
        await query.edit_message_text("Eliminación cancelada.")
        return

    # Manejar "confirmar eliminación" PRIMERO
    if data.startswith("del_confirm_"):
        try:
            product_id = int(data.split('_')[2])
            conn = database.get_db_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Productos WHERE id = ?", (product_id,))
            conn.commit()
            conn.close()
            await query.edit_message_text(f"Producto ID {product_id} eliminado exitosamente.")
        except Exception as e:
            print(f"[Bot] Error en del_confirm: {e}")
            await query.edit_message_text(f"Error al eliminar: {e}")
        return

    # Si no es un caso especial, AHORA podemos hacer el split genérico
    try:
        action, product_id_str = data.split('_')
        product_id = int(product_id_str)
    except ValueError:
        await query.edit_message_text("Error: Botón con datos malformados.")
        print(f"[Bot] Error de split en callback_data: {data}")
        return

    # Manejar el resto de acciones (del, set, update)
    if action == "del":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("SÍ, Eliminar", callback_data=f"del_confirm_{product_id}")],
            [InlineKeyboardButton("Cancelar", callback_data="cancel_delete")]
        ])
        await query.edit_message_text(f"¿Seguro que quieres eliminar el producto ID {product_id}?",
                                      reply_markup=keyboard)

    elif action == "set":
        context.user_data['product_id_to_set'] = product_id
        await query.message.reply_text(f"Por favor, ingresa el nuevo precio objetivo para el producto ID {product_id}:")
        return STATE_SET_TARGET

    elif action == "update":
        await query.message.reply_text(f"Iniciando tracking para ID {product_id} en segundo plano...")
        await asyncio.to_thread(scraper_engine.track_single_product, product_id)
        await query.message.reply_text(f"¡Tracking para ID {product_id} completado!")


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

        await update.message.reply_text(
            f"¡Éxito! ✅\n"
            f"Precio objetivo para el producto ID {product_id} actualizado a S/ {new_price}."
        )

    except ValueError:
        await update.message.reply_text(
            "Eso no es un número. Por favor, intenta de nuevo (ej: 2499.50) o /cancelar para salir.")
        return STATE_SET_TARGET
    except Exception as e:
        await update.message.reply_text(f"Ocurrió un error: {e}")
    finally:
        context.user_data.clear()
        return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END


# ==========================================================
# --- Función Principal del Bot (REESCRITA PARA RESILIENCIA) ---
# ==========================================================

def main():
    """Inicia el bot de Telegram."""
    database.setup_database()  # Asegurar que la BD exista

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Error: TELEGRAM_TOKEN o CHAT_ID no están en el archivo .env")
        return

    print("Iniciando el bot...")
    user_filter = filters.User(user_id=int(CHAT_ID))

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Configurar Conversación
    set_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^set_')],
        states={
            STATE_SET_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target_price)]
        },
        fallbacks=[CommandHandler('cancelar', cancel_conversation)]
    )
    application.add_handler(set_price_conv)

    # Añadir Comandos
    application.add_handler(CommandHandler("start", start, filters=user_filter))
    application.add_handler(CommandHandler("lista", list_products, filters=user_filter))
    application.add_handler(CommandHandler("agregar", add_product, filters=user_filter))
    application.add_handler(CommandHandler("actualizar", update_all_products, filters=user_filter))

    # Manejador de Botones
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^(del_|cancel_delete|update_)'))

    print("El bot está escuchando comandos...")
    application.run_polling()


if __name__ == "__main__":
    # --- ¡NUEVO BUCLE DE RESILIENCIA! ---
    while True:
        try:
            main()
        except NetworkError as e:
            print(f"[Bot_Manager] Error de red: {e}. Reiniciando en 60 segundos...")
            time.sleep(60)
        except Exception as e:
            print(f"[Bot_Manager] Error fatal: {e}. Reiniciando en 5 minutos...")
            time.sleep(300)