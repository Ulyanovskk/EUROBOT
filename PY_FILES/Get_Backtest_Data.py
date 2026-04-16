import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import os
import sys
import io
from func import drop_duplicate, SYMBOL

# Fix for Windows UnicodeEncodeError when printing emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def get_90_days_data():
    if not mt5.initialize():
        print("❌ MT5 initialization failed")
        return

    # Calcul des dates (90 derniers jours)
    os.makedirs("CSV_FILES", exist_ok=True)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)

    print(f"📥 Downloading last 90 days of data for {SYMBOL}...")
    print(f"Period: {start_date.date()} to {end_date.date()}")

    # S'assurer que le symbole est présent dans le MarketWatch
    if not mt5.symbol_select(SYMBOL, True):
        print(f"❌ Failed to select {SYMBOL}")
        return

    # Récupération des données en 5 minutes
    timeframe = mt5.TIMEFRAME_M5
    rates = mt5.copy_rates_range(SYMBOL, timeframe, start_date, end_date)

    if rates is not None and len(rates) > 0:
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Formatage standard
        df.rename(columns={
            'time': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'tick_volume': 'Volume'
        }, inplace=True)
        
        df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
        
        # Sauvegarde
        file_path = f'CSV_FILES/MT5_5M_BT_{SYMBOL}_Dataset.csv'
        df.to_csv(file_path, index=False)
        
        # Nettoyage
        drop_duplicate(file_path)
        
        print(f"✅ Success! {len(df)} candles saved to {file_path}")
    else:
        print("❌ Failed to retrieve data from MT5. Make sure the market is open or your broker provides history.")

    mt5.shutdown()

if __name__ == "__main__":
    get_90_days_data()
