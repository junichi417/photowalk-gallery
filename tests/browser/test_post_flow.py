"""投稿画面の流れを本物のブラウザで確認する（Supabase はテスト用の偽物、投稿処理は本物）。
使い方: python3 tests/browser/test_post_flow.py <fixturesフォルダ>
"""
import json, subprocess, sys, time, threading, functools, http.server, tempfile
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FX = Path(sys.argv[1])
PAGE_PORT, FN_PORT = 8766, 8790
ORIGIN = f"http://localhost:{PAGE_PORT}"
OUT = Path(tempfile.mkdtemp(prefix="uploads-"))
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"  ← {detail}"))

# ページ配信（リポジトリをそのまま）
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
Handler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PAGE_PORT), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
fn = subprocess.Popen(["node", "--experimental-strip-types", "--no-warnings", str(ROOT / "tests/browser/fake_functions_server.ts"),
                       str(FN_PORT), str(OUT), ORIGIN], stdout=subprocess.PIPE, text=True)
assert fn.stdout.readline().strip() == "ready"

site = json.loads((ROOT / "site.json").read_text())
site["supabase"] = {"url": f"http://localhost:{FN_PORT}", "anon_key": "anon-test"}
site["removal_contact"] = "（テスト用の連絡先）"

def new_page(b, init=None, clock=None):
    pg = b.new_page(viewport={"width": 390, "height": 844})
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    pg.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(path=str(ROOT / "tests/browser/fake_supabase.js"), content_type="text/javascript"))
    pg.route(f"{ORIGIN}/site.json", lambda r: r.fulfill(body=json.dumps(site), content_type="application/json"))
    if init: pg.add_init_script(f"window.__FAKE_INIT = {json.dumps(init)};")
    if clock: pg.clock.set_fixed_time(clock)
    pg.goto(f"{ORIGIN}/post.html")
    pg.wait_for_timeout(600)
    return pg

