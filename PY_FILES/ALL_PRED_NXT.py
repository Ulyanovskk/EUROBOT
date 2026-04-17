import ta
import time
import joblib
import numpy as np
import pandas as pd
import sys
import io
import MetaTrader5 as mt5
from datetime import datetime
from func import apply_features,calc_lot_size,place_buy,check_account_info,place_sell,create_targets,SYMBOL,normalize_lot,get_symbol_volume_info,get_pip_info,log_trade,modify_sl

# Fix for Windows UnicodeEncodeError when printing emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

if not mt5.initialize():
    print("ERREUR: MT5 initialization failed")
    quit()

print(f"Bot started for {SYMBOL}...")

# Paramètres du Circuit Breaker et Limites
DAILY_LOSS_LIMIT_PCT = 20.0  
MAX_POSITIONS = 2           
MAX_DAILY_TRADES = 6        # Limite de trades total par jour
ALLOWED_HOURS = range(7, 21) # Session Londres + New York (7h-20h)
TRAILING_STOP_ATR_MULT = 1.5 # Distance du trailing (ATR * mult)

starting_daily_balance = mt5.account_info().balance
current_day = datetime.now().date()
last_known_positions = [] 
daily_trade_count = 0       # Compteur de trades du jour

# --- CHARGEMENT DES MODELES (UNE SEULE FOIS) ---
all_target = ['T_5M','T_10M','T_15M','T_20M','T_30M']
models_bundles = {}
print("Chargement des modèles IA...")
for target in all_target:
    try:
        models_bundles[target] = joblib.load(f"ALL_MODELS/{SYMBOL}_lgbm_{target}.pkl")
    except Exception as e:
        print(f"ERREUR: Impossible de charger le modèle {target}: {e}")
        quit()

