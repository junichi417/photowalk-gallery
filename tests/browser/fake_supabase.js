/* テスト用の偽 Supabase クライアント（ブラウザ内だけで動く）。本番では使わない。
 * window.__FAKE で状態を切り替える：accepting / ended / participant など */
(function () {
  const F = (window.__FAKE = Object.assign({
    accepting: true, ended: false, code: "123456", invite: "oshima-tsubaki-2026",
    session: null, sentTo: null, participant: null, attempts: 0, photos: 0, rpcLog: [],
  }, window.__FAKE_INIT || {}));
  const ok = (data, extra = {}) => Promise.resolve({ data, error: null, ...extra });
  const err = (message) => Promise.resolve({ data: null, error: { message } });
  const thenable = (p) => Object.assign(p, { maybeSingle: () => p, single: () => p });

  function rpc(name, args) {
    F.rpcLog.push(name);
    if (name === "get_event_status") {
      return thenable(ok({ accepting: F.accepting, server_now: new Date().toISOString(),
        submission_deadline: F.ended ? "2000-01-01T00:00:00Z" : "2099-01-01T00:00:00Z" }));
    }
    if (!F.session) return thenable(err("not_authenticated"));
    if (name === "redeem_invite") {
      if (F.attempts >= 5) return thenable(err("too_many_attempts"));
      const norm = String(args.p_code || "").normalize("NFKC").trim().toLowerCase();
      if (norm !== F.invite) { F.attempts++; return thenable(ok(null)); }
      F.participant = { id: "p-1", display_name: args.p_display_name, sns_url: args.p_sns_url, disabled: false };
      return thenable(ok("p-1"));
    }
    if (name === "update_my_profile") {
      if (args.p_sns_url && !/^https:\/\//.test(args.p_sns_url)) return thenable(err("violates check constraint"));
      Object.assign(F.participant, { display_name: args.p_display_name, sns_url: args.p_sns_url });
      return thenable(ok(null));
    }
    return thenable(err("unknown rpc " + name));
  }

  function from(table) {
    const q = {
      select() { return q; }, eq() { return q; }, neq() { return q; },
      maybeSingle() { return ok(table === "participants" ? F.participant : null); },
      then(res, rej) { return ok(null, { count: F.photos }).then(res, rej); },
    };
    return q;
  }

  window.supabase = {
    createClient() {
      return {
        rpc, from,
        auth: {
          getSession: () => ok({ session: F.session }),
          signInWithOtp: ({ email }) => { F.sentTo = email; return ok({}); },
          verifyOtp: ({ email, token }) => {
            if (email !== F.sentTo || token !== F.code) return err("Token has expired or is invalid");
            F.session = { access_token: "fake-token" };
            return ok({ session: F.session });
          },
          signOut: () => { F.session = null; return ok({}); },
        },
      };
    },
  };
})();
