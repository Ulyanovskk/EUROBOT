import joblib
import pandas as pd
from func import apply_features, SYMBOL, create_targets, trade_backtest, analyze_results, send_telegram_message

# Chargement des données de backtest
backtest_data = pd.read_csv(f"CSV_FILES/MT5_5M_BT_{SYMBOL}_Dataset.csv")
backtest_df = apply_features(backtest_data)
backtest_df = create_targets(backtest_df)
backtest_df.dropna(inplace=True)

all_target = ['T_5M', 'T_10M', 'T_15M', 'T_20M', 'T_30M']
main_res = []

print(f"🕵️ Début du Backtest multi-timeframe pour {SYMBOL}...")

for target in all_target:
    bundle = joblib.load(f"ALL_MODELS/{SYMBOL}_lgbm_{target}.pkl")
    model = bundle["model"]
    feature_columns = bundle["features"]

    results = trade_backtest(df=backtest_df, model=model, feature_cols=feature_columns, threshold=55)
    
    print(f"\n📈 Analyse pour {target}:")
    analysis = analyze_results(results)
    main_res.append(analysis)
    
    # Envoi Notification Telegram
    msg = (
        f"📊 *BACKTEST {target} TERMINÉ*\n"
        f"Symbol: {SYMBOL}\n"
        f"Win Rate: `{analysis['win_rate']}%` \n"
        f"Profit total: `{analysis['total_profit_pips']} pips` \n"
        f"Trades: {analysis['total_trades']}"
    )
    send_telegram_message(msg)

print("\n✨ Tous les backtests sont terminés. Résultats envoyés sur Telegram.")
