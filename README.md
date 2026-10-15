# 時譜舎 フォトウォーク ギャラリー

フォトウォークの写真を誰でも見られるWebギャラリー。第1弾は伊豆大島（2026年10月10日〜11日）。
管理Issue：junichi417/secretary #6（非公開リポジトリ）

**いまの状態：閲覧画面の試作版。写真・名前はすべて仮のもの。GitHub Pagesでの一般公開はまだしていない（社長の承認後に行う）。**

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
post.html                  投稿画面（いまは受付状態の表示のみ）
assets/style.css           見た目
assets/app.js              表示の処理。データの取り方は loadGallery() の1か所
site.json                  サイト名と、最初に開くイベント
events/<イベント名>/
  event.json               題名・日付・投稿締切など
  participants.json        掲載する参加者（表示名・SNSリンク）
  photos.json              写真の一覧
  photos/                  写真ファイル
tools/make_placeholders.py 仮画像を作るスクリプト
```

次回のフォトウォーク（小豆島など）は `events/` にフォルダを足し、`?e=<イベント名>` で開ける。

## 手元で見る

```
python3 -m http.server 8000
# → http://localhost:8000/
```

## 投稿締切

`events/<イベント名>/event.json` の `submission_deadline` に1か所で持つ。
画面の「受付中／終了しました」の表示はこの値を見ているだけで、**投稿できるかの判定は必ずサーバー側（Supabase）で行う**。
伊豆大島：`2026-10-31T23:59:59+09:00`
