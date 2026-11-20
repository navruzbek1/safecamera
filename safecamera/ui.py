"""Windows shown by SafeCamera: blur overlay, face-unlock screen and the tray icon."""

import subprocess
import sys
import threading
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

from .util import log
from .winapi import InputBlocker, user32, virtual_screen_rect


class PrivacyOverlay:
    """Blurred screenshot shown over the screen while a stranger looks at it."""

    def __init__(self, root, blur_radius):
        self.root = root
        self.blur_radius = blur_radius
        self.win = None
        self.suppressed_until = 0.0

    @property
    def visible(self):
        return self.win is not None

    def show(self):
        if self.visible or time.time() < self.suppressed_until:
            return
        x, y, w, h = virtual_screen_rect()
        shot = ImageGrab.grab(all_screens=True)
        if shot.size != (w, h):
            shot = shot.resize((w, h))
        shot = shot.filter(ImageFilter.GaussianBlur(self.blur_radius))
        shot = Image.blend(shot, Image.new("RGB", shot.size, (20, 20, 20)), 0.35)
        self._draw_warning(shot)

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self._photo = ImageTk.PhotoImage(shot)
        tk.Label(self.win, image=self._photo, bd=0).pack(fill="both", expand=True)
        self.win.bind("<Escape>", lambda e: self.dismiss())
        self.win.focus_force()
        self._keep_on_top()

    def _keep_on_top(self):
        if self.win is not None:
            self.win.lift()
            self.win.attributes("-topmost", True)
            self.win.after(500, self._keep_on_top)

    def hide(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None
            self._photo = None

    def dismiss(self, seconds=30):
        """Esc pressed: close the overlay and keep it away for a while."""
        self.suppressed_until = time.time() + seconds
        self.hide()

    @staticmethod
    def _draw_warning(img):
        draw = ImageDraw.Draw(img)
        text = "Begona shaxs aniqlandi - ekran yashirildi"
        try:
            font = ImageFont.truetype("segoeui.ttf", 40)
        except OSError:
            font = ImageFont.load_default()
        # centered on the primary monitor
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        cx, cy = (sw - (r - l)) // 2 - vx, (sh - (b - t)) // 2 - vy
        draw.rounded_rectangle((cx - 30, cy - 20, cx + (r - l) + 30, cy + (b - t) + 30),
                               radius=16, fill=(0, 0, 0))
        draw.text((cx, cy), text, font=font, fill=(255, 210, 0))


class FaceLock:
    """Full-screen lock window. It opens when the owner's face is recognized."""

    def __init__(self, root):
        self.root = root
        self.win = None
        self.blocker = InputBlocker()
        self.since = None

    @property
    def visible(self):
        return self.win is not None

    def show(self):
        if self.visible:
            return
        x, y, w, h = virtual_screen_rect()
        self.win = tk.Toplevel(self.root, bg="#0b0f14", cursor="none")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        # text on the primary monitor
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        box = tk.Frame(self.win, bg="#0b0f14")
        box.place(x=sw // 2 - x, y=sh // 2 - y, anchor="center")
        self.clock = tk.Label(box, fg="#ffffff", bg="#0b0f14", font=("Segoe UI Light", 72))
        self.clock.pack()
        self.date = tk.Label(box, fg="#9aa4b2", bg="#0b0f14", font=("Segoe UI", 18))
        self.date.pack()
        tk.Label(box, text="\U0001F512  Kompyuter qulflangan", fg="#ffffff", bg="#0b0f14",
                 font=("Segoe UI Semibold", 24)).pack(pady=(40, 6))
        self.status = tk.Label(box, text="Ochish uchun kameraga qarang", fg="#22c55e",
                               bg="#0b0f14", font=("Segoe UI", 16))
        self.status.pack()
        tk.Label(box, text="Kamera ishlamasa: Ctrl+Alt+Del → Windows paroli",
                 fg="#5b6573", bg="#0b0f14", font=("Segoe UI", 11)).pack(pady=(30, 0))

        self.since = time.time()
        self.blocker.start()
        self._refresh()

    def _refresh(self):
        if self.win is None:
            return
        self.clock.config(text=time.strftime("%H:%M"))
        self.date.config(text=time.strftime("%d.%m.%Y"))
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()
        self.win.after(500, self._refresh)

    def set_status(self, text, color="#22c55e"):
        if self.win is not None:
            self.status.config(text=text, fg=color)

    def hide(self):
        if self.win is not None:
            self.blocker.stop()
            self.win.destroy()
            self.win = None
            self.since = None


def make_icon_image(enabled):
    """Camera-shaped icon: green when enabled, gray when disabled."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (22, 163, 74) if enabled else (120, 120, 120)
    d.ellipse((0, 0, 63, 63), fill=bg)
    d.ellipse((14, 14, 49, 49), fill=(255, 255, 255))
    d.ellipse((22, 22, 41, 41), fill=bg)
    d.ellipse((28, 26, 34, 32), fill=(255, 255, 255))
    if not enabled:
        d.line((12, 52, 52, 12), fill=(220, 38, 38), width=7)
    return img


class TrayIcon:
    """
    Tray icon. pystray runs in its own thread, so it only flips flags here; the real
    work happens in the tkinter thread (SafeCamera.step).
    """

    def __init__(self, app):
        import pystray
        self.app = app
        self._images = {True: make_icon_image(True), False: make_icon_image(False)}
        menu = pystray.Menu(
            pystray.MenuItem("Himoya yoqilgan", self.toggle, default=True,
                             checked=lambda item: not self.app.paused),
            pystray.MenuItem("Yuzimni qayta saqlash", self.re_enroll,
                             enabled=lambda item: not self.app.enrolling),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Chiqish", self.exit),
        )
        self.icon = pystray.Icon("SafeCamera", self._images[True], self.title(), menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def title(self):
        return "SafeCamera - " + ("o'chirilgan" if self.app.paused else "yoqilgan")

    def refresh(self):
        self.icon.icon = self._images[not self.app.paused]
        self.icon.title = self.title()
        self.icon.update_menu()

    def toggle(self, icon=None, item=None):
        self.app.paused = not self.app.paused
        log("Himoya " + ("o'chirildi." if self.app.paused else "yoqildi."))
        self.refresh()

    def re_enroll(self, icon=None, item=None):
        def worker():
            was_paused = self.app.paused
            self.app.enrolling = self.app.paused = True
            self.refresh()
            time.sleep(0.6)  # let the tkinter thread release the camera
            subprocess.run([sys.executable, "-m", "safecamera", "--enroll",
                            "--camera", str(self.app.args.camera)], check=False)
            self.app.recognizer.reload()
            self.app.enrolling, self.app.paused = False, was_paused
            self.refresh()
        threading.Thread(target=worker, daemon=True).start()

    def exit(self, icon=None, item=None):
        self.app.want_quit = True
        self.icon.stop()
