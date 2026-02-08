import sys
print(f"Python: {sys.version}")

def check_import(name):
    try:
        __import__(name)
        print(f"[OK] {name}")
    except ImportError:
        print(f"[FAIL] {name} is MISSING")
    except Exception as e:
        print(f"[ERROR] {name}: {e}")

check_import("cv2")
check_import("mediapipe")
check_import("numpy")
check_import("sklearn")

print("\n--- Testing Imports in Project ---")
try:
    from ai.ml_model import AdvancedAnomalyDetector
    print("[OK] ai.ml_model")
except ImportError as e:
    print(f"[FAIL] ai.ml_model Import Failed: {e}")
except Exception as e:
    print(f"[FAIL] ai.ml_model Code Error: {e}")
