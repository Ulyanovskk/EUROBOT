import os
import pandas as pd
import numpy as np
import cv2
import sys
import io
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

# Fix pour Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Configuration
BASE_PATH = "CSV_FILES/PATERN_TRADING/"
CSV_FILE = os.path.join(BASE_PATH, "Patterns.csv")
IMG_SIZE = 64
os.makedirs("VISION_MODELS", exist_ok=True)

print("--- INITIALISATION DE L'EXPERT VISION ---")

# 1. Chargement du CSV
df = pd.read_csv(CSV_FILE)
print(f"Charge : {len(df)} images referencees.")

# 2. Preparation des donnees
images = []
labels = []

# Encodage des noms de patterns en chiffres
le = LabelEncoder()
df['label_id'] = le.fit_transform(df['ClassName'])
class_names = le.classes_
print(f"Classes detectees : {class_names}")

print("Traitement des images (Resize & Normalize)...")
for idx, row in df.iterrows():
    img_path = os.path.join(BASE_PATH, row['Path'])
    if os.path.exists(img_path):
        # On lit en gris (grayscale) car la couleur n'importe pas pour les patterns
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
        images.append(img)
        labels.append(row['label_id'])

X = np.array(images).reshape(-1, IMG_SIZE, IMG_SIZE, 1) / 255.0
y = np.array(labels)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# 3. Construction du reseau de neurones (CNN)
# On attend la fin de l'installation pour l'import final de TensorFlow
import tensorflow as tf
from tensorflow.keras import layers, models

model = models.Sequential([
    layers.Conv2D(32, (3, 3), activation='relu', input_shape=(IMG_SIZE, IMG_SIZE, 1)),
    layers.MaxPooling2D((2, 2)),
    layers.Conv2D(64, (3, 3), activation='relu'),
    layers.MaxPooling2D((2, 2)),
    layers.Flatten(),
    layers.Dense(64, activation='relu'),
    layers.Dense(len(class_names), activation='softmax')
])

model.compile(optimizer='adam',
              loss='sparse_categorical_crossentropy',
              metrics=['accuracy'])

print("Entrainement du modele Vision...")
model.fit(X_train, y_train, epochs=15, validation_data=(X_test, y_test), verbose=1)

# 4. Sauvegarde
model_path = "VISION_MODELS/pattern_vision_model.keras"
model.save(model_path)
joblib.dump(le, "VISION_MODELS/label_encoder.pkl")

print(f"\n--- EXPERT VISION SAUVEGARDE : {model_path} ---")
print(f"Capacite : Reconnaissance de {len(class_names)} figures graphiques.")
