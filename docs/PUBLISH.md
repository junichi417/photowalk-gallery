# 公開の手順（GitHub Actions）— 社長向け

## 初回だけ（社長・Settings の操作）
1. Settings → Pages → **Source: GitHub Actions** にする
2. Settings → Environments → `github-pages` → **Required reviewers に社長を追加**（承認するまで公開が始まらない）
3. `gh-pages` ブランチは使わない

## 公開するとき（通常はこれだけ）
1. Actions → publish-pages → **Run workflow**
2. 入力は初期値のままでよい：
   - mode = **publish**（複数イベントの同時公開）
   - plan = **izu-oshima-2026:archive,shodoshima-2026:live**
     （伊豆大島は今の静的版のまま、小豆島は受付中として、同じサイトに同時に入る）
3. 公開前の安全確認（秘密鍵・メールアドレス・許可外の画像）が通ると、承認待ちになる
4. 社長が **Review deployments → Approve** → 公開される

## 覚えておくこと
- push しても自動では公開されない（手動実行のみ）。公開のたびにサイト全体が新しい dist で置き換わる
- ルートURL（伊豆大島のページとXのカード）は変わらない。小豆島は `?e=shodoshima-2026` と `/shodoshima-2026/`（X用）
- 受付の開始/停止は公開とは別で、管理画面（admin.html?e=shodoshima-2026）のスイッチで行う
- 画像を置ける場所は決まっている：サイトのトップ写真、各イベントのトップ写真・OGP画像、伊豆大島の静的版の写真だけ。それ以外が混ざると安全確認で止まる
- 1イベントだけを公開し直すときは mode=live / archive にして event に slug を入れる（通常は使わない）
- 締切後に小豆島も静的版にするときは、plan を `izu-oshima-2026:archive,shodoshima-2026:archive` に変えて実行する（その時点で別途相談）
- 削除依頼への対応は docs/OPERATIONS.md の手順。再公開しても公開側に履歴は残らない
