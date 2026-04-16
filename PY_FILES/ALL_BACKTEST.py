import joblib
import pandas as pd
import sys
import io
from func import apply_features, SYMBOL, create_targets, trade_backtest, analyze_results, send_telegram_message

# Fix for Windows UnicodeEncodeError when printing emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Chargement des données de backtest
full_data = pd.read_csv(f"CSV_FILES/MT5_5M_BT_{SYMBOL}_Dataset.csv")

# Test Out-of-sample : On teste sur les 40 derniers % (que le modèle n'a jamais vus)
test_size = int(len(full_data) * 0.40)
backtest_data = full_data.tail(test_size).copy()

print(f"Backtest sur {len(backtest_data)} bougies (40% du dataset - Donnees INCONNUES)...")

backtest_df = apply_features(backtest_data)
backtest_df = create_targets(backtest_df)
backtest_df.dropna(inplace=True)

all_target = ['T_5M', 'T_10M', 'T_15M', 'T_20M', 'T_30M']
main_res = []

print(f"Debut du Backtest multi-timeframe pour {SYMBOL}...")

for target in all_target:
    bundle = joblib.load(f"ALL_MODELS/{SYMBOL}_lgbm_{target}.pkl")
    model = bundle["model"]
    feature_columns = bundle["features"]

    results = trade_backtest(df=backtest_df, model=model, feature_cols=feature_columns, threshold=55)
    
    print(f"\nAnalyse pour {target}:")
    analysis = analyze_results(results)
    main_res.append(analysis)
    
    # Envoi Notification Telegram
    msg = (
        f"*BACKTEST {target} TERMINE*\n"
        f"Symbol: {SYMBOL}\n"
        f"Win Rate: `{analysis['win_rate']}%` \n"
        f"Profit total: `{analysis['total_profit_pips']} pips` \n"
        f"Trades: {analysis['total_trades']}"
    )
    send_telegram_message(msg)

print("\nTous les backtests sont terminés. Résultats envoyés sur Telegram.")
