#!/usr/bin/env python3
"""公開用のサイト一式（dist/）を作る。

  live    投稿受付中：コードだけを置き、写真は Supabase から読む
          python3 tools/build_site.py live --url https://xxxx.supabase.co --anon-key <公開用キー>

  archive 締切後：公開中の写真をすべてダウンロードして、Supabase なしで動く静的サイトにする
          python3 tools/build_site.py archive --url https://xxxx.supabase.co --anon-key <公開用キー>

どちらも dist/ に書き出す。dist/ は main ブランチには入れない（.gitignore 済み）。
公開は tools/publish_pages.sh dist で、履歴を持たない gh-pages ブランチに上書きする。
→ 写真が main の履歴に残らないので、削除依頼があれば本当に消せる。

使うのは公開用キー（anon）と、誰でも見られる一覧（get_gallery）だけ。秘密鍵は不要。
"""
import argparse, hashlib, json, shutil, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ["index.html", "post.html", "admin.html", "assets", "site.json"]

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

def copy_code(dist, slug):
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    for name in CODE:
        src = ROOT / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dist / name)
    (dist / "events" / slug).mkdir(parents=True)
    shutil.copy2(ROOT / "events" / slug / "event.json", dist / "events" / slug / "event.json")
    (dist / ".nojekyll").write_text("")

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "archive"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--anon-key", required=True)
    ap.add_argument("--event", default=None)
    ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args()

    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    slug = a.event or site["default_event"]
    dist = Path(a.out)
    url = a.url.rstrip("/")
    copy_code(dist, slug)
    ev_path = dist / "events" / slug / "event.json"
    event = json.loads(ev_path.read_text(encoding="utf-8"))
    event["prototype"] = False

    if a.mode == "live":
        site["supabase"] = {"url": url, "anon_key": a.anon_key}
        event.update(source="supabase", submission_open=False)  # 表示は実行時にサーバーの受付状態から決める
        write_json(dist / "site.json", site)
        write_json(ev_path, event)
        print(f"live: {dist}（写真は Supabase から読む）")
        return

    # ---- archive：公開中の写真をすべて保存 ----
    rows = http_json(f"{url}/rest/v1/rpc/get_gallery", a.anon_key, {"p_event": slug})
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

    site["supabase"] = {"url": "", "anon_key": ""}   # 静的版は Supabase を使わない
    event.update(source="static", submission_open=False)
    write_json(dist / "site.json", site)
    write_json(ev_path, event)
    write_json(dist / "events" / slug / "photos.json", photos)
    write_json(dist / "events" / slug / "participants.json", list(people.values()))
    write_json(dist / "events" / slug / "manifest.json", {"event": slug, "count": len(photos), "files": manifest})
    total = sum(m["bytes"] for m in manifest)
    print(f"archive: {dist} に {len(photos)} 枚（{total / 1024 / 1024:.1f}MB）")

if __name__ == "__main__":
    main()
