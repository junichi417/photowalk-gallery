#!/usr/bin/env python3
"""公開用のサイト一式（dist/）を作る。

  live    投稿受付中：コードだけを置き、写真は Supabase から読む
          python3 tools/build_site.py live --url https://xxxx.supabase.co --anon-key <公開用キー>

  archive 締切後：公開中の写真をすべてダウンロードして、Supabase なしで動く静的サイトにする
          python3 tools/build_site.py archive --url https://xxxx.supabase.co --anon-key <公開用キー>

  publish 複数イベントの同時公開：イベントごとに live / archive を指定して、1つの dist に入れる
          python3 tools/build_site.py publish --plan izu-oshima-2026:archive,shodoshima-2026:live \
              --url https://xxxx.supabase.co --anon-key <公開用キー>
          静的版（archive）のイベントは events/<slug>/event.json の source が "static" になるため、
          site.json の Supabase 設定（live のイベント用）は静的版の表示に影響しない
          （assets/app.js は event.source で読み分けている）。

どれも dist/ に書き出す。dist/ は main ブランチには入れない（.gitignore 済み）。
公開は GitHub Actions（.github/workflows/pages.yml）から行う。
→ 写真が main の履歴に残らないので、削除依頼があれば本当に消せる。

使うのは公開用キー（anon）と、誰でも見られる一覧（get_gallery）だけ。秘密鍵は不要。
"""
import argparse, hashlib, json, re, shutil, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ["index.html", "post.html", "admin.html", "assets", "site.json"]
SITE_BASE_URL = "https://junichi417.github.io/photowalk-gallery/"
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

def http_json(url, anon, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"apikey": anon, "Authorization": f"Bearer {anon}", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def download(url, dest):
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    dest.write_bytes(data)
    return data

def copy_code(dist, slugs):
    """コード一式と、各イベントの event.json・トップ写真・OGP画像を dist に置く（dist は作り直す）。"""
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    for name in CODE:
        src = ROOT / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dist / name)
    for slug in slugs:
        (dist / "events" / slug).mkdir(parents=True)
        shutil.copy2(ROOT / "events" / slug / "event.json", dist / "events" / slug / "event.json")
        # イベント固有のトップ写真・OGP画像（あれば）も公開側へ。画像チェックの例外は
        # .github/workflows/pages.yml 側で events/*/hero.jpg と events/*/ogp.jpg を許可している
        event = json.loads((ROOT / "events" / slug / "event.json").read_text(encoding="utf-8"))
        for key in ("hero_image", "ogp_image"):
            name = event.get(key)
            if name and (ROOT / "events" / slug / name).exists():
                shutil.copy2(ROOT / "events" / slug / name, dist / "events" / slug / name)
    (dist / ".nojekyll").write_text("")

def write_event_page(dist, slug):
    """イベント専用の静的ページ（<slug>/index.html）を書き出す。

    X は JavaScript を実行しないため、?e=<slug> のままでは伊豆大島の OGP しか出ない。
    このページはイベント専用の OGP を静的に持ち、人はギャラリー（?e=<slug>）へ案内する。
    live / archive のどちらでも出す。
    """
    import html as _html
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    event = json.loads((ROOT / "events" / slug / "event.json").read_text(encoding="utf-8"))
    title = event.get("full_title") or event["title"] + (f" {event['subtitle']}" if event.get("subtitle") else "")
    full_title = f"{site['site_name']}｜{title}"
    desc = event.get("ogp_description") or f"{title}（{event.get('dates_label', '')}）の写真ギャラリー"
    page_url = f"{SITE_BASE_URL}{slug}/"
    ogp_name = event.get("ogp_image")
    if ogp_name and (dist / "events" / slug / ogp_name).exists():
        image_url, iw, ih = f"{SITE_BASE_URL}events/{slug}/{ogp_name}", 1200, 630
    else:
        image_url, iw, ih = f"{SITE_BASE_URL}assets/hero.jpg", 1200, 800
    gallery_url = f"../?e={slug}"
    e = _html.escape
    page = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{e(full_title)}</title>
  <meta name="description" content="{e(desc)}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="{e(site['site_name'])}">
  <meta property="og:title" content="{e(full_title)}">
  <meta property="og:description" content="{e(desc)}">
  <meta property="og:url" content="{e(page_url)}">
  <meta property="og:image" content="{e(image_url)}">
  <meta property="og:image:width" content="{iw}">
  <meta property="og:image:height" content="{ih}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{e(full_title)}">
  <meta name="twitter:image" content="{e(image_url)}">
