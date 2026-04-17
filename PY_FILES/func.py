import ta
import os
import sys
import io
import joblib
import base64
import os
from dotenv import load_dotenv
from openai import OpenAI
import requests
import numpy as np
import pandas as pd
from datetime import datetime

# Chargement des variables d'environnement
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Initialisation du client AI
client = None
if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "VOTRE_CLE_ICI":
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# Fix for Windows UnicodeEncodeError when printing emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')






SYMBOL = "EURUSDm"

# CONFIGURATION TELEGRAM (Pour les notifications push)
TELEGRAM_TOKEN = "8725970972:AAHKf4iYfAnVGio0Sy2LUjQ_HA1hOI2K_g4"
ADMIN_CHAT_ID = 8458843915

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": ADMIN_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Erreur Telegram Send: {e}")


def apply_features(df):
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["Close"] = pd.to_numeric(df["Close"])
    df["High"] = pd.to_numeric(df["High"])
    df["Low"] = pd.to_numeric(df["Low"])
    df["Open"] = pd.to_numeric(df["Open"])
    df["Volume"] = pd.to_numeric(df["Volume"])
    df['Hour'] = df['Date'].dt.hour
    df['Weekday'] = df['Date'].dt.weekday
    df["Date_ordinal"] = df["Date"].apply(lambda x: x.toordinal())

    # 3. INDICATEURS DE TENDANCE (AVEC PENTES)
    df['EMA_20'] = ta.trend.ema_indicator(df['Close'], window=20)
    df['EMA_50'] = ta.trend.ema_indicator(df['Close'], window=50)
    df['EMA_100'] = ta.trend.ema_indicator(df['Close'], window=100)
    df['EMA_200'] = ta.trend.ema_indicator(df['Close'], window=200)
    
    # Calcul des Slopes (Pentes) - Comme dans votre dataset Elite
    df['ema20Slope'] = df['EMA_20'].diff()
    df['ema50Slope'] = df['EMA_50'].diff()
    df['ema100Slope'] = df['EMA_100'].diff()

    # 4. OSCILLATEURS
    df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
    stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
    df['STOCH'] = stoch.stoch()
    df['STOCH_SIGNAL'] = stoch.stoch_signal()

    # 5. CREATION DES LAGS (Historique 1 a 6)
    # On cree des decalages pour donner du contexte temporel a l'IA
    for i in range(1, 7):
        df[f'rsi{i}'] = df['RSI'].shift(i)
        df[f'stoch{i}'] = df['STOCH'].shift(i)
        df[f'ema20Slope{i}'] = df['ema20Slope'].shift(i)
        df[f'ema50Slope{i}'] = df['ema50Slope'].shift(i)
        df[f'ema100Slope{i}'] = df['ema100Slope'].shift(i)

    # 6. STRUCTURE DE MARCHE ET VOLATILITE
    df['TREND'] = np.where(df['EMA_50'] > df['EMA_200'], 1, -1)

    df["MACD"] = ta.trend.macd_diff(df["Close"])
    bb = ta.volatility.BollingerBands(df["Close"], window=20)
    df["BB_H"] = bb.bollinger_hband()
    df["BB_L"] = bb.bollinger_lband()
    df["ATR"] = ta.volatility.average_true_range(df["High"], df["Low"], df["Close"], window=14)
    df["VWAP"] = ta.volume.volume_weighted_average_price(df["High"], df["Low"], df["Close"], df["Volume"])
    df["Candle_Body"] = abs(df["Close"] - df["Open"])
    df["Body_to_Range"] = df["Candle_Body"] / (df["High"] - df["Low"]).replace(0, np.nan)
    df["Log_Return"] = np.log(df["Close"] / df["Close"].shift(1))
    df["Rolling_Mean_Return"] = df["Log_Return"].rolling(window=5).mean()
    df["Rolling_Std_Return"] = df["Log_Return"].rolling(window=5).std()
    df["EMA_Slope"] = df["EMA_20"] - df["EMA_50"]
    df["Dist_from_EMA200"] = df["Close"] - df["EMA_200"]
    df["ADX"] = ta.trend.adx(df["High"], df["Low"], df["Close"], window=14)
    df["Trend_Strength"] = abs(df["Close"] - df["EMA_200"])
    df["Dist_to_Recent_High"] = df["High"].rolling(window=20).max() - df["Close"]
    df["Dist_to_Recent_Low"] = df["Close"] - df["Low"].rolling(window=20).min()
    df["Dist_to_Rolling_Max"] = df["Close"].rolling(window=50).max() - df["Close"]
    df["Dist_to_Rolling_Min"] = df["Close"] - df["Close"].rolling(window=50).min()
    df["Rolling_Mean_Volume"] = df["Volume"].rolling(window=20).mean()
    df["Volume_Spike"] = df["Volume"] / df["Rolling_Mean_Volume"]
    df["Vol_Range"] = df["Volume"] * (df["High"] - df["Low"])

    WINDOW = 20  # you can tune this
    df['rolling_high'] = df['High'].rolling(WINDOW).max()
    df['rolling_low']  = df['Low'].rolling(WINDOW).min()
    df['dist_to_resistance'] = df['rolling_high'] - df['Close']
    df['dist_to_support'] = df['Close'] - df['rolling_low']
    threshold = df['Close'] * 0.001  # 0.1%
    df['near_resistance'] = (df['dist_to_resistance'] < threshold).astype(int)
    # --- OPTIMISATION : Calcul groupé pour éviter la fragmentation ---
    new_cols = {}
    
    new_cols['near_support'] = (df['dist_to_support'] < threshold).astype(int)

    LOOKBACK = 20
    prev_high = df['High'].shift(1).rolling(LOOKBACK).max()
    prev_low  = df['Low'].shift(1).rolling(LOOKBACK).min()
    broke_prev_high = (df['High'] > prev_high).astype(int)
    broke_prev_low = (df['Low'] < prev_low).astype(int)
    
    new_cols['turtle_soup_sell'] = ((broke_prev_high == 1) & (df['Close'] < df['Open'])).astype(int)
    new_cols['turtle_soup_buy'] = ((broke_prev_low == 1) & (df['Close'] > df['Open'])).astype(int)

    STRUCT_WINDOW = 15
    struct_high = df['High'].rolling(STRUCT_WINDOW).max()
    struct_low = df['Low'].rolling(STRUCT_WINDOW).min()
    bos_up = (df['Close'] > struct_high.shift(1)).astype(int)
    bos_down = (df['Close'] < struct_low.shift(1)).astype(int)
    
    new_cols['structure_direction'] = np.where(bos_up == 1, 1, np.where(bos_down == 1, -1, 0))

    FIB_WINDOW = 50
    swing_high = df['High'].rolling(FIB_WINDOW).max()
    swing_low = df['Low'].rolling(FIB_WINDOW).min()
    fib_618 = swing_high - 0.618 * (swing_high - swing_low)
    
    new_cols['fib_618_hit'] = ((df['Close'] - fib_618).abs() < threshold).astype(int)

    body = abs(df['Close'] - df['Open'])
    range_val = df['High'] - df['Low']
    upper_wick = df['High'] - df[['Open', 'Close']].max(axis=1)
    lower_wick = df[['Open', 'Close']].min(axis=1) - df['Low']
    
    new_cols['Candle_Strength'] = (df['Close'] - df['Open']) / (range_val + 1e-6)
    new_cols['PinBar_Bull'] = ((lower_wick > 2 * body) & (upper_wick < body)).astype(int)
    new_cols['PinBar_Bear'] = ((upper_wick > 2 * body) & (lower_wick < body)).astype(int)
    new_cols['Impulse_Bull'] = ((body > 0.6 * range_val) & (df['Close'] > df['Open'])).astype(int)
    new_cols['Impulse_Bear'] = ((body > 0.6 * range_val) & (df['Close'] < df['Open'])).astype(int)
    new_cols['Inside_Bar'] = ((df['High'] < df['High'].shift(1)) & (df['Low'] > df['Low'].shift(1))).astype(int)
    new_cols['Bull_Engulf'] = ((df['Close'] > df['Open']) & (df['Open'] < df['Close'].shift(1)) & (df['Close'] > df['Open'].shift(1))).astype(int)
    new_cols['Bear_Engulf'] = ((df['Close'] < df['Open']) & (df['Open'] > df['Close'].shift(1)) & (df['Close'] < df['Open'].shift(1))).astype(int)
    new_cols['Doji'] = (body < 0.1 * range_val).astype(int)
    new_cols['Bull_Pressure'] = (df['Close'] > df['Open']).rolling(3).sum()
    new_cols['Bear_Pressure'] = (df['Close'] < df['Open']).rolling(3).sum()

    # On ajoute tout d'un coup (Évite le PerformanceWarning)
    df = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)

    # feature_ = df.columns.to_list()
    # for all_feature in feature_:
    #     for amt_lag in range(1,6):
    #         df[f'{all_feature}_lag{amt_lag}'] = df[f'{all_feature}'].shift(amt_lag)

    df.set_index("Date", inplace=True)
    return df



