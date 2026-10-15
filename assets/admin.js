/* 管理画面：写真の非公開・再公開・削除、撮影者の名前表示停止・投稿停止、合言葉、受付の開始/停止
 * 管理者かどうかはサーバー（DB）が判定する。管理者でなければ一覧も操作も拒否される。
 */
(async () => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const say = (t, kind = "error") => { const m = $("message"); m.textContent = t; m.className = "message" + (kind === "info" ? " info" : ""); m.hidden = !t; };
  const show = (s) => ["step-email", "step-code", "step-admin"].forEach((x) => ($(x).hidden = x !== s));

  const site = await (await fetch("site.json", { cache: "no-cache" })).json();
  const slug = site.default_event;
  const conf = site.supabase || {};
  if (!conf.url || !conf.anon_key || !window.supabase) { $("status").textContent = "Supabaseの設定が未完了です"; return; }
  const sb = window.supabase.createClient(conf.url, conf.anon_key);
  const pub = (p) => `${conf.url}/storage/v1/object/public/gallery/${p.split("/").map(encodeURIComponent).join("/")}`;
  let email = "";

  async function route() {
    say("");
    const { data: { session } } = await sb.auth.getSession();
    if (!session) { $("status").textContent = "管理者としてログインしてください"; return show("step-email"); }
    const { data: isAdmin } = await sb.rpc("is_admin");
    if (!isAdmin) { $("status").textContent = "このアカウントは管理者ではありません"; show(null); return; }
    $("status").textContent = `イベント：${slug}`;
    show("step-admin");
    await load();
  }

  async function load() {
    const { data: st } = await sb.rpc("get_event_status", { p_event: slug }).maybeSingle();
    $("accepting").textContent = st?.accepting ? "受付中" : "受付していません";
    const { data, error } = await sb.rpc("admin_list_photos", { p_event: slug });
    if (error) return say(error.message);
    $("count").textContent = `${data.length}枚（非公開を含む）`;
    const grid = $("grid");
    grid.replaceChildren(...data.map((r) => {
      const card = document.createElement("div");
      card.className = "admin-card" + (r.status === "hidden" ? " hidden-photo" : "");
      const img = document.createElement("img");
      img.src = pub(r.thumb_path); img.alt = ""; img.loading = "lazy";
      const meta = document.createElement("div");
      meta.className = "meta";
      const who = document.createElement("span");
      who.textContent = `${r.display_name || "（名前なし）"}${r.name_hidden ? "・名前非表示" : ""}${r.disabled ? "・投稿停止" : ""}`;
      const state = document.createElement("span");
      state.textContent = r.status === "hidden" ? "非公開" : "公開中";
      const actions = document.createElement("div");
      actions.className = "actions";
      const btn = (label, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = "link"; b.textContent = label; b.onclick = fn; return b; };
      actions.append(
        btn(r.status === "hidden" ? "再公開" : "非公開", () => act(sb.rpc("admin_set_photo_hidden", { p_photo_id: r.id, p_hidden: r.status !== "hidden" }))),
        btn("削除", async () => {
          if (!confirm("この写真を完全に削除します。元に戻せません。よろしいですか？")) return;
          const { data: { session } } = await sb.auth.getSession();
          const res = await fetch(`${conf.url}/functions/v1/admin-delete-photo`, {
            method: "POST",
            headers: { Authorization: `Bearer ${session.access_token}`, apikey: conf.anon_key, "content-type": "application/json" },
            body: JSON.stringify({ photo_id: r.id }),
          });
          if (!res.ok) say("削除できませんでした"); else say("削除しました", "info");
          await load();
        }),
        btn(r.name_hidden ? "名前を表示" : "名前を隠す", () => act(sb.rpc("admin_set_participant", { p_participant_id: r.participant_id, p_name_hidden: !r.name_hidden, p_disabled: r.disabled }))),
        btn(r.disabled ? "投稿を再開" : "投稿を停止", () => act(sb.rpc("admin_set_participant", { p_participant_id: r.participant_id, p_name_hidden: r.name_hidden, p_disabled: !r.disabled }))),
      );
      meta.append(who, state, actions);
      card.append(img, meta);
      return card;
    }));
  }

  async function act(promise, okText = "更新しました") {
    const { error } = await promise;
    say(error ? error.message : okText, error ? "error" : "info");
    await load();
  }

  $("form-email").addEventListener("submit", async (e) => {
    e.preventDefault();
    email = $("email").value.trim().toLowerCase();
    const { error } = await sb.auth.signInWithOtp({ email, options: { shouldCreateUser: false } });
    if (error) return say("確認コードを送れませんでした");
    show("step-code");
  });
  $("form-code").addEventListener("submit", async (e) => {
    e.preventDefault();
    const { error } = await sb.auth.verifyOtp({ email, token: $("code").value.trim(), type: "email" });
    if (error) return say("確認コードが違うか、期限が切れています");
    await route();
  });
  $("open-on").onclick = () => confirm("受付を開始します。よろしいですか？") && act(sb.rpc("admin_set_submission_open", { p_event: slug, p_open: true }), "受付を開始しました");
  $("open-off").onclick = () => act(sb.rpc("admin_set_submission_open", { p_event: slug, p_open: false }), "受付を止めました");
  $("set-code").onclick = async () => {
    const code = $("new-code").value;
    await act(sb.rpc("admin_set_invite_code", { p_event: slug, p_code: code }), "合言葉を設定しました（古い合言葉は使えなくなりました）");
    $("new-code").value = "";
  };
  $("disable-code").onclick = () => confirm("合言葉を無効にします。新しい参加登録ができなくなります（登録済みの人は投稿できます）。") &&
    act(sb.rpc("admin_disable_invite_code", { p_event: slug }), "合言葉を無効にしました");
  $("logout").onclick = async () => { await sb.auth.signOut(); await route(); };

  await route();
})();
