# Supabase の設定手順（社長が行う）

所要時間の目安：30〜40分。画面の名前は Supabase・Google の更新で少し変わっていることがあります。迷ったらエマに画面のスクショを送ってください。

**🔒 秘密にするもの（チャット・Issue・リポジトリに絶対に書かない）**
- Supabase の DBパスワード、`service_role`（または `sb_secret_…`）キー
- Gmail のアプリパスワード
- 投稿用の合言葉（参加者グループ以外に出さない）

**エマに渡してよいもの**：プロジェクトURL（`https://xxxx.supabase.co`）と公開用キー（`anon` / `sb_publishable_…`）だけ。

---

## 1. プロジェクトを作る
1. supabase.com にログイン → New project
2. 名前：`photowalk-gallery`／地域：Tokyo（Northeast Asia）／プラン：**Free**
3. DBパスワードは自動生成のまま、社長の手元（パスワード管理）に保存
4. 作成時にカード登録を求められたら、**そこで止めてエマに連絡**（無料の前提が崩れるため）

## 2. データベースを設定する
1. 左メニュー **SQL Editor** → New query
2. リポジトリの `supabase/migrations/20261016000000_gallery.sql` の中身を全部貼り付けて **Run**
3. 「Success」と出ればOK。エラーが出たら、その文面をエマに送る

## 3. メール（認証コード）の設定
**3-1. Gmail のアプリパスワードを作る**
1. 送信元にする Gmail で Google アカウント → セキュリティ → **2段階認証プロセス**を有効にする
2. 同じ画面の **アプリ パスワード** で新しく作る（名前は「photowalk」など）
3. 表示された16文字を控える（この画面でしか見られない。**どこにも貼らない**）

**3-2. Supabase に入力する**
左メニュー Authentication → Emails（または Settings）→ **SMTP Settings** → Enable custom SMTP
| 項目 | 入れる値 |
| --- | --- |
| Sender email | 送信元の Gmail アドレス |
| Sender name | 時譜舎 フォトウォーク |
| Host | `smtp.gmail.com` |
| Port | `465` |
| Username | 送信元の Gmail アドレス |
| Password | 3-1 のアプリパスワード |

**3-3. メールの文面を「6桁のコード」にする**
Authentication → Emails → Templates で、**Magic Link** と **Confirm signup** の2つを次のように変える。
- 件名：`【時譜舎フォトウォーク】確認コード`
- 本文：
```html
<p>時譜舎フォトウォークの写真投稿ページで、次の確認コードを入力してください。</p>
<p style="font-size:24px;letter-spacing:4px"><strong>{{ .Token }}</strong></p>
<p>このメールに心当たりがない場合は、何もせずに削除してください。</p>
```

**3-4. その他**
- Authentication → Sign In / Providers → **Email** が有効、**Confirm email** がオン
- Authentication → URL Configuration → Site URL：`https://junichi417.github.io/photowalk-gallery/`

## 4. 投稿処理（Edge Function）を登録する
左メニュー **Edge Functions** → Deploy a new function → Via Editor で、2つ作る。
| 関数名（そのまま入力） | 貼り付けるファイル |
| --- | --- |
| `upload-photo` | `supabase/deploy/upload-photo.ts` の中身 |
| `admin-delete-photo` | `supabase/deploy/admin-delete-photo.ts` の中身 |

どちらも **Verify JWT（JWTの確認）はオンのまま**。

続けて Edge Functions → **Secrets** に1つ追加：
- 名前 `ALLOWED_ORIGINS`／値 `https://junichi417.github.io`

## 5. 社長を管理者にする
1. Authentication → Users → **Add user** → Create new user で、社長のメールアドレスを登録（Auto Confirm にチェック）
2. SQL Editor で次を実行（メールアドレスだけ書き換える）
```sql
insert into public.admins (user_id)
select id from auth.users where email = '社長のメールアドレス';
```

## 6. エマに連絡
Project Settings → API（または API Keys）から、次の2つをエマに送る。
- Project URL
- 公開用キー（`anon` または `publishable`）

ここまでで**投稿はまだ始まりません**（受付スイッチがオフ・合言葉が未設定のため）。

## 7. 本番テスト → 受付開始（社長の承認後）
1. エマが公開用のページを作り、GitHub Pages の設定をお願いします（Settings → Pages → Branch：`gh-pages`）
2. 社長が `admin.html` にログイン → 合言葉を設定 → **受付を開始する**
3. 社長自身が参加者として1枚投稿してテスト（位置情報が消えているかエマが確認）
4. 問題なければ、合言葉と投稿ページのURLを参加者グループに送る
