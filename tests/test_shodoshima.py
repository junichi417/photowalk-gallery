"""小豆島イベント（shodoshima-2026）の追加ぶんのテスト。
仮画像・ダミー人物だけで確かめる。本番の写真・名前・合言葉は扱わない。
使い方: python3 tests/test_shodoshima.py <fixturesフォルダ>
"""
import functools, http.server, json, shutil, subprocess, sys, tempfile, threading
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FX = Path(sys.argv[1])
EV = "shodoshima-2026"
EVDIR = ROOT / "events" / EV
PORT, PAGE, ROOTPAGE = 8793, 8794, 8795
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"  ← {detail}"))

def run(*cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

print("\n■ イベント定義")
ev = json.loads((EVDIR / "event.json").read_text())
check("slug は shodoshima-2026", ev["slug"] == EV)
check("題名（full_title）は決まった文言どおり", ev["full_title"] == "小豆島へのフェリーと海の撮影旅", ev["full_title"])
check("題字は伊豆大島と同じ型（短い題＋副題）で背表紙に収まる", ev["title"] == "小豆島" and ev["subtitle"] == "フェリーと海の撮影旅", f"{ev['title']} / {ev['subtitle']}")
check("日付は 2026年11月7日", ev["dates_label"] == "2026年11月7日", ev["dates_label"])
check("投稿締切は 2026-11-30 23:59:59 JST（event.json が正）", ev["submission_deadline"] == "2026-11-30T23:59:59+09:00", ev["submission_deadline"])
check("締切ラベルは 11月30日（月）23:59", ev["submission_deadline_label"] == "11月30日（月）23:59", ev["submission_deadline_label"])
check("1人20枚まで", ev["max_photos_per_user"] == 20)
check("受付はまだ開いていない（開始は社長の判断）", ev["submission_open"] is False)

print("\n■ 参加者・写真（仮のものだけか）")
people = json.loads((EVDIR / "participants.json").read_text())
check("参加者はダミー3人だけ（実在の人物名・SNSを入れない）",
      len(people) == 3 and all(p["id"].startswith("dummy-") for p in people)
      and all(p["sns_url"] is None or p["sns_url"].startswith("https://example.com/") for p in people), people)
photos = json.loads((EVDIR / "photos.json").read_text())
check("仮画像の一覧がある", len(photos) >= 1)
ok_files, ok_exif = True, True
for p in photos:
    f = EVDIR / p["src"]
    if not f.exists():
        ok_files = False
        continue
    if Image.open(f).getexif():
        ok_exif = False
check("写真ファイルがすべて実在する", ok_files)
check("仮画像に位置情報などの EXIF がない", ok_exif)

print("\n■ トップ写真・OGP画像（社長選定の写真を加工）")
hero = Image.open(EVDIR / "hero.jpg")
check("トップ写真がある（1430×956・長辺2048以内）", hero.size == (1430, 956), hero.size)
check("トップ写真に EXIF（位置情報・機種など）が残っていない", not hero.getexif())
check("トップ写真の説明文が入っている", "防波堤" in ev["hero_alt"] and "帆船" in ev["hero_alt"], ev["hero_alt"])
ogp_path = EVDIR / ev["ogp_image"]
ogp = Image.open(ogp_path)
check("OGP画像は 1200×630（約1.91:1）", ogp.size == (1200, 630), ogp.size)
check("OGP画像は 5MB 以下で EXIF なし", ogp_path.stat().st_size < 5 * 1024 * 1024 and not ogp.getexif())

print("\n■ 伊豆大島が壊れていないこと")
site = json.loads((ROOT / "site.json").read_text())
check("default_event は伊豆大島のまま（勝手に切り替えない）", site["default_event"] == "izu-oshima-2026", site["default_event"])
izu = json.loads((ROOT / "events/izu-oshima-2026/event.json").read_text())
check("伊豆大島の締切は不変", izu["submission_deadline"] == "2026-10-31T23:59:59+09:00")

print("\n■ Supabase へのイベント追加（SQL）")
mig = (ROOT / "supabase/migrations/20261110000000_shodoshima_event.sql").read_text()
check("insert に slug・題名・締切が入っている",
      "'shodoshima-2026'" in mig and "小豆島へのフェリーと海の撮影旅" in mig and "2026-11-30T23:59:59+09:00" in mig)
check("二重登録しない（on conflict do nothing）", "on conflict (slug) do nothing" in mig)
check("合言葉・秘密鍵は書かれていない", "invite" not in mig and "service_role" not in mig and "sb_secret" not in mig)

# ---- live / archive の両方で静的ページが出ること ----
ROWS = [
    {"id": f"00000000-0000-4000-8000-00000000010{i}", "full_path": f"{EV}/00000000-0000-4000-8000-00000000010{i}.jpg",
     "thumb_path": f"{EV}/00000000-0000-4000-8000-00000000010{i}_t.jpg", "width": 1600, "height": 1067,
     "thumb_width": 640, "thumb_height": 427, "created_at": "2026-11-20T00:00:00Z",
     "participant_id": pid, "display_name": name, "sns_url": sns}
    for i, (pid, name, sns) in enumerate([("pa", "テストA", "https://example.com/a"), ("pb", None, None)], 1)
]
FULL, THUMB = (FX / "gps.jpg").read_bytes(), (FX / "thumb.jpg").read_bytes()

class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/rest/v1/rpc/get_gallery" and body == {"p_event": EV} and self.headers["apikey"] == "anon-test":
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps(ROWS).encode())
        else:
            self.send_response(401); self.end_headers()
    def do_GET(self):
        if self.path.startswith("/storage/v1/object/public/gallery/"):
            self.send_response(200); self.end_headers()
            self.wfile.write(THUMB if self.path.endswith("_t.jpg") else FULL)
        else:
            self.send_response(404); self.end_headers()

srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp(prefix="shodoshima-"))
dist = tmp / "dist"

def ogp_checks(mode):
    page = dist / EV / "index.html"
    check(f"{mode}: イベント専用の静的ページが出る", page.exists())
    if not page.exists():
        return
    html = page.read_text()
    check(f"{mode}: og:title が小豆島の題名", "時譜舎 写真帖｜小豆島へのフェリーと海の撮影旅" in html)
    check(f"{mode}: og:image は絶対URLで小豆島のOGP画像", 'og:image" content="https://junichi417.github.io/photowalk-gallery/events/shodoshima-2026/ogp.jpg"' in html)
    check(f"{mode}: twitter:card は summary_large_image", 'twitter:card" content="summary_large_image"' in html)
    check(f"{mode}: ギャラリー（?e=shodoshima-2026）への案内がある", "?e=shodoshima-2026" in html)
    check(f"{mode}: トップ写真とOGP画像が公開側に入る",
          (dist / "events" / EV / "hero.jpg").exists() and (dist / "events" / EV / "ogp.jpg").exists())

try:
    print("\n■ 受付中の公開版（live）")
    r = run("python3", "tools/build_site.py", "live", "--url", f"http://127.0.0.1:{PORT}", "--anon-key", "anon-test", "--event", EV, "--out", str(dist))
    check("live を組み立てられる", r.returncode == 0, r.stderr)
    ogp_checks("live")
    check("live: 参加者の写真は含まない（Supabaseから読む）", not (dist / "events" / EV / "photos").exists())
    main_html = (dist / "index.html").read_text()
    check("live: 本体 index.html のOGP（伊豆大島）は不変", "伊豆大島 フォトウォーク" in main_html)

    print("\n■ 締切後の保存（archive）")
    r = run("python3", "tools/build_site.py", "archive", "--url", f"http://127.0.0.1:{PORT}", "--anon-key", "anon-test", "--event", EV, "--out", str(dist))
    check("archive を組み立てられる", r.returncode == 0, r.stderr)
    ogp_checks("archive")
    arch = json.loads((dist / "events" / EV / "photos.json").read_text())
    check("archive: 公開中の写真2枚が保存される", len(arch) == 2)

    print("\n■ 手元表示（リポジトリ直下を配信）")
    Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    Handler.log_message = lambda self, *a: None
    page_srv = http.server.ThreadingHTTPServer(("127.0.0.1", ROOTPAGE), Handler)
    threading.Thread(target=page_srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.clock.set_fixed_time("2026-11-10T03:00:00Z")
            pg.goto(f"http://127.0.0.1:{ROOTPAGE}/?e={EV}"); pg.wait_for_timeout(800)
            check("小豆島ページの題名が表示される", "小豆島へのフェリーと海の撮影旅" in pg.title(), pg.title())
            check("仮画像が並ぶ", pg.locator(".tile").count() == len(photos), pg.locator("#count").inner_text())
            hero_src = pg.locator("#hero-img").get_attribute("src") or ""
            check("トップ写真が小豆島のものに差し替わる", hero_src.endswith(f"events/{EV}/hero.jpg"), hero_src)
            check("受付は準備中・締切つきで表示", pg.locator("#status").inner_text() == "写真の受付は準備中です（締切 11月30日（月）23:59）", pg.locator("#status").inner_text())
            pg.goto(f"http://127.0.0.1:{ROOTPAGE}/"); pg.wait_for_timeout(800)
            check("既定（伊豆大島）も表示できる", "伊豆大島" in pg.title(), pg.title())
            hero_src = pg.locator("#hero-img").get_attribute("src") or ""
            check("伊豆大島のトップ写真は既定のまま", hero_src.endswith("assets/hero.jpg"), hero_src)
            b.close()
    finally:
        page_srv.shutdown()
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n結果: {sum(results)} / {len(results)} 件 合格")
sys.exit(0 if all(results) else 1)