</head>
<body>
  <h1>{e(full_title)}</h1>
  <p>{e(desc)}</p>
  <p><a href="{e(gallery_url)}">ギャラリーを見る</a></p>
  <script>location.replace({json.dumps(gallery_url)});</script>
</body>
</html>
"""
    out = dist / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"event page: {out / 'index.html'}（OGP: {image_url}）")

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def build_live(dist, slug):
    ev_path = dist / "events" / slug / "event.json"
    event = json.loads(ev_path.read_text(encoding="utf-8"))
    event["prototype"] = False
    event.update(source="supabase", submission_open=False)  # 表示は実行時にサーバーの受付状態から決める
    write_json(ev_path, event)
    write_event_page(dist, slug)
    print(f"live: {slug}（写真は Supabase から読む）")

def build_archive(dist, slug, url, anon):
    rows = http_json(f"{url}/rest/v1/rpc/get_gallery", anon, {"p_event": slug})
    photo_dir = dist / "events" / slug / "photos"
    photo_dir.mkdir()
    photos, people, manifest = [], {}, []
    for i, r in enumerate(rows, 1):
        pid = r["id"]
        for kind, path in (("full", r["full_path"]), ("thumb", r["thumb_path"])):
            name = f"{pid}.jpg" if kind == "full" else f"{pid}_t.jpg"
            data = download(f"{url}/storage/v1/object/public/gallery/{path}", photo_dir / name)
            if data[:2] != b"\xff\xd8":
                sys.exit(f"JPEGではないファイルを受け取りました: {path}")
            manifest.append({"file": f"photos/{name}", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        photos.append({"id": pid, "src": f"photos/{pid}.jpg", "thumb": f"photos/{pid}_t.jpg",
                       "width": r["width"], "height": r["height"], "alt": "",
                       "participant_id": r["participant_id"]})
        if r["participant_id"] not in people:
            people[r["participant_id"]] = {"id": r["participant_id"], "display_name": r["display_name"], "sns_url": r["sns_url"]}
        print(f"  {i}/{len(rows)} {pid}")

    ev_path = dist / "events" / slug / "event.json"
    event = json.loads(ev_path.read_text(encoding="utf-8"))
    event["prototype"] = False
    event.update(source="static", submission_open=False)
    write_json(ev_path, event)
    write_json(dist / "events" / slug / "photos.json", photos)
    write_json(dist / "events" / slug / "participants.json", list(people.values()))
    write_json(dist / "events" / slug / "manifest.json", {"event": slug, "count": len(photos), "files": manifest})
    write_event_page(dist, slug)
    total = sum(m["bytes"] for m in manifest)
    print(f"archive: {slug} に {len(photos)} 枚（{total / 1024 / 1024:.1f}MB）")

def parse_plan(text):
    plan = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        slug, sep, mode = part.partition(":")
        if not sep or not SLUG_RE.match(slug) or mode not in ("live", "archive"):
            sys.exit(f"--plan の書き方が違います: {part!r}（例: izu-oshima-2026:archive,shodoshima-2026:live）")
        if slug in [s for s, _ in plan]:
            sys.exit(f"--plan に同じイベントが2回あります: {slug}")
        plan.append((slug, mode))
    if not plan:
        sys.exit("--plan が空です")
    return plan

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "archive", "publish"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--anon-key", required=True)
    ap.add_argument("--event", default=None)
    ap.add_argument("--plan", default=None, help="publish 用: slug:live|archive をカンマ区切り")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args()

    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    dist = Path(a.out)
    url = a.url.rstrip("/")

    if a.mode in ("live", "archive"):
        plan = [(a.event or site["default_event"], a.mode)]
    else:
        if not a.plan:
            sys.exit("publish には --plan が要ります（例: --plan izu-oshima-2026:archive,shodoshima-2026:live）")
        plan = parse_plan(a.plan)
    for slug, _ in plan:
        if not (ROOT / "events" / slug / "event.json").exists():
            sys.exit(f"イベントがありません: events/{slug}/event.json")

    copy_code(dist, [slug for slug, _ in plan])

    # site.json の Supabase 設定は live のイベントが1つでもあれば入れる。
    # archive のイベントは event.json の source="static" で読み分けるため、この設定に影響されない。
    if any(mode == "live" for _, mode in plan):
        site["supabase"] = {"url": url, "anon_key": a.anon_key}
    else:
        site["supabase"] = {"url": "", "anon_key": ""}
    write_json(dist / "site.json", site)

    for slug, mode in plan:
        if mode == "live":
            build_live(dist, slug)
        else:
            build_archive(dist, slug, url, a.anon_key)
    print(f"done: {dist}（{', '.join(f'{s}:{m}' for s, m in plan)}）")

if __name__ == "__main__":
    main()
