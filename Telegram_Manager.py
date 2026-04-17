import os
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
    
    log_buffer = [f"--- Demarrage de {task_name} ---"]
    try:
        # Utilisation de -u pour forcer l'affichage instantané (unbuffered)
        process = await asyncio.create_subprocess_exec(
            "python", "-u", *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        current_process = process
        current_task_name = task_name
        last_status_msg = "Demarrage..."

        from datetime import datetime
        while True:
            line = await process.stdout.readline()
            if not line: break
            
            text = line.decode('utf-8', errors='replace').strip()
            if text:
                timestamp = datetime.now().strftime("%H:%M:%S")
                last_status_msg = text
                add_to_log(text)
                # Affichage console enrichi
                print(f"[{timestamp}] [{task_name.upper()}] {text}")

        return_code = await process.wait()
        
        if current_process is not None:
            status_text = "SUCCESS" if return_code == 0 else "WARNING"
            msg = f"[{status_text}] Tâche '{task_name}' terminée."
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
            add_to_log(f"--- Fin de {task_name} (Code: {return_code}) ---")
            
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"[ERREUR] Task: {str(e)}")
    finally:
        current_process = None
        current_task_name = ""
        last_status_msg = "Pret."

async def get_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /log pour voir les derniers messages"""
    if update.effective_user.id != ADMIN_CHAT_ID: return
    
    if not log_buffer:
        await update.message.reply_text("Aucun log en mémoire.")
        return
        
    log_text = "\n".join(log_buffer)
    await update.message.reply_text(f"--- DERNIERS LOGS ---\n\n```\n{log_text}\n```", parse_mode='Markdown')

async def get_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les positions ouvertes"""
    if not mt5.initialize():
        await update.message.reply_text("❌ Erreur MT5")
        return
    
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        await update.message.reply_text(f"Information: Aucune position ouverte sur {SYMBOL}.")
    else:
        msg = "--- POSITIONS ACTIVES ---\n\n"
        for p in positions:
            p_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            msg += (f"{p_type} | Lot: `{p.volume}`\n"
                    f"Prix : `{p.price_open}` → `{p.price_current}`\n"
                    f"Profit : `{round(p.profit, 2)} EUR`\n"
                    f"SL: `{p.sl}` | TP: `{p.tp}`\n"
                    f"---------------\n")
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
    
    status = "OK" if drawdown_pct < 10 else "PRUDENCE" if drawdown_pct < 20 else "STOPPED"
    
    msg = (f"--- GESTION DU RISQUE ---\n\n"
           f"Statut : {status}\n"
           f"Capital initial jour : `{round(initial_balance, 2)} EUR`\n"
           f"Equite actuelle : `{round(account.equity, 2)} EUR`\n"
           f"Drawdown jour : `{round(drawdown_pct, 2)} %` / 20%\n\n"
           f"Marge libre : `{round(account.margin_free, 2)} EUR`")
    
    await update.message.reply_text(msg, parse_mode='Markdown')
    mt5.shutdown()

