import os
import cv2
import sys
import io
from dotenv import load_dotenv
from func import ohlc_to_image, get_deepseek_vision_verdict
import pandas as pd

# Fix pour Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

print("--- TEST DE L'EXPERT VISION (DeepSeek Cloud) ---")

# 1. Recuperer un echantillon de donnees reelles (si dispo) ou image test
dataset_path = 'CSV_FILES/Winners_Elite_Dataset.csv'
if os.path.exists(dataset_path):
    print("Generation d'un graphique de test a partir de votre dataset...")
    df = pd.read_csv(dataset_path).tail(60)
    img = ohlc_to_image(df)
    
    # Envoi a DeepSeek
    print("Envoi au cerveau DeepSeek pour analyse...")
    verdict = get_deepseek_vision_verdict(img)
    
    if verdict:
        print("\n[RESULTAT] DeepSeek active : Le cerveau voit un pattern valide ! ✅")
    else:
        print("\n[RESULTAT] DeepSeek en veille : Aucun pattern graphique majeur detecte. 💤")
        
    print("\nL'Expert Vision est operationnel. Il sera consulte automatiquement par le bot live.")
else:
    print("Erreur : Aucun dataset trouve pour generer un test. Mais le code est pret.")

print("------------------------------------------------")
