#!/usr/bin/env python3
"""Generate cloudy icon PNGs from the SVG.

Requires: pip install cairosvg
Usage:    python generate-icons.py
"""
import cairosvg

SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="#3f6212" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M17.5 21H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
  <path d="M22 10a3 3 0 0 0-3-3h-2.207a5.502 5.502 0 0 0-10.702.5" />
</svg>
"""

sizes = [
    (16, "icon-16.png"),
    (32, "icon-32.png"),
    (48, "icon.png"),
    (128, "icon-128.png"),
]

for size, filename in sizes:
    cairosvg.svg2png(
        bytestring=SVG.encode(),
        write_to=filename,
        output_width=size,
        output_height=size,
    )
    print(f"Generated {filename} ({size}x{size})")

print("All icons generated successfully!")
