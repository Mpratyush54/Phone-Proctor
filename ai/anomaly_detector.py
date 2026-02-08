import numpy as np
import json

class AnomalyModel:
    def __init__(self):
        self.stats = {}
        self.thresholds = {}

    def training_step(self, metrics_list):
        """
        'Learns on itself' by calculating the baseline behavior 
        of this specific user during this specific session.
        Assumes the majority of the session is 'Normal'.
        """
        if not metrics_list:
            return

        # Extract features
        # We focus on continuous variables that fluctuate
        feature_keys = ["gaze_h", "gaze_v", "head_yaw", "face_count"]
        
        data_matrix = {k: [] for k in feature_keys}
        
        for m in metrics_list:
            for k in feature_keys:
                if k in m:
                    val = m[k]
                    # Filter invalid/error codes (-1)
                    if val != -1:
                        data_matrix[k].append(val)

        # Calculate Statistics (Mean, Std Dev)
        for k, values in data_matrix.items():
            if not values:
                continue
            
            arr = np.array(values)
            mean = np.mean(arr)
            std = np.std(arr)
            
            self.stats[k] = {
                "mean": mean,
                "std": std
            }
            
            # Set dynamic thresholds (e.g., 3 Sigma outlier rule)
            # This adapts to how "jittery" the user naturally is.
            self.thresholds[k] = 3.0 * std
            
            # print(f"[AI] Learned Baseline for {k}: Mean={mean:.2f}, Std={std:.2f}")

    def detect_anomalies(self, metrics_list):
        """
        Re-scans the session to find deviations from the learned baseline.
        Returns: List of anomalies with explanations.
        """
        anomalies = []
        
        for idx, m in enumerate(metrics_list):
            timestamp = m.get("timestamp_obj") # Passed during preprocessing
            
            violation_score = 0
            reasons = []

            # Check Face Count (Absolute Rule + Statistical)
            fc = m.get("face_count", 0)
            if fc != 1:
                violation_score += 1.0
                reasons.append(f"Face Count Abnormal: {fc}")

            # Check Gaze/Head (Statistical Z-Score)
            for k in ["gaze_h", "gaze_v", "head_yaw"]:
                if k in self.stats and k in m:
                    val = m[k]
                    if val == -1: continue
                    
                    mean = self.stats[k]["mean"]
                    limit = self.thresholds[k] # 3 sigma
                    
                    # If very low movement, std might be near 0
                    if limit < 0.05: limit = 0.05 
                    
                    diff = abs(val - mean)
                    if diff > limit:
                        severity = diff / limit
                        violation_score += severity * 0.5 # Weight
                        reasons.append(f"{k} Deviation ({diff:.2f} > limit {limit:.2f})")

            # Decision
            if violation_score > 1.0:
                anomalies.append({
                    "timestamp": timestamp,
                    "score": violation_score,
                    "reasons": reasons
                })
        
        return anomalies

    def explain(self, anomalies):
        """
        Generates a natural language summary of the findings.
        """
        if not anomalies:
            return "✅ Model Analysis: Behavior consistent with learned baseline. No cheating detected."
        
        explanation = "⚠️ **Model Analysis: Behavior Patterns Detected**\n"
        explanation += "The model learned your natural posture and gaze baseline. Deviations found:\n"
        
        # Group by type
        reason_counts = {}
        for a in anomalies:
            top_reason = a["reasons"][0]
            # Simplify reason text for grouping
            key = top_reason.split(":")[0].split("(")[0].strip()
            reason_counts[key] = reason_counts.get(key, 0) + 1
            
        for r, count in reason_counts.items():
            explanation += f"- **{r}**: Significant deviation detected {count} times.\n"
            
        return explanation
