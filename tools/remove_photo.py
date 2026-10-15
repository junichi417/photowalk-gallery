#!/usr/bin/env python3
"""締切後（静的版）の写真を削除する。削除依頼が来たときに使う。

  python3 tools/remove_photo.py <写真ID> [--dist dist] [--event izu-oshima-2026]

写真ID は、ギャラリーで写真を開いたときのファイル名（<ID>.jpg）や manifest.json で分かる。
このあと tools/publish_pages.sh dist で公開し直すと、サイトから消える。
バックアップ（社長の手元のコピー）からも同じ写真を消すこと（README の手順を参照）。
"""
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo_id")
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    ap.add_argument("--event", default=None)
    a = ap.parse_args()

    dist = Path(a.dist)
    slug = a.event or json.loads((dist / "site.json").read_text(encoding="utf-8"))["default_event"]
    ev = dist / "events" / slug
    photos = json.loads((ev / "photos.json").read_text(encoding="utf-8"))
    target = [p for p in photos if p["id"] == a.photo_id]
    if not target:
        raise SystemExit(f"写真が見つかりません: {a.photo_id}")

    keep = [p for p in photos if p["id"] != a.photo_id]
    removed = []
    for key in ("src", "thumb"):
        f = ev / target[0][key]
        if f.exists():
            f.unlink()
            removed.append(f.name)
    (ev / "photos.json").write_text(json.dumps(keep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 写真が0枚になった撮影者は、名前・SNSも一覧から外す
    people = json.loads((ev / "participants.json").read_text(encoding="utf-8"))
    still = {p["participant_id"] for p in keep}
    (ev / "participants.json").write_text(
        json.dumps([p for p in people if p["id"] in still], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    man = ev / "manifest.json"
    if man.exists():
        m = json.loads(man.read_text(encoding="utf-8"))
        m["files"] = [x for x in m["files"] if Path(x["file"]).name not in removed]
        m["count"] = len(keep)
        man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"削除しました: {', '.join(removed)}（残り {len(keep)} 枚）")

if __name__ == "__main__":
    main()
