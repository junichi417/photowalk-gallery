#!/usr/bin/env python3
"""招待コード・権限・締切のセキュリティテスト（ローカル PostgreSQL で実行）

使い方（root なら postgres ユーザーで DB を立てる）:
    python3 tests/db/run_db_tests.py

やること
  1. 一時フォルダに PostgreSQL を起動
  2. Supabase の認証・権限の下地（supabase_emulation.sql）→ 本番と同じ migration を適用
  3. 参加者・第三者・管理者・サーバーの立場で操作して、通る／止まるを確認
"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PG_BIN = Path("/usr/lib/postgresql/16/bin")
PORT = 55432
EVENT = "izu-oshima-2026"
CODE = "Oshima-Tsubaki-2026"

def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

class DB:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pwg-db-"))
        os.chmod(self.tmp, 0o777)
        self.data = self.tmp / "data"
        self.as_pg = ["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []

    def start(self):
        r = sh(self.as_pg + [str(PG_BIN / "initdb"), "-D", str(self.data), "-E", "UTF8",
                             "--locale=C.UTF-8", "-U", "postgres", "-A", "trust"])
        assert r.returncode == 0, r.stderr
        r = sh(self.as_pg + [str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-l", str(self.tmp / "log"),
                             "-o", f"-p {PORT} -k {self.tmp} -c listen_addresses=''", "-w", "start"])
        assert r.returncode == 0, r.stderr + (self.tmp / "log").read_text()

    def stop(self):
        sh(self.as_pg + [str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-m", "fast", "stop"])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def psql(self, sql, timeout=30):
        return sh(["psql", "-h", str(self.tmp), "-p", str(PORT), "-U", "postgres", "-d", "postgres",
                   "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql], timeout=timeout)

    def file(self, path):
        r = sh(["psql", "-h", str(self.tmp), "-p", str(PORT), "-U", "postgres", "-d", "postgres",
                "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(path)])
        assert r.returncode == 0, f"{path}: {r.stderr}"

def q(s):
    return "'" + str(s).replace("'", "''") + "'"

def as_role(sql, role="anon", user=None):
    """指定の立場で1トランザクション実行する SQL を作る（PostgREST と同じやり方）"""
    claims = json.dumps({"sub": str(user), "role": role}) if user else json.dumps({"role": role})
    return (f"begin; select set_config('request.jwt.claims', {q(claims)}, true) \\g /dev/null\n"
            f"set local role {role};\n{sql};\ncommit;")

results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"  ← {detail}"))

def run(db, sql, role="postgres", user=None):
    if role == "postgres":
        return db.psql(sql)
    # -c は1文ずつしか \g を解釈しないので、ファイル経由で流す
    f = db.tmp / f"q_{uuid.uuid4().hex}.sql"
    claims = json.dumps({"sub": str(user), "role": role}) if user else json.dumps({"role": role})
    f.write_text(f"begin;\nselect set_config('request.jwt.claims', {q(claims)}, true) \\g /dev/null\n"
                 f"set local role {role};\n{sql};\ncommit;\n", encoding="utf-8")
    os.chmod(f, 0o644)
    r = sh(["psql", "-h", str(db.tmp), "-p", str(PORT), "-U", "postgres", "-d", "postgres",
            "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", str(f)])
    f.unlink()
    return r

def expect_ok(db, name, sql, role="postgres", user=None, want=None):
    r = run(db, sql, role, user)
    out = r.stdout.strip()
    if r.returncode != 0:
        check(name, False, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "error")
    elif want is not None and not want(out):
        check(name, False, f"結果が想定外: {out!r}")
    else:
        check(name, True)
    return out

def expect_err(db, name, sql, pattern, role="postgres", user=None):
    r = run(db, sql, role, user)
    ok = r.returncode != 0 and pattern in r.stderr
    check(name, ok, (r.stderr.strip() or r.stdout.strip() or "通ってしまった")[:200])

def main():
    db = DB()
    db.start()
    try:
        db.file(ROOT / "tests/db/supabase_emulation.sql")
        db.psql("create extension if not exists pgcrypto with schema extensions;")
        db.file(Path(os.environ.get("MIGRATION", ROOT / "supabase/migrations/20261016000000_gallery.sql")))
        db.file(ROOT / "supabase/migrations/20261022000000_delete_my_photo.sql")

        U = {n: uuid.uuid4() for n in ["admin", "alice", "bob", "mallory", "eve", "carol", "dave"]}
        for n, u in U.items():
            confirmed = "null" if n == "mallory" else "now()"
            db.psql(f"insert into auth.users values ({q(u)}, {q(n + '@example.com')}, {confirmed});")
        db.psql(f"insert into public.admins values ({q(U['admin'])});")
        A = dict(role="authenticated")

        def begin(user, consent="true, true", event=EVENT):
            return run(db, f"select photo_id from public.begin_photo_upload({q(event)}, {consent}, 2048, 1365, 640, 427, 500000)",
                       "authenticated", user)

        print("\n■ 準備（管理者が合言葉を設定して受付を開く）")
        expect_ok(db, "管理者は合言葉を設定できる", f"select public.admin_set_invite_code({q(EVENT)}, {q(CODE)})", **A, user=U["admin"])
        expect_ok(db, "管理者は受付を開始できる", f"select public.admin_set_submission_open({q(EVENT)}, true)", **A, user=U["admin"])
        expect_err(db, "8文字未満の合言葉は設定できない", f"select public.admin_set_invite_code({q(EVENT)}, 'abc')", "code_too_short", **A, user=U["admin"])
        h = db.psql(f"select invite_code_hash from public.events where slug={q(EVENT)}").stdout.strip()
        check("合言葉は平文で保存されない（bcryptのハッシュ）", h.startswith("$2") and CODE.lower() not in h.lower(), h[:10])

        print("\n■ ログインしていない第三者（anon）")
        expect_ok(db, "ギャラリーの一覧は誰でも見られる", f"select count(*) from public.get_gallery({q(EVENT)})", "anon")
        expect_ok(db, "受付状態は誰でも見られる（合言葉のハッシュは含まない）",
                  f"select row_to_json(s)::text from public.get_event_status({q(EVENT)}) s", "anon",
                  want=lambda o: '"accepting":true' in o and "hash" not in o)
        expect_err(db, "合言葉の登録はできない", f"select public.redeem_invite({q(EVENT)}, {q(CODE)})", "permission denied", "anon")
        expect_err(db, "投稿の開始はできない", f"select * from public.begin_photo_upload({q(EVENT)}, true, true, 1,1,1,1,1)", "permission denied", "anon")
        expect_err(db, "写真の表へ直接書き込めない", "insert into public.photos (event_slug) values ('x')", "permission denied", "anon")
        expect_err(db, "イベント設定（合言葉のハッシュ）は読めない", "select invite_code_hash from public.events", "permission denied", "anon")
        expect_ok(db, "参加者の表を読んでも0件", "select count(*) from public.participants", "anon", want=lambda o: o == "0")

        print("\n■ メール未確認の人")
        expect_err(db, "正しい合言葉でも登録できない", f"select public.redeem_invite({q(EVENT)}, {q(CODE)})", "email_not_confirmed", **A, user=U["mallory"])

        print("\n■ メール確認済みだが合言葉を通っていない人")
        expect_err(db, "投稿を開始できない", f"select * from public.begin_photo_upload({q(EVENT)}, true, true, 1,1,1,1,1)", "not_participant", **A, user=U["eve"])

        print("\n■ 合言葉を間違えた人（総当たり対策）")
        expect_ok(db, "間違った合言葉では登録されない", f"select coalesce(public.redeem_invite({q(EVENT)}, 'wrong-code-1')::text, 'NULL')", **A, user=U["bob"], want=lambda o: o == "NULL")
        for i in range(2, 6):
            run(db, f"select public.redeem_invite({q(EVENT)}, 'wrong-code-{i}')", "authenticated", U["bob"])
        expect_err(db, "5回間違えると、正しい合言葉でも1時間は登録できない", f"select public.redeem_invite({q(EVENT)}, {q(CODE)})", "too_many_attempts", **A, user=U["bob"])
        expect_ok(db, "間違えた人は参加者になっていない", f"select count(*) from public.participants where user_id={q(U['bob'])}", want=lambda o: o == "0")

        print("\n■ 正しい参加者（alice）")
        pid = expect_ok(db, "合言葉は全角・大文字小文字・前後の空白の違いを許して登録できる",
                        f"select public.redeem_invite({q(EVENT)}, '  ＯＳＨＩＭＡ－ｔｓｕｂａｋｉ－２０２６ ', 'アリス', 'https://example.com/alice')",
                        **A, user=U["alice"], want=lambda o: len(o) == 36)
        expect_err(db, "同意チェックがないと投稿を開始できない", f"select * from public.begin_photo_upload({q(EVENT)}, true, false, 1,1,1,1,1)", "consent_required", **A, user=U["alice"])
        r = begin(U["alice"])
        photo1 = r.stdout.strip()
        check("投稿を開始できる", r.returncode == 0 and len(photo1) == 36, r.stderr)
        expect_ok(db, "保存待ちの写真はギャラリーに出ない", f"select count(*) from public.get_gallery({q(EVENT)})", "anon", want=lambda o: o == "0")
        expect_err(db, "本人は自分で「掲載済み」にできない（サーバーだけ）", f"select public.finish_photo_upload({q(photo1)})", "permission denied", **A, user=U["alice"])
        expect_ok(db, "サーバーが保存を終えると自動掲載される", f"select public.finish_photo_upload({q(photo1)})", "service_role")
        expect_ok(db, "掲載後、ギャラリーに名前とSNSつきで出る",
                  f"select display_name || '|' || sns_url from public.get_gallery({q(EVENT)})", "anon",
                  want=lambda o: o == "アリス|https://example.com/alice")
        expect_err(db, "写真の状態を直接書き換えられない", f"update public.photos set status='hidden'", "permission denied", **A, user=U["alice"])
        expect_err(db, "参加者の表へ直接書き込めない", f"insert into public.participants (user_id, event_slug) values ({q(U['alice'])}, {q(EVENT)})", "permission denied", **A, user=U["alice"])
        expect_ok(db, "本人は自分の写真だけ見える", "select count(*) from public.photos", **A, user=U["alice"], want=lambda o: o == "1")
        expect_ok(db, "他人（eve）からは alice の写真の行は見えない", "select count(*) from public.photos", **A, user=U["eve"], want=lambda o: o == "0")
        expect_err(db, "参加者は写真を非公開にできない", f"select public.admin_set_photo_hidden({q(photo1)}, true)", "admin_only", **A, user=U["alice"])
        expect_err(db, "参加者は写真を削除できない", f"select * from public.admin_delete_photo({q(photo1)})", "admin_only", **A, user=U["alice"])
        expect_err(db, "参加者は合言葉を変えられない", f"select public.admin_set_invite_code({q(EVENT)}, 'hijacked-code')", "admin_only", **A, user=U["alice"])

        print("\n■ 表示名・SNSリンクの入力チェック")
        expect_err(db, "javascript: のリンクは拒否", f"select public.update_my_profile({q(EVENT)}, 'アリス', 'javascript:alert(1)')", "check constraint", **A, user=U["alice"])
        expect_err(db, "http:（暗号化なし）のリンクは拒否", f"select public.update_my_profile({q(EVENT)}, 'アリス', 'http://example.com')", "check constraint", **A, user=U["alice"])
        expect_err(db, "31文字以上の表示名は拒否", f"select public.update_my_profile({q(EVENT)}, {q('あ' * 31)}, null)", "check constraint", **A, user=U["alice"])
        expect_ok(db, "表示名・SNSは空でも登録できる（名前なしで掲載）", f"select public.update_my_profile({q(EVENT)}, '', '')", **A, user=U["alice"])
        expect_ok(db, "名前なしのときギャラリーの名前は空", f"select coalesce(display_name, 'NULL') from public.get_gallery({q(EVENT)})", "anon", want=lambda o: o == "NULL")
        run(db, f"select public.update_my_profile({q(EVENT)}, 'アリス', 'https://example.com/alice')", "authenticated", U["alice"])

        print("\n■ 枚数の上限（1人20枚。テストでは3枚に下げて確認）")
        db.psql(f"update public.events set max_photos_per_user = 3 where slug = {q(EVENT)}")
        begin(U["alice"]); begin(U["alice"])
        r = begin(U["alice"])
        check("上限を超える投稿は止まる", r.returncode != 0 and "photo_limit_reached" in r.stderr, r.stderr or "通ってしまった")
        # 同時に2枚送っても上限を超えないこと（同じ人で2本のトランザクションを並べる）
        run(db, "select 1", "postgres")
        db.psql("delete from public.photos where status='pending'")
        dave_pid = run(db, f"select public.redeem_invite({q(EVENT)}, {q(CODE)}, 'デイブ', null)", "authenticated", U["dave"]).stdout.strip()
        begin(U["dave"]); begin(U["dave"])  # 2枚（残り1枚）
        outs = []
        def slow_begin():
            outs.append(run(db, f"select photo_id from public.begin_photo_upload({q(EVENT)}, true, true, 1,1,1,1,1); select pg_sleep(1.5)", "authenticated", U["dave"]))
        ts = [threading.Thread(target=slow_begin) for _ in range(2)]
        [t.start() for t in ts]; [t.join() for t in ts]
        ok_count = sum(1 for o in outs if o.returncode == 0)
        check("同時に2枚送っても、上限を超えるのは1枚も通らない", ok_count == 1, f"通った数={ok_count}")
        abandoned = begin(U["dave"])
        db.psql("update public.photos set created_at = now() - interval '11 minutes' where status='pending'")
        expect_err(db, "10分以上放置された保存待ちは、あとから掲載できない",
                   f"select public.finish_photo_upload(id) from public.photos where status='pending' limit 1", "upload_not_found", "service_role")
        r = begin(U["dave"])
        check("放置された保存待ちは枚数に数えない", r.returncode == 0, r.stderr)
        db.psql(f"update public.events set max_photos_per_user = 20 where slug = {q(EVENT)}")

        print("\n■ 管理者（社長）")
        expect_ok(db, "非公開にできる", f"select public.admin_set_photo_hidden({q(photo1)}, true)", **A, user=U["admin"])
        expect_ok(db, "非公開の写真はギャラリーに出ない", f"select count(*) from public.get_gallery({q(EVENT)}) where id={q(photo1)}", "anon", want=lambda o: o == "0")
        expect_ok(db, "再公開できる", f"select public.admin_set_photo_hidden({q(photo1)}, false)", **A, user=U["admin"])
        alice_pid = db.psql(f"select id from public.participants where user_id={q(U['alice'])}").stdout.strip()
        expect_ok(db, "名前の表示を止められる", f"select public.admin_set_participant({q(alice_pid)}, true, false)", **A, user=U["admin"])
        expect_ok(db, "名前を止めた人の写真は名前なしで出る", f"select coalesce(display_name,'NULL') || coalesce(sns_url,'NULL') from public.get_gallery({q(EVENT)}) where id={q(photo1)}", "anon", want=lambda o: o == "NULLNULL")
        expect_ok(db, "投稿を止められる", f"select public.admin_set_participant({q(alice_pid)}, false, true)", **A, user=U["admin"])
        r = begin(U["alice"])
        check("投稿を止められた人は投稿できない", r.returncode != 0 and "not_participant" in r.stderr, r.stderr or "通ってしまった")
        db.psql(f"update public.participants set disabled=false where id={q(alice_pid)}")
        expect_ok(db, "削除すると消すべきファイルの場所が返る", f"select full_path from public.admin_delete_photo({q(photo1)})", **A, user=U["admin"], want=lambda o: o == f"{EVENT}/{photo1}.jpg")

        print("\n■ 合言葉の変更・無効化（漏れたとき）")
        expect_ok(db, "合言葉を変更できる", f"select public.admin_set_invite_code({q(EVENT)}, 'new-code-camellia')", **A, user=U["admin"])
        expect_ok(db, "古い合言葉では新しい人は登録できない", f"select coalesce(public.redeem_invite({q(EVENT)}, {q(CODE)})::text,'NULL')", **A, user=U["carol"], want=lambda o: o == "NULL")
        expect_ok(db, "新しい合言葉なら登録できる", f"select public.redeem_invite({q(EVENT)}, 'new-code-camellia')", **A, user=U["carol"], want=lambda o: len(o) == 36)
        print("\n■ 本人による写真の取り消し（締切前・受付中だけ）")
        mine = begin(U["carol"]).stdout.strip()
        run(db, f"select public.finish_photo_upload({q(mine)})", "service_role")
        expect_err(db, "第三者（anon）は取り消せない", f"select * from public.delete_my_photo({q(mine)})", "permission denied", "anon")
        expect_err(db, "他人（alice）の写真は取り消せない", f"select * from public.delete_my_photo({q(mine)})", "photo_not_found", **A, user=U["alice"])
        expect_err(db, "参加者でない人（eve）は取り消せない", f"select * from public.delete_my_photo({q(mine)})", "photo_not_found", **A, user=U["eve"])
        expect_ok(db, "本人は自分の写真を取り消せる（消すファイルの場所が返る）", f"select full_path from public.delete_my_photo({q(mine)})", **A, user=U["carol"], want=lambda o: o == f"{EVENT}/{mine}.jpg")
        expect_ok(db, "取り消した写真はギャラリーから消える", f"select count(*) from public.get_gallery({q(EVENT)}) where id={q(mine)}", "anon", want=lambda o: o == "0")
        expect_err(db, "取り消した写真をもう一度取り消すことはできない", f"select * from public.delete_my_photo({q(mine)})", "photo_not_found", **A, user=U["carol"])
        hid = begin(U["carol"]).stdout.strip()
        run(db, f"select public.finish_photo_upload({q(hid)})", "service_role")
        run(db, f"select public.admin_set_photo_hidden({q(hid)}, true)", "authenticated", U["admin"])
        expect_err(db, "運営が非公開にした写真は本人でも取り消せない", f"select * from public.delete_my_photo({q(hid)})", "photo_not_found", **A, user=U["carol"])
        db.psql(f"update public.events set submission_open = false where slug={q(EVENT)}")
        expect_err(db, "受付が止まっているときは取り消せない", f"select * from public.delete_my_photo({q(hid)})", "photo_not_found", **A, user=U["carol"])
        run(db, f"select public.admin_set_photo_hidden({q(hid)}, false)", "authenticated", U["admin"])
        expect_err(db, "受付スイッチが切れているときは、自分の写真でも取り消せない", f"select * from public.delete_my_photo({q(hid)})", "submission_closed", **A, user=U["carol"])
        db.psql(f"update public.events set submission_open = true where slug={q(EVENT)}")
        db.psql(f"update public.events set submission_deadline = now() - interval '1 second' where slug={q(EVENT)}")
        expect_err(db, "締切後は取り消せない（削除しない約束）", f"select * from public.delete_my_photo({q(hid)})", "submission_closed", **A, user=U["carol"])
        db.psql(f"update public.events set submission_deadline = '2026-10-31T23:59:59+09:00' where slug={q(EVENT)}")
        expect_ok(db, "受付が再開すれば、本人はまた取り消せる", f"select count(*) from public.delete_my_photo({q(hid)})", **A, user=U["carol"], want=lambda o: o == "1")

        expect_ok(db, "合言葉を無効化できる", f"select public.admin_disable_invite_code({q(EVENT)})", **A, user=U["admin"])
        expect_ok(db, "無効化後は誰も登録できない", f"select coalesce(public.redeem_invite({q(EVENT)}, 'new-code-camellia')::text,'NULL')", **A, user=U["eve"], want=lambda o: o == "NULL")
        run(db, f"select public.admin_set_invite_code({q(EVENT)}, {q(CODE)})", "authenticated", U["admin"])

        print("\n■ 大勢で総当たりされたとき")
        db.psql("delete from public.invite_attempts")
        attackers = [uuid.uuid4() for _ in range(8)]
        for a in attackers:
            db.psql(f"insert into auth.users values ({q(a)}, {q(str(a) + '@example.com')}, now())")
            for i in range(4):
                run(db, f"select public.redeem_invite({q(EVENT)}, 'guess-{i}')", "authenticated", a)
        expect_err(db, "10分で30回失敗すると、イベント全体で登録が一時停止する", f"select public.redeem_invite({q(EVENT)}, {q(CODE)})", "too_many_attempts", **A, user=U["eve"])
        db.psql("delete from public.invite_attempts")

        print("\n■ 別のイベント")
        db.psql("insert into public.events (slug, title, submission_deadline, submission_open) values ('shodoshima-2027', '小豆島', now() + interval '30 days', true)")
        r = begin(U["alice"], event="shodoshima-2027")
        check("伊豆大島の参加者は、別イベントには投稿できない", r.returncode != 0 and "not_participant" in r.stderr, r.stderr or "通ってしまった")

        print("\n■ 締切（10/31 23:59 JST）")
        expect_ok(db, "締切は 2026-10-31 14:59:59 UTC（= 23:59:59 JST）で保存されている",
                  f"select to_char(submission_deadline at time zone 'UTC', 'YYYY-MM-DD HH24:MI:SS') from public.events where slug={q(EVENT)}",
                  want=lambda o: o == "2026-10-31 14:59:59")
        pending = begin(U["alice"]).stdout.strip()
        db.psql(f"update public.events set submission_deadline = now() - interval '1 second' where slug={q(EVENT)}")
        expect_ok(db, "締切後は受付状態が「終了」になる", f"select accepting from public.get_event_status({q(EVENT)})", "anon", want=lambda o: o == "f")
        r = begin(U["alice"])
        check("締切後は投稿を開始できない（サーバー側で停止）", r.returncode != 0 and "submission_closed" in r.stderr, r.stderr or "通ってしまった")
        expect_err(db, "締切後は合言葉の登録もできない", f"select public.redeem_invite({q(EVENT)}, {q(CODE)})", "submission_closed", **A, user=U["eve"])
        expect_err(db, "締切後は表示名も変えられない", f"select public.update_my_profile({q(EVENT)}, 'x', null)", "submission_closed", **A, user=U["alice"])
        expect_ok(db, "締切直前に始めた投稿は、締切をまたいでも掲載できる", f"select public.finish_photo_upload({q(pending)})", "service_role")
        expect_ok(db, "締切後もギャラリーは見られ、写真は消えない", f"select count(*) from public.get_gallery({q(EVENT)})", "anon", want=lambda o: int(o) >= 1)
        db.psql(f"update public.events set submission_deadline = now() + interval '1 day', submission_open = false where slug={q(EVENT)}")
        r = begin(U["alice"])
        check("受付スイッチを切ると締切前でも投稿できない", r.returncode != 0 and "submission_closed" in r.stderr, r.stderr or "通ってしまった")

        print("\n■ 設定そのものの点検")
        expect_ok(db, "public の全テーブルで RLS が有効",
                  "select count(*) from pg_tables where schemaname='public' and not rowsecurity", want=lambda o: o == "0")
        expect_ok(db, "SECURITY DEFINER の関数はすべて search_path を固定している",
                  "select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prosecdef and (p.proconfig is null or not exists (select 1 from unnest(p.proconfig) c where c like 'search_path=%'))",
                  want=lambda o: o == "0")
        expect_ok(db, "ストレージに参加者向けの書き込みポリシーがない",
                  "select count(*) from pg_policies where schemaname='storage'", want=lambda o: o == "0")
        expect_ok(db, "第三者（anon）が実行できる関数は2つだけ（一覧・受付状態）",
                  "select string_agg(p.proname, ',' order by p.proname) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and has_function_privilege('anon', p.oid, 'execute')",
                  want=lambda o: o == "get_event_status,get_gallery")
    finally:
        db.stop()

    failed = [r for r in results if not r[1]]
    print(f"\n結果: {len(results) - len(failed)} / {len(results)} 件 合格")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
