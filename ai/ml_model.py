import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
import os

class AdvancedAnomalyDetector:
    def __init__(self):
        # Isolation Forest is a powerful anomaly detection algorithm 
        # using ensemble trees to isolate outliers.
        self.clf = IsolationForest(
            n_estimators=100,
            contamination=0.1, # Approx 10% expected issues (cheating)
            random_state=42
        )
        self.scaler = StandardScaler()
        self.feature_names = ["gaze_h", "gaze_v", "head_yaw", "face_count"]
        self.is_trained = False

    def _extract_features(self, metrics_list):
        """
        Convert sparse JSON metrics into a dense NumPy array for ML.
        """
        data = []
        timestamps = []
        
        for m in metrics_list:
            # We must handle missing values or errors (-1)
            # For simplicity, filter them out or impute mean (here we filter)
            if m.get("gaze_h", -1) != -1 and m.get("gaze_v", -1) != -1:
                row = [
                    m.get("gaze_h", 0.5), # Default center
                    m.get("gaze_v", 0.5), # Default center
                    m.get("head_yaw", 0.0),
                    m.get("face_count", 1)
                ]
                data.append(row)
                timestamps.append(m.get("timestamp_obj"))
                
        return np.array(data), timestamps

    def train_and_detect(self, metrics_list):
        """
        1. Standardizes Data.
        2. Fits Isolation Forest on the USER's data (Unsupervised Learning).
        3. Predicts Anomalies (-1).
        4. Explains Anomalies by looking at feature contribution.
        """
        if len(metrics_list) < 20:
            return [] # Not enough data for ML
            
        X, timestamps = self._extract_features(metrics_list)
        
        # 1. Scaling (Important for most ML models, less for RF but good practice)
        X_scaled = self.scaler.fit_transform(X)
        
        # 2. Train Model
        self.clf.fit(X_scaled)
        self.is_trained = True
        
        # 3. Predict (1 = Normal, -1 = Anomaly)
        predictions = self.clf.predict(X_scaled)
        scores = self.clf.decision_function(X_scaled) # Lower is more anomalous
        
        anomalies = []
        
        # 4. Interpret Results
        for i, pred in enumerate(predictions):
            if pred == -1: # Anomaly Detected
                # Explain WHY.
                # Heuristic: Which scaled feature is furthest from 0 (mean)?
                features = X_scaled[i]
                max_dev_idx = np.argmax(np.abs(features))
                
                # Check magnitude of deviation
                metric_name = self.feature_names[max_dev_idx]
                metric_val = X[i][max_dev_idx]
                
                # Form explanation
                anomalies.append({
                    "timestamp": timestamps[i],
                    "score": round(abs(scores[i]), 4), # Confidence
                    "reasons": [f"{metric_name} deviation (Val: {metric_val:.2f})"]
                })
                
        return anomalies

    def explain_model(self, anomalies):
        if not self.is_trained:
            return "⚠️ Model Error: Not enough data points to train (Need >20 samples)."
            
        if not anomalies:
            return "✅ ML Analysis: The Isolation Forest model detected no significant statistical outliers in your behavior."
            
        text = "⚠️ **ML Analysis (Isolation Forest)**\n"
        text += "The system trained a Random Forest ensemble on your session data to find statistical outliers.\n\n"
        text += f"**Detected {len(anomalies)} anomalous frames.**\n"
        
        return text
