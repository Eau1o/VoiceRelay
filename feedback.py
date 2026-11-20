import logging
import winsound

TONES = {"TYPELESS": (1200, 80), "WETYPE": (600, 80), "denied": (300, 150),
         "exhausted": (300, 150), "restored": (900, 120), "warning": (850, 80)}


def play(event):
    try:
        winsound.Beep(*TONES[event])
    except RuntimeError:
        try:
            winsound.MessageBeep()
        except RuntimeError:
            logging.warning("feedback_unavailable")
