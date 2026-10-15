#!/usr/bin/env bash
# すべてのテストを順に実行する。  bash tests/run_all.sh
set -uo pipefail
cd "$(dirname "$0")/.."
FX="$(mktemp -d)"; trap 'rm -rf "$FX"' EXIT
python3 tests/functions/make_fixtures.py "$FX" >/dev/null || exit 1
fail=0
run() { echo; echo "=== $1"; shift; "$@" || fail=1; }
run "Edge Function の一体化ファイルが最新か" python3 tools/bundle_functions.py --check
run "DB：招待コード・権限・締切" python3 tests/db/run_db_tests.py
run "投稿処理・画像検査" env FIXTURES="$FX" node --experimental-strip-types --no-warnings --test tests/functions/upload.test.ts
run "端末側の写真の作り直し（ブラウザ）" python3 tests/browser/test_image_prep.py "$FX"
run "投稿画面の流れ（ブラウザ）" python3 tests/browser/test_post_flow.py "$FX"
run "締切後の保存・削除依頼・公開" python3 tests/test_archive.py "$FX"
echo; [ $fail -eq 0 ] && echo "すべて合格" || echo "不合格あり"
exit $fail
