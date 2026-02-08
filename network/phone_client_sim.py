import time
import socket
import json
import random

SERVER_IP = "127.0.0.1"
SERVER_PORT = 5000

def run_client():
    """
    Simulates the Phone Client connecting to the Laptop.
    """
    print(f"[PHONE] Connecting to {SERVER_IP}:{SERVER_PORT}...")
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((SERVER_IP, SERVER_PORT))
        print("[PHONE] Connected!")
        
        while True:
            # 1. Simulate Telemetry (Battery, Network Status)
            telemetry = {
                "type": "TELEMETRY",
                "data": {
                    "battery": random.randint(20, 100),
                    "network": "WiFi-Hotspot-X",
                    "device_tilted": False
                }
            }
            
            # 2. Simulate Alert randomly (e.g. Phone moved)
            if random.random() < 0.1: # 10% chance
                 telemetry = {
                    "type": "ALERT",
                    "data": "PHONE_MOVED_DETECTED"
                 }
                 print("[PHONE] 🚨 Sending Alert: Phone Moved!")

            # Send as JSON Line
            msg = json.dumps(telemetry) + "\n"
            s.sendall(msg.encode('utf-8'))
            print(f"[PHONE] Sent: {telemetry['type']}")
            
            time.sleep(2)
            
    except ConnectionRefusedError:
        print("[PHONE] ❌ Could not connect. Is main.py running?")
    except KeyboardInterrupt:
        print("[PHONE] Stopping...")
    finally:
        s.close()

if __name__ == "__main__":
    run_client()
