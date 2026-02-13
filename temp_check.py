from ai.cheat_predictor import CheatPredictor
import numpy as np

p = CheatPredictor()
if p.is_trained:
    importances = p.model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    print(f'Total features: {len(p.feature_names)}')
    print()
    print('Feature Importances (Multi-Modal):')
    print('-' * 55)
    for i in sorted_idx:
        src = 'VISION' if p.feature_names[i].startswith('v_') else ('AUDIO' if p.feature_names[i].startswith('a_') else 'EVENT ')
        bar = '#' * int(importances[i] * 50)
        print(f'  [{src}] {p.feature_names[i]:30s} {importances[i]:.4f} {bar}')
