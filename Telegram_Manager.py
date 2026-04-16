import os
import subprocess
import asyncio
import MetaTrader5 as mt5
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==========================================
# CONFIGURATION
# ==========================================
# Remplacez par vos vraies infos
TELEGRAM_TOKEN = "VOTRE_BOT_TOKEN_ICI"
ADMIN_CHAT_ID = 000000000  # Remplacez par votre Chat ID (utilisez @userinfobot sur Telegram)

# Dictionnaire pour suivre le processus en cours
current_process = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principal avec boutons"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("🚫 Accès refusé.")
        return

    keyboard = [
        [InlineKeyboardButton("🚀 Lancer Trading Live", callback_data='live')],
        [InlineKeyboardButton("🧠 Entraîner les Modèles", callback_data='train')],
        [InlineKeyboardButton("📊 Lancer Backtest 90j", callback_data='backtest')],
        [InlineKeyboardButton("💰 Infos Compte", callback_data='status')],
        [InlineKeyboardButton("🛑 TOUT ARRÊTER", callback_data='stop')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('🤖 EUROBOT - Tour de Contrôle\nChoisissez une action :', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les clics sur les boutons"""
    global current_process
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID:
        return

    action = query.data

    if action == 'stop':
        if current_process:
            current_process.terminate()
            current_process = None
            await query.edit_message_text("🛑 Tous les processus ont été arrêtés.")
        else:
            await query.edit_message_text("ℹ️ Aucun processus n'est en cours.")
        return

    if current_process:
        await query.edit_message_text(f"⚠️ Un processus est déjà en cours. Arrêtez-le avant d'en lancer un autre.")
        return

    if action == 'live':
        await query.edit_message_text("🚀 Lancement du TRADING LIVE...")
        current_process = subprocess.Popen(["python", "PY_FILES/ALL_PRED_NXT.py"])
        
    elif action == 'train':
        await query.edit_message_text("🧠 Lancement de l'ENTRAÎNEMENT... (Cela peut être long)")
        current_process = subprocess.Popen(["python", "PY_FILES/ALL_PROCESS.py"])

    elif action == 'backtest':
        await query.edit_message_text("📊 Récupération des données et BACKTEST...")
        # On lance d'abord la récupération puis le backtest
        subprocess.run(["python", "PY_FILES/Get_Backtest_Data.py"])
        current_process = subprocess.Popen(["python", "PY_FILES/ALL_BACKTEST.py"])

    elif action == 'status':
        if not mt5.initialize():
            await query.edit_message_text("❌ Erreur de connexion à MT5.")
            return
        
        account = mt5.account_info()
        status_msg = (
            f"💰 --- ÉTAT DU COMPTE ---\n"
            f"Solde : {account.balance} {account.currency}\n"
            f"Équité : {account.equity} {account.currency}\n"
            f"Marge Libre : {account.margin_free} {account.currency}\n"
            f"Levier : 1:{account.leverage}"
        )
        mt5.shutdown()
        await query.edit_message_text(status_msg)

def main():
    """Lancement du bot Telegram"""
    print("🛰️ Telegram Manager en attente de commandes...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
