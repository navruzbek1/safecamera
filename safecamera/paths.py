"""Where models and the owner's face data live.

Everything is stored outside the repository, in %LOCALAPPDATA%\\SafeCamera by default
(override with the SAFECAMERA_DATA_DIR environment variable). The owner's face data is
biometric, so it never sits next to the source code.
"""

import os
from pathlib import Path

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"


def data_dir() -> Path:
    override = os.environ.get("SAFECAMERA_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SafeCamera"


def detector_model_path() -> Path:
    return data_dir() / "face_detection_yunet_2023mar.onnx"


def recognizer_model_path() -> Path:
    return data_dir() / "face_recognition_sface_2021dec.onnx"


def owner_face_path() -> Path:
    return data_dir() / "owner_face.npy"
