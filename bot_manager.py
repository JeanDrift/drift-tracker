import sqlite3
import os
import asyncio
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, filters,
    CallbackQueryHandler, ConversationHandler, MessageHandler
)
import scraper_engine
import database
import log_setup

log = log_setup.setup_logging('bot_manager')
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

(STATE_SET_TARGET) = range(1)


def detect_store(url):
    dom = urlparse(url).netloc.lower()
    if 'mercadolibre' in dom: return 'MercadoLibre'
    if 'lacuracao' in dom: return 'LaCuracao'
    if 'lg.com' in dom: return 'LG'
    if 'memorykings' in dom: return 'MemoryKings'
    return None


async def send_product_card(update_or_query, pid):
    """
    Función maestra para enviar la tarjeta de un producto con sus botones.
    Funciona tanto con mensajes nuevos como con callbacks de botones.
    """
    try:
        with database.db_pool.get_conn() as conn:
            cursor = conn.cursor()
            query = """
            SELECT P.id, P.nombre, P.precio_objetivo, P.status, P.precio_mas_bajo, P.url, P.tienda,
            (SELECT H.precio FROM HistorialPrecios H WHERE H.producto_id = P.id ORDER BY H.fecha DESC LIMIT 1) as ultimo_precio
            FROM Productos P WHERE P.id = ?
            """
            cursor.execute(query, (pid,))
            prod = cursor.fetchone()

        if not prod:
            return

        pid, nombre, objetivo, status, p_min, url, tienda, ultimo = prod

        sym = scraper_engine.get_currency_symbol(tienda)
        nombre_str = nombre if nombre else "(Sin nombre detectado)"
        nombre_str = nombre_str.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[')
        obj_str = f"{sym} {objetivo}" if objetivo else "Sin meta"
        ult_str = f"{sym} {ultimo}" if ultimo else "N/A"
        min_str = f"{sym} {p_min}" if p_min else "N/A"
        icon = "🟢" if status == "disponible" else "🔴" if status == "no disponible" else "⚪"

        msg = (f"📦 *{nombre_str}*\n"
               f"🏬 {tienda} | {icon} {status.capitalize()}\n"
               f"💰 Actual: *{ult_str}*\n"
               f"📉 Mínimo: {min_str}\n"
               f"🎯 Meta: {obj_str}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Ver Producto", url=url)],
            [InlineKeyboardButton("🎯 Meta", callback_data=f"set_{pid}"),
             InlineKeyboardButton("🗑️ Borrar", callback_data=f"del_{pid}")],
            [InlineKeyboardButton("🔄 Actualizar ahora", callback_data=f"update_{pid}")]
        ])

        # Detectar si viene de un comando o de un botón
        if hasattr(update_or_query, 'message') and update_or_query.message:
            await update_or_query.message.reply_text(msg, reply_markup=keyboard, parse_mode='Markdown')
        else:
            await update_or_query.edit_message_text(msg, reply_markup=keyboard, parse_mode='Markdown')

    except Exception as e:
        log.error(f"Error enviando tarjeta ID {pid}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Tracker de Precios Activo\n/lista - Ver productos\n/agregar <URL> - Nuevo item\n/actualizar - Todo el stock")


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with database.db_pool.get_conn() as conn:
            cursor = conn.cursor()
            # SELECCIONAMOS 8 COLUMNAS EXACTAS
            query = """
            SELECT P.id, P.nombre, P.precio_objetivo, P.status, P.precio_mas_bajo, P.url, P.tienda,
            (SELECT H.precio FROM HistorialPrecios H WHERE H.producto_id = P.id ORDER BY H.fecha DESC LIMIT 1) as ultimo_precio
            FROM Productos P
            """
            cursor.execute(query)
            productos = cursor.fetchall()

        if not productos:
            await update.message.reply_text("Vacío. Usa /agregar <URL>")
            return

        for prod in productos:
            pid, nombre, objetivo, status, p_min, url, tienda, ultimo = prod

            sym = scraper_engine.get_currency_symbol(tienda)
            nombre_str = nombre if nombre else "(Cargando...)"
            nombre_str = nombre_str.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[')
            obj_str = f"{sym} {objetivo}" if objetivo else "Sin meta"
            ult_str = f"{sym} {ultimo}" if ultimo else "N/A"
            min_str = f"{sym} {p_min}" if p_min else "N/A"
            icon = "🟢" if status == "disponible" else "🔴" if status == "no disponible" else "⚪"

            msg = (f"📦 *{nombre_str}*\n"
                   f"🏬 {tienda} | {icon} {status.capitalize()}\n"
                   f"💰 Actual: *{ult_str}*\n"
                   f"📉 Mínimo: {min_str}\n"
                   f"🎯 Meta: {obj_str}")

            keyboard = InlineKeyboardMarkup([
                [
                    # Este botón abre el navegador directamente en el celular
                    InlineKeyboardButton("🌐 Ver Producto", url=url)
                ],
                [
                    InlineKeyboardButton("🎯 Meta", callback_data=f"set_{pid}"),
                    InlineKeyboardButton("🗑️ Borrar", callback_data=f"del_{pid}")
                ],
                [
                    InlineKeyboardButton("🔄 Actualizar ahora", callback_data=f"update_{pid}")
                ]
            ])
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        log.error(f"Error en /lista: {e}")
        await update.message.reply_text("Error al cargar la lista.")


async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /agregar <URL>");
        return
    url = context.args[0]
    tienda = detect_store(url)
    if not tienda:
        await update.message.reply_text("Tienda no soportada.");
        return

    try:
        with database.db_pool.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Productos (url, tienda, status) VALUES (?, ?, 'ninguno')", (url, tienda))
            conn.commit()
            pid = cursor.lastrowid

        await update.message.reply_text(f"✅ Agregado (ID {pid}). Extrayendo datos...")

        # Realizamos el tracking
        await asyncio.to_thread(scraper_engine.track_single_product, pid)

        # ¡ESTO ES LO NUEVO! Enviamos la tarjeta con los resultados
        await send_product_card(update, pid)

    except sqlite3.IntegrityError:
        await update.message.reply_text("Esa URL ya está en el sistema.")


async def update_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = scraper_engine.get_product_count()
    await update.message.reply_text(f"🔄 Actualizando {count} productos. Te avisaré al terminar.")
    await scraper_engine.track_all_products()
    await update.message.reply_text("✅ ¡Actualización masiva completada!")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, pid = query.data.split('_', 1)

    if action == "update":
        # Cambiamos el texto temporalmente para dar feedback
        await query.edit_message_text(f"⏳ Actualizando ID {pid}...")

        # Hacemos el tracking
        await asyncio.to_thread(scraper_engine.track_single_product, pid)

        # ¡REFRESCAMOS LA TARJETA!
        await send_product_card(query, pid)
    elif action == "del":
        with database.db_pool.get_conn() as conn:
            conn.execute("DELETE FROM Productos WHERE id = ?", (pid,))
            conn.commit()
        await query.edit_message_text("🗑️ Producto eliminado.")
    elif action == "set":
        context.user_data['pid'] = pid
        await query.message.reply_text(f"Ingresa el precio objetivo para ID {pid}:")
        return STATE_SET_TARGET


async def save_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text)
        pid = context.user_data['pid']
        with database.db_pool.get_conn() as conn:
            conn.execute("UPDATE Productos SET precio_objetivo = ?, notificacion_objetivo_enviada = 0 WHERE id = ?",
                         (val, pid))
            conn.commit()
        await update.message.reply_text(f"🎯 Meta fijada en {val}")
    except:
        await update.message.reply_text("Número inválido.")
    return ConversationHandler.END


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    user_filter = filters.User(user_id=int(CHAT_ID))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^set_')],
        states={STATE_SET_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_target)]},
        fallbacks=[]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start, filters=user_filter))
    app.add_handler(CommandHandler("lista", list_products, filters=user_filter))
    app.add_handler(CommandHandler("agregar", add_product, filters=user_filter))
    app.add_handler(CommandHandler("actualizar", update_all, filters=user_filter))
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^(update_|del_)'))

    log.info("Bot en marcha...")
    app.run_polling()


if __name__ == "__main__":
    main()