def calc_lot_size(balance, risk_percent, sl_pips,pip_value_per_lot, min_lot, max_lot):
    risk_amount = balance * (risk_percent / 100)
    lot_cal = risk_amount / (sl_pips * pip_value_per_lot)
    lot = max(min_lot, min(lot_cal, max_lot))
    return lot



def check_trade_result(mt5, result):
    if result is None:
        print("ERREUR: Order failed: result is None")
        print("MT5 last error:", mt5.last_error())
        return False

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print("ERREUR: Order rejected")
        print("Retcode:", result.retcode)
        print("Comment:", result.comment)
        print("Request ID:", result.request_id)
        return False

    print("OK: Trade placed successfully")
    print("Order Ticket:", result.order)
    print("Deal Ticket:", result.deal)
    print("Volume:", result.volume)
    print("Price:", result.price)
    return True

def get_symbol_volume_info(mt5, symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("Failed to get symbol info")

    return {
        "min": info.volume_min,
        "max": info.volume_max,
        "step": info.volume_step
    }



def normalize_lot(lot, vol_min, vol_max, vol_step):
    lot = max(vol_min, min(lot, vol_max))
    lot = np.floor(lot / vol_step) * vol_step
    return round(lot, 2)


def place_sell(mt5,symbol, lot, entry_price, sl, tp):
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_SELL,
        "price": entry_price,
        "sl": sl,
        "tp": tp,
        "deviation": 50,
        "magic": 10002,
        "comment": "Auto SELL",
        "type_time": mt5.ORDER_TIME_GTC
    }

    result = mt5.order_send(request)
    check_trade_result(mt5, result)
    return result



