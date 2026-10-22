"""Wrist camera: latest frame in the background, Claude to find an object once, local tracking after.

Claude is slow (~3 s from here) but understands any description; template matching is instant but
only follows what it was shown. So: Claude finds the object, its box becomes the template, and the
template is followed frame to frame while the arm turns or moves closer.
"""
import os
import threading
import time

import cv2

import planner

CAMERA_INDEX = int(os.environ.get("BRAIN_CAMERA", "0"))  # OpenCV index of the wrist camera
SEND_SIZE = (768, 432)  # what Claude sees


class Camera:
    def __init__(self, index: int = CAMERA_INDEX):
        self.lock = threading.Lock()
        self.frame = None
        self.stamp = 0.0
        threading.Thread(target=self._run, args=(index,), daemon=True).start()

    def _run(self, index):
        cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        while True:
            ok, frame = cap.read()
            if ok:
                with self.lock:
                    self.frame, self.stamp = frame, time.time()
            else:
                time.sleep(0.1)

    def latest(self, newer_than: float = 0.0, timeout: float = 2.0):
        """A frame captured after `newer_than` (so it shows the arm where it is now)."""
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if self.frame is not None and self.stamp > newer_than:
                    return self.frame.copy()
            time.sleep(0.02)
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def jpeg(self, frame=None, size=SEND_SIZE, quality=80) -> bytes | None:
        frame = self.latest() if frame is None else frame
        if frame is None:
            return None
        return cv2.imencode(".jpg", cv2.resize(frame, size), [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()


class Target:
    """An object found by Claude, followed locally by template matching."""

    def __init__(self, frame, box):
        self.box = box  # normalized center x, y, w, h
        self._set_template(frame, box)

    def _set_template(self, frame, box):
        h, w = frame.shape[:2]
        bw, bh = max(16, int(box["w"] * w)), max(16, int(box["h"] * h))
        x0, y0 = max(0, int(box["x"] * w - bw / 2)), max(0, int(box["y"] * h - bh / 2))
        self.template = cv2.cvtColor(frame[y0:y0 + bh, x0:x0 + bw], cv2.COLOR_BGR2GRAY)

    def follow(self, frame) -> dict | None:
        """New normalized box in `frame`, or None when lost. Tries a few scales (it grows as the arm nears)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        best = None
        for scale in (0.85, 1.0, 1.15, 1.3):
            t = cv2.resize(self.template, None, fx=scale, fy=scale)
            if t.shape[0] >= gray.shape[0] or t.shape[1] >= gray.shape[1]:
                continue
            _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
            if best is None or score > best[0]:
                best = (score, loc, t.shape)
        if best is None or best[0] < 0.55:
            return None
        _, (x0, y0), (th, tw) = best
        h, w = gray.shape
        self.box = {"x": (x0 + tw / 2) / w, "y": (y0 + th / 2) / h, "w": tw / w, "h": th / h}
        self._set_template(frame, self.box)  # keep up with the changing view
        return self.box


def find(camera: Camera, description: str, after: float = 0.0) -> Target | None:
    """Ask Claude where `description` is in a fresh frame; None if it is not visible."""
    frame = camera.latest(newer_than=after)
    if frame is None:
        return None
    box = planner.locate(camera.jpeg(frame), description)
    return Target(frame, box) if box else None


def annotate(frame, box, color=(0, 255, 0)):
    h, w = frame.shape[:2]
    x0, y0 = int((box["x"] - box["w"] / 2) * w), int((box["y"] - box["h"] / 2) * h)
    x1, y1 = int((box["x"] + box["w"] / 2) * w), int((box["y"] + box["h"] / 2) * h)
    cv2.rectangle(frame, (x0, y0), (x1, y1), color, 4)
    return frame
