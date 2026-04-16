import ta
import time
import joblib
import numpy as np
import pandas as pd
import sys
import io
import MetaTrader5 as mt5
from datetime import datetime
from func import apply_features,calc_lot_size,place_buy,check_account_info,place_sell,create_targets,SYMBOL,normalize_lot,get_symbol_volume_info,get_pip_info,log_trade

# Fix for Windows UnicodeEncodeError when printing emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

if not mt5.initialize():
    print("❌ MT5 initialization failed")
    quit()

print(f"🚀 Bot started for {SYMBOL}...")

# Paramètres du Circuit Breaker
DAILY_LOSS_LIMIT_PCT = 3.0  # Seuil de 3%
starting_daily_balance = mt5.account_info().balance
current_day = datetime.now().date()

try:
    while True:
        # Vérification du changement de jour pour le Circuit Breaker
        now_dt = datetime.now()
        if now_dt.date() > current_day:
            print(f"🌞 Nouveau jour détecté ({now_dt.date()}). Réinitialisation du capital de référence.")
            current_day = now_dt.date()
            starting_daily_balance = mt5.account_info().balance

        # Calcul du Drawdown journalier
        account = mt5.account_info()
        equity = account.equity
        current_drawdown_pct = ((starting_daily_balance - equity) / starting_daily_balance) * 100

        if current_drawdown_pct >= DAILY_LOSS_LIMIT_PCT:
            print(f"🛑 CIRCUIT BREAKER ACTIF : Perte de {round(current_drawdown_pct, 2)}% atteinte.")
            print(f"ℹ️ Trading suspendu jusqu'à demain. (Start Balance: {starting_daily_balance}, Equity: {equity})")
            time.sleep(60)
            continue

        TIMEFRAME = mt5.TIMEFRAME_M5
        N_BARS = 2000

        rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 1, N_BARS)

        if rates is None or len(rates) < N_BARS:
            print("❌ Failed to fetch enough closed candles. Retrying in 10s...")
            time.sleep(10)
            continue

        data = pd.DataFrame(rates)
        data['Date'] = pd.to_datetime(data['time'], unit='s')
        data.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)

        new_df = data[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].copy()
        new_df.sort_values('Date', inplace=True)
        new_df.reset_index(drop=True, inplace=True)

        df = apply_features(new_df)
        df.dropna(inplace=True)

        all_target = ['T_5M','T_10M','T_15M','T_20M','T_30M']
        up_moves = {}
        down_moves = {}
        previos_res_df = df[['Open', 'Close']].tail(5).copy()

        for target in all_target:
            bundle = joblib.load(f"ALL_MODELS/{SYMBOL}_lgbm_{target}.pkl")
            model = bundle["model"]
            feature_columns = bundle["features"]

            next_candle = df.loc[:, feature_columns].tail(1)
            proba = model.predict_proba(next_candle)
            up_moves[target] = round(proba[:,1][0] * 100, 2)
            down_moves[target] = round(proba[:,0][0] * 100, 2)

        up_moves_mean = round(sum(up_moves.values())/len(up_moves), 2) 
        down_moves_mean = round(sum(down_moves.values())/len(down_moves), 2)
        
        print(f"\n🔍 Confiance: UP {up_moves_mean}% | DOWN {down_moves_mean}%")

        # Vérification des positions ouvertes
        positions = mt5.positions_get(symbol=SYMBOL)
        has_position = len(positions) > 0

        if has_position:
            print(f"ℹ️ Position déjà ouverte sur {SYMBOL}. En attente...")
        else:
            THRESHOLD = 55
            if up_moves_mean >= THRESHOLD and up_moves_mean > down_moves_mean:
                print("🟢 Signal BUY détecté!")
                # Calcul des paramètres (prix, SL, TP, lot)
                tick = mt5.symbol_info_tick(SYMBOL)
                pip_info = get_pip_info(mt5, SYMBOL)
                row = df.iloc[-1]
                ATR_pips = row["ATR"] / pip_info["pip_size"]
                SL_pips = max(min(ATR_pips * 1.5, 200), 5)
                TP_pips = max(min(ATR_pips * 4.5, 400), 10)
                
                lot_size = calc_lot_size(mt5.account_info().balance, 1, SL_pips, pip_info["pip_value_per_lot"], 0.01, 2)
                vol_info = get_symbol_volume_info(mt5, SYMBOL)
                lot_size = normalize_lot(lot_size, vol_info["min"], vol_info["max"], vol_info["step"])

                entry_buy = tick.ask
                SL_buy = entry_buy - (SL_pips * pip_info["pip_size"])
                TP_buy = entry_buy + (TP_pips * pip_info["pip_size"])

                result = place_buy(mt5, SYMBOL, lot_size, entry_buy, SL_buy, TP_buy)
                log_trade(SYMBOL, "BUY", entry_buy, SL_buy, TP_buy, lot_size, up_moves_mean, down_moves_mean, result)

            elif down_moves_mean >= THRESHOLD and down_moves_mean > up_moves_mean:
                print("🔴 Signal SELL détecté!")
                tick = mt5.symbol_info_tick(SYMBOL)
                pip_info = get_pip_info(mt5, SYMBOL)
                row = df.iloc[-1]
                ATR_pips = row["ATR"] / pip_info["pip_size"]
                SL_pips = max(min(ATR_pips * 1.5, 200), 5)
                TP_pips = max(min(ATR_pips * 4.5, 400), 10)

                lot_size = calc_lot_size(mt5.account_info().balance, 1, SL_pips, pip_info["pip_value_per_lot"], 0.01, 2)
                vol_info = get_symbol_volume_info(mt5, SYMBOL)
                lot_size = normalize_lot(lot_size, vol_info["min"], vol_info["max"], vol_info["step"])

                entry_sell = tick.bid
                SL_sell = entry_sell + (SL_pips * pip_info["pip_size"])
                TP_sell = entry_sell - (TP_pips * pip_info["pip_size"])

                result = place_sell(mt5, SYMBOL, lot_size, entry_sell, SL_sell, TP_sell)
                log_trade(SYMBOL, "SELL", entry_sell, SL_sell, TP_sell, lot_size, up_moves_mean, down_moves_mean, result)

        print("😴 Sleeping for 10 seconds...")
        time.sleep(10)

except KeyboardInterrupt:
    print("\n👋 Bot stopped by user.")
except Exception as e:
    print(f"\n❌ Massive Error: {e}")
finally:
    mt5.shutdown()