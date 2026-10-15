"""端末側の写真の作り直し（assets/image-prep.js）を本物のブラウザ（Chromium）で確認する。
使い方: python3 tests/browser/test_image_prep.py <fixturesフォルダ>
"""
import base64, io, json, subprocess, sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FX = Path(sys.argv[1])
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"  ← {detail}"))

def info(b):
    im = Image.open(io.BytesIO(b)); im.load()
    ex = im.getexif()
    return {"size": im.size, "exif": len(ex), "gps": len(ex.get_ifd(0x8825)), "fmt": im.format}

def server_accepts(b, limits):
    """サーバー側の検査（jpeg.ts）にも通るか"""
    p = FX / "_out.jpg"; p.write_bytes(b)
    js = f"""import {{ sanitizeJpeg }} from '{ROOT}/supabase/functions/_shared/jpeg.ts';
import {{ readFileSync }} from 'node:fs';
const r = sanitizeJpeg(new Uint8Array(readFileSync('{p}')), {json.dumps(limits)});
console.log(r.width + 'x' + r.height);"""
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", js], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout or r.stderr).strip()

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.route("http://t.test/**", lambda route: route.fulfill(
        path=str(ROOT / "assets/image-prep.js") if route.request.url.endswith("image-prep.js") else str(FX / route.request.url.rsplit("/", 1)[1])))
    pg.route("http://t.test/", lambda route: route.fulfill(body="<!doctype html><script src='/image-prep.js'></script>", content_type="text/html"))
    pg.goto("http://t.test/")

    def prep(name, mime="image/jpeg"):
        return pg.evaluate("""async ([name, mime]) => {
          const buf = await (await fetch('/' + name)).arrayBuffer();
          const file = new File([buf], name, { type: mime });
          try {
            const r = await ImagePrep.prepareImage(file);
            const b64 = async (blob) => { const a = new Uint8Array(await blob.arrayBuffer()); let s=''; for (const x of a) s += String.fromCharCode(x); return btoa(s); };
            return { ok: true, full: await b64(r.full), thumb: await b64(r.thumb), w: r.width, h: r.height, tw: r.thumbWidth, th: r.thumbHeight };
          } catch (e) { return { ok: false, code: e.code, message: e.message }; }
        }""", [name, mime])

    print("\n■ 端末側での写真の作り直し（Chromium）")
    r = prep("gps.jpg")
    full, thumb = base64.b64decode(r["full"]), base64.b64decode(r["thumb"])
    i, t = info(full), info(thumb)
    check("位置情報つき写真 → 作り直した写真に EXIF・GPS が無い", i["exif"] == 0 and i["gps"] == 0 and t["exif"] == 0, i)
    check("大きさはそのまま（2048px以下なので縮めない）", i["size"] == (1600, 1067), i["size"])
    check("サムネイルは長い辺640px", t["size"] == (640, 427), t["size"])
    ok, d = server_accepts(full, {"maxWidth": 2048, "maxHeight": 2048, "maxBytes": 4194304})
    check("作り直した写真はサーバーの検査にも通る", ok, d)
    ok, d = server_accepts(thumb, {"maxWidth": 640, "maxHeight": 640, "maxBytes": 409600})
    check("サムネイルもサーバーの検査に通る", ok, d)

    r = prep("phone_4032.jpg")
    i = info(base64.b64decode(r["full"]))
    check("スマホの大きな写真（4032×3024）→ 2048×1536 に縮める", i["size"] == (2048, 1536) and i["gps"] == 0, i)
    check("縮めた写真の容量は4MB以下", len(base64.b64decode(r["full"])) < 4 * 1024 * 1024, len(r["full"]))

    r = prep("orient6.jpg")
    i = info(base64.b64decode(r["full"]))
    check("縦撮り（向き情報つき）→ 正しい向きの縦長で保存し、向き情報は残さない", i["size"] == (1067, 1600) and i["exif"] == 0, i)

    r = prep("alpha.png", "image/png")
    i = info(base64.b64decode(r["full"]))
    check("透過PNG → JPEGに変換（透明部分は白）", i["fmt"] == "JPEG" and i["size"] == (900, 600), i)

    r = prep("fake.jpg")
    check("画像でないファイル → 読み込めないと伝える", not r["ok"] and r["code"] == "decode_failed", r)

    r = pg.evaluate("""async () => {
      const f = new File([new Uint8Array(11 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' });
      try { await ImagePrep.prepareImage(f); return '通ってしまった'; } catch (e) { return e.code; } }""")
    check("10MBを超える写真 → 選び直しを案内", r == "too_large", r)

    r = pg.evaluate("""async () => {
      const f = new File(['<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'], 'x.svg', { type: 'image/svg+xml' });
      try { await ImagePrep.prepareImage(f); return '通ってしまった'; } catch (e) { return e.code; } }""")
    check("SVG（スクリプトを含められる形式）→ 受け付けない", r == "bad_type", r)
    b.close()

print(f"\n結果: {sum(results)} / {len(results)} 件 合格")
sys.exit(0 if all(results) else 1)
