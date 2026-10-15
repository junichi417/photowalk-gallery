# 時譜舎 フォトウォーク ギャラリー

フォトウォークの写真を誰でも見られるWebギャラリー。第1弾は伊豆大島（2026年10月10日〜11日）。
管理Issue：junichi417/secretary #6（非公開リポジトリ）

**いまの状態（2026-10-15）：投稿機能を実装し、テスト142件すべて合格。Supabase の設定（社長）待ち。一般公開・受付開始は社長の承認後。**
閲覧画面の写真・名前はすべて仮のもの。

- 社長の設定手順：[docs/SETUP.md](docs/SETUP.md)
- 受付期間・締切後・削除依頼の手順：[docs/OPERATIONS.md](docs/OPERATIONS.md)

## ⚠ このリポジトリは公開されている

次のものは**絶対にコミットしない**。

- Supabaseの秘密鍵（`service_role` キー）、各種パスワード
- 投稿用の合言葉
- 参加者のメールアドレス
- 掲載の了承が取れていない写真・名前・SNSリンク

フロントに置いてよいのは Supabase の公開用キー（`anon` キー）だけ。これは公開前提のキーで、守りはデータベース側の権限設定（RLS）で行う。

## 構成

```
index.html                 ギャラリー（閲覧画面）
post.html                  投稿画面（メール確認コード→合言葉→同意→投稿）
admin.html                 管理画面（非公開・削除・合言葉・受付の開始/停止）
assets/app.js              閲覧の処理。データの取り方は loadGallery() の1か所
assets/post.js             投稿の処理
assets/image-prep.js       端末内で写真を作り直す（位置情報の除去・縮小）
assets/admin.js            管理の処理
site.json                  サイト名・最初に開くイベント・Supabase の公開用設定
supabase/migrations/       DB（権限・締切・合言葉の判定はすべてここ）
supabase/functions/        投稿処理（画像検査・保存・掲載）の元ファイル
supabase/deploy/           管理画面に貼り付ける1ファイル版（自動生成）
tools/build_site.py        公開用サイトを組み立てる（受付中 live／締切後 archive）
tools/publish_pages.sh     gh-pages に履歴なしで公開
tools/remove_photo.py      締切後の削除依頼に対応
tools/bundle_functions.py  Edge Function を1ファイルにまとめる
tests/run_all.sh           全テスト
events/<イベント名>/
  event.json               題名・日付・投稿締切など
  participants.json        掲載する参加者（表示名・SNSリンク）
  photos.json              写真の一覧
  photos/                  写真ファイル
tools/make_placeholders.py 仮画像を作るスクリプト
```

次回のフォトウォーク（小豆島など）は `events/` にフォルダを足し、`?e=<イベント名>` で開ける。

## テスト

```
bash tests/run_all.sh
```
| 対象 | 件数 |
| --- | --- |
| DB：招待コード・権限・締切（ローカルPostgresでSupabaseの権限を再現） | 66 |
| 投稿処理・画像検査（偽装・位置情報・壊れたファイル） | 22 |
| 端末側の写真の作り直し（Chromium） | 12 |
| 投稿画面の流れ（Chromium・投稿処理は本物） | 24 |
| 締切後の保存・削除依頼・履歴なし公開 | 18 |

## 手元で見る

```
python3 -m http.server 8000
# → http://localhost:8000/
```

## 投稿締切

`events/<イベント名>/event.json` の `submission_deadline` に1か所で持つ。
画面の「受付中／終了しました」の表示はこの値を見ているだけで、**投稿できるかの判定は必ずサーバー側（Supabase）で行う**。
伊豆大島：`2026-10-31T23:59:59+09:00`
