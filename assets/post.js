/* 投稿画面の動き
 *  メール → 確認コード → 合言葉で参加登録 → 同意 → 写真を選ぶ → 端末で作り直し → 送信
 * 「投稿してよいか」はすべてサーバーが判定する。この画面は案内と表示だけ。
 */
(async () => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SLUG_RE = /^[a-z0-9-]{1,64}$/;
  const steps = ["step-email", "step-code", "step-join", "step-post"];

  function show(step) { steps.forEach((s) => ($(s).hidden = s !== step)); }
  function say(text, kind = "error") {
    const m = $("message");
    m.textContent = text;
    m.className = "message" + (kind === "info" ? " info" : "");
    m.hidden = !text;
  }

  // サーバーからのエラーを、画面の言葉に
  const MESSAGES = {
    submission_closed: "写真の受付は終了しました",
    too_many_attempts: "合言葉の入力回数が多すぎます。1時間ほど時間をおいてからお試しください",
    email_not_confirmed: "メールアドレスの確認がまだです。確認コードを入力してください",
    not_participant: "参加登録がまだです。合言葉を入力してください",
    check_violation: "表示名は30文字まで、SNSのURLは https:// で始まるものを入力してください",
  };
  function explain(err, fallback) {
    const text = String(err?.message || err || "");
    for (const [k, v] of Object.entries(MESSAGES)) if (text.includes(k)) return v;
    if (text.includes("check constraint")) return MESSAGES.check_violation;
    if (/rate limit|over_email_send_rate_limit|security purposes/i.test(text)) return "送信が続いたため、少し時間をおいてからお試しください";
    if (/otp|token/i.test(text) && /expired|invalid/i.test(text)) return "確認コードが違うか、期限が切れています。送り直してください";
    return fallback;
  }

  // ---- 設定の読み込み ----
  let site, event, sb;
  try {
    site = await (await fetch("site.json", { cache: "no-cache" })).json();
    const asked = new URLSearchParams(location.search).get("e");
    const slug = asked && SLUG_RE.test(asked) ? asked : site.default_event;
    event = await (await fetch(`events/${slug}/event.json`, { cache: "no-cache" })).json();
  } catch {
    $("status").textContent = "設定を読み込めませんでした。時間をおいて開き直してください";
    return;
  }
  $("ev-title").textContent = `${event.title}${event.subtitle ? " " + event.subtitle : ""}`;
  document.title = `写真を投稿する｜${event.title}`;
  $("back-link").href = `./?e=${encodeURIComponent(event.slug)}`;
  $("deadline-label").textContent = event.submission_deadline_label;
  if (site.removal_contact) $("removal-contact").textContent = site.removal_contact;
  else $("rule-contact").hidden = true;

  const closedByClock = Date.now() > Date.parse(event.submission_deadline);
  const sbConf = site.supabase || {};
  if (closedByClock) {
    $("status").textContent = "写真の受付は終了しました";
    $("status").classList.add("closed");
    return;
  }
  if (!sbConf.url || !sbConf.anon_key || !window.supabase) {
    $("status").textContent = `写真の受付は準備中です（締切 ${event.submission_deadline_label}）`;
    return;
  }
  sb = window.supabase.createClient(sbConf.url, sbConf.anon_key, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });

  // ---- 受付状態（サーバーの時計で判定）----
  const { data: st, error: stErr } = await sb.rpc("get_event_status", { p_event: event.slug }).maybeSingle();
  if (stErr || !st) {
    $("status").textContent = "受付状態を確認できませんでした。時間をおいて開き直してください";
    return;
  }
  if (!st.accepting) {
    const ended = Date.parse(st.server_now) > Date.parse(st.submission_deadline);
    $("status").textContent = ended ? "写真の受付は終了しました" : `写真の受付は準備中です（締切 ${event.submission_deadline_label}）`;
    if (ended) $("status").classList.add("closed");
    return;
  }
  $("status").textContent = `写真の受付は${event.submission_deadline_label}まで`;

  // ---- 状態に合わせて画面を出し分け ----
  let email = "";
  async function route() {
    say("");
    const { data: { session } } = await sb.auth.getSession();
    if (!session) return show("step-email");
    const { data: me } = await sb.from("participants")
      .select("id, display_name, sns_url, disabled").eq("event_slug", event.slug).maybeSingle();
    if (!me) return show("step-join");
    if (me.disabled) { show(null); say("この登録では投稿できません。運営にお問い合わせください"); return; }
    $("p-name").value = me.display_name || "";
    $("p-sns").value = me.sns_url || "";
    await refreshQuota();
    await loadMine();
    show("step-post");
  }

  // 1. メールアドレス → コード送信
  let resendTimer;
  async function sendCode() {
    const { error } = await sb.auth.signInWithOtp({ email, options: { shouldCreateUser: true } });
    if (error) { say(explain(error, "確認コードを送れませんでした。アドレスを確かめてください")); return false; }
    $("sent-to").textContent = email;
    $("resend").disabled = true;
    clearTimeout(resendTimer);
    resendTimer = setTimeout(() => ($("resend").disabled = false), 60000);
    return true;
  }
  $("form-email").addEventListener("submit", async (e) => {
    e.preventDefault();
    say("");
    email = $("email").value.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return say("メールアドレスを確かめてください");
    if (await sendCode()) { show("step-code"); $("code").focus(); }
  });
  $("resend").addEventListener("click", async () => { if (await sendCode()) say("確認コードを送り直しました", "info"); });
  $("change-email").addEventListener("click", () => { say(""); show("step-email"); });

  // 2. 確認コード
  $("form-code").addEventListener("submit", async (e) => {
    e.preventDefault();
    say("");
    const token = $("code").value.replace(/\D/g, "");
    if (token.length < 6) return say("確認コードを入力してください");
    const { error } = await sb.auth.verifyOtp({ email, token, type: "email" });
    if (error) return say(explain(error, "確認コードが違うか、期限が切れています。送り直してください"));
    await route();
  });

  // 3. 合言葉で参加登録
  function cleanSns(v) {
    v = v.trim();
    if (!v) return null;
    return /^https:\/\/[^\s<>"]+$/.test(v) ? v : undefined;
  }
  $("form-join").addEventListener("submit", async (e) => {
    e.preventDefault();
    say("");
    const sns = cleanSns($("sns").value);
    if (sns === undefined) return say("SNSのURLは https:// で始まるものを入力してください");
    const { data, error } = await sb.rpc("redeem_invite", {
      p_event: event.slug, p_code: $("invite").value,
      p_display_name: $("name").value.trim() || null, p_sns_url: sns,
    });
    if (error) return say(explain(error, "参加登録できませんでした。時間をおいてお試しください"));
    if (!data) return say("合言葉が違います");
    $("invite").value = "";
    await route();
  });

  // 4. 投稿
  let remaining = 0;
  async function refreshQuota() {
    const { count } = await sb.from("photos").select("id", { count: "exact", head: true })
      .eq("event_slug", event.slug).neq("status", "pending");
    const max = event.max_photos_per_user || 20;
    remaining = Math.max(0, max - (count || 0));
    $("quota").textContent = `投稿済み ${count || 0}枚／あと${remaining}枚まで投稿できます。`;
  }

  // 自分の投稿の一覧と取り消し（受付の間だけ・自分の掲載中の写真だけ。判定はサーバー側）
  const publicUrl = (path) => `${sbConf.url}/storage/v1/object/public/gallery/${path.split("/").map(encodeURIComponent).join("/")}`;
  async function loadMine() {
    const { data, error } = await sb.from("photos").select("id, thumb_path, status, created_at")
      .eq("event_slug", event.slug).neq("status", "pending").order("created_at", { ascending: false });
    const list = $("mine-list");
    if (error || !data || data.length === 0) { $("mine").hidden = true; list.replaceChildren(); return; }
    $("mine").hidden = false;
    list.replaceChildren(...data.map((r) => {
      const li = document.createElement("li");
      const img = document.createElement("img");
      img.src = publicUrl(r.thumb_path); img.alt = ""; img.loading = "lazy";
      const state = document.createElement("span");
      state.className = "mine-state";
      li.append(img, state);
      if (r.status === "published") {
        state.textContent = "掲載中";
        const btn = document.createElement("button");
        btn.type = "button"; btn.className = "link"; btn.textContent = "取り消す";
        btn.onclick = () => cancelPhoto(r.id, btn);
        li.append(btn);
      } else {
        state.textContent = "運営が非公開にしています";
      }
      return li;
    }));
  }

  async function cancelPhoto(id, btn) {
    if (!confirm("この写真を取り消します。ギャラリーから消え、元に戻せません。よろしいですか？")) return;
    btn.disabled = true;
    say("");
    try {
      const { data: { session } } = await sb.auth.getSession();
      if (!session) throw new Error("ログインし直してください");
      const res = await fetch(`${sbConf.url}/functions/v1/delete-my-photo`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}`, apikey: sbConf.anon_key, "content-type": "application/json" },
        body: JSON.stringify({ photo_id: id }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.message || "取り消せませんでした");
      say("写真を取り消しました", "info");
    } catch (err) {
      say(err.message || "取り消せませんでした");
    }
    await refreshQuota();
    await loadMine();
  }

  const consentOk = () => $("consent-own").checked && $("consent-people").checked;
  const updateSubmit = () => ($("submit-post").disabled = !(consentOk() && $("files").files.length > 0));
  ["consent-own", "consent-people", "files"].forEach((id) => $(id).addEventListener("change", updateSubmit));

  $("form-post").addEventListener("submit", async (e) => {
    e.preventDefault();
    say("");
    if (!consentOk()) return say("投稿前の確認2つにチェックしてください");
    const files = Array.from($("files").files);
    if (files.length > remaining) return say(`あと${remaining}枚まで投稿できます。選ぶ枚数を減らしてください`);

    $("submit-post").disabled = true;
    const queue = $("queue");
    queue.replaceChildren();
    let okCount = 0;

    for (const file of files) {
      const li = document.createElement("li");
      const thumb = document.createElement("img");
      thumb.alt = "";
      const label = document.createElement("span");
      label.textContent = `${file.name}：準備中`;
      li.append(thumb, label);
      queue.appendChild(li);

      try {
        const prepared = await window.ImagePrep.prepareImage(file);
        thumb.src = URL.createObjectURL(prepared.thumb);
        label.textContent = `${file.name}：送信中`;

        const { data: { session } } = await sb.auth.getSession();
        if (!session) throw new Error("ログインし直してください");
        const fd = new FormData();
        fd.set("event", event.slug);
        fd.set("consent_own_photo", "true");
        fd.set("consent_people", "true");
        fd.set("full", prepared.full, "full.jpg");
        fd.set("thumb", prepared.thumb, "thumb.jpg");
        const res = await fetch(`${sbConf.url}/functions/v1/upload-photo`, {
          method: "POST",
          headers: { Authorization: `Bearer ${session.access_token}`, apikey: sbConf.anon_key },
          body: fd,
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.message || "投稿できませんでした");
        label.textContent = `${file.name}：掲載しました`;
        label.className = "ok";
        okCount++;
      } catch (err) {
        label.textContent = `${file.name}：${err.message || "投稿できませんでした"}`;
        label.className = "ng";
        if (String(err.message).includes("受付は終了")) break;
      }
    }

    $("files").value = "";
    await refreshQuota();
    await loadMine();
    updateSubmit();
    if (okCount > 0) say(`${okCount}枚をギャラリーに掲載しました`, "info");
  });

  // 表示名・SNSの変更
  $("form-profile").addEventListener("submit", async (e) => {
    e.preventDefault();
    const sns = cleanSns($("p-sns").value);
    if (sns === undefined) return say("SNSのURLは https:// で始まるものを入力してください");
    const { error } = await sb.rpc("update_my_profile", {
      p_event: event.slug, p_display_name: $("p-name").value.trim() || null, p_sns_url: sns,
    });
    say(error ? explain(error, "保存できませんでした") : "保存しました", error ? "error" : "info");
  });

  $("logout").addEventListener("click", async () => { await sb.auth.signOut(); await route(); });

  await route();
})();
