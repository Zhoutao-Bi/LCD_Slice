"""Minimal plugin contract. Receives and returns a writable H×W uint8 array.

context contains: layer_index (zero based), sample_z_mm, layer_top_mm,
layer_height_mm, resolution (W,H), build_size_mm (X,Y), pixel_size_mm (X,Y).
Called after edge compensation and gamma, before mirror/invert/manual edits.
The same function runs for previews, single-layer saves, and full exports.
"""

def process(image, context):
    return image
