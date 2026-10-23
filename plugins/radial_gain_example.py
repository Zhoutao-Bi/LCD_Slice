"""Example grayscale exposure compensation; starts with zero correction.

Set STRENGTH to e.g. 0.15 to reduce central intensity relative to edges.
This is an integration example, not a calibrated optical compensation model.
"""
import numpy as np

STRENGTH = 0.0


def process(image, context):
    if STRENGTH == 0:
        return image
    height, width = image.shape
    # Row blocks avoid allocating multiple full-resolution float arrays.
    x = np.linspace(-1, 1, width, dtype=np.float32)[None, :]
    for top in range(0, height, 128):
        stop = min(top + 128, height)
        y = (np.arange(top, stop, dtype=np.float32) / max(1, height - 1) * 2 - 1)[:, None]
        gain = np.clip(1 - STRENGTH * (1 - (x * x + y * y) / 2), 0, 1)
        image[top:stop] = np.clip(image[top:stop] * gain, 0, 255).astype(np.uint8)
    return image
