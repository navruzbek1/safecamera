import numpy as np
import pytest

from safecamera.detection import Face
from safecamera.recognition import OwnerRecognizer


def make_recognizer(owner=None, threshold=0.4):
    """Recognizer without loading the ONNX models; face.raw doubles as the embedding."""
    rec = OwnerRecognizer.__new__(OwnerRecognizer)
    rec.threshold = threshold
    rec.last_owner_box = None
    rec.owner = owner
    rec.feature = lambda frame, face: face.raw
    return rec


def face(box, embedding):
    return Face(box, 0.0, 0.5, raw=np.array(embedding, dtype=np.float32))


OWNER = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)


def test_not_enrolled_largest_face_is_owner():
    rec = make_recognizer(owner=None)
    big, small = face((0, 0, 100, 100), [1, 0, 0]), face((0, 0, 20, 20), [0, 1, 0])
    rec.label(None, [big, small])
    assert big.is_owner and not small.is_owner


def test_no_faces_is_a_noop():
    rec = make_recognizer(owner=OWNER)
    rec.label(None, [])
    assert rec.last_owner_box is None


def test_matching_face_is_owner_and_stranger_is_not():
    rec = make_recognizer(owner=OWNER)
    stranger, owner = face((0, 0, 100, 100), [0, 1, 0]), face((200, 0, 50, 50), [1, 0, 0])
    rec.label(None, [stranger, owner])
    assert owner.is_owner and not stranger.is_owner
    assert owner.similarity == pytest.approx(1.0)
    assert rec.last_owner_box == owner.box


def test_no_match_clears_last_owner_box():
    rec = make_recognizer(owner=OWNER)
    rec.last_owner_box = (0, 0, 10, 10)
    stranger = face((500, 500, 50, 50), [0, 1, 0])
    rec.label(None, [stranger])
    assert not stranger.is_owner
    assert rec.last_owner_box is None


def test_turned_head_keeps_owner_by_position():
    rec = make_recognizer(owner=OWNER)
    rec.last_owner_box = (100, 100, 80, 80)
    # embedding below the threshold (0.3 < 0.4) but above 0.2, same place as before
    turned = face((102, 102, 80, 80), [0.3, 0.95, 0.0])
    rec.label(None, [turned])
    assert turned.is_owner
