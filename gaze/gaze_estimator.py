import cv2
import numpy as np


class GazeEstimator:
    def __init__(self):
        # Indices for eyes (based on MediaPipe Face Mesh)
        # Left Eye
        self.LEFT_EYE_RIGHT = 33  # User's numeric Left (Outer)
        self.LEFT_EYE_LEFT = 133  # User's numeric Right (Inner)
        self.LEFT_EYE_TOP = 159
        self.LEFT_EYE_BOTTOM = 145
        self.LEFT_IRIS_CENTER = 468

        # Right Eye
        self.RIGHT_EYE_RIGHT = 362 # User's numeric Left (Inner)
        self.RIGHT_EYE_LEFT = 263  # User's numeric Right (Outer)
        self.RIGHT_EYE_TOP = 386
        self.RIGHT_EYE_BOTTOM = 374
        self.RIGHT_IRIS_CENTER = 473

    def estimate(self, landmarks, frame_shape):
        """
        Estimates the gaze direction (Horizontal and Vertical).
        Returns:
             is_looking_away (bool)
             gaze_scores (dict)
        """
        h, w = frame_shape[:2]

        def get_point(idx):
            return np.array(landmarks[idx])

        # ----------------------------------------
        # Horizontal Gaze (Left/Right)
        # ----------------------------------------
        # Logic: Calculate relative position of Iris between horizontal eye corners
        
        # Left Eye (User's Left)
        l_right = get_point(self.LEFT_EYE_RIGHT) # outer
        l_left = get_point(self.LEFT_EYE_LEFT)   # inner
        l_iris = get_point(self.LEFT_IRIS_CENTER)
        
        # Width: Distance between corners
        l_width_horiz = np.linalg.norm(l_right - l_left)
        # Dist from Right(Outer) corner
        l_dist_horiz = np.linalg.norm(l_iris - l_right)
        
        l_ratio_h = l_dist_horiz / l_width_horiz if l_width_horiz > 0 else 0.5

        # Right Eye (User's Right)
        r_right = get_point(self.RIGHT_EYE_RIGHT) # inner
        r_left = get_point(self.RIGHT_EYE_LEFT)   # outer
        r_iris = get_point(self.RIGHT_IRIS_CENTER)
        
        r_width_horiz = np.linalg.norm(r_right - r_left)
        # Dist from Right(Inner) corner. 
        # Note: We measure from "User's Leftward" point to align directions
        # Here 'r_right' is actually index 362 (Inner/Nasal), which is to the User's Left
        r_dist_horiz = np.linalg.norm(r_iris - r_right)
        
        r_ratio_h = r_dist_horiz / r_width_horiz if r_width_horiz > 0 else 0.5

        # Avg Horizontal Ratio (0=User Looking Left, 1=User Looking Right)
        avg_ratio_h = (l_ratio_h + r_ratio_h) / 2.0

        # ----------------------------------------
        # Vertical Gaze (Up/Down)
        # ----------------------------------------
        # Logic: Position of Iris between Top and Bottom eyelids
        
        # Left Eye Vertical
        l_top = get_point(self.LEFT_EYE_TOP)
        l_bottom = get_point(self.LEFT_EYE_BOTTOM)
        l_height = np.linalg.norm(l_top - l_bottom)
        l_dist_vert = np.linalg.norm(l_iris - l_top) # Dist from Top
        l_ratio_v = l_dist_vert / l_height if l_height > 0 else 0.5

        # Right Eye Vertical
        r_top = get_point(self.RIGHT_EYE_TOP)
        r_bottom = get_point(self.RIGHT_EYE_BOTTOM)
        r_height = np.linalg.norm(r_top - r_bottom)
        r_dist_vert = np.linalg.norm(r_iris - r_top) # Dist from Top
        r_ratio_v = r_dist_vert / r_height if r_height > 0 else 0.5
        
        avg_ratio_v = (l_ratio_v + r_ratio_v) / 2.0

        # ----------------------------------------
        # Thresholds & Decision
        # ----------------------------------------
        # Tighter thresholds for "Looking Here and There"
        
        is_looking_away = False
        direction = "CENTER"

        # Horizontal Thresholds (0.42 to 0.58 is strict center)
        if avg_ratio_h < 0.42:
            is_looking_away = True
            direction = "RIGHT" # Camera perspective (User looking Left)
        elif avg_ratio_h > 0.58:
            is_looking_away = True
            direction = "LEFT" # Camera perspective (User looking Right)
            
        # Vertical Thresholds (Ratio increases as you look down)
        # 0.0 = Top, 1.0 = Bottom
        # Normal gaze is usually slightly above center (e.g., 0.45)
        if avg_ratio_v < 0.40: # Looking Up
            is_looking_away = True
            direction = "UP"
        elif avg_ratio_v > 0.60: # Looking Down (e.g. at keyboard/phone)
            is_looking_away = True
            direction = "DOWN"

        return is_looking_away, {
            "h_ratio": avg_ratio_h, 
            "v_ratio": avg_ratio_v,
            "direction": direction
        }
