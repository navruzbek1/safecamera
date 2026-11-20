import numpy as np
import pytest

from safecamera.detection import Face, FaceDetector, iou


def landmarks(nose_dx=0.0, nose_dy=0.0):
    """Right eye, left eye, nose, right mouth corner, left mouth corner."""
    return np.array([[100, 100], [140, 100], [120 + nose_dx, 120 + nose_dy],
                     [105, 140], [135, 140]], dtype=float)


def test_head_pose_facing_camera():
    yaw, pitch = FaceDetector.head_pose(landmarks())
    assert yaw == pytest.approx(0.0)
    assert pitch == pytest.approx(0.5)


def test_head_pose_turned_head_increases_yaw():
    yaw, _ = FaceDetector.head_pose(landmarks(nose_dx=20))
    assert yaw == pytest.approx(0.5)
    yaw_left, _ = FaceDetector.head_pose(landmarks(nose_dx=-20))
    assert yaw_left == pytest.approx(-0.5)


def test_head_pose_tilted_down_changes_pitch():
    _, pitch = FaceDetector.head_pose(landmarks(nose_dy=10))
    assert pitch == pytest.approx(0.75)


def test_head_pose_degenerate_landmarks_do_not_divide_by_zero():
    lm = np.zeros((5, 2))
    yaw, pitch = FaceDetector.head_pose(lm)
    assert yaw == 0.0 and pitch == 0.0


def test_iou_identical_boxes():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)


def test_iou_disjoint_boxes():
    assert iou((0, 0, 10, 10), (20, 20, 10, 10)) == 0


def test_iou_half_overlap():
    assert iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(1 / 3)


@pytest.mark.parametrize("yaw, pitch, expected", [
    (0.0, 0.5, True),     # facing the screen
    (0.1, 0.5, True),
    (0.4, 0.5, False),    # head turned away
    (-0.4, 0.5, False),
    (0.0, 0.1, False),    # looking far up
    (0.0, 0.95, False),   # looking far down
])
def test_is_looking(yaw, pitch, expected):
    face = Face((0, 0, 10, 10), yaw, pitch, raw=None)
    assert face.is_looking(max_yaw=0.25) is expected
