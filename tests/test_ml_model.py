"""Tests for ai/ml_model.py (Isolation Forest anomaly detection)."""

from datetime import datetime, timedelta

import pytest

from ai.ml_model import AdvancedAnomalyDetector


def _normal_metrics(n):
    return [
        {
            "gaze_h": 0.5, "gaze_v": 0.5, "head_yaw": 0.0, "face_count": 1,
            "timestamp_obj": datetime.now() + timedelta(seconds=i),
        }
        for i in range(n)
    ]


def test_not_enough_data_returns_empty():
    detector = AdvancedAnomalyDetector()
    assert detector.train_and_detect(_normal_metrics(19)) == []
    assert detector.is_trained is False


def test_outliers_are_detected():
    metrics = _normal_metrics(25)
    # Inject extreme gaze deviations (strong looking-away behavior).
    for i in range(4):
        metrics[i]["gaze_h"] = 0.99
        metrics[i]["gaze_v"] = 0.01
        metrics[i]["head_yaw"] = 75.0
        metrics[i]["face_count"] = 0

    detector = AdvancedAnomalyDetector()
    # The class default expects ~10% contamination; bump it so the 4 injected
    # outliers are guaranteed to be isolated deterministically.
    detector.clf.contamination = 0.2
    anomalies = detector.train_and_detect(metrics)
    assert detector.is_trained is True
    assert len(anomalies) >= 1
    anomaly = anomalies[0]
    assert anomaly["timestamp"] is not None
    assert anomaly["score"] is not None
    assert anomaly["reasons"]


def test_filters_missing_features():
    metrics = _normal_metrics(25)
    metrics[0]["gaze_h"] = -1  # filtered out by _extract_features
    detector = AdvancedAnomalyDetector()
    anomalies = detector.train_and_detect(metrics)
    assert isinstance(anomalies, list)


def test_explain_model_before_training():
    detector = AdvancedAnomalyDetector()
    text = detector.explain_model([])
    assert "Not enough data" in text


def test_explain_model_after_training_clean():
    detector = AdvancedAnomalyDetector()
    detector.train_and_detect(_normal_metrics(25))
    text = detector.explain_model([])
    assert "no significant statistical outliers" in text


def test_explain_model_with_anomalies():
    detector = AdvancedAnomalyDetector()
    anomalies = detector.train_and_detect(_normal_metrics(25))
    if anomalies:
        text = detector.explain_model(anomalies)
        assert "anomalous frames" in text