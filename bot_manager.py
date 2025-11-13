import sqlite3
import os
from urllib.parse import urlparse  # <-- NUEVA IMPORTACIÓN
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, filters,
    CallbackQueryHandler, ConversationHandler, MessageHandler
)

# --- Cargar variables de entorno ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DB_NAME = "precios.db"

# --- Estados para la conversación ---
(STATE_SET_TARGET) = range(1)


# ==========================================================
# --- Lógica de Tienda (Duplicada de add_product.py) ---
# ==========================================================
def detect_store(url):
    """Analiza la URL para detectar el nombre de la tienda."""
    domain = urlparse(url).netloc.lower()

    if 'mercadolibre' in domain:
        return 'MercadoLibre'
    if 'lacuracao' in domain:
        return 'LaCuracao'
    if 'falabella' in domain:
        return 'Falabella'
    if 'ripley' in domain:
        return 'Ripley'

    return None  # Si no la conocemos


# ==========================================================
# --- Comandos del Bot ---
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía un mensaje de bienvenida."""
    await update.message.reply_text(
        "¡Hola! Soy tu bot de seguimiento de precios.\n"
        "Usa /lista para ver y gestionar tus productos.\n"
        "Usa /agregar <URL> para agregar un nuevo producto." # <-- CAMBIO AQUÍ
    )


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene la lista de productos y la envía con botones."""
    print("Comando /lista recibido.")
    conn = sqlite3.connect(DB_NAME)
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
        await update.message.reply_text("No hay productos en la base de datos. Usa /añadir <URL> para empezar.")
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
            ]
        ])

        await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')


# --- ¡NUEVO COMANDO! ---
async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Añade un nuevo producto a la BD desde una URL."""
    print(f"Comando /añadir recibido con args: {context.args}")

    # 1. Validar que se pasó una URL
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Error: Formato incorrecto.\n"
            "Usa /añadir <URL_COMPLETA_DEL_PRODUCTO>"
        )
        return

    url = context.args[0].strip()

    # 2. Detectar la tienda
    tienda = detect_store(url)
    if not tienda:
        await update.message.reply_text(
            "Error: Tienda no reconocida o URL no válida.\n"
            "Por ahora solo se soporta: MercadoLibre, LaCuracao, Falabella, Ripley."
        )
        return

    # 3. Insertar en la Base de Datos
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Insertamos con todos los valores por defecto
        cursor.execute(
            """
            INSERT INTO Productos (url, tienda, status, notificacion_objetivo_enviada)
            VALUES (?, ?, 'ninguno', 0)
            """, (url, tienda)
        )
        conn.commit()
        product_id = cursor.lastrowid
        await update.message.reply_text(
            f"¡Éxito! ✅\n"
            f"Producto añadido (ID: {product_id}) de la tienda: {tienda}.\n"
            "Se rastreará en el próximo ciclo."
        )

    except sqlite3.IntegrityError:
        # Esto salta si la URL ya existe (por la regla 'UNIQUE')
        await update.message.reply_text("Error: Esta URL ya está siendo rastreada.")
    except Exception as e:
        print(f"Error en /añadir: {e}")
        await update.message.reply_text(f"Ocurrió un error inesperado: {e}")
    finally:
        conn.close()


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las pulsaciones de los botones (Callbacks)."""
    query = update.callback_query
    await query.answer()  # Responder al clic

    data = query.data

    if data == "cancel_delete":
        await query.edit_message_text("Eliminación cancelada.")
        return

    action, product_id = data.split('_')

    if action == "del":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("SÍ, Eliminar", callback_data=f"del_confirm_{product_id}"),
                InlineKeyboardButton("Cancelar", callback_data="cancel_delete")
            ]
        ])
        await query.edit_message_text(f"¿Seguro que quieres eliminar el producto ID {product_id}?",
                                      reply_markup=keyboard)

    elif action == "del_confirm":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Productos WHERE id = ?", (product_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"Producto ID {product_id} eliminado exitosamente.")

    elif action == "set":
        context.user_data['product_id_to_set'] = product_id
        await query.message.reply_text(f"Por favor, ingresa el nuevo precio objetivo para el producto ID {product_id}:")
        return STATE_SET_TARGET


async def receive_target_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe el precio del usuario (segundo paso de la conversación)."""
    try:
        new_price = float(update.message.text)
        product_id = context.user_data['product_id_to_set']

        conn = sqlite3.connect(DB_NAME)
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
    """Comando para cancelar la conversación de fijar precio."""
    context.user_data.clear()
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END


# ==========================================================
# --- Función Principal del Bot ---
# ==========================================================

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Error: TELEGRAM_TOKEN o CHAT_ID no están en el archivo .env")
        return

    print("Iniciando el bot...")
    user_filter = filters.User(user_id=int(CHAT_ID))

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # --- Configurar la Conversación para fijar precios ---
    set_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^set_')],
        states={
            STATE_SET_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target_price)]
        },
        fallbacks=[CommandHandler('cancelar', cancel_conversation)]
    )

    application.add_handler(set_price_conv)

    # --- Añadir otros manejadores ---
    application.add_handler(CommandHandler("start", start, filters=user_filter))
    application.add_handler(CommandHandler("lista", list_products, filters=user_filter))

    # --- ¡CAMBIO AQUÍ! ---
    # Cambiamos "añadir" por "agregar"
    application.add_handler(CommandHandler("agregar", add_product, filters=user_filter))

    # Manejador para los botones de "eliminar" y "cancelar"
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^del_'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^cancel_delete'))

    print("El bot está escuchando comandos...")
    application.run_polling()


if __name__ == "__main__":
    main()