def place_buy(mt5,symbol, lot, entry_price, sl, tp):
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY,
        "price": entry_price,
        "sl": sl,
        "tp": tp,
        "deviation": 50,
        "magic": 10001,
        "comment": "Auto BUY",
        "type_time": mt5.ORDER_TIME_GTC
    }

    result = mt5.order_send(request)
    check_trade_result(mt5, result)
    return result




def drop_duplicate(path):
    all_df = pd.read_csv(path)
    all_df = all_df.drop_duplicates(keep='first')
    all_df = all_df.reset_index()
    all_df.drop(['index'], axis=1, inplace=True)
    all_df.to_csv(path, index=False)


def create_targets(df, pip_threshold=2.5):
    """
    Cree des cibles intelligentes : 
    1 si le prix monte de plus de pip_threshold pips dans l'horizon.
    Ignore les mouvements trop faibles (bruit).
    """
    horizons = {
        "T_5M": 1,
        "T_10M": 2,
        "T_15M": 3,
        "T_20M": 4,
        "T_30M": 6
    }
    
    # On recupere la taille du pip pour EURUSDm
    pip_size = 0.0001
    
    for name, step in horizons.items():
        # Variation de prix future (Close_futur - Close_actuel)
        future_change = df['Close'].shift(-step) - df['Close']
        future_pips = future_change / pip_size
        
        # Label 1 si mouvement > seuil pips, sinon 0
        df[name] = (future_pips > pip_threshold).astype(int)
        
    df = df.iloc[:-10] # Supprimer les dernieres lignes sans futur
    return df


