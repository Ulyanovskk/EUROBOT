import joblib
import numpy as np
import pandas as pd
import sys
import io
import os
import optuna
from catboost import CatBoostClassifier
from sklearn.model_selection import TimeSeriesSplit
from func import apply_features, create_targets, SYMBOL

# Fix pour Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.makedirs("ALL_MODELS", exist_ok=True)
full_data = pd.read_csv(f'CSV_FILES/MT5_5M_BT_{SYMBOL}_Dataset.csv') 

# On utilise les 300 derniers jours pour l'entrainement total
print(f"Preparation des donnees pour {SYMBOL}...")
df = apply_features(full_data)
df = create_targets(df)

# --- DECOUPAGE STRATEGIQUE POUR BACKTEST ---
# On n'entraine que sur les donnees AVANT le 1er Janvier 2026
if 'time' in df.columns:
    df['time'] = pd.to_datetime(df['time'])
    old_size = len(df)
    df = df[df['time'] < '2026-01-01']
    print(f"Entrainement bride avant le 2026-01-01 ({len(df)}/{old_size} lignes conservees)")

df.dropna(inplace=True)

all_target = ['T_5M', 'T_10M', 'T_15M', 'T_20M', 'T_30M']

def objective(trial, X, y):
    # Espace de recherche des parametres CatBoost
    params = {
        "iterations": 500,
        "depth": trial.suggest_int("depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.1, log=True),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 15.0),
        "random_seed": 42,
        "logging_level": 'Silent',
        "allow_writing_files": False
    }
    
    # Validation Croisee Temporelle (3 Folds)
    tscv = TimeSeriesSplit(n_splits=3)
    scores = []
    
    for train_index, test_index in tscv.split(X):
        X_t, X_v = X.iloc[train_index], X.iloc[test_index]
        y_t, y_v = y.iloc[train_index], y.iloc[test_index]
        
        model = CatBoostClassifier(**params)
        model.fit(X_t, y_t, eval_set=(X_v, y_v), early_stopping_rounds=50)
        
        # On score sur l'accuracy (ou F1 si on veut plus de precision)
        scores.append(model.get_best_score()['validation']['Logloss'])
        
    return np.mean(scores)

# Boucle d'optimisation et d'entrainement
for target in all_target:
    print(f"\n--- OPTIMISATION OPTUNA : {target} ---")
    
    y = df[target]
    X = df.drop(columns=all_target)
    
    # Etape 1 : Feature Selection Rapide
    pre_model = CatBoostClassifier(iterations=300, logging_level='Silent', allow_writing_files=False)
    pre_model.fit(X, y)
    importance = pre_model.get_feature_importance()
    top_76_features = [X.columns[i] for i in np.argsort(importance)[::-1][:76]]
    X_top = X[top_76_features]
    
    # Etape 2 : Recherche Optuna
    study = optuna.create_study(direction="minimize")
    study.optimize(lambda trial: objective(trial, X_top, y), n_trials=20)
    
    print(f"Meilleurs parametres pour {target}: {study.best_params}")
    
    # Etape 3 : Entrainement Final
    final_params = {
        **study.best_params,
        "iterations": 1000,
        "random_seed": 42,
        "logging_level": 'Silent',
        "allow_writing_files": False
    }
    
    final_model = CatBoostClassifier(**final_params)
    final_model.fit(X_top, y)
    
    # Sauvegarde
    joblib.dump(final_model, f"ALL_MODELS/{SYMBOL}_catboost_{target}.pkl")
    print(f"Fichier enregistre : {SYMBOL}_catboost_{target}.pkl")

print("\n--- PROCESSUS D'ENTRAINEMENT OPTIMISE TERMINE AVEC SUCCES ---")