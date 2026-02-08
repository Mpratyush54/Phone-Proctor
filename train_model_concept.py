import os
import json
import glob
from collections import Counter

DATASET_ROOT = "data/dataset"

def analyze_dataset():
    """
    Scans the data/dataset folder and mimics a training data loader.
    """
    if not os.path.exists(DATASET_ROOT):
        print("❌ Dataset folder not found. Run main.py first to generate data.")
        return

    sessions = glob.glob(os.path.join(DATASET_ROOT, "*"))
    print(f"📚 Found {len(sessions)} Training Sessions")

    total_samples = 0
    violation_samples = 0
    normal_samples = 0
    
    for session_path in sessions:
        if not os.path.isdir(session_path): continue
        
        jsonl_path = os.path.join(session_path, "events.jsonl")
        if not os.path.exists(jsonl_path): continue

        with open(jsonl_path, 'r') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    # Check if we have an image
                    img_path = record.get("image_path")
                    if img_path:
                        abs_img_path = os.path.join(session_path, img_path)
                        if os.path.exists(abs_img_path):
                            total_samples += 1
                            
                            # Label logic (Self-learning logic)
                            msg_type = record.get("type")
                            if msg_type == "VIOLATION":
                                violation_samples += 1
                            elif msg_type == "METRICS":
                                # We can use the 'is_looking_away' flag as a weak label
                                data = record.get("data", {})
                                if data.get("is_looking_away", False):
                                    violation_samples += 1
                                else:
                                    normal_samples += 1
                except:
                    pass

    print("\n🔍 Dataset Statistics:")
    print(f"   Total Labeled Images: {total_samples}")
    print(f"   Positives (Cheating): {violation_samples}")
    print(f"   Negatives (Normal):   {normal_samples}")
    
    if total_samples > 0:
        print("\n✅ Data Pipeline Ready for Training.")
        print("   To train a model: Load these images + labels into PyTorch/TensorFlow.")
    else:
        print("\n⚠️  No image data found yet. Run the main proctoring app to collect data.")

if __name__ == "__main__":
    analyze_dataset()
