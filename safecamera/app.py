"""Main loop: decides when to blur the screen, lock it, or escalate to the Windows lock."""

import argparse
import os
import signal
import sys
import time
import tkinter as tk

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2

from .detection import FaceDetector
from .recognition import OwnerRecognizer, enroll_owner
from .ui import FaceLock, PrivacyOverlay, TrayIcon
from .util import log
from .winapi import (
    already_running,
    enable_dpi_awareness,
    is_session_locked,
    is_workstation_locked,
    lock_workstation,
)


class SafeCamera:
    def __init__(self, args):
        self.args = args
        self.detector = FaceDetector()
        self.recognizer = OwnerRecognizer(args.match)
        self.cap = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = PrivacyOverlay(self.root, args.blur)
        self.facelock = FaceLock(self.root)

        now = time.time()
        self.escalate = False       # escalate from the face lock to the Windows lock
        self.hard_lock_grace = 0.0
        self.last_frame_ok = now
        self.owner_frames = 0
        self.intruder_since = None
        self.last_face_seen = now
        self.multi_since = None     # since when 2+ faces are visible
        self.single_since = None    # since when only 1 face is visible again
        self.was_locked = False

        self.paused = False         # switched off from the tray icon
        self.enrolling = False      # owner's face is being re-enrolled
        self.want_quit = False
        self.tray = None if args.no_tray else TrayIcon(self)

    # --- camera ---
    def open_camera(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(self.args.camera, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not self.cap.isOpened():
                # Windows may still be loading - try again on the next tick
                self.cap = None
                self.last_face_seen = time.time()
                return False
        return True

    def release_camera(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.args.preview:
            cv2.destroyAllWindows()

    # --- loop ---
    def tick(self):
        try:
            self.step()
        finally:
            self.root.after(self.args.interval, self.tick)

    def step(self):
        now = time.time()

        if self.want_quit:
            self.quit()
            return
        # Switched off from the tray: release the camera and do nothing.
        # (Cannot be switched off while the face lock is open, or it would never unlock.)
        if self.paused and not self.facelock.visible:
            if self.cap is not None:
                self.overlay.hide()
                self.release_camera()
            self.last_face_seen = now
            self.multi_since = self.single_since = None
            return

        # After switching to the Windows lock, wait until it is really active
        if now < self.hard_lock_grace:
            return

        # Real Windows lock: release the camera and wait for the password
        if is_session_locked():
            if not self.was_locked:
                log("Windows qulflangan - kamera to'xtatildi.")
                self.overlay.hide()
                self.facelock.hide()
                self.release_camera()
                self.was_locked = True
            return
        if self.was_locked:
            log("Windows ochildi - kuzatuv davom etmoqda.")
            self.was_locked = False
            self.escalate = False
            self.last_face_seen = now
            self.multi_since = self.single_since = None

        # Ctrl+Alt+Del menu / UAC prompt is showing. During the face lock this may be an
        # attempt to kill the program from Task Manager.
        if is_workstation_locked():
            if self.facelock.visible and not self.escalate:
                log("Qulf vaqtida Ctrl+Alt+Del bosildi.")
                self.escalate = True
            return
        if self.escalate:
            self.hard_lock("Ctrl+Alt+Del bosilgan edi")
            return

        if not self.open_camera():
            self.check_camera_failure(now)
            return
        ok, frame = self.cap.read()
        if not ok:
            self.check_camera_failure(now)
            return
        self.last_frame_ok = now
        faces = self.detector.detect(frame)
        self.recognizer.label(frame, faces)

        if self.facelock.visible:
            self.step_locked(frame, faces, now)
            if self.args.preview:
                self.draw_preview(frame, faces, now)
            return

        owner_here = any(f.is_owner for f in faces)

        # 1) The owner walked away -> lock.
        #    With an enrolled face, the computer also locks if a stranger sits down.
        if owner_here:
            self.last_face_seen = now
        elif now - self.last_face_seen >= self.args.away:
            who = "egasi" if self.recognizer.enrolled else "hech kim"
            if self.args.face_unlock and self.recognizer.enrolled:
                log(f"{self.args.away} soniya davomida {who} ko'rinmadi - yuz qulfi yoqildi.")
                self.soft_lock()
            else:
                self.hard_lock(f"{self.args.away} soniya davomida {who} ko'rinmadi")
            return

        # 2) A stranger LOOKS AT THE SCREEN -> blur.
        #    So the owner's own face does not blur the screen when recognition briefly
        #    fails: with 2+ faces and no owner match, the largest face is taken as the owner.
        #    A single unknown face alone is not blurred; the lock timer handles it.
        if not owner_here and len(faces) >= 2:
            faces[0].is_owner = True
        others = [f for f in faces if not f.is_owner] if len(faces) >= 2 else []
        watchers = [f for f in others if f.is_looking(self.args.gaze)]
        if watchers:
            self.single_since = None
            self.multi_since = self.multi_since or now
            if not self.overlay.visible and now - self.multi_since >= self.args.peek:
                log(f"{len(watchers)} ta begona shaxs ekranga qarayapti - ekran xiralashtirildi.")
                self.overlay.show()
        else:
            self.multi_since = None
            if self.overlay.visible:
                self.single_since = self.single_since or now
                if now - self.single_since >= self.args.clear:
                    log("Begona shaxs endi ekranga qaramayapti - ekran ochildi.")
                    self.overlay.hide()

        if self.args.preview:
            self.draw_preview(frame, faces, now)

    # --- locks ---
    def soft_lock(self):
        """Face-unlock lock (not the Windows lock)."""
        self.overlay.hide()
        self.facelock.show()
        self.recognizer.last_owner_box = None  # the face must be recognized again to unlock
        self.owner_frames = 0
        self.intruder_since = None
        self.last_frame_ok = time.time()

    def hard_lock(self, reason):
        """Real Windows lock: only a password / PIN / Windows Hello opens it."""
        log(f"{reason} - Windows qulfiga o'tilmoqda.")
        lock_workstation()          # lock first, then close the windows - no gap in between
        self.overlay.hide()
        self.facelock.hide()
        self.escalate = False
        self.hard_lock_grace = time.time() + 2

    def check_camera_failure(self, now):
        # Camera dies during the face lock: it cannot be unlocked, so use the Windows lock
        if self.facelock.visible and now - self.last_frame_ok > 5:
            self.hard_lock("Kamera ishlamayapti")

    def step_locked(self, frame, faces, now):
        """While the face lock is open: wait for the owner, watch for strangers."""
        owner = [f for f in faces
                 if f.similarity is not None and f.similarity >= self.args.match]

        # Owner recognized in 3 consecutive frames -> unlock (guards against a stray match)
        if owner:
            self.owner_frames += 1
            if self.owner_frames >= 3:
                log(f"Egasi tanildi (o'xshashlik {owner[0].similarity:.2f}) - qulf ochildi.")
                self.facelock.hide()
                self.last_face_seen = now
                self.multi_since = self.single_since = None
                return
            self.facelock.set_status("Tanilmoqda...")
        else:
            self.owner_frames = 0
            self.facelock.set_status("Ochish uchun kameraga qarang")

        # A stranger right in front of the camera is looking at the screen
        min_w = frame.shape[1] // 7
        intruders = [f for f in faces if f not in owner and f.box[2] >= min_w
                     and f.is_looking(self.args.gaze)]
        if intruders and not owner:
            self.intruder_since = self.intruder_since or now
            self.facelock.set_status("Notanish shaxs!", "#ef4444")
            if now - self.intruder_since >= 3:
                self.hard_lock("Kompyuter oldida notanish odam")
                return
        else:
            self.intruder_since = None

        # Owner did not come back for a long time: switch to the Windows lock for safety
        if self.args.hard_after > 0 and now - self.facelock.since >= self.args.hard_after * 60:
            self.hard_lock(f"{self.args.hard_after:g} daqiqa davomida egasi qaytmadi")

    def draw_preview(self, frame, faces, now):
        # green - owner, red - stranger looking at the screen, yellow - stranger looking away
        for f in faces:
            x, y, w, h = f.box
            if f.is_owner:
                color, label = (0, 200, 0), "egasi"
            elif f.is_looking(self.args.gaze):
                color, label = (0, 0, 255), "QARAYAPTI"
            else:
                color, label = (0, 220, 255), "qaramayapti"
            sim = "" if f.similarity is None else f" sim={f.similarity:.2f}"
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, f"{label} yaw={f.yaw:+.2f}{sim}", (x, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        absent = now - self.last_face_seen
        cv2.putText(frame, f"Yuzlar: {len(faces)}  Yo'q: {absent:4.1f}s / {self.args.away}s",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow("SafeCamera (q - chiqish)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            self.quit()

    def run(self):
        log(f"SafeCamera ishga tushdi: bloklash {self.args.away}s, "
            f"xiralash {self.args.peek}s. To'xtatish: Ctrl+C")
        if not self.recognizer.enrolled:
            log("Egasining yuzi saqlanmagan - eng yaqin yuz egasi hisoblanadi. "
                "Saqlash uchun: python -m safecamera --enroll")
        self.root.after(0, self.tick)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.release_camera()

    def quit(self):
        if self.facelock.visible:
            lock_workstation()  # closed during the face lock: do not leave the PC open
        self.facelock.hide()
        self.overlay.hide()
        self.release_camera()
        if self.tray is not None:
            self.tray.icon.stop()
        self.root.quit()


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="safecamera", description="Web kamera orqali kompyuterni himoya qilish")
    p.add_argument("--camera", type=int, default=0, help="kamera indeksi (standart 0)")
    p.add_argument("--away", type=float, default=5,
                   help="necha soniya yuz ko'rinmasa bloklansin (standart 5)")
    p.add_argument("--peek", type=float, default=1.0,
                   help="begona necha soniya ekranga qarasa xiralashsin (standart 1)")
    p.add_argument("--gaze", type=float, default=0.25,
                   help="bosh burilishi chegarasi: kichikroq = faqat to'g'ri qaraganda "
                        "ishlaydi, kattaroq = qiyaroq qarashda ham (standart 0.25)")
    p.add_argument("--clear", type=float, default=2.0,
                   help="begona ketgach necha soniyada ekran ochilsin (standart 2)")
    p.add_argument("--blur", type=int, default=25, help="xiralik darajasi (standart 25)")
    p.add_argument("--interval", type=int, default=150,
                   help="kadrlar orasidagi vaqt, ms (standart 150)")
    p.add_argument("--preview", action="store_true", help="kamera oynasini ko'rsatish")
    p.add_argument("--no-face-unlock", dest="face_unlock", action="store_false",
                   help="yuz qulfini ishlatmaslik - darhol Windows qulfi (Win+L)")
    p.add_argument("--hard-after", type=float, default=15,
                   help="yuz qulfi necha daqiqadan keyin Windows qulfiga aylansin, "
                        "0 = hech qachon (standart 15)")
    p.add_argument("--no-tray", action="store_true", help="soat yonida ikonka ko'rsatmaslik")
    p.add_argument("--enroll", action="store_true",
                   help="egasining yuzini kameradan saqlash (bir marta bajariladi)")
    p.add_argument("--match", type=float, default=0.40,
                   help="egasini tanish chegarasi 0..1: kattaroq = qattiqroq (standart 0.40)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    enable_dpi_awareness()
    if args.enroll:
        enroll_owner(args.camera)
        sys.exit(0)
    if already_running():
        sys.exit("SafeCamera allaqachon ishlayapti (soat yonidagi ikonkaga qarang).")
    app = SafeCamera(args)
    # so Ctrl+C also works inside tkinter (tick runs Python code every 150 ms)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    app.run()
