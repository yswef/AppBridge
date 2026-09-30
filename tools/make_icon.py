"""Render packaging/appbridge.ico (multi-size) from code, so no binary design tool is needed.

pip install pillow && python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "appbridge.ico"


def render(size: int = 256) -> Image.Image:
    s = size * 4  # supersample
    grad = Image.new("RGBA", (s, s))
    px = grad.load()
    a, b = (99, 102, 241), (20, 184, 166)
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * s)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 4, fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w = s // 12
    d.arc((s * 0.22, s * 0.30, s * 0.78, s * 0.86), 180, 360, fill="white", width=w)
    for x0 in (0.16, 0.69):
        d.rounded_rectangle((s * x0, s * 0.58, s * (x0 + 0.15), s * 0.82), radius=s // 25, fill="white")
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    render().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT}")
