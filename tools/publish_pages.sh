#!/usr/bin/env bash
# dist/ の中身を gh-pages ブランチとして公開する（GitHub Pages の公開元）。
#
#   tools/publish_pages.sh dist [リモート名=origin]
#
# 毎回「親のない1コミット」を作って強制上書きする。
# → gh-pages には過去の版が残らない。削除依頼で消した写真を、履歴からたどれなくする。
# ※ 公開は社長の承認後に行う（README 参照）
set -euo pipefail

DIST="${1:?使い方: tools/publish_pages.sh dist [remote]}"
REMOTE="${2:-origin}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_URL="$(git -C "$REPO_DIR" remote get-url "$REMOTE" 2>/dev/null || echo "$REMOTE")"

[ -f "$DIST/index.html" ] || { echo "dist に index.html がありません: $DIST" >&2; exit 1; }
if grep -rqiE 'service_role|sb_secret_' "$DIST"; then
  echo "dist に秘密鍵らしき文字列があります。公開を中止しました" >&2; exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -R "$DIST"/. "$WORK"/
cd "$WORK"
git init -q -b gh-pages
git add -A
git -c user.name="photowalk-gallery" -c user.email="noreply@users.noreply.github.com" \
    commit -q -m "公開版 $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push -q --force "$REMOTE_URL" gh-pages:gh-pages
echo "gh-pages に公開しました（$(git ls-files | wc -l | tr -d ' ') ファイル・履歴なし）"
