"""仮画像を生成する（本番写真ではない）。実在の人物・場所の写真は含まない。
使い方: python3 tools/make_placeholders.py events/izu-oshima-2026
"""
import json, sys, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
# テーマ（予定している撮影場所の雰囲気）に合わせた色の組
THEMES = [
    ("裏砂漠", (58, 54, 52), (120, 110, 104)),
    ("海", (34, 78, 96), (120, 170, 185)),
    ("夕景", (178, 92, 60), (238, 190, 120)),
    ("街並み", (110, 106, 96), (200, 194, 180)),
    ("ポートレート", (90, 80, 86), (196, 172, 168)),
]
SIZES = [(1600, 1067), (1067, 1600), (1600, 1200), (1200, 1600), (1600, 900), (1400, 1400)]

def gradient(w, h, c1, c2):
    img = Image.new("RGB", (w, h), c1)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    return img

def main(event_dir):
    out = Path(event_dir) / "photos"
    out.mkdir(parents=True, exist_ok=True)
    random.seed(1015)
    photos = []
    for i in range(14):
        theme, c1, c2 = THEMES[i % len(THEMES)]
        w, h = SIZES[i % len(SIZES)]
        img = gradient(w, h, c1, c2)
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(FONT, int(min(w, h) * 0.07))
        label = f"仮画像 {i+1:02d}\n{theme}"
        d.multiline_text((w * 0.06, h * 0.08), label, font=f, fill=(255, 255, 255), spacing=12)
        name = f"placeholder-{i+1:02d}.jpg"
        img.save(out / name, "JPEG", quality=72, optimize=True)
        photos.append({
            "id": f"p{i+1:02d}",
            "src": f"photos/{name}",
            "width": w, "height": h,
            "alt": f"仮画像（{theme}）",
            # p13 / p14 は表示名なしの投稿者を想定した確認用
            "participant_id": None if i >= 12 else f"dummy-{'abc'[i % 3]}",
        })
    (Path(event_dir) / "photos.json").write_text(json.dumps(photos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(photos)} placeholders -> {out}")

if __name__ == "__main__":
    main(sys.argv[1])
