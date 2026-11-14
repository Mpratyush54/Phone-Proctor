import json
import os
from datetime import datetime

from analysis.observable_summary import ObservableSessionSummary


class SessionAnalyzer(ObservableSessionSummary):
    """Backward-compatible wrapper. Reports contain evidence only (A4)."""

    def analyze(self):
        return super().analyze()
