"""Crop Map 3 (page 13 of Scenario1.pdf, rendered to data/map3_page-13.png)
to the map content area, make white transparent, and write the georeferenced
overlay bounds. Requires data/map3_calibration.json from the calibration step
(pixel extremes of the town boundary matched to its lat/lon bbox).

Outputs: data/map3_overlay.png, bounds added to data/map3_calibration.json.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

DATA = Path(__file__).parent / "data"
CROP = {"x0": 60, "x1": 1595, "y0": 340, "y1": 2100}  # keeps legend, drops title/footer


def main():
    cal = json.load(open(DATA / "map3_calibration.json"))
    px, geo = cal["px"], cal["geo"]

    im = Image.open(DATA / "map3_page-13.png").convert("RGB")
    im = im.crop((CROP["x0"], CROP["y0"], CROP["x1"], CROP["y1"]))
    a = np.array(im)

    rgba = np.dstack([a, np.full(a.shape[:2], 255, dtype=np.uint8)])
    white = (a > 235).all(axis=2)
    rgba[white, 3] = 0
    Image.fromarray(rgba).save(DATA / "map3_overlay.png")

    # linear px->deg from boundary calibration, evaluated at crop corners
    sx = (geo["east"] - geo["west"]) / (px["east"] - px["west"])
    sy = (geo["south"] - geo["north"]) / (px["south"] - px["north"])
    cal["overlay_bounds"] = {
        "west": geo["west"] + (CROP["x0"] - px["west"]) * sx,
        "east": geo["west"] + (CROP["x1"] - px["west"]) * sx,
        "north": geo["north"] + (CROP["y0"] - px["north"]) * sy,
        "south": geo["north"] + (CROP["y1"] - px["north"]) * sy,
    }
    json.dump(cal, open(DATA / "map3_calibration.json", "w"), indent=1)
    print("wrote data/map3_overlay.png", im.size, "bounds:", cal["overlay_bounds"])


if __name__ == "__main__":
    main()
