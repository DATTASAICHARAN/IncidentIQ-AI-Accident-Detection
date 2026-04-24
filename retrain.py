import os
import shutil
import yaml
import glob
from ultralytics import YOLO

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RETRAINING_DATA_DIR = os.path.join(BASE_DIR, "retraining_data")
FALSE_POSITIVE_DIR = os.path.join(RETRAINING_DATA_DIR, "false_positive")
TRUE_POSITIVE_DIR = os.path.join(RETRAINING_DATA_DIR, "true_positive")

# New dataset location (YOLO expects a specific structure)
DATASET_DIR = os.path.join(BASE_DIR, "dataset_retrain")
IMAGES_DIR = os.path.join(DATASET_DIR, "images", "train")
LABELS_DIR = os.path.join(DATASET_DIR, "labels", "train")

# Model paths
ORIGINAL_MODEL = os.path.join(BASE_DIR, "accident_model_v2.pt")
RETRAINED_MODEL_NAME = "accident_model_v2_retrained" # Will be saved in runs/detect/...

# Class Names (MUST MATCH server.py)
CLASS_NAMES = {
    0: "Vehicle Collision",
    1: "Multi-car Pileup",
    2: "Hit & Run",
    3: "Pedestrian Accident",
    4: "Accident",
}

def setup_dataset():
    """
    Prepares the dataset structure for YOLO.
    - Cleans/Creates dataset_retrain/ directory.
    - Copies False Positive images to images/train.
    - Creates EMPTY label files for False Positives (background images).
    - (Future) Copies True Positive images and their labels if they exist.
    """
    print(f"[Retrain] 📂 Setting up dataset in {DATASET_DIR}...")
    
    # 1. Clean and Create Directories
    if os.path.exists(DATASET_DIR):
        shutil.rmtree(DATASET_DIR)
    
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(LABELS_DIR, exist_ok=True)

    count_fp = 0
    count_tp = 0

    # 2. Process False Positives (Background Images)
    # Background images are images with NO objects. YOLO learns from them if provided with an empty label file.
    if os.path.exists(FALSE_POSITIVE_DIR):
        for img_path in glob.glob(os.path.join(FALSE_POSITIVE_DIR, "*.*")):
            if not img_path.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')):
                continue
                
            filename = os.path.basename(img_path)
            name_no_ext = os.path.splitext(filename)[0]
            
            # Copy Image
            shutil.copy(img_path, os.path.join(IMAGES_DIR, filename))
            
            # Create Empty Label File
            label_path = os.path.join(LABELS_DIR, f"{name_no_ext}.txt")
            with open(label_path, "w") as f:
                pass # Empty file = No detections = Background image
            
            count_fp += 1

    # 3. Process True Positives (Only if labeled data exists)
    # Note: Currently the system saves raw frames. To use True Positives, 
    # you would technically need to manually label them or use the model's prediction as a weak label.
    # For now, we are focusing on False Positives (correcting errors).
    if os.path.exists(TRUE_POSITIVE_DIR):
        print("[Retrain] ℹ️  True Positive folder found. Use a labeling tool (like LabelImg) to create .txt labels for these if you want to include them.")
        # Logic to copy them would go here if label files existed.

    print(f"[Retrain] ✅ Dataset prepared: {count_fp} background images (False Positives).")
    return count_fp


def create_yaml_config():
    """Generates the data.yaml file required by YOLO."""
    yaml_content = {
        'path': DATASET_DIR,
        'train': 'images/train',
        'val': 'images/train', # Using train as val for simple retraining (ideal: separate split)
        'names': {k: v for k, v in CLASS_NAMES.items()}
    }
    
    yaml_path = os.path.join(DATASET_DIR, "data.yaml")
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_content, f, default_flow_style=False)
    
    print(f"[Retrain] 📄 Config saved to {yaml_path}")
    return yaml_path


def train_model(yaml_path):
    """Runs YOLO training."""
    print(f"[Retrain] 🚀 Starting training with {ORIGINAL_MODEL}...")
    
    # Load the model
    model = YOLO(ORIGINAL_MODEL)
    
    # Train
    # We use a low learning rate and few epochs to fine-tune without destroying previous knowledge
    model.train(
        data=yaml_path,
        epochs=10, 
        imgsz=640,
        batch=4,
        lr0=0.001, # Low learning rate for fine-tuning
        name=RETRAINED_MODEL_NAME,
        exist_ok=True # Overwrite existing run detection
    )
    
    print("[Retrain] 🎉 Training complete!")
    print(f"[Retrain] 💾 New model saved in: runs/detect/{RETRAINED_MODEL_NAME}/weights/best.pt")
    
    # Optional: Update the main model file automatically?
    # For safety, we won't overwrite the original 'accident_model_v2.pt' automatically.
    # The user should verify the new model first.
    return os.path.join(BASE_DIR, "runs", "detect", RETRAINED_MODEL_NAME, "weights", "best.pt")


if __name__ == "__main__":
    count = setup_dataset()
    if count > 0:
        config_path = create_yaml_config()
        new_model_path = train_model(config_path)
        
        print("\n" + "="*60)
        print("✅ RETRAINING SUCCESSFUL")
        print("="*60)
        print(f"1. New model is at: {new_model_path}")
        print("2. To use this model, update 'server.py' to point to this new file,")
        print("   OR rename it to 'accident_model_v3.pt' and update the path.")
    else:
        print("\n[Retrain] ⚠️  No False Positive data found to train on.")
        print("mark some detections as 'False Alarm' in the dashboard first.")