def trade_backtest(df, model, feature_cols, threshold=55, atr_sl=1.5, atr_tp=4.5, spread_pips=1.2, slippage_pips=0.2, pip_value=0.0001, elite_model=None):
    trades = []
    spread = spread_pips * pip_value
    slippage = slippage_pips * pip_value
    
    # --- OPTIMISATION VITESSE ---
    # On prepare les colonnes pour les deux modeles une seule fois
    X_math = df[feature_cols].values
    
    X_elite = None
    if elite_model is not None:
        if isinstance(elite_model, dict):
            actual_elite = elite_model['model']
            elite_features = elite_model['features']
        else:
            actual_elite = elite_model
            elite_features = actual_elite.feature_names_
        X_elite = df[elite_features].values
    else:
        actual_elite = None
    # ----------------------------

    i = 0 
    while i < len(df) - 1:
        row = df.iloc[i]
        next_row = df.iloc[i + 1]
        
        # Recuperation rapide des probabilités via numpy
        proba = model.predict_proba(X_math[i:i+1])[0]
        up_conf, down_conf = proba[1] * 100, proba[0] * 100

        # Filtre 1 : Confiance Mathématique
        if max(up_conf, down_conf) < threshold:
            i += 1
            continue
            
        # Filtre 2 : Expert ELITE (Experience) - Rapide via numpy
        if actual_elite is not None:
            elite_proba = actual_elite.predict_proba(X_elite[i:i+1])[0][1]
            if elite_proba < 0.50:
                i += 1
                continue

        direction = "BUY" if up_conf > down_conf else "SELL"
        atr = row["ATR"]
        
        # Risk/Reward en pips (approximatif pour le log)
        sl_dist = atr_sl * atr
        tp_dist = atr_tp * atr

        if direction == "BUY":
            entry = next_row["Open"] + spread + slippage
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            entry = next_row["Open"] - slippage
            sl = entry + sl_dist
            tp = entry - tp_dist

        for j in range(i + 1, len(df)):
            candle = df.iloc[j]
            
            if direction == "BUY":
                if candle["Low"] <= sl:
                    trades.append(("LOSS", direction, i, j, -sl_dist))
                    i = j; break
                elif candle["High"] >= tp:
                    trades.append(("WIN", direction, i, j, tp_dist))
                    i = j; break
            else:
                candle_high_ask = candle["High"] + spread
                candle_low_ask = candle["Low"] + spread
                
                if candle_high_ask >= sl:
                    trades.append(("LOSS", direction, i, j, -sl_dist))
                    i = j; break
                elif candle_low_ask <= tp:
                    trades.append(("WIN", direction, i, j, tp_dist))
                    i = j; break
        else:
            i += 1
    return trades



def analyze_results(trades):
    total = len(trades)
    if total == 0:
        print("No trades executed.")
        return {"win_rate": 0, "total_profit": 0}

    wins = sum(1 for t in trades if t[0] == "WIN")
    losses = total - wins
    win_rate = round((wins / total) * 100, 2)
    total_profit_raw = sum(t[4] for t in trades)
    
    # Conversion pips (approximatif, dépend de la paire)
    pip_scale = 10000 if SYMBOL != "USDJPY" else 100
    total_profit_pips = round(total_profit_raw * pip_scale, 1)

    print(f"--- Backtest Results ---")
    print(f"Total Trades: {total}")
    print(f"Wins: {wins} | Losses: {losses}")
    print(f"Win Rate: {win_rate}%")
    print(f"Total Profit: {total_profit_pips} pips")
    print(f"Avg Profit/Trade: {round(total_profit_pips/total, 2)} pips")
    print("------------------------")
    
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_profit_pips": total_profit_pips
    }




