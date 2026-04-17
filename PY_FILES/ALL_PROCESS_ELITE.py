import joblib
import numpy as np
import pandas as pd
import sys
import io
import os
import optuna
from catboost import CatBoostClassifier
from func import apply_features, SYMBOL

# Fix pour Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.makedirs("ELITE_MODELS", exist_ok=True)

print("Chargement des datasets pour l'entrainement ELITE...")

# 1. Chargement des GAGNANTS (Classe 1)
df_winners = pd.read_csv('CSV_FILES/Winners_Elite_Dataset.csv')
df_winners['target_elite'] = 1

# 2. Chargement du DATASET GENERAL pour creer des exemples "Non-Elite" (Classe 0)
df_general_raw = pd.read_csv(f'CSV_FILES/MT5_5M_BT_{SYMBOL}_Dataset.csv')
df_general = apply_features(df_general_raw)
df_general.dropna(inplace=True)

# On selectionne des echantillons aleatoires du general pour equilibrer
# On s'assure d'avoir les memes colonnes
common_cols = list(set(df_winners.columns) & set(df_general.columns))
X_winners = df_winners[common_cols].drop(columns=['target_elite'], errors='ignore')
y_winners = df_winners['target_elite']

X_general = df_general[X_winners.columns].sample(n=len(df_winners), random_state=42)
y_general = np.zeros(len(X_general))

# Fusion pour l'entrainement
X = pd.concat([X_winners, X_general])
y = pd.concat([y_winners, pd.Series(y_general)])

print(f"Entrainement ELITE sur {len(X)} exemples (50% Gagnants / 50% Standards)...")

# Optimisation rapide Optuna pour l'Elite
def objective(trial):
    params = {
        "iterations": 500,
        "depth": trial.suggest_int("depth", 4, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1, 10),
        "logging_level": 'Silent',
        "allow_writing_files": False
    }
    model = CatBoostClassifier(**params)
    # Split simple pour l'elite (pas besoin de tscv complexe ici)
    from sklearn.model_selection import train_test_split
    X_t, X_v, y_t, y_v = train_test_split(X, y, test_size=0.2, random_state=42)
    model.fit(X_t, y_t, eval_set=(X_v, y_v), early_stopping_rounds=50)
    return model.get_best_score()['validation']['Logloss']

study = optuna.create_study(direction="minimize")
study.optimize(objective, n_trials=10)

# Entrainement final de l'expert
print(f"Meilleurs parametres Elite : {study.best_params}")
elite_model = CatBoostClassifier(**study.best_params, iterations=1000, logging_level='Silent', allow_writing_files=False)
elite_model.fit(X, y)

# Sauvegarde
joblib.dump({"model": elite_model, "features": list(X_winners.columns)}, f"ELITE_MODELS/{SYMBOL}_Elite_Expert.pkl")

print(f"\n--- MODELE ELITE SAUVEGARDE : ELITE_MODELS/{SYMBOL}_Elite_Expert.pkl ---")
