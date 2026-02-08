import torch
import torch.nn as nn
import numpy as np
import cv2
import os

class LipReadingLSTM(nn.Module):
    """
    Original geometric LSTM. kept for reference or legacy weights.
    """
    def __init__(self, input_size=3, hidden_size=64, num_layers=2):
        super(LipReadingLSTM, self).__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        _, (h_n, _) = self.lstm(x)
        out = self.fc(h_n[-1])
        return self.sigmoid(out)

class LipReadingCNNLSTM(nn.Module):
    """
    End-to-End model: CNN (Mouth Features) -> LSTM (Temporal) -> FC (Decision)
    Input: (Batch, Sequence_Len, Channels, Height, Width)
    Example: (B, 30, 1, 64, 64) for Grayscale mouth crops
    """
    def __init__(self, hidden_size=128, num_layers=2):
        super(LipReadingCNNLSTM, self).__init__()
        
        # 1. CNN Encoder (Spatial Features per frame)
        # Input: (B * Seq, 1, 64, 64)
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2, 2), # -> 32x32

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2, 2), # -> 16x16

            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2, 2), # -> 8x8
            
            nn.Flatten() # -> 128 * 8 * 8 = 8192
        )
        
        self.fc_cnn = nn.Linear(8192, 256) # Reduce to manage LSTM size
        
        # 2. LSTM (Temporal patterns)
        self.lstm = nn.LSTM(input_size=256, 
                            hidden_size=hidden_size, 
                            num_layers=num_layers, 
                            batch_first=True, 
                            dropout=0.3)
        
        # 3. Classifier
        self.fc = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        # x: (Batch, Seq_Len, C, H, W)
        batch_size, seq_len, c, h, w = x.size()
        
        # Merge Batch and Seq for CNN
        x = x.view(batch_size * seq_len, c, h, w)
        
        # Extract features
        features = self.cnn(x)
        features = self.fc_cnn(features) # (B*S, 256)
        
        # Reshape for LSTM: (Batch, Seq_Len, Features)
        features = features.view(batch_size, seq_len, -1)
        
        # LSTM
        self.lstm.flatten_parameters()
        lstm_out, _ = self.lstm(features)
        
        # Take last time step
        final_out = lstm_out[:, -1, :]
        
        # Classify
        out = self.fc(final_out)
        return self.sigmoid(out)

class LipFeatureExtractor:
    def __init__(self, use_cnn=True):
        self.use_cnn = use_cnn
        
        # Landmarks for ROI extraction
        self.ROI_POINTS = [
            61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, # Outer lip loop (approx)
            61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291   # Or specific bounds
        ]
        
        self.frame_buffer = [] # Stores (H, W) arrays
        self.mar_history = []  # Stores scalar MAR values
        self.MAX_SEQ_LEN = 30
        self.IMG_SIZE = 64 # Input size for CNN
        
        # Load Model
        self.model = LipReadingCNNLSTM()
        self.model_path = "data/models/lip_cnn_lstm.pth"
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        self.has_weights = False
        if os.path.exists(self.model_path):
            try:
                self.model.load_state_dict(torch.load(self.model_path, map_location=self.device))
                self.model.to(self.device)
                self.model.eval()
                self.has_weights = True
                print(f"[INFO] Loaded CNN+LSTM Lip Model from {self.model_path}")
            except Exception as e:
                print(f"[WARN] Failed to load lip model: {e}")
        else:
            print("[INFO] No trained lip model found. Using heuristic fallback.")

    def extract_mouth_roi(self, frame, landmarks):
        """
        Extracts 64x64 Grayscale ROI of the mouth.
        """
        h_frame, w_frame, _ = frame.shape
        
        # Get bounding box from landmarks
        xs = [int(landmarks[i][0]) for i in range(len(landmarks)) if i in [61, 291, 13, 14]] # Left, Right, Top, Bottom
        ys = [int(landmarks[i][1]) for i in range(len(landmarks)) if i in [61, 291, 13, 14]]
        
        if not xs or not ys:
            return None
            
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        
        # Add padding
        pad_x = int((x_max - x_min) * 0.5)
        pad_y = int((y_max - y_min) * 0.5)
        
        x_min = max(0, x_min - pad_x)
        x_max = min(w_frame, x_max + pad_x)
        y_min = max(0, y_min - pad_y)
        y_max = min(h_frame, y_max + pad_y)
        
        if x_max - x_min < 10 or y_max - y_min < 10:
            return None
            
        roi = frame[y_min:y_max, x_min:x_max]
        
        # Preprocess: Grayscale -> Resize -> Normalize
        try:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            roi_resized = cv2.resize(roi_gray, (self.IMG_SIZE, self.IMG_SIZE))
            return roi_resized
        except Exception:
            return None

    def process(self, frame, landmarks):
        """
        Updates buffer and returns prediction (Probability 0.0-1.0)
        """
        roi = self.extract_mouth_roi(frame, landmarks)
        if roi is None:
            return 0.0, 0.0 # Prob, MAR (Compatibility)
            
        # Store for CNN
        self.frame_buffer.append(roi)
        if len(self.frame_buffer) > self.MAX_SEQ_LEN:
            self.frame_buffer.pop(0)
            
        # Also compute MAR for Heuristic Fallback
        mar = self._get_mar_heuristic(landmarks)
        
        if self.has_weights and len(self.frame_buffer) == self.MAX_SEQ_LEN:
            # Run CNN+LSTM inference
            prob = self._predict() 
            return prob, mar
        else:
            # Fallback: Variance Validation
            self.mar_history.append(mar)
            if len(self.mar_history) > self.MAX_SEQ_LEN:
                self.mar_history.pop(0)

            if len(self.mar_history) < 5:
                return 0.0, mar
            
            variance = np.var(self.mar_history)
            # Threshold matches previous file
            heuristic_prob = 1.0 if variance > 0.002 else 0.0
            return heuristic_prob, mar

    def _predict(self):
        # Prepare Tensor with shape (Batch=1, Seq=30, Channel=1, H=64, W=64)
        # Check current buffer size
        if len(self.frame_buffer) < self.MAX_SEQ_LEN:
            return 0.0

        # Convert list of images to numpy array
        # images are grayscale (64, 64) -> add channel dim
        data = np.array(self.frame_buffer, dtype=np.float32) / 255.0 # (30, 64, 64)
        tensor = torch.tensor(data).unsqueeze(0).unsqueeze(2) # (1, 30, 1, 64, 64)
        
        if torch.cuda.is_available():
            tensor = tensor.cuda()
            
        with torch.no_grad():
            output = self.model(tensor)
            prob = output.item()
            
        return prob

    def _get_mar_heuristic(self, landmarks):
        # MediaPipe indices
        UPPER_LIP_TOP = 13
        LOWER_LIP_BOTTOM = 14
        LIP_LEFT = 61
        LIP_RIGHT = 291 

        try:
             # Ensure landmarks is list of tuples (x, y)
             # or list of objects. Main.py passes list of (x,y)
            p1 = np.array(landmarks[UPPER_LIP_TOP])
            p2 = np.array(landmarks[LOWER_LIP_BOTTOM])
            p3 = np.array(landmarks[LIP_LEFT])
            p4 = np.array(landmarks[LIP_RIGHT])
            
            height = np.linalg.norm(p1 - p2)
            width = np.linalg.norm(p3 - p4)
            return height / width if width > 0 else 0
        except Exception:
            return 0
    
    def heuristic_is_speaking(self):
        # Check variance of last N MARs? 
        # For compatibility with main.py, we might rely on the probability returned by process()
        return False # Deprecated, use process() return
