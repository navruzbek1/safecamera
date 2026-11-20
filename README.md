# SafeCamera

[![CI](https://github.com/navruzbek1/safecamera/actions/workflows/ci.yml/badge.svg)](https://github.com/navruzbek1/safecamera/actions/workflows/ci.yml)

Protect a Windows PC with its webcam. SafeCamera watches the camera and

- **locks the screen** when the owner walks away (and unlocks it again when it recognizes
  the owner's face),
- **blurs the screen** when someone else looks at it from behind or from the side.

Everything runs locally, on the CPU, with two small ONNX models from the
[OpenCV Zoo](https://github.com/opencv/opencv_zoo): YuNet (face detection and 5 landmarks)
and SFace (face recognition).

> The on-screen messages are in Uzbek (the language of the original users). The code,
> comments and this README are in English.

## How it works

The camera is read every 150 ms. For each frame:

1. **YuNet** finds faces and 5 landmarks per face (eyes, nose, mouth corners).
2. **Head pose** is estimated from those landmarks: *yaw* is how far the nose is shifted
   from the midpoint between the eyes, relative to the eye distance; *pitch* is the nose
   position between the eye line and the mouth. A face counts as "looking at the screen"
   when yaw and pitch are within limits (`--gaze`).
3. **SFace** turns each face into an embedding. It is compared by cosine similarity with
   the owner's saved embeddings (threshold `--match`, default 0.40; SFace recommends 0.363).

Decisions (see `safecamera/app.py`, `SafeCamera.step`):

| Situation | Reaction |
|---|---|
| Owner not visible for `--away` s (default 5) and a face is enrolled | **Face lock**: full-screen lock that swallows all keyboard and mouse input (low-level hooks). It opens when the owner is recognized in 3 consecutive frames. |
| Same, but nobody is enrolled or `--no-face-unlock` | Immediately the real **Windows lock** (Win+L). |
| Someone else looks at the screen for `--peek` s (default 1) while the owner is present | The screen is replaced by a **blurred screenshot**. It disappears `--clear` s (default 2) after the person looks away. `Esc` dismisses it for 30 s. |

While the face lock is open, SafeCamera **escalates to the real Windows lock** when the
owner does not return within `--hard-after` minutes (default 15), when Ctrl+Alt+Del is
pressed (Windows does not allow blocking it), when an unknown person sits in front of the
camera for 3 s, when the camera stops delivering frames for 5 s, or when SafeCamera is
closed. The face lock is a convenience layer, the Windows lock is the fallback.

If no face is enrolled, the largest (closest) face is treated as the owner.

## Install and run

Windows, Python 3.10+, a webcam.

```bash
python -m pip install -e .
python -m safecamera --enroll     # once: saves the owner's face (move your head slowly)
python -m safecamera              # run (tray icon appears)
python -m safecamera --preview    # run with a camera window, useful for tuning
```

The models are downloaded from the OpenCV Zoo on first run (about 39 MB). Check their
licenses in that repository before redistributing them.

`scripts/enroll.bat` stops the background instance, re-enrolls and starts it again.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--camera` | 0 | camera index |
| `--away` | 5 | seconds without the owner before locking |
| `--peek` | 1.0 | seconds a stranger looks before the screen blurs |
| `--clear` | 2.0 | seconds after the stranger looks away before the screen clears |
| `--gaze` | 0.25 | head-turn limit for "looking at the screen" (smaller = stricter) |
| `--blur` | 25 | blur radius |
| `--interval` | 150 | milliseconds between frames |
| `--match` | 0.40 | owner recognition threshold (larger = stricter) |
| `--hard-after` | 15 | minutes before the face lock becomes the Windows lock, 0 = never |
| `--no-face-unlock` | off | skip the face lock, use the Windows lock directly |
| `--no-tray` | off | no tray icon |
| `--preview` | off | show the camera window with detections |
| `--enroll` | off | save the owner's face and exit |

## Data and privacy

- Frames are processed in memory and never saved or sent anywhere. The only network
  access is the one-time model download.
- The owner is stored as face **embeddings** (not photos) in
  `%LOCALAPPDATA%\SafeCamera\owner_face.npy` (override with `SAFECAMERA_DATA_DIR`).
  That is biometric data: it is kept outside the repository and `.gitignore` excludes it.

## Limitations

- Windows only (`ctypes` calls into user32, wtsapi32 and kernel32).
- **No liveness check:** a photo or video of the owner may be accepted by the face lock.
  Treat the face lock as a convenience, not as a security boundary.
- Thresholds (`--gaze`, `--match`) were tuned by hand on one webcam and may need
  adjusting for other cameras and lighting.
- Automated tests cover the pure logic (head pose, box overlap, owner matching, CLI
  defaults). The camera, tkinter windows and Windows lock paths are not covered by tests.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
python -m pytest
```

```
safecamera/
  app.py          main loop and the lock / blur decisions
  detection.py    YuNet detector, head pose, box IoU
  recognition.py  SFace owner matching, enrollment
  ui.py           blur overlay, face-lock screen, tray icon
  winapi.py       Windows lock state, input hooks, single-instance mutex
  paths.py        where models and owner data live
tests/            pytest
scripts/          enroll.bat
```

<details>
<summary><b>O'zbekcha qisqacha</b></summary>

**SafeCamera** veb-kamera yordamida Windows kompyuterni himoya qiladi:

- Egasi kompyuterdan uzoqlashsa, ekranni **yuz qulfi** bilan yopadi va egasining yuzi tanilganda
  qulfni o'zi ochadi.
- Begona odam ekranga qarasa (yon tomondan yoki orqadan), ekranni **xiralashtiradi**.
- Kamera ishlamasa, Ctrl+Alt+Del bosilsa yoki egasi uzoq qaytmasa, haqiqiy Windows qulfiga
  (Win+L) o'tadi.

Hammasi lokal ishlaydi (OpenCV: YuNet va SFace modellari), kadrlar saqlanmaydi va hech qayerga
yuborilmaydi. Egasining yuzi rasm emas, yuz "izlari" (embedding) sifatida
`%LOCALAPPDATA%\SafeCamera` papkasida saqlanadi.

```bash
python -m pip install -e .
python -m safecamera --enroll    # bir marta: egasining yuzini saqlash
python -m safecamera             # ishga tushirish
```

**Cheklovlar:** faqat Windows; jonlilik tekshiruvi (liveness) yo'q, ya'ni egasining
fotosurati yuz qulfini ochishi mumkin. Yuz qulfi qulaylik uchun, xavfsizlik chegarasi emas.

</details>

## License

MIT, see [LICENSE](LICENSE).
