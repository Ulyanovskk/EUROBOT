import os
import subprocess
import asyncio
import sys
import io
import MetaTrader5 as mt5
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Fix for Windows UnicodeEncodeError when printing emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from PY_FILES.func import SYMBOL

# ==========================================
# CONFIGURATION
# ==========================================
# Remplacez par vos vraies infos
TELEGRAM_TOKEN = "8725970972:AAHKf4iYfAnVGio0Sy2LUjQ_HA1hOI2K_g4"
ADMIN_CHAT_ID = 8458843915  # Remplacez par votre Chat ID (utilisez @userinfobot sur Telegram)

# Dictionnaire pour suivre le processus en cours
current_process = None
current_task_name = ""
last_status_msg = "Aucun log pour le moment."
log_buffer = []  # Buffer pour stocker les derniers logs

def add_to_log(text):
    global log_buffer
    log_buffer.append(text)
    if len(log_buffer) > 15: # Garder les 15 dernières lignes
        log_buffer.pop(0)

async def run_process_task(command, task_name, context: ContextTypes.DEFAULT_TYPE):
    """Exécute un processus en arrière-plan et capture la sortie pour le suivi"""
    global current_process, current_task_name, last_status_msg, log_buffer
    
    log_buffer = [f"--- Démarrage de {task_name} ---"]
    try:
        process = await asyncio.create_subprocess_exec(
            "python", *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        current_process = process
        current_task_name = task_name
        last_status_msg = "Démarrage..."

        while True:
            line = await process.stdout.readline()
            if not line: break
            
            text = line.decode('utf-8', errors='replace').strip()
            if text:
                last_status_msg = text
                add_to_log(text)
                print(f"[{task_name}] {text}")

        return_code = await process.wait()
        
        if current_process is not None:
            status_emoji = "✅" if return_code == 0 else "⚠️"
            msg = f"{status_emoji} Tâche '{task_name}' terminée."
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
            add_to_log(f"--- Fin de {task_name} (Code: {return_code}) ---")
            
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Erreur Task: {str(e)}")
    finally:
        current_process = None
        current_task_name = ""
        last_status_msg = "Prêt."

async def get_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /log pour voir les derniers messages"""
    if update.effective_user.id != ADMIN_CHAT_ID: return
    
    if not log_buffer:
        await update.message.reply_text("📋 Aucun log en mémoire.")
        return
        
    log_text = "\n".join(log_buffer)
    await update.message.reply_text(f"📋 **DERNIERS LOGS :**\n\n```\n{log_text}\n```", parse_mode='Markdown')

async def get_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les positions ouvertes"""
    if not mt5.initialize():
        await update.message.reply_text("❌ Erreur MT5")
        return
    
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        await update.message.reply_text(f"ℹ️ Aucune position ouverte sur {SYMBOL}.")
    else:
        msg = "🎯 **POSITIONS ACTIVES :**\n\n"
        for p in positions:
            p_type = "🟢 BUY" if p.type == mt5.ORDER_TYPE_BUY else "🔴 SELL"
            msg += (f"{p_type} | Lot: `{p.volume}`\n"
                    f"Prix : `{p.price_open}` → `{p.price_current}`\n"
                    f"Profit : `{round(p.profit, 2)} €`\n"
                    f"SL: `{p.sl}` | TP: `{p.tp}`\n"
                    f"───────────────\n")
        await update.message.reply_text(msg, parse_mode='Markdown')
    mt5.shutdown()

async def get_risk_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vérifie l'exposition au risque et le circuit breaker"""
    if not mt5.initialize(): return
    
    account = mt5.account_info()
    # On récupère l'historique depuis minuit
    from datetime import datetime, time
    today_start = datetime.combine(datetime.now().date(), time.min)
    
    history_deals = mt5.history_deals_get(today_start, datetime.now())
    # Approximation du balance de début de journée
    initial_balance = account.balance
    if history_deals:
        daily_profit = sum(d.profit + d.commission + d.swap for d in history_deals)
        initial_balance = account.balance - daily_profit

    drawdown_pct = ((initial_balance - account.equity) / initial_balance) * 100
    
    status = "✅ OK" if drawdown_pct < 10 else "⚠️ PRUDENCE" if drawdown_pct < 20 else "🛑 STOPPED"
    
    msg = (f"🛡️ **GESTION DU RISQUE :**\n\n"
           f"Statut : {status}\n"
           f"Capital initial jour : `{round(initial_balance, 2)} €`\n"
           f"Équité actuelle : `{round(account.equity, 2)} €`\n"
           f"Drawdown jour : `{round(drawdown_pct, 2)} %` / 20%\n\n"
           f"🎯 Marge libre : `{round(account.margin_free, 2)} €`")
    
    await update.message.reply_text(msg, parse_mode='Markdown')
    mt5.shutdown()

async def get_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rapport de performance de la journée"""
    if not mt5.initialize(): return
    
    from datetime import datetime, time
    today_start = datetime.combine(datetime.now().date(), time.min)
    deals = mt5.history_deals_get(today_start, datetime.now())
    
    if not deals:
        await update.message.reply_text("📋 Aucun trade clôturé aujourd'hui.")
    else:
        wins = [d for d in deals if d.profit > 0 and d.entry == mt5.DEAL_ENTRY_OUT]
        losses = [d for d in deals if d.profit <= 0 and d.entry == mt5.DEAL_ENTRY_OUT]
        total_p = sum(d.profit + d.commission + d.swap for d in deals if d.entry == mt5.DEAL_ENTRY_OUT)
        
        msg = (f"📊 **RAPPORT JOURNALIER :**\n\n"
               f"Trades clos : `{len(wins) + len(losses)}`\n"
               f"Gagnés : `{len(wins)}` | Perdus : `{len(losses)}` \n"
               f"Profit/Perte Net : `{round(total_p, 2)} €` \n\n"
               f"💰 Solde : `{mt5.account_info().balance} €`")
        await update.message.reply_text(msg, parse_mode='Markdown')
    mt5.shutdown()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principal avec boutons"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("🚫 Accès refusé.")
        return

    status_icon = "🟢" if current_process else "⚪"
    status_text = f"{status_icon} En cours : {current_task_name}" if current_process else "⚪ Prêt"
    
    keyboard = [
        [InlineKeyboardButton("🚀 Lancer Trading Live", callback_data='live')],
        [InlineKeyboardButton("🧠 Entraîner / 📊 Backtest", callback_data='menu_train')],
        [InlineKeyboardButton("🔍 Avancement & 📋 Logs", callback_data='menu_logs')],
        [InlineKeyboardButton("💰 Compte & 📊 Report", callback_data='menu_account')],
        [InlineKeyboardButton("🛑 STOP TOUT", callback_data='stop')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f'🤖 EUROBOT - Tour de Contrôle\nStatut : {status_text}\n\nActions disponibles :', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les clics sur les boutons et les sous-menus"""
    global current_process, current_task_name, last_status_msg
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID: return
    action = query.data

    # --- SOUS-MENUS ---
    if action == 'menu_train':
        keyboard = [
            [InlineKeyboardButton("🧠 Entraîner les Modèles", callback_data='train')],
            [InlineKeyboardButton("📊 Lancer Backtest 90j", callback_data='backtest')],
            [InlineKeyboardButton("⬅️ Retour", callback_data='main_menu')]
        ]
        await query.edit_message_text("🛠️ **MODÈLES & ANALYSE**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if action == 'menu_logs':
        keyboard = [
            [InlineKeyboardButton("🔍 Voir l'avancement", callback_data='progress')],
            [InlineKeyboardButton("📋 Derniers Logs", callback_data='show_logs')],
            [InlineKeyboardButton("⬅️ Retour", callback_data='main_menu')]
        ]
        await query.edit_message_text("📝 **SUIVI GÉNÉRAL**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if action == 'menu_account':
        keyboard = [
            [InlineKeyboardButton("💰 Mon Solde", callback_data='status')],
            [InlineKeyboardButton("🎯 Mes Positions", callback_data='positions')],
            [InlineKeyboardButton("🛡️ État du Risque", callback_data='risk')],
            [InlineKeyboardButton("📊 Rapport Journalier", callback_data='report')],
            [InlineKeyboardButton("⬅️ Retour", callback_data='main_menu')]
        ]
        await query.edit_message_text("💰 **COMPTE & PERFORMANCE**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if action == 'main_menu':
        await start(query, context) # On réutilise start
        return

    # --- ACTIONS DIRECTES ---
    if action == 'stop':
        if current_process:
            task_name = current_task_name
            try:
                current_process.terminate()
                # Sur Windows, terminate() est parfois ignoré par les sous-processus Python
                # On attend une seconde et on kill si c'est toujours là
                await asyncio.sleep(0.5)
                if current_process:
                    current_process.kill()
            except:
                pass
            
            current_process = None
            current_task_name = ""
            last_status_msg = "Arrêté par l'utilisateur."
            add_to_log("🛑 ARRÊT GLOBAL DÉTECTÉ")
            
            # On s'assure que MT5 est coupé si le bot était en live
            try: mt5.shutdown()
            except: pass
            
            await query.edit_message_text(f"🛑 Processus '{task_name}' arrêté. Le bot est à nouveau disponible.")
        else:
            await query.edit_message_text("ℹ️ Aucun processus n'est en cours.")
        return

    if action == 'progress':
        if current_process:
            await query.message.reply_text(f"📊 **AVANCEMENT : {current_task_name}**\n\n🕒 Dernier log :\n`{last_status_msg}`", parse_mode='Markdown')
        else:
            await query.message.reply_text("⚪ Aucun processus actif.")
        return

    if action == 'show_logs':
        if not log_buffer:
            await query.message.reply_text("📋 Aucun log en mémoire.")
        else:
            log_text = "\n".join(log_buffer)
            await query.message.reply_text(f"📋 **DERNIERS LOGS :**\n\n```\n{log_text}\n```", parse_mode='Markdown')
        return

    if action == 'positions':
        await get_positions(query, context)
        return
        
    if action == 'risk':
        await get_risk_status(query, context)
        return
        
    if action == 'report':
        await get_daily_report(query, context)
        return

    # --- LANCEMENT DE PROCESSUS ---
    if current_process and action in ['live', 'train', 'backtest']:
        await query.edit_message_text(f"⚠️ Un processus ('{current_task_name}') est déjà en cours.")
        return

    if action == 'live':
        await query.edit_message_text("🚀 Lancement du TRADING LIVE...")
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PRED_NXT.py"], "Trading Live", context))
        
    elif action == 'train':
        await query.edit_message_text("🧠 Lancement de l'ENTRAÎNEMENT...")
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PROCESS.py"], "Entraînement Modèles", context))

    elif action == 'backtest':
        await query.edit_message_text("📊 Préparation du Backtest...")
        async def run_backtest_flow():
            global current_process, current_task_name, last_status_msg
            try:
                current_task_name = "Backtest (Data)"
                last_status_msg = "Récupération data..."
                p1 = await asyncio.create_subprocess_exec("python", "PY_FILES/Get_Backtest_Data.py")
                current_process = p1
                await p1.wait()
                
                if p1.returncode != 0:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="❌ Échec Data.")
                    return

                current_task_name = "Backtest (Run)"
                last_status_msg = "Analyse des stratégies..."
                p2 = await asyncio.create_subprocess_exec("python", "PY_FILES/ALL_BACKTEST.py", stdout=asyncio.subprocess.PIPE)
                current_process = p2
                while True:
                    line = await p2.stdout.readline()
                    if not line: break
                    text = line.decode('utf-8', errors='replace').strip()
                    if text: last_status_msg = text

                return_code = await p2.wait()
                if return_code == 0:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Backtest terminé avec succès.")
                else:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Le backtest a échoué (Code: {return_code}). Vérifiez les logs.")
            except Exception as e:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Erreur: {str(e)}")
            finally:
                current_process = None
                current_task_name = ""
                last_status_msg = "Prêt."
        asyncio.create_task(run_backtest_flow())

    elif action == 'status':
        if not mt5.initialize():
            await query.edit_message_text("❌ Erreur MT5.")
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
    application.add_handler(CommandHandler("log", get_logs))
    application.add_handler(CommandHandler("positions", get_positions))
    application.add_handler(CommandHandler("risk", get_risk_status))
    application.add_handler(CommandHandler("report", get_daily_report))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