async def get_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rapport de performance de la journée"""
    if not mt5.initialize(): return
    
    from datetime import datetime, time
    today_start = datetime.combine(datetime.now().date(), time.min)
    deals = mt5.history_deals_get(today_start, datetime.now())
    
    if not deals:
        await update.message.reply_text("Rapport: Aucun trade cloture aujourd'hui.")
    else:
        wins = [d for d in deals if d.profit > 0 and d.entry == mt5.DEAL_ENTRY_OUT]
        losses = [d for d in deals if d.profit <= 0 and d.entry == mt5.DEAL_ENTRY_OUT]
        total_p = sum(d.profit + d.commission + d.swap for d in deals if d.entry == mt5.DEAL_ENTRY_OUT)
        
        msg = (f"--- RAPPORT JOURNALIER ---\n\n"
               f"Trades clos : `{len(wins) + len(losses)}`\n"
               f"Gagnes : `{len(wins)}` | Perdus : `{len(losses)}` \n"
               f"Profit/Perte Net : `{round(total_p, 2)} EUR` \n\n"
               f"Solde : `{mt5.account_info().balance} EUR`")
        await update.message.reply_text(msg, parse_mode='Markdown')
    mt5.shutdown()

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    """Affiche ou modifie le menu principal"""
    status_text_icon = "[RUNNING]" if current_process else "[WAITING]"
    status_text = f"{status_text_icon} En cours : {current_task_name}" if current_process else "[READY] Pret"
    
    keyboard = [
        [InlineKeyboardButton("Lancer Trading Live", callback_data='live')],
        [InlineKeyboardButton("Entrainer / Backtest", callback_data='menu_train')],
        [InlineKeyboardButton("Avancement & Logs", callback_data='menu_logs')],
        [InlineKeyboardButton("Compte & Report", callback_data='menu_account')],
        [InlineKeyboardButton("STOP TOUT", callback_data='stop')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f'*EUROBOT - Tour de Controle*\nStatut : `{status_text}`\n\nActions disponibles :'
    
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Acces refuse.")
        return
    await send_main_menu(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les clics sur les boutons et les sous-menus"""
    global current_process, current_task_name, last_status_msg
    query = update.callback_query
    
    if query.from_user.id != ADMIN_CHAT_ID: 
        await query.answer("Acces refuse.", show_alert=True)
        return

    await query.answer()
    action = query.data

    # --- SOUS-MENUS ---
    if action == 'menu_train':
        keyboard = [
            [InlineKeyboardButton("1. Recup Donnees MT5", callback_data='get_data')],
            [InlineKeyboardButton("2. Expert MATHEMATIQUE (Standard)", callback_data='train')],
            [InlineKeyboardButton("3. Expert EXPERIENCE (Elite)", callback_data='train_elite')],
            [InlineKeyboardButton("4. Expert VISION (Patterns)", callback_data='train_vision')],
            [InlineKeyboardButton("Retour", callback_data='main_menu')]
        ]
        await query.edit_message_text("*WORKFLOW ENTRAINEMENT*\n(Etape 1 puis au choix)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if action == 'menu_logs':
        keyboard = [
            [InlineKeyboardButton("Voir l'avancement", callback_data='progress')],
            [InlineKeyboardButton("Derniers Logs", callback_data='show_logs')],
            [InlineKeyboardButton("Lancer un Backtest", callback_data='backtest')],
            [InlineKeyboardButton("Retour", callback_data='main_menu')]
        ]
        await query.edit_message_text("*SUIVI & TESTS*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if action == 'menu_account':
        keyboard = [
            [InlineKeyboardButton("Mon Solde", callback_data='status')],
            [InlineKeyboardButton("Mes Positions", callback_data='positions')],
            [InlineKeyboardButton("Etat du Risque", callback_data='risk')],
            [InlineKeyboardButton("Rapport Journalier", callback_data='report')],
            [InlineKeyboardButton("Retour", callback_data='main_menu')]
        ]
        await query.edit_message_text("*COMPTE & PERFORMANCE*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if action == 'main_menu':
        await send_main_menu(update, context, edit=True)
        return

    # --- ACTIONS DIRECTES ---
    if action == 'stop':
        if current_process:
            task_name = current_task_name
            try:
                # Sur Windows on essaie de tuer proprement puis brutalement
                current_process.terminate()
                await asyncio.sleep(1)
                if current_process: current_process.kill()
            except: pass
            
            current_process = None
            current_task_name = ""
            last_status_msg = "Arrete."
            add_to_log("ARRET GLOBAL PAR L'UTILISATEUR")
            await query.edit_message_text(f"DONE: Processus `{task_name}` arrete.")
        else:
            await query.answer("Aucun processus en cours.")
        return

    if action == 'progress':
        msg = f"Tache active : `{current_task_name if current_task_name else 'Aucune'}`\n\nDernier Log :\n`{last_status_msg}`"
        await query.message.reply_text(msg, parse_mode='Markdown')
        return

    if action == 'show_logs':
        log_text = "\n".join(log_buffer) if log_buffer else "Aucun log."
        await query.message.reply_text(f"*DERNIERS LOGS*\n\n```\n{log_text}\n```", parse_mode='Markdown')
        return

    if action == 'positions':
        # On utilise une fonction séparée pour éviter de bloquer
        await get_positions(update, context)
        return
        
    if action == 'risk':
        await get_risk_status(update, context)
        return
        
    if action == 'report':
        await get_daily_report(update, context)
        return

    # --- LANCEMENT DE PROCESSUS ---
    if current_process and action in ['live', 'train', 'backtest', 'get_data']:
        await query.answer(f"Attention: Une tache ({current_task_name}) est deja en cours.", show_alert=True)
        return

    if action == 'live':
        await query.edit_message_text("Lancement du TRADING LIVE...", parse_mode='Markdown')
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PRED_NXT.py"], "Trading Live", context))
        
    elif action == 'train':
        await query.edit_message_text("Lancement de l'ENTRAINEMENT...", parse_mode='Markdown')
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PROCESS.py"], "Entrainement", context))

    elif action == 'get_data':
        await query.edit_message_text("Recuperation des donnees...", parse_mode='Markdown')
        asyncio.create_task(run_process_task(["PY_FILES/Get_Backtest_Data.py"], "Recup Data", context))

    elif action == 'train_elite':
        await query.edit_message_text("Lancement Expert EXPERIENCE (ELITE)...", parse_mode='Markdown')
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PROCESS_ELITE.py"], "Elite Train", context))

    elif action == 'train_vision':
        await query.edit_message_text("Lancement Expert VISION (Patterns)...", parse_mode='Markdown')
        asyncio.create_task(run_process_task(["PY_FILES/ALL_PROCESS_VISION.py"], "Vision Train", context))
        
    elif action == 'backtest':
        await query.edit_message_text("Lancement du BACKTEST...", parse_mode='Markdown')
        asyncio.create_task(run_process_task(["PY_FILES/ALL_BACKTEST.py"], "Backtest", context))

    elif action == 'status':
        if not mt5.initialize():
            await query.answer("Erreur MT5.", show_alert=True)
            return
        account = mt5.account_info()
        if account:
            status_msg = (
                f"*ETAT DU COMPTE*\n\n"
                f"Solde : `{account.balance} {account.currency}`\n"
                f"Equite : `{account.equity} {account.currency}`\n"
                f"Marge Libre : `{account.margin_free} {account.currency}`\n"
                f"Levier : `1:{account.leverage}`"
            )
            await query.message.reply_text(status_msg, parse_mode='Markdown')
        mt5.shutdown()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log l'erreur et ignore les erreurs reseau temporaires"""
    import telegram.error
    
    if isinstance(context.error, telegram.error.NetworkError):
        print(f"Erreur Reseau detectee : {context.error}. Le bot attendra le retour de la connexion...")
    else:
        print(f"Erreur d'application : {context.error}")
        # On pourrait logger l'erreur complete ici si besoin

def main():
    """Lancement du bot Telegram avec haute resilience"""
    print("Telegram Manager en attente de commandes (Mode Resilience actif)...")
    
    # Configuration de l'application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Ajout du gestionnaire d'erreurs
    application.add_error_handler(error_handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("log", get_logs))
    application.add_handler(CommandHandler("positions", get_positions))
    application.add_handler(CommandHandler("risk", get_risk_status))
    application.add_handler(CommandHandler("report", get_daily_report))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Configuration du polling simplifiee (Resilience standard)
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
