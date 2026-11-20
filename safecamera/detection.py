"""Face detection (YuNet) and head-pose estimation from its 5 landmarks."""

import os
import urllib.request
from pathlib import Path

import cv2

from .paths import ZOO, detector_model_path
from .util import log


def ensure_model(path: Path, url: str, name: str) -> None:
    """Download an ONNX model from the OpenCV Zoo on first use."""
    if not path.exists():
        log(f"{name} modeli yuklab olinmoqda (bir marta)...")
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        urllib.request.urlretrieve(url, part)
        os.replace(part, path)


class Face:
    def __init__(self, box, yaw, pitch, raw):
        self.box, self.yaw, self.pitch, self.raw = box, yaw, pitch, raw
        self.is_owner = False
        self.similarity = None  # similarity to the owner's face (0..1)

    def is_looking(self, max_yaw, pitch_range=(0.25, 0.85)):
        """True when the face is turned towards the camera (and the screen below it)."""
        return abs(self.yaw) <= max_yaw and pitch_range[0] <= self.pitch <= pitch_range[1]


def iou(a, b):
    """Intersection over union of two (x, y, w, h) boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter or 1)


class FaceDetector:
    """YuNet network (bundled with OpenCV). Finds frontal and tilted (side) faces."""

    def __init__(self, score_threshold=0.7):
        path = detector_model_path()
        ensure_model(path, ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
                     "Yuz aniqlash")
        self.net = cv2.FaceDetectorYN.create(str(path), "", (320, 320),
                                             score_threshold, 0.3, 50)

    def detect(self, frame):
        h, w = frame.shape[:2]
        self.net.setInputSize((w, h))
        _, faces = self.net.detect(frame)
        if faces is None:
            return []
        min_side = w // 20  # ignore very small / distant faces
        result = []
        for f in faces:
            if f[2] < min_side:
                continue
            box = tuple(int(v) for v in f[:4])
            yaw, pitch = self.head_pose(f[4:14].reshape(5, 2))
            result.append(Face(box, yaw, pitch, f))
        # largest (closest to the camera) face first
        result.sort(key=lambda fc: fc.box[2] * fc.box[3], reverse=True)
        return result

    @staticmethod
    def head_pose(lm):
        """
        YuNet's 5 points: right eye, left eye, nose, right mouth corner, left mouth corner.
        yaw   - how far the nose is shifted sideways from the midpoint between the eyes,
                relative to the eye distance (0 = facing the camera, ~0.5+ = head turned)
        pitch - vertical position of the nose between eye line and mouth (~0.5 = level)
        """
        eye_mid = (lm[0] + lm[1]) / 2
        mouth_mid = (lm[3] + lm[4]) / 2
        eye_dist = max(1.0, float(abs(lm[1][0] - lm[0][0])))
        yaw = float(lm[2][0] - eye_mid[0]) / eye_dist
        span = max(1.0, float(mouth_mid[1] - eye_mid[1]))
        pitch = float(lm[2][1] - eye_mid[1]) / span
        return yaw, pitch
