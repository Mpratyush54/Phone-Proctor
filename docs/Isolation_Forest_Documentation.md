# Isolation Forest — Complete Technical Documentation
### Author: Pratyush Mishra
### Application: Multi-Modal Cheating Detection in Phone-Proctor

---

## Table of Contents
1. [Why Unsupervised Learning?](#1-why-unsupervised-learning)
2. [What is Isolation Forest?](#2-what-is-isolation-forest)
3. [Core Intuition](#3-core-intuition)
4. [The Mathematics](#4-the-mathematics)
5. [Algorithm Step-by-Step](#5-algorithm-step-by-step)
6. [Anomaly Score Calculation](#6-anomaly-score-calculation)
7. [Hyperparameters Explained](#7-hyperparameters-explained)
8. [Multi-Modal Feature Pipeline](#8-multi-modal-feature-pipeline)
9. [How Our Model Uses It](#9-how-our-model-uses-it)
10. [Comparison with Other Methods](#10-comparison-with-other-methods)
11. [Limitations & Mitigations](#11-limitations--mitigations)
12. [References](#12-references)

---

## 1. Why Unsupervised Learning?

In a proctoring system, we face a fundamental problem:

> **We don't have labeled data telling us "this session was cheating" vs "this session was clean."**

Traditional supervised learning (like logistic regression, neural networks) needs thousands of labeled examples:
```
Session_001  →  CHEATING     (label)
Session_002  →  NOT_CHEATING (label)
Session_003  →  CHEATING     (label)
...
```

We don't have these reliable labels. What we DO have is **raw behavioral data** — gaze patterns, head movements, focus switches, face images, audio clips. We need an algorithm that can learn what "normal" looks like **without being told** and then flag anything that deviates.

This is exactly what **Unsupervised Anomaly Detection** does.

### Supervised vs Unsupervised

| Aspect | Supervised | Unsupervised (Our Approach) |
|--------|-----------|---------------------------|
| Labels needed? | Yes (thousands) | **No** |
| Learns from | Labeled examples | Data structure itself |
| Detects | Known patterns | **Unknown anomalies** |
| Adapts to new cheating? | No (needs retraining) | **Yes (automatically)** |
| Risk of overfitting labels | High | Low |

---

## 2. What is Isolation Forest?

**Isolation Forest (iForest)** is an unsupervised anomaly detection algorithm published by Fei Tony Liu, Kai Ming Ting, and Zhi-Hua Zhou in 2008.

Unlike most anomaly detection methods that try to build a profile of "normal" behavior first, Isolation Forest takes the opposite approach:

> **It directly isolates anomalies instead of profiling normal behavior.**

The key insight is:

> **Anomalies are few and different. They are easier to isolate (separate from the rest) than normal points.**

---

## 3. Core Intuition

Imagine you have a dataset of exam sessions plotted in feature space. Most sessions cluster together (normal behavior), but a few are scattered far away (suspicious behavior).

### The Isolation Game

Pick a random feature (e.g., `focus_rate`) and pick a random split value between min and max. This divides all sessions into two groups. Repeat recursively until every session is alone ("isolated").

```
                    All 97 Sessions
                    /              \
            focus_rate < 5.2    focus_rate >= 5.2
              /       \              |
        yaw < 15   yaw >= 15    [Session X] ← ISOLATED in 2 splits!
         /    \       ...
       ...    ...
              ...
     [Session Y] ← ISOLATED in 8 splits (deep in the tree)
```

**Key observation:**
- **Session X** (anomaly) was isolated in just **2 splits** — it's far from the crowd
- **Session Y** (normal) took **8 splits** — it's buried deep in the cluster

> **Anomalies require fewer random splits to isolate = shorter path length in the tree.**

This is the entire foundation of Isolation Forest.

---

## 4. The Mathematics

### 4.1 Isolation Tree (iTree)

An Isolation Tree is a binary tree built by:

1. **Randomly select** a feature `q` from the feature set `Q = {q₁, q₂, ..., q_d}`
2. **Randomly select** a split value `p` between `min(q)` and `max(q)` of the current data
3. **Partition** data into left child (values < p) and right child (values ≥ p)
4. **Recurse** until:
   - The node has only 1 sample (fully isolated), OR
   - The tree reaches maximum height `l = ⌈log₂(n)⌉`

Formally, for a dataset `X = {x₁, x₂, ..., xₙ}` with `d` features:

```
BuildiTree(X, current_height, height_limit):
    if |X| ≤ 1  OR  current_height ≥ height_limit:
        return LeafNode(size = |X|)
    
    q ← randomly select feature from {1, 2, ..., d}
    p ← random uniform value in [min(X_q), max(X_q)]
    
    X_left  ← {x ∈ X : x_q < p}
    X_right ← {x ∈ X : x_q ≥ p}
    
    return InternalNode(
        left  = BuildiTree(X_left,  current_height + 1, height_limit),
        right = BuildiTree(X_right, current_height + 1, height_limit),
        split_feature = q,
        split_value = p
    )
```

### 4.2 Path Length h(x)

For a data point `x`, the **path length** `h(x)` is the number of edges traversed from the root to the leaf node where `x` ends up.

- **Short path** → point was easily isolated → likely anomaly
- **Long path** → point was hard to isolate → likely normal

### 4.3 The Height Limit

The height limit `l` is set to:

```
l = ⌈log₂(ψ)⌉
```

where `ψ` is the sub-sampling size (number of samples used per tree). This is because:
- Average path length of a balanced Binary Search Tree with `ψ` samples = O(log ψ)
- We don't need to go deeper because we're only interested in **short** paths (anomalies)
- This makes the algorithm extremely efficient: **O(n log ψ)** instead of O(n²)

### 4.4 Isolation Forest (Ensemble)

A single tree is noisy. We build an **ensemble** of `t` trees, each trained on a random sub-sample of the data:

```
BuildiForest(X, t, ψ):
    Forest ← {}
    for i = 1 to t:
        X_sample ← randomly sample ψ points from X (without replacement)
        Tree_i ← BuildiTree(X_sample, current_height=0, height_limit=⌈log₂(ψ)⌉)
        Forest ← Forest ∪ {Tree_i}
    return Forest
```

In our implementation:
- `t = 200` (number of trees / `n_estimators`)
- `ψ = 256` (default sub-sample size, or len(X) if smaller)

### 4.5 Average Path Length E[h(x)]

For a point `x`, we compute the **average path length** across all trees:

```
E[h(x)] = (1/t) × Σᵢ hᵢ(x)
```

where `hᵢ(x)` is the path length of `x` in tree `i`.

---

## 5. Algorithm Step-by-Step

### Training Phase (Our Pipeline Step 7)

```
Input: Feature matrix X (88 sessions × 45 features)

1. STANDARDIZE features (zero mean, unit variance)
   X_scaled = (X - μ) / σ
   
2. For each tree i = 1 to 200:
   a. Draw random sub-sample Xᵢ from X_scaled
   b. Build isolation tree:
      - Pick random feature (e.g., "v_pitch_mean")
      - Pick random split (e.g., 0.35)
      - Recursively partition until isolated
   c. Store tree in forest

3. Forest is ready — no labels were used!
```

### Prediction Phase

```
Input: New session feature vector x (1 × 45)

1. Standardize x using stored μ, σ from training
2. Pass x through all 200 trees
3. Record path length in each tree
4. Compute average path length E[h(x)]
5. Compute anomaly score s(x)
6. Convert to cheat probability (0-100%)
```

---

## 6. Anomaly Score Calculation

### 6.1 The c(n) Normalization Factor

To compare path lengths across different sample sizes, we need a baseline. The expected path length of an **unsuccessful search** in a Binary Search Tree (BST) with `n` nodes is:

```
c(n) = 2H(n-1) - 2(n-1)/n
```

where `H(k)` is the harmonic number:

```
H(k) = ln(k) + γ    (γ = 0.5772... is the Euler-Mascheroni constant)
```

This `c(n)` represents the **average path length** we'd expect if the data were completely uniform (no anomalies).

For our dataset (n = 88):
```
c(88) = 2 × H(87) - 2(87)/88
      = 2 × (ln(87) + 0.5772) - 1.977
      = 2 × (4.4659 + 0.5772) - 1.977
      = 2 × 5.0431 - 1.977
      = 10.086 - 1.977
      = 8.109
```

So a "normal" point should have an average path length around **8.1**.

### 6.2 The Anomaly Score s(x, n)

The final anomaly score is:

```
s(x, n) = 2^(-E[h(x)] / c(n))
```

This maps the average path length to a score between 0 and 1:

| E[h(x)] | Compared to c(n) | s(x, n) | Interpretation |
|----------|------------------|---------|----------------|
| **≪ c(n)** | Much shorter | **→ 1** | **Definite anomaly** |
| **≈ c(n)** | Similar | **→ 0.5** | Uncertain |
| **≫ c(n)** | Much longer | **→ 0** | Definitely normal |

### 6.3 Score Interpretation

```
s(x) close to 1.0  →  ANOMALY (cheating suspected)
s(x) close to 0.5  →  UNCERTAIN (borderline behavior)
s(x) close to 0.0  →  NORMAL (legitimate behavior)
```

### 6.4 Our Conversion to Cheat Probability

We convert the raw anomaly score to a percentage:

```python
# decision_function returns: higher = more normal, lower = more anomalous
raw_scores = model.decision_function(X_scaled)

# Normalize to [0, 100] where 100 = definitely cheating
score_min, score_max = raw_scores.min(), raw_scores.max()
cheat_prob = (1.0 - (raw_score - score_min) / (score_max - score_min)) × 100
```

---

## 7. Hyperparameters Explained

### Our Configuration

```python
IsolationForest(
    n_estimators=200,      # Number of trees
    contamination=0.15,    # Expected anomaly ratio
    max_features=0.8,      # Feature sampling per tree
    random_state=42,       # Reproducibility
    n_jobs=-1,             # Parallel processing
)
```

### Detailed Explanation

| Parameter | Value | What It Does | Why This Value |
|-----------|-------|-------------|---------------|
| `n_estimators` | 200 | Number of isolation trees in the ensemble | More trees = more stable scores. 200 is a good balance between accuracy and speed |
| `contamination` | 0.15 | Expected proportion of anomalies in the data | We expect ~15% of sessions to show suspicious behavior. This sets the decision boundary |
| `max_features` | 0.8 | Fraction of features each tree sees | Each tree uses 80% of features (36 out of 45). This adds randomness and prevents overfitting to any single feature |
| `random_state` | 42 | Random seed | Ensures reproducible results across runs |
| `n_jobs` | -1 | Number of CPU cores | -1 = use all available cores for parallel tree building |

### Effect of Contamination

```
contamination = 0.05  →  Very conservative: only 5% flagged as anomalies
contamination = 0.15  →  Our setting: 15% flagged (moderate sensitivity)
contamination = 0.30  →  Aggressive: 30% flagged (many false positives)
```

### Feature Sub-sampling Math

With `max_features = 0.8` and 45 total features:
```
Features per tree = ⌊0.8 × 45⌋ = 36 features

Each tree sees a DIFFERENT random subset of 36 features.
This ensemble diversity is what makes the forest robust.
```

---

## 8. Multi-Modal Feature Pipeline

Our model doesn't just use one data source — it fuses **three modalities**:

### 8.1 Event Log Features (20 features)

Extracted from the `events.jsonl` files:

| Feature | Formula | What It Captures |
|---------|---------|-----------------|
| `gaze_rate` | gaze_violations / duration_min | How often eyes leave screen |
| `focus_rate` | focus_lost_events / duration_min | App/window switching frequency |
| `head_rate` | head_violations / duration_min | Physical head turning |
| `total_violations_per_min` | all_events / duration_min | Overall violation intensity |
| `gaze_ratio` | gaze_events / total_events | Proportion of gaze violations |
| `focus_ratio` | focus_events / total_events | Proportion of focus violations |
| `head_ratio` | head_events / total_events | Proportion of head violations |
| `object_count` | count(phone, book, etc.) | Forbidden objects detected |
| `face_anomaly_count` | count(no_face OR multi_face) | Face detection anomalies |
| `audio_count` | count(audio_events) | Audio anomaly events |
| `yaw_mean` | mean(\|yaw\|) | Average head horizontal rotation |
| `yaw_max` | max(\|yaw\|) | Maximum head horizontal rotation |
| `yaw_std` | std(\|yaw\|) | Variability of head rotation |
| `pitch_mean` | mean(\|pitch\|) | Average head vertical tilt |
| `pitch_max` | max(\|pitch\|) | Maximum head vertical tilt |
| `pitch_std` | std(\|pitch\|) | Variability of head tilt |
| `burst_density` | rapid_violations / total | Ratio of rapid-fire violations (<3s apart) |
| `session_duration_min` | (last_ts - first_ts) / 60 | Session length |
| `violation_diversity` | count(unique_categories) | How many different violation types |
| `suspicious_app_focus` | count(browser/messaging switches) | Switches to known suspicious apps |

### 8.2 Vision Features (17 features)

Extracted from violation images using **MediaPipe FaceMesh** (468 facial landmarks):

| Feature | Method | What It Captures |
|---------|--------|-----------------|
| `v_no_face_ratio` | face_mesh detection | Fraction of frames with no face visible |
| `v_multi_face_ratio` | face_mesh detection | Fraction of frames with 2+ faces |
| `v_avg_face_count` | mean(face_count) | Average number of faces per frame |
| `v_yaw_mean` | solvePnP → Rodrigues | Average head horizontal rotation (from images) |
| `v_yaw_max` | max(yaw) | Maximum head rotation captured in images |
| `v_yaw_std` | std(yaw) | How much head rotation varies |
| `v_pitch_mean` | solvePnP → Rodrigues | Average head vertical tilt |
| `v_pitch_max` | max(pitch) | Maximum head tilt captured |
| `v_pitch_std` | std(pitch) | Variability of head tilt |
| `v_ear_mean` | Eye Aspect Ratio formula | Average eye openness (gaze proxy) |
| `v_ear_min` | min(EAR) | Minimum eye openness (looking away?) |
| `v_ear_std` | std(EAR) | Variability of eye openness |
| `v_face_size_mean` | bbox_area / frame_area | Average face size (distance proxy) |
| `v_face_size_std` | std(face_size) | Face size variability (moving around?) |
| `v_brightness_mean` | mean(gray_pixels) / 255 | Average image brightness |
| `v_brightness_std` | std(brightness) | Lighting variability |
| `v_images_analyzed` | count | Number of images processed |

#### Head Pose Estimation Math (solvePnP)

We estimate 3D head pose from 2D facial landmarks using the **Perspective-n-Point (PnP)** algorithm:

```
Given:
  - 6 known 2D image points (nose tip, chin, eye corners, mouth corners)
  - 6 corresponding 3D model points (standard face model)
  - Camera intrinsic matrix K

Solve for rotation matrix R and translation vector t:

  s × [u, v, 1]ᵀ = K × [R | t] × [X, Y, Z, 1]ᵀ

Where:
  K = [[f_x, 0, c_x],    (camera matrix, approximated from image dimensions)
       [0, f_y, c_y],
       [0,  0,   1 ]]

  R = rotation matrix (3×3) → decomposed to yaw, pitch, roll via RQDecomposition
  t = translation vector (3×1)
```

The resulting **yaw** (left-right turn) and **pitch** (up-down tilt) tell us the exact head orientation in degrees.

#### Eye Aspect Ratio (EAR)

```
        P2    P3
       /  \  /  \
  P1 ●─────────── ● P4
       \  /  \  /
        P6    P5

EAR = (||P2 - P6|| + ||P3 - P5||) / (2 × ||P1 - P4||)

Normal open eye:  EAR ≈ 0.25 - 0.35
Closed/squinting: EAR < 0.20
Looking away:     EAR varies significantly
```

### 8.3 Audio Features (8 features)

Extracted from WAV files using **scipy signal processing**:

| Feature | Formula | What It Captures |
|---------|---------|-----------------|
| `a_rms_mean` | mean(√(mean(x²))) | Average volume across all clips |
| `a_rms_max` | max(RMS) | Loudest audio clip |
| `a_rms_std` | std(RMS) | Volume variability |
| `a_zcr_mean` | mean(zero_crossings / samples) | Speech vs noise indicator |
| `a_peak_mean` | mean(max(\|x\|)) | Average peak amplitude |
| `a_total_duration` | sum(clip_lengths) | Total captured audio |
| `a_speech_ratio` | speech_clips / total_clips | Fraction of clips with detected speech |
| `a_clip_count` | count(wav_files) | Number of audio recordings |

#### Voice Activity Detection (VAD)

Simple energy-based VAD:
```
if RMS_energy > 0.02:
    → Speech detected (someone is talking/whispering)
else:
    → Silence/ambient noise
```

---

## 9. How Our Model Uses It

### Training Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│  97 Sessions     │     │  17,457 Images   │     │  41 WAV Clips  │
│  (events.jsonl)  │     │  (violation JPG) │     │  (microphone)  │
└────────┬────────┘     └────────┬─────────┘     └───────┬────────┘
         │                       │                        │
    ┌────▼────┐            ┌────▼──────┐           ┌────▼─────┐
    │ Clean   │            │ MediaPipe │           │  scipy   │
    │ Parse   │            │ FaceMesh  │           │  wavfile │
    │ Filter  │            │ solvePnP  │           │  RMS/ZCR │
    └────┬────┘            └────┬──────┘           └────┬─────┘
         │                      │                       │
    ┌────▼────┐            ┌────▼────┐            ┌────▼────┐
    │20 feats │            │17 feats │            │ 8 feats │
    │per sess │            │per sess │            │ shared  │
    └────┬────┘            └────┬────┘            └────┬────┘
         │                      │                      │
         └──────────┬───────────┘──────────────────────┘
                    │
              ┌─────▼──────┐
              │  FUSION    │
              │ 45 features│
              │ per session│
              └─────┬──────┘
                    │
              ┌─────▼──────┐
              │ Standardize│
              │ (μ=0, σ=1) │
              └─────┬──────┘
                    │
              ┌─────▼──────────────┐
              │  ISOLATION FOREST  │
              │  200 random trees  │
              │  (unsupervised)    │
              └─────┬──────────────┘
                    │
              ┌─────▼──────────┐
              │ Anomaly Score  │
              │ s(x) ∈ [0, 1] │
              │                │
              │ → Cheat %      │
              │   (0-100%)     │
              └────────────────┘
```

### Actual Results from Our Data

| Risk Level | Cheat % Range | Sessions | What It Means |
|-----------|--------------|----------|---------------|
| LOW | 0 - 20% | 44 | Normal exam behavior |
| MODERATE | 20 - 50% | 34 | Minor deviations, likely OK |
| HIGH | 50 - 75% | 5 | Significant behavioral anomalies |
| CRITICAL | 75 - 100% | 4 | Strongly anomalous — investigate |

### Top Contributing Features (from permutation importance)

```
Rank  Source   Feature               Importance
────  ──────   ───────               ──────────
 1    VISION   v_pitch_max           0.0792   ███████
 2    VISION   v_avg_face_count      0.0713   ███████
 3    EVENT    focus_ratio           0.0586   █████
 4    VISION   v_pitch_mean          0.0585   █████
 5    VISION   v_brightness_mean     0.0561   █████
 6    EVENT    total_violations/min  0.0560   █████
 7    EVENT    violation_diversity   0.0488   ████
 8    VISION   v_no_face_ratio       0.0470   ████
 9    EVENT    burst_density         0.0461   ████
10    VISION   v_ear_mean            0.0455   ████
```

**Vision features dominate** — the model relies heavily on what it sees in the webcam images (head tilt, face count, eye openness) rather than just event logs. This validates the multi-modal approach.

---

## 10. Comparison with Other Methods

| Method | Type | Pros | Cons | Why Not Used |
|--------|------|------|------|-------------|
| **Isolation Forest** ✓ | Unsupervised | No labels needed, fast, scalable, handles high dimensions | Can't explain individual predictions easily | **We use this** |
| K-Means | Unsupervised | Simple, interpretable | Assumes spherical clusters, needs K | Cheating isn't cleanly clustered |
| DBSCAN | Unsupervised | Finds arbitrary-shaped clusters | Sensitive to eps/minPts | Hard to tune for high dimensions |
| One-Class SVM | Semi-supervised | Strong boundary learning | Slow for large data, needs kernel tuning | Doesn't scale well |
| Autoencoder | Unsupervised (DL) | Learns complex patterns | Needs lots of data, black box | 97 sessions too few |
| Logistic Regression | Supervised | Highly interpretable | **Needs labeled data** | No reliable labels |
| Random Forest | Supervised | Accurate, feature importance | **Needs labeled data** | No reliable labels |

### Why Isolation Forest is Ideal for Proctoring

1. **No labels needed** — We can't reliably label "cheating" vs "not cheating"
2. **Sub-linear time complexity** — O(t × n × log ψ) vs O(n²) for distance-based methods
3. **Handles mixed features** — Works with event counts, angles, ratios, all in one model
4. **Low memory** — Only stores tree structures, not the entire dataset
5. **Naturally handles the "contamination" concept** — We can set expected cheating rate

---

## 11. Limitations & Mitigations

| Limitation | Impact | Our Mitigation |
|-----------|--------|---------------|
| No true labels → can't measure precision/recall | Don't know exact accuracy | Cross-validate with Z-score analysis as baseline |
| Assumes anomalies are "few and different" | Doesn't work if many students cheat the same way | contamination=0.15 accounts for moderate cheating rate |
| Random splits can miss axis-aligned boundaries | Might miss some patterns | 200 trees with 80% feature sampling adds diversity |
| Audio features are shared (not per-session) | Audio doesn't discriminate between sessions | Future: per-session audio recording |
| Sensitive to feature scaling | Unscaled features bias toward high-magnitude ones | StandardScaler applied before training |
| Small dataset (88-97 sessions) | Less reliable boundaries | Sub-sampling (ψ) handles small datasets well |

---

## 12. References

1. **Liu, F. T., Ting, K. M., & Zhou, Z. H.** (2008). "Isolation Forest." *Proceedings of the 2008 Eighth IEEE International Conference on Data Mining*, pp. 413-422.

2. **Liu, F. T., Ting, K. M., & Zhou, Z. H.** (2012). "Isolation-Based Anomaly Detection." *ACM Transactions on Knowledge Discovery from Data (TKDD)*, 6(1), Article 3.

3. **Luengo, J. et al.** (2020). "A tutorial on the Isolation Forest algorithm for anomaly detection." *IEEE Access*.

4. **scikit-learn documentation**: [IsolationForest](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)

5. **MediaPipe Face Mesh**: [Google AI](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) — 468 3D facial landmarks in real-time.

6. **Soukupova & Cech** (2016). "Real-Time Eye Blink Detection using Facial Landmarks." — Eye Aspect Ratio (EAR) formula.

---

*Document generated for Phone-Proctor multi-modal cheating detection system.*
*Model: Isolation Forest (Unsupervised) | Features: 45 (Event + Vision + Audio)*
*Training data: 97 sessions, 17,457 images, 41 audio clips*
