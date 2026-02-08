import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import cv2
import os
import numpy as np
import glob
import sys
# Add parent directory to path to allow imports from ai package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.lip_reading import LipReadingCNNLSTM

# Configuration
DATA_DIR = "data/dataset_lips"
MODEL_PATH = "data/models/lip_cnn_lstm.pth"
BATCH_SIZE = 8
EPOCHS = 20
SEQ_LEN = 30
IMG_SIZE = 64

class LipDataset(Dataset):
    def __init__(self, root_dir, transform=None):
        """
        Expects directory structure:
        root_dir/
          speaking/
            seq_001/ (contains 30 frames 1.jpg, 2.jpg...)
            seq_002/
          silent/
            seq_001/
            ...
        """
        self.root_dir = root_dir
        self.samples = []
        
        # Load Speaking Samples (Label 1)
        speak_dir = os.path.join(root_dir, "speaking")
        if os.path.exists(speak_dir):
            for seq_name in os.listdir(speak_dir):
                seq_path = os.path.join(speak_dir, seq_name)
                if os.path.isdir(seq_path):
                    self.samples.append((seq_path, 1.0))

        # Load Silent Samples (Label 0)
        silent_dir = os.path.join(root_dir, "silent")
        if os.path.exists(silent_dir):
            for seq_name in os.listdir(silent_dir):
                seq_path = os.path.join(silent_dir, seq_name)
                if os.path.isdir(seq_path):
                    self.samples.append((seq_path, 0.0))
                    
        print(f"[INFO] Found {len(self.samples)} samples.")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        seq_path, label = self.samples[idx]
        frames = []
        
        # Read frames (sorted)
        img_files = sorted(glob.glob(os.path.join(seq_path, "*.jpg")))
        
        # Handle length mismatch (pad or truncate)
        # Ideally, we expect exactly SEQ_LEN frames
        for i in range(SEQ_LEN):
            if i < len(img_files):
                img = cv2.imread(img_files[i], cv2.IMREAD_GRAYSCALE)
                if img is None:
                    # Black frame if error
                    img = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.uint8)
                else:
                    img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
            else:
                 # Pad with zeros
                 img = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.uint8)
            
            frames.append(img)
            
        # Convert to Tensor (Seq, 1, H, W)
        # Normalize 0-1
        data = np.array(frames, dtype=np.float32) / 255.0
        data = np.expand_dims(data, axis=1) # (30, 1, 64, 64)
        
        return torch.tensor(data), torch.tensor([label], dtype=torch.float32)

def train():
    if not os.path.exists(DATA_DIR):
        print(f"[ERROR] Data directory {DATA_DIR} not found.")
        print("Please organize your dataset as:")
        print("  data/dataset_lips/speaking/seq_X/...")
        print("  data/dataset_lips/silent/seq_Y/...")
        return

    # Prepare Data
    dataset = LipDataset(DATA_DIR)
    if len(dataset) == 0:
        print("[ERROR] No data found.")
        return
        
    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)
    
    # Model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] Training on {device}")
    
    model = LipReadingCNNLSTM().to(device)
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.BCELoss()
    
    # Loop
    model.train()
    for epoch in range(EPOCHS):
        total_loss = 0
        correct = 0
        total = 0
        
        for X, y in dataloader:
            X, y = X.to(device), y.to(device)
            
            optimizer.zero_grad()
            output = model(X)
            
            loss = criterion(output, y)
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
            
            # Accuracy
            preds = (output > 0.5).float()
            correct += (preds == y).sum().item()
            total += y.size(0)
            
        print(f"Epoch {epoch+1}/{EPOCHS} | Loss: {total_loss/len(dataloader):.4f} | Acc: {correct/total:.2f}")

    # Save
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    print(f"[INFO] Model saved to {MODEL_PATH}")

if __name__ == "__main__":
    train()
