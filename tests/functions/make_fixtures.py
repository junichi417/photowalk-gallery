"""検査用のJPEGを作る（位置情報つき・偽装・壊れたファイルなど）。実在の写真は使わない。"""
import io, sys
from pathlib import Path
from PIL import Image, ImageDraw

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)

def base(w, h, mode="RGB"):
    img = Image.new("RGB", (w, h), (40, 90, 110))
    d = ImageDraw.Draw(img)
    for x in range(0, w, 40):
        d.line([(x, 0), (w - x, h)], fill=(220, 160, 90), width=6)
    return img.convert(mode)

def gps_exif():
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"          # メーカー
    exif[0x0110] = "Model-X"             # 機種
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"; gps[2] = (34.0, 44.0, 12.5)   # 緯度
    gps[3] = "E"; gps[4] = (139.0, 24.0, 3.0)   # 経度
    return exif.tobytes()

img = base(1600, 1067)
icc = b"\x00" * 128 + b"fake-icc-profile"
img.save(out / "gps.jpg", "JPEG", quality=85, exif=gps_exif(), icc_profile=icc, comment=b"secret comment")
img.save(out / "prog.jpg", "JPEG", quality=85, progressive=True, exif=gps_exif())
img.resize((640, 427)).save(out / "thumb.jpg", "JPEG", quality=80)
img.resize((640, 640)).save(out / "thumb_mismatch.jpg", "JPEG", quality=80)
base(800, 600, "L").save(out / "gray.jpg", "JPEG", quality=85)
base(800, 600, "CMYK").save(out / "cmyk.jpg", "JPEG", quality=85)
base(3000, 2000).save(out / "huge_dims.jpg", "JPEG", quality=60)
base(400, 300).save(out / "photo.png", "PNG")
raw = (out / "gps.jpg").read_bytes()
(out / "trailing.jpg").write_bytes(raw + b"PK\x03\x04hidden-zip-or-html<script>alert(1)</script>")
(out / "truncated.jpg").write_bytes(raw[: len(raw) * 6 // 10])
(out / "fake.jpg").write_bytes(b"\xff\xd8<html><script>alert(1)</script></html>")
# 確認：作った gps.jpg に本当に位置情報が入っているか
ex = Image.open(out / "gps.jpg").getexif().get_ifd(0x8825)
assert ex.get(2) is not None, "GPSが入っていない"
print("fixtures ok:", sorted(p.name for p in out.iterdir()))
