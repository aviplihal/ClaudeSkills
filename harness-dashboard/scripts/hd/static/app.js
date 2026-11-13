// app.js: dashboard front end. Renders every data string with textContent only; token lives in memory, never in the URL.
(function () {
  "use strict";
  var token = null;
  var timer = null;
  var lastOk = 0;
  var ICON = { green: "[OK]", amber: "[!]", red: "[X]", grey: "[?]", neutral: "[-]" };
  var WORD = { green: "GREEN", amber: "AMBER", red: "RED", grey: "GREY (no data or idle)" };
  var root = document.getElementById("root");

  // el: create an element with optional class and text (text set via textContent).
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }
  // clear: remove all children of a node.
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  // api: fetch a path with the bearer header.
  function api(path, opts) {
    opts = opts || {};
    var h = { "Authorization": "Bearer " + token };
    if (opts.body) { h["Content-Type"] = "application/json"; }
    return fetch(path, { method: opts.method || "GET", headers: h, body: opts.body, cache: "no-store", credentials: "omit" });
  }
  // showExpired: blank the page and tell the user to get a fresh link.
  function showExpired() {
    if (timer) { clearInterval(timer); timer = null; }
    token = null;
    document.body.classList.remove("greyed");
    clear(root);
    root.appendChild(el("p", "expired", "expired — get a fresh link from the terminal"));
  }
  // chip: a labeled colored chip with an icon and word, so color is never the only signal.
  function chip(name, part) {
    var c = part.color || "grey";
    return el("span", "chip c-" + c, ICON[c] + " " + name + ": " + (WORD[c] || c).split(" ")[0] + " - " + part.reason);
  }
  // renderVerdict: the verdict bar.
  function renderVerdict(v, st) {
    var c = v.color || "grey";
    var card = el("section", "card verdict c-" + c);
    card.appendChild(el("div", "big c-" + c, ICON[c] + " " + (WORD[c] || c)));
    card.appendChild(el("div", "reason", v.reason));
    var chips = el("div", "chips");
    chips.appendChild(chip("Goal", v.goal));
    chips.appendChild(chip("Safety", v.safety));
    card.appendChild(chips);
    if (v.last_run) { card.appendChild(el("div", "age", "Last run: " + v.last_run.result + ", " + v.last_run.ago)); }
    card.appendChild(el("div", "age", "Data age: " + (v.data_age_s === null ? "no heartbeat" : v.data_age_s + " s") + " | server time " + v.server_ts));
    if (st.goal_text) { card.appendChild(el("div", "age", "Goal: " + st.goal_text)); }
    return card;
  }
  // renderSessions: one card per session.
  function renderSessions(list) {
    var box = el("section");
    box.appendChild(el("h2", null, "Sessions"));
    if (!list.length) { box.appendChild(el("div", "card muted", "No sessions observed.")); }
    list.forEach(function (s) {
      var card = el("div", "card");
      var top = el("div", "row");
      top.appendChild(el("span", "status", s.status.toUpperCase() + (s.stuck_reason ? " - " + s.stuck_reason : "")));
      top.appendChild(el("span", "muted", s.since_last_event_s + " s since last event"));
      card.appendChild(top);
      card.appendChild(el("div", null, s.harness + " / " + s.session_id));
      card.appendChild(el("div", "muted", "subagents " + s.subagents_active + " active, " + s.subagents_done + " finished; last tool: " + (s.last_tool || "none")));
      if (s.working_on) { card.appendChild(el("div", null, "Working on: " + s.working_on)); }
      box.appendChild(card);
    });
    return box;
  }
  // renderSecurity: every security line with its label.
  function renderSecurity(lines) {
    var box = el("section");
    box.appendChild(el("h2", null, "Security"));
    lines.forEach(function (ln) {
      var card = el("div", "card");
      card.appendChild(el("div", "label c-" + ln.color, ICON[ln.color] + " " + ln.label));
      card.appendChild(el("div", null, ln.text));
      if (ln.detail) { card.appendChild(el("div", "muted", ln.detail)); }
      if (ln.link === "mapping") {
        var b = el("button", null, "Open control mapping");
        b.addEventListener("click", function () { showMapping(card, b); });
        card.appendChild(b);
      }
      box.appendChild(card);
    });
    return box;
  }
  // showMapping: fetch the mapping page and show it as plain text.
  function showMapping(card, btn) {
    api("/api/mapping").then(function (r) { return r.ok ? r.text() : "could not load"; }).then(function (t) {
      btn.remove();
      card.appendChild(el("pre", null, t));
    });
  }
  // renderTable: a simple table from header names and row arrays.
  function renderTable(heads, rows) {
    var t = el("table");
    var tr = el("tr");
    heads.forEach(function (h) { tr.appendChild(el("th", null, h)); });
    t.appendChild(tr);
    rows.forEach(function (r) {
      var x = el("tr");
      r.forEach(function (c) { x.appendChild(el("td", null, c === null ? "-" : c)); });
      t.appendChild(x);
    });
    return t;
  }
  // renderMiddle: declarative panels; unknown types show a notice only.
  function renderMiddle(panels) {
    var box = el("section");
    panels.forEach(function (p) {
      var card = el("div", "card");
      card.appendChild(el("div", "label", p.title));
      if (p.type === "tool_inventory") {
        card.appendChild(renderTable(["Tool", "Calls", "Last used", "Error rate", "Flag"], p.rows.map(function (r) {
          return [r.tool, r.calls, r.last_used, Math.round(r.error_rate * 100) + "%", r.never_called ? "never called" : ""];
        })));
      } else if (p.type === "pipeline") {
        card.appendChild(renderTable(["Stage", "Count"], p.stages.map(function (s) { return [s.label, s.count]; })));
      } else if (p.type === "queue" || p.type === "data_store") {
        var keys = Object.keys(p.values);
        card.appendChild(keys.length ? renderTable(["Name", "Value"], keys.map(function (k) { return [k, p.values[k]]; })) : el("div", "muted", "no data observed"));
      } else {
        card.appendChild(el("div", "muted", p.note || "unsupported panel"));
      }
      box.appendChild(card);
    });
    return box;
  }
  // act: POST a confirmed action after a browser confirmation dialog.
  function act(path, body, question) {
    if (!window.confirm(question)) { return; }
    api(path, { method: "POST", body: JSON.stringify(body) }).then(function (r) { return r.json(); }).then(function (j) {
      window.alert(j.ok ? "Recorded." : (j.error || "failed"));
      poll();
    });
  }
  // renderActions: buttons for confirmed actions.
  function renderActions(st) {
    var box = el("section");
    box.appendChild(el("h2", null, "Actions (confirmed and recorded)"));
    var card = el("div", "card");
    var defs = [
      ["Confirm I screened the data", "/api/screening/confirm", { confirm: true }, "Record that you screened the data sources now?"],
      ["Release retention hold", "/api/hold/release", { confirm: true }, "Release the retention hold? Only after the incident note is handled."],
      ["Approve current set", "/api/approve", { confirm: true }, "Approve the current hooks, wall, signals and tool definitions?"],
      [st.mode === "strict" ? "Switch to Standard" : "Switch to Strict", "/api/mode",
        { mode: st.mode === "strict" ? "standard" : "strict", confirm: true }, "Change the mode? This is written to the records log."]
    ];
    defs.forEach(function (d) {
      var b = el("button", null, d[0]);
      b.addEventListener("click", function () { act(d[1], d[2], d[3]); });
      card.appendChild(b);
    });
    box.appendChild(card);
    return box;
  }
  // render: rebuild the whole page from a state payload.
  function render(st) {
    clear(root);
    root.appendChild(el("h1", null, "Harness: " + st.harness));
    root.appendChild(renderVerdict(st.verdict, st));
    root.appendChild(renderSessions(st.sessions));
    root.appendChild(renderSecurity(st.security));
    var ef = el("section");
    ef.appendChild(el("h2", null, "Effects"));
    ef.appendChild(el("div", "card muted", st.effects));
    root.appendChild(ef);
    root.appendChild(renderMiddle(st.middle));
    root.appendChild(renderActions(st));
  }
  // setGrey: grey the page out when data cannot be refreshed or is old.
  function setGrey(on, msg) {
    document.body.classList.toggle("greyed", on);
    var old = document.getElementById("stale");
    if (old) { old.remove(); }
    if (on) {
      var b = el("div", "stale-banner", msg);
      b.id = "stale";
      root.insertBefore(b, root.firstChild);
    }
  }
  // poll: fetch /api/state and render, handling expiry and failures.
  function poll() {
    if (!token) { return; }
    api("/api/state").then(function (r) {
      if (r.status === 401) { showExpired(); return null; }
      if (!r.ok) { throw new Error("http " + r.status); }
      return r.json();
    }).then(function (st) {
      if (!st) { return; }
      lastOk = Date.now();
      render(st);
      var age = st.verdict.data_age_s;
      setGrey(age === null || age > 30, "STALE: no data from the collector for over 30 s");
    }).catch(function () {
      if (lastOk) { setGrey(true, "STALE: cannot refresh, showing last data"); }
      else { clear(root); root.appendChild(el("p", "expired", "cannot reach the dashboard server")); }
    });
  }
  // start: take the token from the fragment, remove it from the address bar, begin polling.
  function start() {
    var m = /(?:^#|&)t=([^&]+)/.exec(window.location.hash || "");
    if (m) { token = decodeURIComponent(m[1]); }
    try { window.history.replaceState(null, "", window.location.pathname); } catch (e) { /* ignore */ }
    if (!token) { showExpired(); return; }
    poll();
    timer = setInterval(poll, 3000);
  }
  start();
})();
