"""Owner recognition with the SFace model and one-time enrollment."""

import sys
import time

import cv2
import numpy as np

from .detection import FaceDetector, ensure_model, iou
from .paths import ZOO, owner_face_path, recognizer_model_path
from .util import log


class OwnerRecognizer:
    """
    SFace face recognition. The owner's face is saved once (--enroll), then every
    detected face is compared with it by cosine similarity.
    """
    # SFace's recommended cosine-similarity threshold is 0.363
    def __init__(self, threshold=0.40):
        path = recognizer_model_path()
        ensure_model(path, ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
                     "Yuz tanish")
        self.net = cv2.FaceRecognizerSF.create(str(path), "")
        self.threshold = threshold
        self.last_owner_box = None
        self.reload()

    def reload(self):
        path = owner_face_path()
        self.owner = np.load(path) if path.exists() else None

    @property
    def enrolled(self):
        return self.owner is not None

    def feature(self, frame, face):
        aligned = self.net.alignCrop(frame, face.raw)
        f = self.net.feature(aligned).flatten()
        return f / (np.linalg.norm(f) + 1e-9)

    def label(self, frame, faces):
        """Sets is_owner on every face."""
        if not faces:
            return
        if not self.enrolled:
            faces[0].is_owner = True  # nobody enrolled: the largest face is the owner
            return
        best, best_sim = None, self.threshold
        for fc in faces:
            fc.similarity = float(np.max(self.owner @ self.feature(frame, fc)))
            if fc.similarity >= best_sim:
                best, best_sim = fc, fc.similarity
        # Recognition gets harder when the head is turned sharply, so a face that sits
        # where the owner was in the previous frame is also treated as the owner.
        if best is None and self.last_owner_box is not None:
            near = max(faces, key=lambda fc: iou(fc.box, self.last_owner_box))
            if iou(near.box, self.last_owner_box) > 0.5 and (near.similarity or 0) > 0.2:
                best = near
        if best is not None:
            best.is_owner = True
        self.last_owner_box = best.box if best is not None else None


def enroll_owner(camera, samples=25):
    """Capture the owner's face from the camera and save it to owner_face.npy."""
    detector, rec = FaceDetector(), OwnerRecognizer()
    cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        sys.exit("Kamera ochilmadi (dastur fonda ishlayotgan bo'lsa avval to'xtating).")
    feats, last = [], 0.0
    title = "Yuzni saqlash (Esc - bekor qilish)"
    while len(feats) < samples:
        ok, frame = cap.read()
        if not ok:
            continue
        faces = detector.detect(frame)
        msg = "Kameraga qarang, boshingizni sekin u yoq-bu yoqqa buring"
        area = lambda fc: fc.box[2] * fc.box[3]
        # small faces in the background (picture, poster, distant person) must not interfere
        if len(faces) > 1 and area(faces[0]) >= 4 * area(faces[1]):
            faces = faces[:1]
        if len(faces) == 1:
            if time.time() - last > 0.2:
                feats.append(rec.feature(frame, faces[0]))
                last = time.time()
            x, y, w, h = faces[0].box
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 200, 0), 2)
        elif len(faces) > 1:
            msg = "Kadrda faqat siz bo'lishingiz kerak!"
        cv2.putText(frame, msg, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        pw = int(frame.shape[1] * len(feats) / samples)
        cv2.rectangle(frame, (0, frame.shape[0] - 12), (pw, frame.shape[0]), (0, 200, 0), -1)
        cv2.imshow(title, frame)
        if cv2.waitKey(1) & 0xFF == 27:
            cap.release()
            cv2.destroyAllWindows()
            sys.exit("Bekor qilindi.")
    cap.release()
    cv2.destroyAllWindows()
    path = owner_face_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.array(feats, dtype=np.float32))
    log(f"Egasining yuzi saqlandi ({samples} ta namuna): {path}")
