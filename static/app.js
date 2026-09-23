// DnD News — 속보 자동 새로고침과 필터 (서버 없이 정적 JSON만 읽음)
(function () {
  const REFRESH_MS = 60 * 1000;
  const fmt = (iso, opt) => new Date(iso).toLocaleString("ko-KR", Object.assign({ timeZone: "Asia/Seoul", hour12: false }, opt));
  const hhmm = (iso) => fmt(iso, { hour: "2-digit", minute: "2-digit" });
  const mmdd = (iso) => fmt(iso, { month: "2-digit", day: "2-digit" }).replace(/\s/g, "").replace(/\.$/, "");
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  async function load(src) {
    const r = await fetch(src + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  // ── 속보 페이지 ──
  const tl = document.getElementById("timeline");
  if (tl) {
    const names = window.SECTION_NAMES || {};
    let filter = "all";
    const apply = () => {
      tl.querySelectorAll(".tl").forEach((li) => {
        const show = filter === "all" || (filter === "flash" ? li.dataset.flash === "1" : "sec-" + li.dataset.sec === filter);
        li.classList.toggle("hide", !show);
      });
    };
    document.querySelectorAll(".filters button").forEach((b) =>
      b.addEventListener("click", () => {
        document.querySelectorAll(".filters button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        filter = b.dataset.f;
        apply();
      })
    );

    const render = (f) => {
      const li = el("li", "tl sec-" + f.section + (f.flash ? " flash" : ""));
      li.dataset.sec = f.section; li.dataset.flash = f.flash ? "1" : "0"; li.dataset.id = f.id;
      const t = el("time", null, hhmm(f.time)); t.dateTime = f.time; t.appendChild(el("small", null, mmdd(f.time)));
      const body = el("div", "tl-body"); const tags = el("div", "tl-tags");
      if (f.flash) tags.appendChild(el("span", "badge", "속보"));
      if (f.official) tags.appendChild(el("span", "badge off", "공식발표"));
      tags.appendChild(el("span", "chip sec-" + f.section, names[f.section] || ""));
      (f.people || []).forEach((p) => tags.appendChild(el("span", "chip person", p)));
      const a = el("a", "tl-title", f.ko); a.href = safeUrl(f.url); a.target = "_blank"; a.rel = "noopener";
      body.append(tags, a);
      if (f.lang !== "ko" && f.ko !== f.title) body.appendChild(el("p", "orig", f.title));
      const src = el("p", "src", f.outlet);
      if (f.also && f.also.length) src.appendChild(el("span", "also", " · 함께 보도: " + f.also.join(", ")));
      body.appendChild(src);
      li.append(t, body);
      return li;
    };

    const known = new Set();
    const upd = document.getElementById("updated");
    async function refresh(first) {
      try {
        const feed = await load(tl.dataset.src);
        if (first) { tl.innerHTML = ""; }
        const fresh = feed.filter((f) => !known.has(f.id));
        const nodes = fresh.map((f) => { known.add(f.id); const n = render(f); if (!first) n.classList.add("new"); return n; });
        if (first) nodes.forEach((n) => tl.appendChild(n));
        else nodes.reverse().forEach((n) => tl.prepend(n));
        if (!feed.length && first) tl.appendChild(el("li", "empty", "아직 수집된 속보가 없습니다."));
        apply();
        if (upd) upd.textContent = "마지막 확인 " + hhmm(new Date().toISOString());
      } catch (e) { /* 정적 파일 직접 열람 등: 서버 렌더 목록 유지 */ }
    }
    refresh(true);
    setInterval(() => refresh(false), REFRESH_MS);
  }

  // ── 1면 속보 상자 ──
  const box = document.querySelector("ol.flash[data-live]");
  if (box) {
    setInterval(async () => {
      try {
        const feed = (await load(box.dataset.live)).slice(0, 8);
        if (!feed.length) return;
        box.innerHTML = "";
        feed.forEach((f) => {
          const li = el("li"); li.appendChild(el("time", null, hhmm(f.time)));
          const a = el("a", null, f.ko); a.href = safeUrl(f.url); a.target = "_blank"; a.rel = "noopener";
          li.append(a, el("span", "src", f.outlet)); box.appendChild(li);
        });
      } catch (e) {}
    }, REFRESH_MS);
  }

  const clock = document.getElementById("clock");
  if (clock) {
    const tick = () => (clock.textContent = fmt(new Date().toISOString(), { year: "numeric", month: "long", day: "numeric", weekday: "long", hour: "2-digit", minute: "2-digit" }) + " KST");
    tick(); setInterval(tick, 30000);
  }
})();
