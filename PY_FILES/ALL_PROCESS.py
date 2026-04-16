import ta
import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from func import apply_features, create_targets, SYMBOL

# 1. Chargement des données
data = pd.read_csv(f'CSV_FILES/MT5_5M_{SYMBOL}_Exchange_Rate_Dataset.csv') 
df = apply_features(data)
df = create_targets(df)
df.dropna(inplace=True)

all_target = ['T_5M', 'T_10M', 'T_15M', 'T_20M', 'T_30M']
train_df = df.copy()
X_train = train_df.drop(columns=all_target)

# 2. Boucle d'entraînement pour chaque Timeframe
for target in all_target:
    print(f'🚀 Entraînement CatBoost pour la cible : {target}...')
    y_train = train_df[target]
    
    # Premier passage pour identifier les meilleures features
    model = CatBoostClassifier(
        iterations=200,
        random_seed=42,
        logging_level='Silent',
        allow_writing_files=False
    )
    
    model.fit(X_train, y_train)
    importance = model.get_feature_importance()
    feature_names = X_train.columns.to_list()
    sort_indx = np.argsort(importance)[::-1]

    # On garde les 76 meilleures features
    top_76_indx = sort_indx[:76]
    top76_features = [feature_names[i] for i in top_76_indx]
    print(f'✅ TOP 76 FEATURES sélectionnées pour {target}.')

    # Réentraînement final avec les meilleures features uniquement
    X_train_top76 = X_train[top76_features]
    model_top76 = CatBoostClassifier(
        iterations=200,
        random_seed=42,
        logging_level='Silent',
        allow_writing_files=False
    )
    model_top76.fit(X_train_top76, y_train)

    # Sauvegarde du modèle (bundle)
    # Note: On garde le nom "lgbm" dans le fichier pour ne pas avoir à modifier les autres scripts
    joblib.dump({"model": model_top76, "features": top76_features}, f"ALL_MODELS/{SYMBOL}_lgbm_{target}.pkl")
    print(f'💾 Modèle enregistré : ALL_MODELS/{SYMBOL}_lgbm_{target}.pkl')
    print('-------------------------------------')

print("✨ Entraînement de tous les modèles terminé avec succès (Moteur: CatBoost).")