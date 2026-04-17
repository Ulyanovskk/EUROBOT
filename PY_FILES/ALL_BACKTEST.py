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

# --- DECOUPAGE STRATEGIQUE POUR BACKTEST ---
# On ne teste que sur les donnees APRES le 1er Janvier 2026
if 'time' in full_data.columns:
    full_data['time'] = pd.to_datetime(full_data['time'])
    backtest_data = full_data[full_data['time'] >= '2026-01-01'].copy()
    print(f"Backtest sur la periode INCONNUE (Depuis 2026-01-01) : {len(backtest_data)} bougies.")
else:
    # Fallback si pas de colonne time
    test_size = int(len(full_data) * 0.20)
    backtest_data = full_data.tail(test_size).copy()
    print(f"Backtest sur les 20 derniers % ({len(backtest_data)} bougies).")

backtest_df = apply_features(backtest_data)
backtest_df = create_targets(backtest_df)
backtest_df.dropna(inplace=True)

all_target = ['T_5M', 'T_10M', 'T_15M', 'T_20M', 'T_30M']
main_res = []

print(f"Debut du Backtest multi-timeframe pour {SYMBOL}...")

for target in all_target:
    # On charge le modele CatBoost (Expert Math)
    model = joblib.load(f"ALL_MODELS/{SYMBOL}_catboost_{target}.pkl")
    # Pour CatBoost, on n'a plus besoin de feature_cols separe si le modele les contient
    feature_columns = model.feature_names_

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

    # SAUVEGARDE DANS LE TRACKER DE PERFORMANCE (POUR EXCEL)
    from datetime import datetime
    import os
    report_file = "CSV_FILES/Backtest_Performance_Tracker.csv"
    report_data = {
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Symbol": SYMBOL,
        "Timeframe": target,
        "Win_Rate": analysis['win_rate'],
        "Profit_Pips": analysis['total_profit_pips'],
        "Total_Trades": analysis['total_trades'],
        "Note": "Train: 80% / Test: 20% (1 an de data)"
    }
    
    df_report = pd.DataFrame([report_data])
    if not os.path.exists(report_file):
        df_report.to_csv(report_file, index=False)
    else:
        df_report.to_csv(report_file, mode='a', header=False, index=False)

print("\nTous les backtests sont terminés. Résultats envoyés sur Telegram et enregistrés dans le Tracker.")
