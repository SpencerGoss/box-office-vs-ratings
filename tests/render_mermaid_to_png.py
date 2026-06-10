"""Render docs/architecture.mmd (Mermaid source) to docs/architecture.png.

Renders locally via Edge headless + mermaid.js from CDN (mermaid.ink proved
unreliable), then auto-crops the surrounding whitespace. Requires Pillow
(`pip install pillow`) for the crop step; skips cropping if unavailable.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "architecture.mmd"
TARGET = ROOT / "docs" / "architecture.png"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

HTML_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: true, theme: 'neutral', flowchart: {{ htmlLabels: true }} }});
</script>
<style>body{{margin:20px;background:white}}</style></head>
<body><pre class="mermaid">{src}</pre></body></html>"""


def main() -> int:
    src = SOURCE.read_text(encoding="utf-8")
    # strip Mermaid comment lines (%%) — they confuse the <pre> embedding
    src = "\n".join(l for l in src.splitlines() if not l.strip().startswith("%%"))
    escaped = src.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html_path = ROOT / "docs" / "_arch_render.html"
    html_path.write_text(HTML_TEMPLATE.format(src=escaped), encoding="utf-8")
    try:
        subprocess.run(
            [
                EDGE, "--headless", "--disable-gpu", "--window-size=1900,950",
                "--virtual-time-budget=8000", f"--screenshot={TARGET}",
                html_path.as_uri(),
            ],
            check=True, capture_output=True,
        )
        time.sleep(2)
    finally:
        html_path.unlink(missing_ok=True)

    try:
        from PIL import Image, ImageChops

        img = Image.open(TARGET).convert("RGB")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bbox = ImageChops.difference(img, bg).getbbox()
        if bbox:
            pad = 16
            img.crop((
                max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height),
            )).save(TARGET)
    except ImportError:
        print("Pillow not installed -- skipping whitespace crop.")

    print(f"Wrote {TARGET} ({TARGET.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
