/* 時譜舎フォトウォーク ギャラリー（閲覧画面）
 *
 * データの取り方は loadGallery() の1か所にまとめてある。
 *  - いま（試作）と締切後の静的版：events/<slug>/ の JSON を読む（source: "static"）
 *  - 投稿受付中：Supabase から同じ形のデータを読む（source: "supabase"）
 * どちらも { event, participants, photos } の同じ形を返すので、画面側は変えなくてよい。
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SLUG_RE = /^[a-z0-9-]{1,64}$/;

  // SNSリンクは https のみ表示する（javascript: などを通さない）
  function safeHttpsUrl(value) {
    if (typeof value !== "string" || value.length > 300) return null;
    try {
      const u = new URL(value);
      return u.protocol === "https:" ? u.href : null;
    } catch { return null; }
  }

  async function getJson(path) {
    const res = await fetch(path, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path} を読めませんでした（${res.status}）`);
    return res.json();
  }

  async function loadGallery() {
    const site = await getJson("site.json");
    const asked = new URLSearchParams(location.search).get("e");
    const slug = asked && SLUG_RE.test(asked) ? asked : site.default_event;
    const base = `events/${slug}/`;
    const event = await getJson(base + "event.json");

    if (event.source === "supabase") {
      // 投稿受付中：Supabase の公開用の一覧（非公開・保存待ちの写真は含まれない）から読む
      const sbc = site.supabase || {};
      if (!sbc.url || !sbc.anon_key) throw new Error("ギャラリーの設定が未完了です");
      const res = await fetch(`${sbc.url}/rest/v1/rpc/get_gallery`, {
        method: "POST",
        headers: { apikey: sbc.anon_key, "content-type": "application/json" },
        body: JSON.stringify({ p_event: event.slug }),
      });
      if (!res.ok) throw new Error(`写真の一覧を読めませんでした（${res.status}）`);
      const rows = await res.json();
      const pub = (path) => `${sbc.url}/storage/v1/object/public/gallery/${path.split("/").map(encodeURIComponent).join("/")}`;
      const people = new Map();
      for (const r of rows) {
        if (!people.has(r.participant_id)) {
          people.set(r.participant_id, { id: r.participant_id, display_name: r.display_name, sns_url: r.sns_url });
        }
      }
      return {
        site, event,
        participants: [...people.values()],
        photos: rows.map((r) => ({
          id: r.id, src: pub(r.full_path), thumb: pub(r.thumb_path),
          width: r.width, height: r.height, alt: "", participant_id: r.participant_id,
        })),
      };
    }

    const [participants, photos] = await Promise.all([
      getJson(base + "participants.json"),
      getJson(base + "photos.json"),
    ]);
    return {
      site, event,
      participants,
      photos: photos.filter((p) => !p.hidden).map((p) => ({ ...p, src: base + p.src, thumb: p.thumb ? base + p.thumb : base + p.src })),
    };
  }

  // ---- 受付状態（表示だけ。投稿できるかの判定は常にサーバー側で行う） ----
  function renderStatus(event) {
    const deadline = Date.parse(event.submission_deadline);
    const closed = Number.isFinite(deadline) && Date.now() > deadline;
    const status = $("status");
    const btn = $("post-btn");
    if (closed) {
      status.textContent = "写真の受付は終了しました";
      status.classList.add("closed");
      btn.hidden = true;
    } else if (event.submission_open) {
      status.textContent = `写真の受付は${event.submission_deadline_label}まで`;
      btn.setAttribute("aria-disabled", "false");
    } else {
      status.textContent = `写真の受付は準備中です（締切 ${event.submission_deadline_label}）`;
    }
  }

  // ---- 写真の並び ----
  let state = { photos: [], byId: new Map(), filter: null, shown: [] };

  function columnCount() {
    const w = $("grid").clientWidth || window.innerWidth;
    if (w < 520) return 2;
    if (w < 900) return 3;
    if (w < 1300) return 4;
    return 5;
  }

  function personLabel(pid) {
    const p = pid && state.byId.get(pid);
    return p && p.display_name ? p.display_name : null;
  }

  function renderGrid() {
    const grid = $("grid");
    const shown = state.filter
      ? state.photos.filter((p) => p.participant_id === state.filter)
      : state.photos;
    state.shown = shown;

    const n = columnCount();
    const cols = Array.from({ length: n }, () => {
      const c = document.createElement("div");
      c.className = "col";
      return { el: c, h: 0 };
    });

    shown.forEach((photo, i) => {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "tile";
      const name = personLabel(photo.participant_id);
      tile.setAttribute("aria-label", `${photo.alt || "写真"}${name ? `（${name}）` : ""}を拡大`);

      const img = document.createElement("img");
      img.src = photo.thumb || photo.src;
      img.alt = photo.alt || "";
      img.width = photo.width;
      img.height = photo.height;
      img.loading = i < 8 ? "eager" : "lazy";
      img.decoding = "async";
      tile.appendChild(img);

      if (name) {
        const who = document.createElement("span");
        who.className = "who";
        who.textContent = name;
        tile.appendChild(who);
      }
      tile.addEventListener("click", () => openViewer(i));

      // いちばん低い列に足す（並び順をなるべく保ったまま高さをそろえる）
      const target = cols.reduce((a, b) => (b.h < a.h ? b : a));
      target.el.appendChild(tile);
      target.h += photo.height / photo.width;
    });

    grid.replaceChildren(...cols.map((c) => c.el));
    $("count").textContent = `${shown.length}枚`;
    $("empty").hidden = shown.length > 0;
  }

  function renderPeople() {
    const list = $("people");
    const named = state.participants.filter((p) =>
      p.display_name && state.photos.some((ph) => ph.participant_id === p.id));
    if (named.length === 0) { list.parentElement.hidden = true; return; }

    const make = (label, id) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("aria-pressed", String(state.filter === id));
      b.addEventListener("click", () => {
        state.filter = id;
        list.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        renderGrid();
      });
      li.appendChild(b);
      return li;
    };
    list.replaceChildren(make("すべての写真", null), ...named.map((p) => make(p.display_name, p.id)));
  }

  // ---- 拡大表示 ----
  let current = 0;

  function showAt(i) {
    const list = state.shown;
    if (list.length === 0) return;
    current = (i + list.length) % list.length;
    const photo = list[current];
    const img = $("viewer-img");
    img.src = photo.src;
    img.alt = photo.alt || "";

    const who = $("viewer-who");
    who.replaceChildren();
    const p = photo.participant_id && state.byId.get(photo.participant_id);
    if (p && p.display_name) {
      const url = safeHttpsUrl(p.sns_url);
      if (url) {
        const a = document.createElement("a");
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = p.display_name;
        who.appendChild(a);
      } else {
        who.textContent = p.display_name;
      }
    }
    $("viewer-pos").textContent = `${current + 1} / ${list.length}`;
  }

  function openViewer(i) {
    showAt(i);
    const dlg = $("viewer");
    if (!dlg.open) dlg.showModal();
  }

  function setupViewer() {
    const dlg = $("viewer");
    $("prev").addEventListener("click", () => showAt(current - 1));
    $("next").addEventListener("click", () => showAt(current + 1));
    $("close").addEventListener("click", () => dlg.close());
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") showAt(current - 1);
      if (e.key === "ArrowRight") showAt(current + 1);
    });
    // 写真の外側（背景）をタップしたら閉じる
    dlg.querySelector(".viewer-stage").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) dlg.close();
    });
    // 左右スワイプで送る
    let x0 = null;
    const stage = dlg.querySelector(".viewer-stage");
    stage.addEventListener("pointerdown", (e) => { x0 = e.clientX; });
    stage.addEventListener("pointerup", (e) => {
      if (x0 === null) return;
      const dx = e.clientX - x0;
      x0 = null;
      if (Math.abs(dx) > 50) showAt(current + (dx < 0 ? 1 : -1));
    });
  }

  // ---- 起動 ----
  async function start() {
    setupViewer();
    try {
      const data = await loadGallery();
      state.photos = data.photos;
      state.participants = data.participants;
      state.byId = new Map(data.participants.map((p) => [p.id, p]));

      const ev = data.event;
      document.title = `${ev.title}${ev.subtitle ? " " + ev.subtitle : ""}｜${data.site.site_name}`;
      $("ev-title").textContent = ev.title;
      $("ev-subtitle").textContent = ev.subtitle || "";
      $("ev-dates").textContent = ev.dates_label || "";
      $("site-name").textContent = data.site.site_name;
      $("proto-note").hidden = !ev.prototype;
      $("post-btn").href = `post.html?e=${encodeURIComponent(ev.slug)}`;

      renderStatus(ev);
      renderPeople();
      renderGrid();

      let lastCols = columnCount();
      window.addEventListener("resize", () => {
        const n = columnCount();
        if (n !== lastCols) { lastCols = n; renderGrid(); }
      });
    } catch (err) {
      $("count").textContent = "";
      const empty = $("empty");
      empty.hidden = false;
      empty.textContent = `写真を読み込めませんでした。時間をおいて開き直してください。（${err.message}）`;
    }
  }

  start();
})();
