# 公開の手順(GitHub Actions)

## 初回だけ(社長・Settingsの操作)
1. Settings → Pages → **Source: GitHub Actions** にする
2. Settings → Environments → `github-pages` → **Required reviewers に社長を追加**(承認するまで公開が始まらない)
3. (あれば)`gh-pages` ブランチは使わない。古いものは作らないこと

## 公開するとき
1. Actions → publish-pages → **Run workflow**(mode=live)
2. 公開前の安全確認(秘密鍵・メールアドレス・画像の混入)が通ると、承認待ちになる
3. 社長が **Review deployments → Approve** → 公開
4. 受付の開始/停止は公開とは別で、管理画面のスイッチで行う(画面の表示はサーバーの受付状態に自動で合う)

## 締切後(11/1〜)
- mode=archive で実行 → 写真を全件ダウンロードして Supabase なしで動く版に切り替える(社長の承認後)
- 削除依頼は docs/OPERATIONS.md の手順 → 再実行すると、公開側には履歴が残らない

## 補足
- push しても自動では公開されない(手動実行のみ)
- 従来の `tools/publish_pages.sh`(gh-pages の強制上書き)は使わない方針にする
