"""複数イベントの同時公開（publish）のテスト。
伊豆大島=静的版（archive）と小豆島=受付中（live）を、1回のビルドで同じ dist に入れ、
両方が表示でき、ルートの OGP（伊豆大島）が変わらず、安全確認の許可範囲も守られることを確かめる。
Supabase の公開APIをまねた偽サーバーを使う。使い方: python3 tests/test_publish.py <fixturesフォルダ>
"""
import functools, http.server, json, shutil, subprocess, sys, tempfile, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FX = Path(sys.argv[1])
PORT, PAGE = 8793, 8794
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"  ← {detail}"))

IZU, SHO = "izu-oshima-2026", "shodoshima-2026"
def rows(ev, n, pid, name):
    return [
        {"id": f"00000000-0000-4000-8000-00000000010{i}", "full_path": f"{ev}/00000000-0000-4000-8000-00000000010{i}.jpg",
         "thumb_path": f"{ev}/00000000-0000-4000-8000-00000000010{i}_t.jpg", "width": 1600, "height": 1067,
         "thumb_width": 640, "thumb_height": 427, "created_at": "2026-10-25T00:00:00Z",
         "participant_id": pid, "display_name": name, "sns_url": None}
        for i in range(1, n + 1)
    ]
GALLERY = {IZU: rows(IZU, 3, "pa", "テストA"), SHO: rows(SHO, 2, "ps", "テストS")}
FULL, THUMB = (FX / "gps.jpg").read_bytes(), (FX / "thumb.jpg").read_bytes()

class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        ev = body.get("p_event")
        if self.headers["apikey"] != "anon-test":
            self.send_response(401); self.end_headers(); return
        if self.path == "/rest/v1/rpc/get_gallery" and ev in GALLERY:
            payload = json.dumps(GALLERY[ev]).encode()
        elif self.path == "/rest/v1/rpc/get_event_status" and ev in GALLERY:
            payload = json.dumps([{"accepting": ev == SHO}]).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        self.wfile.write(payload)
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "apikey, content-type, authorization")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS"); self.end_headers()
    def do_GET(self):
        if self.path.startswith("/storage/v1/object/public/gallery/"):
            self.send_response(200); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
            self.wfile.write(THUMB if self.path.endswith("_t.jpg") else FULL)
        else:
            self.send_response(404); self.end_headers()

srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp(prefix="publish-"))
dist = tmp / "dist"

def run(*cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

try:
    print("\n■ 同時公開ビルド（伊豆大島:archive ＋ 小豆島:live）")
    r = run("python3", "tools/build_site.py", "publish", "--plan", f"{IZU}:archive,{SHO}:live",
            "--url", f"http://127.0.0.1:{PORT}", "--anon-key", "anon-test", "--out", str(dist))
    check("ビルドが成功する", r.returncode == 0, r.stderr or r.stdout)

    site = json.loads((dist / "site.json").read_text())
    check("site.json の Supabase 設定は live 用に入り、default_event は伊豆大島のまま",
          site["supabase"]["anon_key"] == "anon-test" and site["default_event"] == IZU, site)

    izu = dist / "events" / IZU
    ev = json.loads((izu / "event.json").read_text())
    m = json.loads((izu / "manifest.json").read_text())
    check("伊豆大島は静的版（source=static・写真3枚・manifest 3件）",
          ev["source"] == "static" and len(list((izu / "photos").glob("*.jpg"))) == 6 and m["count"] == 3, ev.get("source"))

    sho = dist / "events" / SHO
    ev = json.loads((sho / "event.json").read_text())
    check("小豆島は live（source=supabase・写真ファイルは持たない）",
          ev["source"] == "supabase" and not (sho / "photos").exists(), ev.get("source"))
    check("小豆島のトップ写真・OGP画像は dist に入る", (sho / "hero.jpg").exists() and (sho / "ogp.jpg").exists())

    check("ルートの index.html はリポジトリのものと同一（OGPは伊豆大島のまま変わらない）",
          (dist / "index.html").read_bytes() == (ROOT / "index.html").read_bytes())
    check("両イベントの OGP 用静的ページが出る", (dist / IZU / "index.html").exists() and (dist / SHO / "index.html").exists())
    sho_page = (dist / SHO / "index.html").read_text()
    check("小豆島ページの OGP 画像は小豆島の ogp.jpg", f"events/{SHO}/ogp.jpg" in sho_page)

    print("\n■ 公開前の画像チェック（pages.yml と同じ条件）")
    find_cmd = ("find dist -type f \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \\) "
                "! -path 'dist/assets/hero.jpg' ! -path 'dist/events/*/hero.jpg' ! -path 'dist/events/*/ogp.jpg' "
                "! -path 'dist/events/izu-oshima-2026/photos/*'")
    r = subprocess.run(find_cmd, shell=True, cwd=tmp, capture_output=True, text=True)
    check("同時公開の dist はチェックを通る（違反0件）", r.stdout.strip() == "", r.stdout)
    (sho / "stray.jpg").write_bytes(FULL)
    r = subprocess.run(find_cmd, shell=True, cwd=tmp, capture_output=True, text=True)
    check("小豆島側に写真ファイルを置くと違反として検出される", "stray.jpg" in r.stdout, r.stdout)
    (sho / "stray.jpg").unlink()
    (izu / "extra.jpg").write_bytes(FULL)
    r = subprocess.run(find_cmd, shell=True, cwd=tmp, capture_output=True, text=True)
    check("伊豆大島でも photos/ の外の画像は違反になる", "extra.jpg" in r.stdout, r.stdout)
    (izu / "extra.jpg").unlink()

    print("\n■ 手元表示（同じ dist で両方）")
    Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    Handler.log_message = lambda self, *a: None
    page = http.server.ThreadingHTTPServer(("127.0.0.1", PAGE), Handler)
    threading.Thread(target=page.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg.clock.set_fixed_time("2026-11-10T03:00:00Z")
        pg.goto(f"http://127.0.0.1:{PAGE}/"); pg.wait_for_timeout(800)
        check("ルート（伊豆大島・静的版）が Supabase 設定入りの site.json でも表示される（3枚）",
              pg.locator(".tile").count() == 3, pg.locator("#count").inner_text())
        check("伊豆大島は「写真の受付は終了しました」", pg.locator("#status").inner_text() == "写真の受付は終了しました")
        pg.goto(f"http://127.0.0.1:{PAGE}/?e={SHO}"); pg.wait_for_timeout(800)
        check("小豆島（live）が同じ dist で表示される（2枚・サーバーから取得）",
              pg.locator(".tile").count() == 2, pg.locator("#count").inner_text())
        check("小豆島のトップ写真が差し替わる", "shodoshima" in (pg.locator("#hero-img").get_attribute("src") or ""))
        pg.goto(f"http://127.0.0.1:{PAGE}/admin.html?e={SHO}"); pg.wait_for_timeout(800)
        body = pg.locator("body").inner_text()
        check("管理画面（admin.html?e=小豆島）が開ける", pg.locator("h1").count() >= 0 and "管理" in body, body[:80])
        b.close()
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n結果: {sum(results)} / {len(results)} 件 合格")
sys.exit(0 if all(results) else 1)
