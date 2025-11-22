# main.py
import asyncio
import random
import os
import logging
import urllib.request
import urllib.error
import json
import signal
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- Config logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

# Token desde variables de entorno (Railway: Environment)
TOKEN = os.getenv("BOT_TOKEN")
if TOKEN:
    log.info("BOT_TOKEN detectado (no muestro el valor por seguridad).")
else:
    log.error("❌ ERROR: No se encontró la variable de entorno BOT_TOKEN. Añádela e intenta de nuevo.")
    # salir para que el proceso falle rápido en el deploy en caso de token faltante
    sys.exit(1)

# Intentamos eliminar cualquier webhook previo en Telegram para evitar conflictos
def clear_telegram_webhook(token: str):
    url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            try:
                data = json.loads(body)
                if data.get("ok"):
                    log.info("Webhook eliminado en Telegram (o no existía).")
                else:
                    log.warning("Respuesta deleteWebhook de Telegram: %s", data)
            except Exception:
                log.info("Respuesta inesperada de deleteWebhook: %s", body)
    except urllib.error.HTTPError as e:
        log.warning("HTTPError al borrar webhook: %s", e)
    except Exception as e:
        log.warning("No se pudo contactar Telegram para borrar webhook: %s", e)

# Estado en memoria de los sorteos
sorteos = {}

# ---------------- handlers (mantengo tu lógica, con ligeros ajustes) ----------------
async def start_sorteo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    try:
        member = await chat.get_member(user.id)
    except Exception:
        await update.message.reply_text("No he podido comprobar permisos, inténtalo de nuevo.")
        return

    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("🚫 Solo los administradores pueden iniciar un sorteo.")
        return

    if len(context.args) < 3:
        await update.message.reply_text("Uso: /sorteo <premio> <ganadores> <tiempo>\nEj: /sorteo 100_Robux 1 10m")
        return

    premio = context.args[0].replace("_", " ")
    try:
        ganadores_num = int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ El número de ganadores debe ser un número entero (ej: 1, 2).")
        return

    tiempo = context.args[2]
    if tiempo.endswith("m"):
        duracion = int(tiempo[:-1]) * 60
    elif tiempo.endswith("h"):
        duracion = int(tiempo[:-1]) * 3600
    else:
        await update.message.reply_text("⚠️ El tiempo debe terminar en 'm' o 'h'. Ej: 10m o 1h")
        return

    teclado = InlineKeyboardMarkup([[InlineKeyboardButton("🎟 Unirse", callback_data="join")]])
    mensaje = await update.message.reply_text(
        f"⪩⪨ ¡ nuevo sorteo iniciado!\n\n"
        f"  ꭷ hecho por: @{user.username if user.username else user.first_name}\n"
        f"  ꭷ premio: {premio}\n"
        f"  ꭷ ganadores: {ganadores_num}\n"
        f"  ꭷ duración: {tiempo}\n\n"
        f"pulsa el botón para unirte!",
        parse_mode="HTML",
        reply_markup=teclado
    )

    sorteos[mensaje.message_id] = {
        "chat_id": chat.id,
        "premio": premio,
        "ganadores": ganadores_num,
        "participantes": [],
        "activo": True,
        "creador": user
    }

    # Lanzamos la tarea de finalizar sin bloquear (en memoria)
    asyncio.create_task(finalizar_sorteo(context, mensaje.message_id, duracion))


async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    msg_id = query.message.message_id

    if msg_id not in sorteos or not sorteos[msg_id]["activo"]:
        await query.answer("Este sorteo ya ha finalizado o no existe.", show_alert=True)
        return

    participantes = sorteos[msg_id]["participantes"]
    if any(p.id == user.id for p in participantes):
        await query.answer("Ya estás participando.", show_alert=False)
        return

    participantes.append(user)
    await query.answer("¡Te has unido al sorteo! 🎉", show_alert=False)

    chat_id = sorteos[msg_id]["chat_id"]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"@{user.username if user.username else user.first_name}, ¡gracias por unirte al sorteo, suerte! 🍀",
        reply_to_message_id=msg_id
    )


async def finalizar_sorteo(context: ContextTypes.DEFAULT_TYPE, message_id: int, duracion: int):
    await asyncio.sleep(duracion)
    if message_id in sorteos and sorteos[message_id]["activo"]:
        await anunciar_ganadores(context, message_id)


async def anunciar_ganadores(context: ContextTypes.DEFAULT_TYPE, message_id: int):
    sorteo = sorteos.get(message_id)
    if not sorteo:
        return

    sorteo["activo"] = False
    participantes = sorteo["participantes"]
    chat_id = sorteo["chat_id"]
    sorteo_msg_id = message_id
    premio = sorteo["premio"]
    ganadores_num = sorteo["ganadores"]
    creador = sorteo["creador"]

    if not participantes:
        await context.bot.send_message(
            chat_id=chat_id,
            reply_to_message_id=sorteo_msg_id,
            text=f"😔 El sorteo de <b>{premio}</b> terminó sin participantes.",
            parse_mode="HTML"
        )
        return

    ganadores = random.sample(participantes, min(ganadores_num, len(participantes)))
    ganadores_texto = "\n".join(
        [f"@{u.username}" if u.username else f"<a href='tg://user?id={u.id}'>{u.first_name}</a>" for u in ganadores]
    )

    await context.bot.send_message(
        chat_id=chat_id,
        reply_to_message_id=sorteo_msg_id,
        text=(
            f"丙 ¡sorteo finalizado!\n\n"
            f"  ꭷ premio: {premio}\n"
            f"  ꭷ ganador/es:\n{ganadores_texto}\n\n"
            f"¡felicidades! puedes reclamar tu premio por dm al creador del sorteo: "
            f"@{creador.username if creador.username else creador.first_name} 🎁"
        ),
        parse_mode="HTML",
    )


async def end_sorteo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    try:
        member = await chat.get_member(user.id)
    except Exception:
        await update.message.reply_text("No he podido comprobar permisos.")
        return

    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("🚫 Solo los administradores pueden usar /endsorteo.")
        return

    if not sorteos:
        await update.message.reply_text("⚠️ No hay sorteos activos.")
        return

    ultimo_msg_id = list(sorteos.keys())[-1]
    if sorteos[ultimo_msg_id]["activo"]:
        sorteos[ultimo_msg_id]["activo"] = False
        await update.message.reply_text("🛑 Sorteo finalizado manualmente.")
        await anunciar_ganadores(context, ultimo_msg_id)
    else:
        await update.message.reply_text("⚠️ Ese sorteo ya ha terminado.")

# ---------------- main ----------------
def main():
    # Limpiamos webhook viejo para evitar conflictos con polling
    log.info("Intentando borrar webhook previo (si existiera)...")
    clear_telegram_webhook(TOKEN)

    # Construimos la app
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("sorteo", start_sorteo))
    app.add_handler(CallbackQueryHandler(join_callback, pattern="^join$"))
    app.add_handler(CommandHandler("endsorteo", end_sorteo))

    # Señales para shutdown limpio
    def _sigterm_handler(signum, frame):
        log.info("Recibida señal de terminación (%s). Deteniendo app...", signum)
        # stop application gracefully
        try:
            # Application.run_polling() maneja KeyboardInterrupt, asi que usamos sys.exit
            sys.exit(0)
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _sigterm_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)

    log.info("✅ Bot de sorteos en marcha (usando polling).")
    try:
        app.run_polling()
    except Exception as e:
        log.exception("Excepción al ejecutar run_polling(): %s", e)
    finally:
        log.info("Proceso finalizado.")

if __name__ == "__main__":
    main()
