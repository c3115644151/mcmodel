"""Crop one item icon out of a container screenshot and print a colour census.

Guessing a crop box, or hunting for warm pixels, both fail on a real screen: JEI's item list, the
wooden UI and the player's own copy of the icon are all the same colour. A container screen is
laid out from a flat panel, so the panel is found first - the largest block of vanilla's container
grey - and the first slot is then a fixed offset inside it. The GUI scale must come from the slot
frame pitch, not from the panel's own width: the panel's outer shadow columns are close enough to
the panel grey to widen the measured box, which yields a fractional scale and crops that land a few
game pixels off every slot.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

PANEL_GREY = (198, 198, 198)
# The 16x16 item draw area inside each slot is a flat opaque #8B8B8B.
SLOT_BACKGROUND = (139, 139, 139)
# The vanilla container texture is 176x166 at scale 1 and its first slot starts at (8, 18).
PANEL_SIZE = (176, 166)
SLOT_INSET = (8, 18)
SLOT_SIZE = 18


def panel_origin(pixels, tolerance=3):
    """Bounding box of the flat container panel, which anchors every slot on the screen."""
    distance = np.abs(pixels[:, :, :3].astype(np.int16) - np.array(PANEL_GREY, dtype=np.int16)).sum(axis=2)
    mask = distance <= tolerance * 3
    # The panel is one large rectangle, so its rows and columns are dense: take the extremes of the
    # dense rows instead of the extremes of every stray pixel of similar grey.
    rows = np.where(mask.sum(axis=1) > 80)[0]
    cols = np.where(mask.sum(axis=0) > 60)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1


def _longest_dark_run(line):
    padded = np.concatenate(([False], line, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return int((edges[1::2] - edges[0::2]).max()) if edges.size >= 2 else 0


def _band_starts(lines, min_run):
    """Start rows/columns of contiguous long dark runs, with each run's length."""
    bands = []
    for index, line in enumerate(lines):
        run = _longest_dark_run(line)
        if run >= min_run:
            bands.append((index, run))
    if not bands:
        return []
    grouped = []
    for index, run in bands:
        if grouped and index - grouped[-1][-1][0] <= 1:
            grouped[-1].append((index, run))
        else:
            grouped.append([(index, run)])
    return [(group[0][0], max(run for _index, run in group)) for group in grouped]


def _consistent_pitch(bands):
    """Keep the largest arithmetic run of bands: the slot grid, not JEI's item list.

    The screen carries more than one grid (JEI's item panel has its own slot lines with
    a different stride), so a single adaptive run-length threshold cannot separate them.
    The container slots are the bands that repeat with one constant pitch.
    """
    if len(bands) < 2:
        return []
    starts = [start for start, _run in bands]
    diffs = [starts[index + 1] - starts[index] for index in range(len(starts) - 1)]
    best = []
    for pitch in sorted(set(diffs)):
        chain = [starts[0]] if diffs[0] == pitch else []
        for index, diff in enumerate(diffs):
            if diff == pitch:
                if not chain:
                    chain = [starts[index]]
                chain.append(starts[index + 1])
            elif chain:
                break
        if len(chain) > len(best):
            best = chain
    return best


def slot_grid(pixels):
    """Recover the container slot grid from the slot border lines themselves.

    Deriving the GUI scale from the panel bounding box is unreliable: the panel's
    outer shadow columns sit within tolerance of the panel grey, so the measured
    width comes out fractional (measured 3.86 for a true GUI scale of 4) and every
    crop lands a few game pixels off. The slot frames are exact instead - each
    18x18 vanilla slot is a 1px dark (#373737) top/left edge, a 16x16 #8B8B8B draw
    area, and a 1px white bottom/right highlight - so their pitch gives the scale.

    Scans stay inside the container panel so an open JEI item panel (a second grid
    with its own stride, drawn beside the container) cannot take over the search.

    Returns (x0, y0, pitch, scale): x0/y0 are the top-left screen pixel of the
    slot(0,0) draw area, pitch is the slot stride in screen pixels.
    """
    dark = np.all(np.abs(pixels[:, :, :3].astype(np.int16) - 55) <= 3, axis=2)
    panel = panel_origin(pixels)
    if panel is None:
        return None
    left, top, right, bottom = panel
    left, top = max(0, left), max(0, top)
    right = min(dark.shape[1], right)
    bottom = min(dark.shape[0], bottom)

    rows = _consistent_pitch(_band_starts(dark[top:bottom, left:right], 40))
    columns = _consistent_pitch(_band_starts(dark[top:bottom, left:right].T, 40))
    if len(rows) < 2 or len(columns) < 2:
        return None
    row_pitch = int(np.median(np.diff(rows)))
    column_pitch = int(np.median(np.diff(columns)))
    scale = int(round(min(row_pitch, column_pitch) / float(SLOT_SIZE)))
    if scale < 1:
        return None
    return (left + columns[0] + scale, top + rows[0] + scale, column_pitch, scale)
