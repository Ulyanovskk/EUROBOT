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
TELEGRAM_TOKEN = "8725970972:AAHKf4iYfAnVGio0Sy2LUjQ_HA1hOI2K_g4"
ADMIN_CHAT_ID = 8458843915  # Remplacez par votre Chat ID (utilisez @userinfobot sur Telegram)

# Dictionnaire pour suivre le processus en cours
current_process = None
current_task_name = ""

async def run_process_task(command, task_name, context: ContextTypes.DEFAULT_TYPE):
    """Exécute un processus en arrière-plan et notifie à la fin"""
    global current_process, current_task_name
    
    try:
        # Lancement du processus
        # On utilise subprocess.Popen pour pouvoir le terminer facilement plus tard si besoin
        # Mais on va l'attendre de manière asynchrone
        process = subprocess.Popen(["python"] + command)
        current_process = process
        current_task_name = task_name
        
        # Attendre la fin du processus sans bloquer l'event loop
        while process.poll() is None:
            await asyncio.sleep(1)
            
        # Si on arrive ici, c'est que le processus est fini (ou a été terminé)
        if current_process is not None: # Si pas annulé manuellement
            return_code = process.returncode
            status_emoji = "✅" if return_code == 0 else "⚠️"
            msg = f"{status_emoji} Tâche '{task_name}' terminée.\nCode de retour : {return_code}"
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
            
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Erreur Task ({task_name}): {str(e)}")
    finally:
        current_process = None
        current_task_name = ""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principal avec boutons"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("🚫 Accès refusé.")
        return

    status = f"🟢 En cours : {current_task_name}" if current_process else "⚪ Prêt"
    
    keyboard = [
        [InlineKeyboardButton("🚀 Lancer Trading Live", callback_data='live')],
        [InlineKeyboardButton("🧠 Entraîner les Modèles", callback_data='train')],
        [InlineKeyboardButton("📊 Lancer Backtest 90j", callback_data='backtest')],
        [InlineKeyboardButton("💰 Infos Compte", callback_data='status')],
        [InlineKeyboardButton("🛑 TOUT ARRÊTER", callback_data='stop')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f'🤖 EUROBOT - Tour de Contrôle\n{status}\n\nChoisissez une action :', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les clics sur les boutons"""
    global current_process, current_task_name
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID:
        return

    action = query.data

    if action == 'stop':
        if current_process:
            task_name = current_task_name
            current_process.terminate()
            current_process = None
            current_task_name = ""
            await query.edit_message_text(f"🛑 Processus '{task_name}' arrêté manuellement.")
        else:
            await query.edit_message_text("ℹ️ Aucun processus n'est en cours.")
        return

    if current_process:
        await query.edit_message_text(f"⚠️ Un processus ('{current_task_name}') est déjà en cours. Arrêtez-le avant d'en lancer un autre.")
        return

    if action == 'live':
        await query.edit_message_text("🚀 Lancement du TRADING LIVE...")
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PRED_NXT.py"], "Trading Live", context))
        
    elif action == 'train':
        await query.edit_message_text("🧠 Lancement de l'ENTRAÎNEMENT... (Cela peut être long)")
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PROCESS.py"], "Entraînement Modèles", context))

    elif action == 'backtest':
        await query.edit_message_text("📊 Récupération des données et BACKTEST...")
        # On ne bloque pas pour Get_Backtest_Data non plus
        async def run_backtest_flow():
            global current_process, current_task_name
            try:
                current_task_name = "Backtest (Data)"
                # Étape 1 : Récupération data
                p1 = subprocess.Popen(["python", "PY_FILES/Get_Backtest_Data.py"])
                current_process = p1
                while p1.poll() is None: await asyncio.sleep(1)
                
                if p1.returncode != 0:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="❌ Échec de la récupération des données backtest.")
                    current_process = None
                    return

                # Étape 2 : Lancement backtest
                current_task_name = "Backtest (Run)"
                p2 = subprocess.Popen(["python", "PY_FILES/ALL_BACKTEST.py"])
                current_process = p2
                while p2.poll() is None: await asyncio.sleep(1)
                
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Backtest terminé (Code: {p2.returncode})")
            except Exception as e:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Erreur Backtest: {str(e)}")
            finally:
                current_process = None
                current_task_name = ""

        asyncio.create_task(run_backtest_flow())

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