def get_pip_info(mt5, symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info not found for {symbol}")

    tick_size = info.trade_tick_size
    tick_value = info.trade_tick_value
    digits = info.digits

    # Determine pip size
    if digits in (3, 5):
        pip_size = tick_size * 10
    else:
        pip_size = tick_size

    # Pip value per 1 lot
    pip_value_per_lot = (pip_size / tick_size) * tick_value

    return {
        "pip_size": pip_size,
        "pip_value_per_lot": pip_value_per_lot,
        "tick_size": tick_size,
        "tick_value": tick_value
    }



LOG_FILE = "CSV_FILES/Trade_log.csv"
def log_trade(symbol, direction, entry_price, SL, TP, lot_size, proba_up, proba_down, order_result):
    """
    Logs trade info to CSV.
    
    symbol       : trading symbol
    direction    : 'BUY' or 'SELL'
    entry_price  : price of entry
    SL, TP       : stop loss and take profit
    lot_size     : lots
    proba_up     : predicted probability for UP
    proba_down   : predicted probability for DOWN
    order_result : response from MT5 order
    """
    now = datetime.now()
    log_entry = {
        "Datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "Symbol": symbol,
        "Direction": direction,
        "EntryPrice": entry_price,
        "SL": SL,
        "TP": TP,
        "LotSize": lot_size,
        "Proba_UP": proba_up,
        "Proba_DOWN": proba_down,
        "OrderResult": str(order_result)
    }

    # If file exists, append; else create new
    if os.path.exists(LOG_FILE):
        df_log = pd.read_csv(LOG_FILE)
        df_log = pd.concat([df_log, pd.DataFrame([log_entry])], ignore_index=True)
    else:
        df_log = pd.DataFrame([log_entry])

    df_log.to_csv(LOG_FILE, index=False)
    print("Trade logged successfully")

    # ENVOI NOTIFICATION TELEGRAM
    status_text = "DONE" if "DONE" in str(order_result) else "FAILED"
    msg = (
        f"[{status_text}] NOUVEAU TRADE - {symbol}\n\n"
        f"Direction : *{direction}*\n"
        f"Prix : `{entry_price}`\n"
        f"Lot : `{lot_size}`\n"
        f"SL : `{round(SL, 5)}` | TP : `{round(TP, 5)}`\n\n"
        f"Confiance : UP {proba_up}% | DN {proba_down}%"
    )
    send_telegram_message(msg)



def modify_sl(mt5, ticket, new_sl, symbol):
    """Modifie le Stop Loss d'une position existante"""
    position = mt5.positions_get(ticket=ticket)
    if not position:
        return False
    
    pos = position[0]
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": new_sl,
        "tp": pos.tp, # On ne change pas le TP
        "magic": pos.magic
    }
    
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        return True
    return False

def check_account_info(mt5):
    account_info = mt5.account_info()
    balance = account_info.balance
    equity = account_info.equity
    currency = account_info.currency
    
    return {"balance": balance, "equity": equity, "currency": currency}

def ohlc_to_image(df_ohlc, img_size=64):
    """
    Transforme un DataFrame OHLC en image 64x64 (ligne noire sur fond blanc)
    pour l'Expert VISION.
    """
    import numpy as np
    import cv2
    
    # On cree une image blanche
    img = np.ones((img_size, img_size), dtype=np.uint8) * 255
    
    # On normalise les prix pour qu'ils rentrent dans le carre
    # Gestion flexible de la casse (Close ou close)
    col_name = 'Close' if 'Close' in df_ohlc.columns else 'close'
    if col_name not in df_ohlc.columns: return img
    
    prices = df_ohlc[col_name].values
    if len(prices) < 2: return img
    
    min_p, max_p = np.min(prices), np.max(prices)
    if max_p == min_p: return img
    
    # Echelle
    scaled_prices = (prices - min_p) / (max_p - min_p) * (img_size - 10) + 5
    # Inversion (en image Y=0 est en haut)
    y_coords = img_size - scaled_prices.astype(int)
    # X reparti sur la largeur
    x_coords = np.linspace(5, img_size - 5, len(prices)).astype(int)
    
    # Tracé des lignes
    for i in range(len(prices) - 1):
        cv2.line(img, (x_coords[i], y_coords[i]), (x_coords[i+1], y_coords[i+1]), (0, 0, 0), 1)
        
    return img # Retourne enfin l'image !
        
def get_deepseek_vision_verdict(img_array):
    """
    Envoie l'image du graphique a DeepSeek Vision pour validation.
    """
    if client is None:
        return True # On ne bloque pas si l'API n'est pas configuree
        
    try:
        # 1. Conversion de l'image (numpy array) en Base64
        import cv2
        _, buffer = cv2.imencode('.jpg', img_array)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # 2. Requete a l'IA (Format simplifie)
        response = client.chat.completions.create(
            model="deepseek-chat", # On tente le modele principal qui souvent redirige vers le bon moteur
            messages=[
                {
                    "role": "user",
                    "content": f"Ceci est un graphique EURUSD (Image Base64). Vois-tu une figure de retournement claire ? Réponds par OUI ou NON.\nImage: data:image/jpeg;base64,{img_base64}"
                }
            ],
            max_tokens=10
        )
        
        verdict = response.choices[0].message.content.strip().upper()
        return "OUI" in verdict
    except Exception as e:
        print(f"Erreur Vision AI: {e}")
        return True # Fallback amical