def visible(pg, sel): return pg.locator(sel).is_visible()
def msg(pg): return pg.locator("#message").inner_text() if visible(pg, "#message") else ""

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        print("\n■ 投稿画面の流れ（スマホ幅）")
        pg = new_page(b)
        check("受付中はメール入力から始まる", visible(pg, "#step-email") and "まで" in pg.locator("#status").inner_text())
        pg.fill("#email", "not-an-email"); pg.click("#form-email button")
        check("メールの形が違うと止まる", "確かめて" in msg(pg), msg(pg))
        pg.fill("#email", "Alice@Example.com"); pg.click("#form-email button"); pg.wait_for_timeout(200)
        check("コード入力に進み、送信先を表示", visible(pg, "#step-code") and "alice@example.com" in pg.locator("#sent-to").inner_text())
        check("送り直しは60秒間押せない", pg.locator("#resend").is_disabled())
        pg.fill("#code", "000000"); pg.click("#form-code button"); pg.wait_for_timeout(200)
        check("違うコードでは進めない", visible(pg, "#step-code") and "違うか" in msg(pg), msg(pg))
        pg.fill("#code", "123456"); pg.click("#form-code button"); pg.wait_for_timeout(300)
        check("正しいコードで参加登録（合言葉）に進む", visible(pg, "#step-join"))
        pg.fill("#invite", "wrong"); pg.click("#form-join button"); pg.wait_for_timeout(200)
        check("合言葉が違うと「合言葉が違います」", msg(pg) == "合言葉が違います", msg(pg))
        pg.fill("#invite", "ＯＳＨＩＭＡ-tsubaki-2026"); pg.fill("#sns", "javascript:alert(1)"); pg.click("#form-join button"); pg.wait_for_timeout(200)
        check("SNSに javascript: を入れると止まる", "https://" in msg(pg) and visible(pg, "#step-join"), msg(pg))
        pg.fill("#name", "テスト参加者"); pg.fill("#sns", "https://example.com/test"); pg.click("#form-join button"); pg.wait_for_timeout(300)
        check("正しい合言葉で投稿画面に進む", visible(pg, "#step-post"))
        check("掲載ルールと削除の連絡先が表示される", "誰でも見られます" in pg.locator("#rules").inner_text() and "テスト用の連絡先" in pg.locator("#rules").inner_text())
        check("残り枚数を表示（あと20枚）", "あと20枚" in pg.locator("#quota").inner_text(), pg.locator("#quota").inner_text())
        pg.set_input_files("#files", [str(FX / "gps.jpg"), str(FX / "orient6.jpg")])
        check("同意チェック前は投稿ボタンが押せない", pg.locator("#submit-post").is_disabled())
        pg.check("#consent-own")
        check("同意が1つだけでも押せない", pg.locator("#submit-post").is_disabled())
        pg.check("#consent-people")
        check("同意2つ＋写真で押せる", pg.locator("#submit-post").is_enabled())
        pg.click("#submit-post"); pg.wait_for_function("document.querySelectorAll('#queue .ok, #queue .ng').length === 2", timeout=20000)
        oks = pg.locator("#queue .ok").count()
        check("2枚とも「掲載しました」", oks == 2, pg.locator("#queue").inner_text())
        saved = sorted(OUT.glob("*.jpg"))
        check("サーバーに拡大用とサムネイルが2枚分（4ファイル）届いた", len(saved) == 4, [s.name for s in saved])
        gps = [len(Image.open(s).getexif().get_ifd(0x8825)) for s in saved]
        check("届いたファイルのどれにも位置情報が無い", all(g == 0 for g in gps), gps)
        sizes = {s.name: Image.open(s).size for s in saved}
        check("縦撮りの写真は縦長で届いた", sizes.get("ph2.jpg") == (1067, 1600), sizes)

        # 締切の瞬間に送信 → サーバーが拒否したら画面に「終了」を出す
        subprocess.run(["curl", "-s", f"http://localhost:{FN_PORT}/__close"], capture_output=True)
        pg.set_input_files("#files", [str(FX / "gps.jpg")]); pg.click("#submit-post")
        pg.wait_for_function("document.querySelectorAll('#queue .ng').length === 1", timeout=20000)
        check("画面上は受付中でも、サーバーが締切と判定したら投稿されない", "受付は終了しました" in pg.locator("#queue").inner_text(), pg.locator("#queue").inner_text())
        check("締切後に送ったファイルは保存されていない", len(list(OUT.glob("*.jpg"))) == 4)
        pg.screenshot(path=str(OUT / "post_done.png"), full_page=True)

        print("\n■ 受付状態")
        pg = new_page(b, init={"accepting": False, "ended": True})
        check("サーバーが締切後と判定 →「写真の受付は終了しました」だけ表示", pg.locator("#status").inner_text() == "写真の受付は終了しました" and not visible(pg, "#step-email"))
        pg = new_page(b, init={"accepting": False, "ended": False})
        check("受付開始前 →「準備中」、入力欄は出ない", "準備中" in pg.locator("#status").inner_text() and not visible(pg, "#step-email"))
        pg = new_page(b, clock="2026-10-31T15:00:01Z")
        check("端末の時計が締切後でも「終了」を表示", pg.locator("#status").inner_text() == "写真の受付は終了しました")
        pg = new_page(b, init={"attempts": 5, "session": {"access_token": "fake-token"}})
        pg.fill("#invite", "oshima-tsubaki-2026"); pg.click("#form-join button"); pg.wait_for_timeout(200)
        check("合言葉を5回間違えた後は、時間をおくよう案内", "時間をおいて" in msg(pg), msg(pg))
        b.close()
finally:
    fn.kill(); srv.shutdown()

print(f"\n結果: {sum(results)} / {len(results)} 件 合格")
print("スクリーンショット:", OUT / "post_done.png")
sys.exit(0 if all(results) else 1)
