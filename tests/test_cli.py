from safecamera.app import parse_args


def test_defaults():
    args = parse_args([])
    assert args.camera == 0
    assert args.away == 5
    assert args.peek == 1.0
    assert args.match == 0.40
    assert args.hard_after == 15
    assert args.face_unlock is True
    assert args.enroll is False


def test_flags():
    args = parse_args(["--enroll", "--no-face-unlock", "--away", "10", "--camera", "1"])
    assert args.enroll is True
    assert args.face_unlock is False
    assert args.away == 10
    assert args.camera == 1
