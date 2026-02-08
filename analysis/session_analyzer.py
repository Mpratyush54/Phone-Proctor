import json
import os
from datetime import datetime
from ai.ml_model import AdvancedAnomalyDetector

class SessionAnalyzer:
    def __init__(self, session_dir):
        self.session_dir = session_dir
        self.log_file = os.path.join(session_dir, "events.jsonl")
        self.report_file = os.path.join(session_dir, "FINAL_REPORT.md")
        self.model = AdvancedAnomalyDetector()

    def analyze(self):
        """
        Parses the event log and generates a cheating confidence score and explanation using Scikit-Learn.
        """
        if not os.path.exists(self.log_file):
            print("❌ No logs found for this session.")
            return

        events = []
        metrics_list = []
        
        with open(self.log_file, 'r') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    events.append(record)
                    
                    if record["type"] == "METRICS":
                        data = record["data"]
                        # Inject timestamp for the model to use later
                        data["timestamp_obj"] = datetime.fromisoformat(record["timestamp"])
                        metrics_list.append(data)
                except json.JSONDecodeError:
                    print(f"⚠️ Skipping malformed JSON line in {self.log_file}: {line.strip()}")
                    continue
                except KeyError as e:
                    print(f"⚠️ Skipping record due to missing key '{e}' in {self.log_file}: {line.strip()}")
                    continue
                except ValueError as e: # For datetime.fromisoformat errors
                    print(f"⚠️ Skipping record due to data format error '{e}' in {self.log_file}: {line.strip()}")
                    continue

        # ---------------------------
        # Real ML Pipeline (Isolation Forest)
        # ---------------------------
        # 1. Train & Detect in one pass (Unsupervised)
        anomalies = self.model.train_and_detect(metrics_list)
        
        # 2. Explain
        ai_explanation = self.model.explain_model(anomalies)

        # ---------------------------
        # Hard Rule Aggregation (Forensics)
        # ---------------------------
        stats = {
            "focus_lost_count": 0,
            "looking_away_count": 0,
            "multi_face_count": 0,
            "network_violation": 0,
            "tampering_detected": 0,
            "duration_seconds": 0
        }

        timeline = []
        start_time = None
        end_time = None

        for e in events:
            ts = datetime.fromisoformat(e["timestamp"])
            if start_time is None: start_time = ts
            end_time = ts

            etype = e.get("type")
            data = e.get("data", "")
            
            if etype == "VIOLATION":
                desc = str(data)
                timeline.append(f"- **{ts.strftime('%H:%M:%S')}**: {desc}")
                
                if "Focus Lost" in desc:
                    stats["focus_lost_count"] += 1
                elif "Looking Away" in desc:
                    stats["looking_away_count"] += 1
                elif "Multiple Faces" in desc:
                    stats["multi_face_count"] += 1
                elif "Network" in desc or "Traffic" in desc:
                    stats["tampering_detected"] += 1 # Treating high network anomalies as tampering
                elif "Tampering" in desc:
                    stats["tampering_detected"] += 1

        if start_time and end_time:
            stats["duration_seconds"] = (end_time - start_time).total_seconds()

        # Combine ML Anomaly Count + Hard Rule Violations
        score = 0
        explanations = []
        
        # Add ML Findings
        explanations.append(ai_explanation)
        if anomalies:
            score += min(len(anomalies) * 10, 50) # Cap AI contribution at 50%

        # Add Critical Hard Failures (OS Level)
        if stats["tampering_detected"] > 0:
            score += 100
            explanations.append("🚨 **CRITICAL**: System/Camera Tampering Detected.")

        if stats["focus_lost_count"] > 2:
            score += 40
            explanations.append(f"⚠️ **Focus**: Candidate left the exam window {stats['focus_lost_count']} times.")
            
        score = min(score, 100)

        # Verdict
        if score >= 60:
            verdict = "CHEAT DETECTED"
            color = "🔴"
        elif score >= 30:
            verdict = "SUSPICIOUS"
            color = "🟡"
        else:
            verdict = "CLEAN"
            color = "🟢"

        self._write_report(stats, score, verdict, color, explanations, timeline, anomalies)

    def _write_report(self, stats, score, verdict, color, explanations, timeline, anomalies):
        
        # Format ML anomalies for timeline
        ai_timeline = []
        for a in anomalies:
            if a.get("timestamp"):
                ts_str = a["timestamp"].strftime('%H:%M:%S')
                reasons = ", ".join(a["reasons"])
                ai_timeline.append(f"- **{ts_str}** (ML Anomaly): {reasons}")
            
        full_timeline = sorted(timeline + ai_timeline)

        content = f"""# 📊 Final Proctoring Report
**Session Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Verdict:** {color} **{verdict}** (Confidence: {score}/100)

## 🧠 AI Analysis (Isolation Forest Model)
{chr(10).join(explanations)}

## 🔢 Statistics
- **Duration:** {int(stats['duration_seconds'] // 60)} min {int(stats['duration_seconds'] % 60)} sec
- **ML Anomalies Detected:** {len(anomalies)}
- **Focus Lost Events:** {stats['focus_lost_count']}
- **Hard Rule Violations:** {len(timeline)}

## 🕒 Forensic Timeline
{chr(10).join(full_timeline)}

---
*Generated by Advanced ML Proctoring Engine*
"""
        with open(self.report_file, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"\n[REPORT] Generated: {self.report_file}")
        print(f"[REPORT] Verdict: {verdict} ({score}%)")