try:
    while True:
        now_dt = datetime.now()
        
        # Réinitialisation journalière (Profit/Perte + Compteur de trades)
        if now_dt.date() > current_day:
            print(f"Nouveau jour détecté ({now_dt.date()}). Réinitialisation...")
            current_day = now_dt.date()
            starting_daily_balance = mt5.account_info().balance
            daily_trade_count = 0

        # 1. Filtre de Session
        if now_dt.hour not in ALLOWED_HOURS:
            if now_dt.minute % 15 == 0 and now_dt.second < 10: # Log toutes les 15 min
                print(f"Hors session de trading ({now_dt.hour}h). En attente de 07:00...")
            time.sleep(10)
            continue

        # 2. Vérification Limite de Trades Journalière
        if daily_trade_count >= MAX_DAILY_TRADES:
            if now_dt.minute % 15 == 0 and now_dt.second < 10:
                print(f"Limite journalière de {MAX_DAILY_TRADES} trades atteinte. Reprise demain.")
            time.sleep(10)
            continue

        # 3. Circuit Breaker (Drawdown)
        account = mt5.account_info()
        equity = account.equity
        current_drawdown_pct = ((starting_daily_balance - equity) / starting_daily_balance) * 100

        if current_drawdown_pct >= DAILY_LOSS_LIMIT_PCT:
            print(f"CIRCUIT BREAKER ACTIF : Perte de {round(current_drawdown_pct, 2)}% atteinte.")
            time.sleep(60)
            continue

        # --- Analyse Technique ---
        TIMEFRAME = mt5.TIMEFRAME_M5
        N_BARS = 2000
        rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 1, N_BARS)

        if rates is None or len(rates) < N_BARS:
            print("ERREUR: Données MT5 insuffisantes. Retry...")
            time.sleep(10)
            continue

        data = pd.DataFrame(rates)
        data['Date'] = pd.to_datetime(data['time'], unit='s')
        data.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
        df = apply_features(data[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].copy())
        df.dropna(inplace=True)

        # Prédictions
        up_moves = {}
        down_moves = {}
        next_candle = df.tail(1)

        for target in all_target:
            bundle = models_bundles[target]
            model = bundle["model"]
            features = bundle["features"]
            X = next_candle[features]
            proba = model.predict_proba(X)
            up_moves[target] = round(proba[:,1][0] * 100, 2)
            down_moves[target] = round(proba[:,0][0] * 100, 2)

        up_moves_mean = round(sum(up_moves.values())/len(up_moves), 2) 
        down_moves_mean = round(sum(down_moves.values())/len(down_moves), 2)
        
        # --- GESTION DU TRAILING STOP ---
        raw_positions = mt5.positions_get(symbol=SYMBOL)
        current_positions = raw_positions if raw_positions is not None else []
        
        atr_value = df.iloc[-1]["ATR"]
        trailing_dist = atr_value * TRAILING_STOP_ATR_MULT

        for p in current_positions:
            ticket = p.ticket
            current_sl = p.sl
            p_type = p.type # 0 = BUY, 1 = SELL
            price = p.price_current
            
            if p_type == mt5.ORDER_TYPE_BUY:
                new_sl = round(price - trailing_dist, 5)
                # Le SL ne doit que MONTER
                if new_sl > current_sl + (0.00005): # Seuil de 0.5 pips pour eviter trop d'appels
                    if modify_sl(mt5, ticket, new_sl, SYMBOL):
                        print(f"\n[TRAILING] BUY Ticket {ticket}: Nouveau SL -> {new_sl}")
            
            elif p_type == mt5.ORDER_TYPE_SELL:
                new_sl = round(price + trailing_dist, 5)
                # Le SL ne doit que DESCENDRE (ou etre initialise si 0)
                if current_sl == 0 or new_sl < current_sl - (0.00005):
                    if modify_sl(mt5, ticket, new_sl, SYMBOL):
                        print(f"\n[TRAILING] SELL Ticket {ticket}: Nouveau SL -> {new_sl}")

        print(f"\r[{now_dt.strftime('%H:%M:%S')}] Confiance: UP {up_moves_mean}% | DOWN {down_moves_mean}% | Trades: {daily_trade_count}/{MAX_DAILY_TRADES}", end="")

        # --- SURVEILLANCE DES FERMETURES ---
        current_ticket_ids = [p.ticket for p in current_positions]
        
        for old_ticket in last_known_positions:
            if old_ticket not in current_ticket_ids:
                from datetime import timedelta
                history = mt5.history_deals_get(datetime.now() - timedelta(minutes=10), datetime.now())
                if history:
                    for deal in history:
                        if deal.position_id == old_ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
                            profit = deal.profit + deal.commission + deal.swap
                            msg = (f"--- TRADE FERME ({'PROFIT' if profit > 0 else 'LOSS'}) ---\n"
                                   f"Ticket: `{old_ticket}` | Gain: `{round(profit, 2)} EUR`")
                            from func import send_telegram_message
                            send_telegram_message(msg)
                            print(f"\n[FERMETURE] Ticket {old_ticket} ferme: {round(profit, 2)} EUR")
        
        last_known_positions = current_ticket_ids

        # --- PRISE DE POSITION ---
        nb_positions = len(current_positions)
        if nb_positions < MAX_POSITIONS:
            # Récupérer les directions déjà ouvertes
            existing_dirs = []
            for p in current_positions:
                existing_dirs.append("BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL")

            # --- FILTRES DE TIMING (REBOND) ---
            THRESHOLD = 55
            signal_direction = None
            
            # Recuperation du RSI et des prix actuels pour le timing
            row = df.iloc[-1]
            rsi_val = row["RSI"]
            last_close = row["Close"]
            tick = mt5.symbol_info_tick(SYMBOL)
            
            # Logique de Direction IA
            if up_moves_mean >= THRESHOLD and up_moves_mean > down_moves_mean:
                # OPTIMISATION BUY : Attendre que le prix rebondisse
                # 1. Le prix actuel (bid) doit etre superieur a l'ouverture (bougie verte)
                # 2. Le prix doit etre au-dessus de la clôture de la bougie precedente (rebond confirme)
                # 3. Le RSI ne doit pas etre deja en sur-achat (> 70)
                is_rebounding = (tick.bid > row["Open"]) and (tick.bid > last_close)
                
                if is_rebounding and rsi_val < 70:
                    signal_direction = "BUY"
                else:
                    if up_moves_mean > 60: # On previent que le signal est la mais attend le timing
                        print(f" -> Signal BUY en attente de rebond (RSI: {round(rsi_val,1)})")

            elif down_moves_mean >= THRESHOLD and down_moves_mean > up_moves_mean:
                # OPTIMISATION SELL : Attendre que le prix chute
                # 1. Le prix actuel (ask) doit etre inferieur a l'ouverture (bougie rouge)
                # 2. Le prix doit etre sous la clôture precedente
                # 3. Le RSI ne doit pas etre deja en sur-vente (< 30)
                is_dropping = (tick.ask < row["Open"]) and (tick.ask < last_close)
                
                if is_dropping and rsi_val > 30:
                    signal_direction = "SELL"
                else:
                    if down_moves_mean > 60:
                        print(f" -> Signal SELL en attente de baisse (RSI: {round(rsi_val,1)})")

            # Exécution si le Timing est validé
            if signal_direction and signal_direction not in existing_dirs:
                print(f"\n[TIMING OK] Signal {signal_direction} confirme par le prix. Execution...")
                pip_info = get_pip_info(mt5, SYMBOL)
                ATR_pips = row["ATR"] / pip_info["pip_size"]
                SL_pips = max(min(ATR_pips * 1.5, 200), 10)
                TP_pips = max(min(ATR_pips * 4.5, 400), 20)
                
                lot_size = calc_lot_size(mt5.account_info().balance, 1.0, SL_pips, pip_info["pip_value_per_lot"], 0.01, 2.0)
                vol_info = get_symbol_volume_info(mt5, SYMBOL)
                lot_size = normalize_lot(lot_size, vol_info["min"], vol_info["max"], vol_info["step"])

                if signal_direction == "BUY":
                    entry = tick.ask
                    sl, tp = entry - (SL_pips * pip_info["pip_size"]), entry + (TP_pips * pip_info["pip_size"])
                    res = place_buy(mt5, SYMBOL, lot_size, entry, sl, tp)
                else:
                    entry = tick.bid
                    sl, tp = entry + (SL_pips * pip_info["pip_size"]), entry - (TP_pips * pip_info["pip_size"])
                    res = place_sell(mt5, SYMBOL, lot_size, entry, sl, tp)

                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    daily_trade_count += 1
                    log_trade(SYMBOL, signal_direction, entry, sl, tp, lot_size, up_moves_mean, down_moves_mean, res)
        
        time.sleep(10)

except KeyboardInterrupt:
    print("\nBot arrêté par l'utilisateur.")
except Exception as e:
    import traceback
    print(f"\nERREUR FATALE: {e}")
    traceback.print_exc()
finally:
    mt5.shutdown()