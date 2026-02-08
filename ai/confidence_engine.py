class ConfidenceEngine:
    def __init__(self):
        # Weights for different modalities
        self.w_vad = 0.4
        self.w_lip = 0.3
        self.w_gaze = 0.3
        
        # Thresholds
        self.VAD_THRESHOLD = 0.6
        self.LIP_THRESHOLD = 0.5
        self.HEAD_YAW_THRESHOLD = 25 # Degrees
        self.HEAD_PITCH_THRESHOLD = 20 # Degrees
        
        self.history = []

    def evaluate(self, vad_prob, lip_prob, head_yaw, head_pitch, face_count):
        """
        Returns:
        - status: "SAFE", "WARNING", "FLAG"
        - confidence: 0.0 to 1.0 (Probability of cheating/violation)
        - reasons: List of strings explaining the decision
        """
        score = 0.0
        reasons = []
        is_speaking = False
        is_someone_else = False
        
        # 1. Audio / Voice Logic
        if vad_prob > self.VAD_THRESHOLD:
            # Voice detected. Is it the user?
            if lip_prob > self.LIP_THRESHOLD:
                # User is speaking
                is_speaking = True
                score += 0.4 # Speaking might be okay, but suspicious
                reasons.append(f"User Speaking (Conf: {vad_prob:.2f})")
            else:
                # Voice detected but user lips not moving -> Someone else speaking
                is_someone_else = True
                score += 0.8 # Highly suspicious
                reasons.append(f"External Voice Detected (Conf: {vad_prob:.2f})")

        # 2. Head Pose Logic
        if abs(head_yaw) > self.HEAD_YAW_THRESHOLD:
            score += 0.3
            reasons.append(f"Looking Away (Yaw: {int(head_yaw)}°)")
            
        if abs(head_pitch) > self.HEAD_PITCH_THRESHOLD:
            score += 0.2
            reasons.append(f"Looking Up/Down (Pitch: {int(head_pitch)}°)")

        # 3. Multiple Faces
        if face_count > 1:
            score += 1.0 # Instant Flag
            reasons.append(f"Multiple Faces Detected ({face_count})")
        elif face_count == 0:
            score += 0.5
            reasons.append("No Face Detected")

        # Cap score
        score = min(score, 1.0)
        
        # Determine Status
        status = "SAFE"
        if score > 0.7:
            status = "FLAG"
        elif score > 0.3:
            status = "WARNING"
            
        return {
            "status": status,
            "score": score,
            "reasons": reasons,
            "metadata": {
                "vad": vad_prob,
                "lip": lip_prob,
                "is_speaking": is_speaking,
                "is_external_audio": is_someone_else
            }
        }
