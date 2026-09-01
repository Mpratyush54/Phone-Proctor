
import cv2
import numpy as np
import time
import threading

# List of restricted items (COCO class names)
# Items the user is EXPECTED to have 1 of (their own laptop/monitor)
ALLOWED_ONE = {'laptop', 'tv'}

RESTRICTED_ITEMS = {
    'cell phone': 'Cell Phone Detected',
    'laptop': 'Extra Laptop/Monitor Detected',
    'book': 'Book/Notes Detected',
    'tv': 'Extra Monitor/TV Detected',
    'remote': 'Remote Control Detected',
}

class ObjectDetector:
    def __init__(self, model_path="yolov8n.pt", conf_threshold=0.5):
        self.model = None
        self.conf_threshold = conf_threshold
        self.available = False
        
        # Try importing Ultralytics YOLO
        try:
            from ultralytics import YOLO
            print("[AI] Loading YOLOv8 Object Detector...")
            self.model = YOLO(model_path)
            self.available = True
            print("[AI] Object Detector Loaded Successfully.")
        except ImportError:
            print("[AI] Warning: 'ultralytics' library not found. Object detection disabled.")
            print("     Install via: pip install ultralytics")
        except Exception as e:
            print(f"[AI] Error loading YOLO myolov8nodel: {e}")

    def detect(self, frame):
        """
        Detects restricted items in the frame.
        Returns: 
            detections: list of strings (e.g., ["Cell Phone Detected"])
            annotated_frame: frame with bounding boxes (or None if no detections/model)
        """
        if not self.available or frame is None:
            return [], frame

        detections = []
        annotated_frame = frame.copy()
        
        try:
            results = self.model(frame, verbose=False, conf=self.conf_threshold)
            
            for result in results:
                boxes = result.boxes
                annotated_frame = result.plot()
                
                # Count instances of each restricted class
                class_counts = {}
                for box in boxes:
                    cls_id = int(box.cls[0])
                    class_name = self.model.names[cls_id]
                    
                    if class_name in RESTRICTED_ITEMS:
                        class_counts[class_name] = class_counts.get(class_name, 0) + 1
                
                # Generate alerts based on counts
                for class_name, count in class_counts.items():
                    if class_name in ALLOWED_ONE:
                        # User's own laptop/monitor is expected - only flag extras
                        if count >= 2:
                            alert_msg = RESTRICTED_ITEMS[class_name]
                            if alert_msg not in detections:
                                detections.append(alert_msg)
                    else:
                        # Zero tolerance items (phone, book, remote)
                        alert_msg = RESTRICTED_ITEMS[class_name]
                        if alert_msg not in detections:
                            detections.append(alert_msg)
                            
        except Exception as e:
            print(f"[AI] Detection Error: {e}")
            
        return detections, annotated_frame

    def close(self):
        self.model = None
        self.available = False
