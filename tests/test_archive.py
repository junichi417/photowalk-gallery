"""締切後の保存（静的版への書き出し・削除依頼・履歴を残さない公開）のテスト。
Supabase の公開APIをまねた偽サーバーから書き出して確かめる。
使い方: python3 tests/test_archive.py <fixturesフォルダ>
"""
import functools, http.server, json, shutil, subprocess, sys, tempfile, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FX = Path(sys.argv[1])
PORT, PAGE = 8791, 8792
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"  ← {detail}"))

EV = "izu-oshima-2026"
ROWS = [
    {"id": f"00000000-0000-4000-8000-00000000000{i}", "full_path": f"{EV}/00000000-0000-4000-8000-00000000000{i}.jpg",
     "thumb_path": f"{EV}/00000000-0000-4000-8000-00000000000{i}_t.jpg", "width": 1600, "height": 1067,
     "thumb_width": 640, "thumb_height": 427, "created_at": "2026-10-25T00:00:00Z",
     "participant_id": pid, "display_name": name, "sns_url": sns}
    for i, (pid, name, sns) in enumerate([("pa", "テストA", "https://example.com/a"), ("pa", "テストA", "https://example.com/a"), ("pb", None, None)], 1)
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
tmp = Path(tempfile.mkdtemp(prefix="archive-"))
dist = tmp / "dist"

def run(*cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

try:
    print("\n■ 受付中の公開版（live）")
    r = run("python3", "tools/build_site.py", "live", "--url", f"http://127.0.0.1:{PORT}", "--anon-key", "anon-test", "--out", str(dist))
    site = json.loads((dist / "site.json").read_text())
    ev = json.loads((dist / f"events/{EV}/event.json").read_text())
    check("公開用キーだけが入り、写真は含まない", r.returncode == 0 and site["supabase"]["anon_key"] == "anon-test" and ev["source"] == "supabase" and not (dist / f"events/{EV}/photos").exists(), r.stderr)

    print("\n■ 締切後の保存（archive）")
    r = run("python3", "tools/build_site.py", "archive", "--url", f"http://127.0.0.1:{PORT}", "--anon-key", "anon-test", "--out", str(dist))
    check("公開中の写真3枚を書き出せる", r.returncode == 0, r.stderr)
    evd = dist / "events" / EV
    photos = json.loads((evd / "photos.json").read_text())
    check("写真3枚分の拡大用・サムネイル（6ファイル）が保存される", len(photos) == 3 and len(list((evd / "photos").glob("*.jpg"))) == 6)
    site = json.loads((dist / "site.json").read_text())
    ev = json.loads((evd / "event.json").read_text())
    check("静的版は Supabase を使わない（キーも消える）", site["supabase"]["url"] == "" and site["supabase"]["anon_key"] == "" and ev["source"] == "static")
    check("受付は閉じた状態になる", ev["submission_open"] is False)
    m = json.loads((evd / "manifest.json").read_text())
    check("ファイルの一覧と照合用の値（sha256）が残る", m["count"] == 3 and len(m["files"]) == 6 and all(len(f["sha256"]) == 64 for f in m["files"]))

    Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    Handler.log_message = lambda self, *a: None
    page = http.server.ThreadingHTTPServer(("127.0.0.1", PAGE), Handler)
    threading.Thread(target=page.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg.clock.set_fixed_time("2026-11-01T03:00:00Z")
        pg.goto(f"http://127.0.0.1:{PAGE}/"); pg.wait_for_timeout(800)
        check("Supabaseなしでギャラリーが表示される（3枚）", pg.locator(".tile").count() == 3, pg.locator("#count").inner_text())
        check("「写真の受付は終了しました」と表示", pg.locator("#status").inner_text() == "写真の受付は終了しました")
        check("撮影者の名前で絞り込める（名前なしの人は一覧に出ない）", pg.locator("#people button").all_inner_texts() == ["すべての写真", "テストA"], pg.locator("#people button").all_inner_texts())
        broken = pg.evaluate("[...document.querySelectorAll('.tile img')].filter(i => i.complete && i.naturalWidth === 0).length")
        check("壊れた画像がない", broken == 0, broken)
        pg.goto(f"http://127.0.0.1:{PAGE}/post.html"); pg.wait_for_timeout(500)
        check("投稿画面も「写真の受付は終了しました」", pg.locator("#status").inner_text() == "写真の受付は終了しました")
        b.close()

    print("\n■ 削除依頼（締切後）")
    target = ROWS[2]["id"]
    r = run("python3", "tools/remove_photo.py", target, "--dist", str(dist))
    photos = json.loads((evd / "photos.json").read_text())
    people = json.loads((evd / "participants.json").read_text())
    check("指定した写真をファイルごと削除", r.returncode == 0 and len(photos) == 2 and not (evd / f"photos/{target}.jpg").exists() and not (evd / f"photos/{target}_t.jpg").exists(), r.stderr)
    check("写真が0枚になった人は撮影者一覧からも消える", [x["id"] for x in people] == ["pa"], people)
    r = run("python3", "tools/remove_photo.py", "no-such-id", "--dist", str(dist))
    check("存在しないIDはエラーで止まる（ほかを消さない）", r.returncode != 0 and len(json.loads((evd / "photos.json").read_text())) == 2)

    print("\n■ 履歴を残さない公開（gh-pages）")
    bare = tmp / "remote.git"
    run("git", "init", "-q", "--bare", str(bare))
    # 削除前の版を一度公開 → 削除後の版を公開、の順で確かめる
    before = tmp / "before"
    shutil.copytree(dist, before)
    shutil.copy2(FX / "gps.jpg", before / f"events/{EV}/photos/{target}.jpg")
    r1 = run("bash", "tools/publish_pages.sh", str(before), str(bare))
    r2 = run("bash", "tools/publish_pages.sh", str(dist), str(bare))
    count = run("git", "-C", str(bare), "rev-list", "--count", "gh-pages").stdout.strip()
    objs = run("git", "-C", str(bare), "rev-list", "--objects", "gh-pages").stdout
    check("公開できる", r1.returncode == 0 and r2.returncode == 0, r1.stderr + r2.stderr)
    check("gh-pages は常に1コミットだけ（過去の版を持たない）", count == "1", count)
    check("削除した写真は gh-pages の履歴からもたどれない", target not in objs)
    leak = tmp / "leak"; shutil.copytree(dist, leak)
    (leak / "x.js").write_text("const k='service_role'")
    r = run("bash", "tools/publish_pages.sh", str(leak), str(bare))
    check("秘密鍵らしき文字列があると公開を止める", r.returncode != 0 and "中止" in r.stderr, r.stderr)
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n結果: {sum(results)} / {len(results)} 件 合格")
sys.exit(0 if all(results) else 1)
