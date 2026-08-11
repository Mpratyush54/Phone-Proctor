"""
Multi-Modal Sensor Fusion Engine (VISION.md Sections 6 & 7)

Fuses normalized per-modality signals (each 0..1, higher = more suspicious)
into a single violation confidence score using configurable weights, then maps
the score to a status:  SAFE / WARNING / FLAG.

Signals consumed (all optional, missing => 0):
    gaze_away    - GazeEstimator decided looking away (0/1)
    head_away    - Head pose exceeded yaw/pitch thresholds (0/1)
    phone_face   - Phone camera sees a face (head-toward-phone) (0/1)
    multi_face   - Webcam sees 2+ faces (0/1)
    no_face      - Webcam sees 0 faces (0/1)
    object       - Restricted object detected by YOLO (0/1)
    audio        - Unattended audio (PC voice w/o phone voice) anomaly (0/1)
    network      - Network integrity violation (0/1)

The engine is stateless per call (persistence/temporal rules live in the
RuleEngine / ProctorThread), so it is trivially unit-testable.
"""


class ScoreFusion:
    STATUS_SAFE = "SAFE"
    STATUS_WARNING = "WARNING"
    STATUS_FLAG = "FLAG"

    def __init__(self, thresholds=None):
        if thresholds is None:
            from rules.thresholds import Thresholds
            thresholds = Thresholds()

        default_weights = {
            "gaze_away": 0.20,
            "head_away": 0.20,
            "phone_face": 0.25,
            "multi_face": 0.15,
            "no_face": 0.05,
            "object": 0.10,
            "audio": 0.05,
            "network": 0.30,
        }
        configured = thresholds.fusion_weights()
        self.weights = {**default_weights, **(configured or {})}
        self.warning_score = thresholds.warning_score()
        self.flag_score = thresholds.flag_score()

    def fuse(self, signals):
        """
        Signals: dict of modality -> float 0..1.
        Returns: dict { score, status, reasons, contributions }
        """
        contributions = []
        score = 0.0
        reasons = []

        for key, weight in self.weights.items():
            value = float(signals.get(key, 0.0) or 0.0)
            value = max(0.0, min(1.0, value))
            if value > 0:
                contribution = value * weight
                score += contribution
                contributions.append({
                    "signal": key,
                    "value": round(value, 2),
                    "weight": weight,
                    "contribution": round(contribution, 3),
                })
                reasons.append(self._signal_to_reason(key, value))

        score = min(score, 1.0)
        status = self.STATUS_SAFE
        if score >= self.flag_score:
            status = self.STATUS_FLAG
        elif score >= self.warning_score:
            status = self.STATUS_WARNING

        # Include all activated signals (not only reason text) for reporting.
        return {
            "score": round(score, 3),
            "status": status,
            "reasons": reasons,
            "contributions": contributions,
        }

    def _signal_to_reason(self, key, value):
        labels = {
            "gaze_away": "Gaze away from screen",
            "head_away": "Head turned away",
            "phone_face": "Head toward phone detected",
            "multi_face": "Multiple faces detected",
            "no_face": "No face detected",
            "object": "Restricted object detected",
            "audio": "Unattended audio anomaly",
            "network": "Network integrity violation",
        }
        label = labels.get(key, key)
        return f"{label} (conf {value:.2f})"

    def verdict(self, status):
        return {
            ScoreFusion.STATUS_SAFE: "SAFE",
            ScoreFusion.STATUS_WARNING: "WARNING",
            ScoreFusion.STATUS_FLAG: "FLAG",
        }.get(status, status)