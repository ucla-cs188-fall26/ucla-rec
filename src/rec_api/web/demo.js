/* Sample data for previewing the dashboard without an API.
   Events and Wooden zone names come from real saved pages; everything else is invented. */
(() => {
  "use strict";
  const TZ = "America/Los_Angeles";
  const FACILITIES = [
    { id: "wooden-center", name: "John Wooden Center", type: "gym", venues: ["JWC"] },
    { id: "bfit", name: "BFit", type: "fitness_center", venues: [] },
    { id: "hitch-courts", name: "Hitch Basketball Courts", type: "court", venues: [] },
    { id: "sunset-rec", name: "Sunset Rec", type: "gym", venues: ["SCRC"] },
    { id: "pools", name: "Pools", type: "pool",
      venues: ["Park Pool", "Dirks Pool", "Family Pool", "North Pool", "SAC Pool", "Student Activities Center Pool"] },
  ];
  // [name, open, count, percent_full, capacity, band]
  const WOODEN = [["Collins Court", true, 35, 1.9358407079646016, 1808, "low"], ["Pardee Gym", true, 16, 32.0, 50, "low"], ["Cardio Zone", true, 30, 50.0, 60, "low"], ["Free Weight Zone", true, 41, 63.07692307692307, 65, "medium"], ["Functional Training Zone", true, 17, 42.5, 40, "low"], ["Advanced Circuit Zone", true, 36, 80.0, 45, "medium"], ["Novice Circuit Zone", true, 16, 80.0, 20, "medium"], ["The Pit", true, 36, 72.0, 50, "medium"]];
  const BFIT = [["Cardio", true, 31, 62, 50, "medium"], ["Strength", true, 22, 37, 60, "low"],
                ["Group fitness room", true, 0, 0, 40, "low"], ["Stretch area", false, 0, null, null, null]];
  const SUNSET = [["Fitness floor", true, 12, 24, 50, "low"], ["Courts", true, 18, 90, 20, "high"]];
  const OFFICIAL = { "wooden-center": [WOODEN, 7], bfit: [BFIT, 4], "sunset-rec": [SUNSET, 9] };
  // minutes ago, level 1 to 3
  const REPORTS = {
    "hitch-courts": [[4, 2], [12, 3], [20, 2], [31, 1]],
    pools: [[8, 1], [26, 1]],
    "wooden-center": [[6, 2], [15, 3], [33, 2]],
    "sunset-rec": [[19, 1]],
  };
  // [name, kind, venue, space, startMinuteOfDay, endMinuteOfDay]
  const EVENTS = [["Custodial Cleaning","maintenance","JWC","Yates Gym",0,30],["DIA Soccer Post Season Championships","athletics","WAS","Annenberg Stadium",0,0],["Custodial Cleaning","maintenance","JWC","Collins Courts All",300,390],["DIA Women's Volleyball Games","athletics","Pauley","Pavilion Club - ALL",300,780],["JWC Seismic Improvement Project","maintenance","JWC","Courtyard",300,300],["JWC Seismic Improvement Project","maintenance","JWC","Dynasty",300,300],["JWC Seismic Improvement Project","maintenance","JWC","EVTLob",300,300],["JWC Seismic Improvement Project","maintenance","JWC","Plaza View",300,300],["JWC Seismic Improvement Project","maintenance","JWC","Squash 10",300,300],["Open Recreation Fitness","open_recreation","JWC","Pardee - East",315,420],["Open Recreation Fitness","open_recreation","JWC","Pardee - West",315,645],["Bruin Masters Swimming","club_sport","Park Pool","PP - All",345,435],["Army ROTC Leadership Lab","other","SCRC","Mesa Lawn",360,540],["DIA Football Practice (Backup)","athletics","IM Field","4 - NE",360,720],["DIA Football Practice (Backup)","athletics","IM Field","5 - NM",360,720],["DIA Football Practice (Backup)","athletics","IM Field","6 - NW",360,720],["DIA WSW F26","athletics","Dirks Pool","DP - 35m",360,510],["JWC Training","other","JWC","Yates Conference",360,540],["Lap Swimming (FP) 2026","open_recreation","Family Pool","FP - All",360,600],["Open Recreation","open_recreation","Drake","Track 5-9",360,480],["Open Recreation","open_recreation","SCRC","Amph Lawn - All",360,1200],["BHIPOn-Class- Fitwell","class","Drake","Track - NE",375,435],["MRugby-Practice- Comp","club_sport","Drake","NPFE",390,510],["MRugby-Practice- Comp","club_sport","Drake","NPFW",390,510],["Open Recreation Basketball","open_recreation","JWC","Collins 1",390,945],["Open Recreation Basketball","open_recreation","JWC","Collins 2",390,945],["Open Recreation Basketball","open_recreation","JWC","Collins 3",390,1080],["UCLA Women's Rowing","athletics","Drake","Upper North Con",390,600],["UCLA Women's Rowing","athletics","Drake","Upper South Con",390,600],["Club Swimming 26-27","club_sport","SAC Pool","SAC - Lane 1",420,480],["Club Swimming 26-27","club_sport","SAC Pool","SAC - Lane 2",420,480],["Club Swimming 26-27","club_sport","SAC Pool","SAC - Lane 3",420,480],["Club Swimming 26-27","club_sport","SAC Pool","SAC - Lane 4",420,480],["Club Triathlon 26-27","club_sport","SAC Pool","SAC - Lane 5",420,480],["Club Triathlon 26-27","club_sport","SAC Pool","SAC - Lane 6",420,480],["Club Triathlon 26-27","club_sport","SAC Pool","SAC - Lane 7",420,480],["Club Triathlon 26-27","club_sport","SAC Pool","SAC - Lane 8",420,480],["DIA Golf Practice","athletics","IM Field","2 - SM",420,720],["DIA Golf Practice","athletics","IM Field","5 - NM",420,720],["DIA--WDV Fall26 Training","athletics","Park Pool","PP - Dryland",420,840],["GSRC","other","SAC","Room 4",420,1140],["UCLA Cheer Squad Practice","athletics","JWC","Pardee - East",420,540],["UCLA Dance Team Practice","athletics","JWC","Gold Room",420,540],["Archer Cross Country Locker Room Use","other","North Pool","NP - Classroom",435,465],["BHIPOn-Class- Fitwell","class","Drake","Track - NE",435,495],["Open Recreation","open_recreation","Drake","NFIT",435,1035],["DIA Gymnastics Practice","athletics","JWC","Yates Gym",450,675],["DIA--WDV Fall26 Training","athletics","Dirks Pool","DP - 15m",450,570],["MARTIALART-CLASS- Comp","class","JWC","Blue Room",450,540],["Athletic Performance - Softball","athletics","IM Field","1 - SW",480,540]];
  const EXTRA = [
    ["Open Recreation Basketball", "open_recreation", "Hitch", "Court 1", 8 * 60, 22 * 60],
    ["Court resurfacing", "maintenance", "Hitch", "Court 2", 9 * 60, 13 * 60],
    ["Intramural Basketball", "club_sport", "Hitch", "Courts 1-2", 18 * 60, 21 * 60],
    ["Equipment inspection", "maintenance", "BFit", "Weight room", 6 * 60, 8 * 60],
    ["BHIPOn-Class- Cycle", "class", "BFit", "Studio", 17 * 60, 18 * 60],
  ];
  const FACILITY_OF = { JWC: "wooden-center", SCRC: "sunset-rec", Hitch: "hitch-courts", BFit: "bfit",
    "Park Pool": "pools", "Dirks Pool": "pools", "Family Pool": "pools", "North Pool": "pools", "SAC Pool": "pools" };

  const reports = {};
  for (const k in REPORTS) reports[k] = REPORTS[k].map(([m, l], i) => ({ user: "seed" + i, at: Date.now() - m * 60000, level: l }));
  let tokenUser = null;

  const iso = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z");
  // The UTC instant that is midnight in Los Angeles, `offsetDays` from today.
  const dayStartUtc = (offsetDays) => {
    const key = new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date(Date.now() + offsetDays * 864e5));
    const [y, m, d] = key.split("-").map(Number);
    const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    for (let h = 6; h <= 9; h++) {                 // midnight in LA is 07:00 or 08:00 UTC
      const t = Date.UTC(y, m - 1, d, h);
      if (fmt.format(new Date(t)) === "00:00") return t;
    }
    return Date.UTC(y, m - 1, d, 8);
  };

  function official(id) {
    const o = OFFICIAL[id]; if (!o) return null;
    const asOf = Date.now() - o[1] * 60000;
    return { as_of: iso(asOf), stale: false, zones: o[0].map(([name, open, count, pct, cap, band]) => ({
      zone_id: name.toLowerCase().replace(/[^a-z0-9]+/g, "-"), name, open, count, percent_full: pct, capacity: cap, band, updated_at: iso(asOf) })) };
  }
  function combine(levels) {
    let s = [...levels].sort(), method = "median";
    if (s.length >= 5) { s = s.slice(1, -1); method = "trimmed_median"; }
    const mid = s.length >> 1, score = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
    return [score, method];
  }
  function reported(id) {
    const since = Date.now() - 45 * 60000, latest = {};
    for (const r of (reports[id] || []).filter((r) => r.at >= since).sort((a, b) => a.at - b.at)) latest[r.user] = r;
    const list = Object.values(latest); if (!list.length) return null;
    const [score, method] = combine(list.map((r) => r.level));
    const level = Math.floor(score + 0.5);
    return { level, label: ["", "Quiet", "Moderate", "Busy"][level], score, reports: list.length, window_minutes: 45, method,
             as_of: iso(Math.max(...list.map((r) => r.at))) };
  }
  const activity = (id) => ({ facility_id: id, official: official(id), reported: reported(id) });

  function events(id) {
    const out = [], now = Date.now();
    for (const day of [0, 1, 2]) {
      const base = dayStartUtc(day);
      [...EVENTS, ...EXTRA].forEach(([name, kind, venue, space, s, e], i) => {
        if (FACILITY_OF[venue] !== id) return;
        const start = base + s * 60000, end = base + e * 60000;
        out.push({ id: day * 1000 + i, name, kind, status: "scheduled", start: iso(start), end: iso(end), all_day: false,
          location: space ? venue + " - " + space : venue, venue, space, facility_id: id, source_id: "sample" });
      });
    }
    return out.sort((a, b) => a.start.localeCompare(b.start));
  }

  // Sample pool calendar: three weeks starting with this week's Monday, one maintenance
  // stretch and one holiday, in the order the real calendar lists a day's pools.
  function poolCalendar(id) {
    if (id !== "pools") return [];
    const out = [];
    const la = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date());
    const dow = (new Date(la + "T12:00:00Z").getUTCDay() + 6) % 7;
    const PP = ["PP", "Park Pool"], FP = ["FP", "Family Pool"], SAC = ["SAC", "Student Activities Center Pool"], NP = ["North Pool", "North Pool"];
    for (let d = -dow; d < -dow + 21; d++) {
      const base = dayStartUtc(d), wk = (d + dow) % 7, idx = d + dow;
      const row = (name, kind, [code, venue], s, e, all) => out.push({ id: out.length + 1, name, kind, status: "scheduled",
        start: iso(base + (all ? 0 : s) * 60000), end: iso(base + (all ? 1440 : e) * 60000), all_day: !!all, location: venue, venue,
        space: code, facility_id: id, source_id: "sample-pool-calendar" });
      if (idx === 16) { for (const p of [PP, FP, SAC]) row("Thanksgiving Holiday All Pools Closed", "closed", p, 0, 0, true); continue; }
      if (idx >= 12 && idx <= 13) {
        row("Closed (SCRC Maintenance)", "closed", PP, 0, 0, true); row("Closed (SCRC Maintenance)", "closed", FP, 0, 0, true);
        row("Closed (Deck Maintenance)", "closed", SAC, 0, 0, true); row("Hours not yet posted", "tbd", NP, 0, 0, true); continue;
      }
      if (wk < 5) {
        row("Open", "pool_hours", PP, 660, 1200); row("Open Rec Diving", "pool_activity", PP, 900, 1020);
        row("Open", "pool_hours", FP, 360, 600); row("Open", "pool_hours", FP, 720, 1080);
        row("Adult Lessons Lap Lanes", "pool_activity", FP, 1020, 1080); row("Open", "pool_hours", SAC, 660, 780);
        if (wk === 1) row("Aqua Tabata BH Area", "pool_activity", SAC, 720, 780);
      } else {
        row("Open", "pool_hours", PP, 600, 1080); row("Open Rec Diving", "pool_activity", PP, 780, 900);
        row("Open", "pool_hours", FP, 600, 1080);
      }
    }
    return out;
  }

  const fail = (status, message) => Object.assign(new Error(message), { status });

  window.recDemoApi = async (method, path, body, token) => {
    await new Promise((r) => setTimeout(r, 120));
    const url = new URL(path, "http://x"), p = url.pathname;
    if (p === "/v1/facilities") return FACILITIES;
    if (p === "/v1/activity") return FACILITIES.map((f) => activity(f.id));
    let m;
    if ((m = p.match(/^\/v1\/facilities\/([^/]+)\/activity$/))) return activity(m[1]);
    if (p === "/v1/events") {
      const fid = url.searchParams.get("facility_id"), kinds = (url.searchParams.get("kind") || "").split(",").filter(Boolean);
      const date = url.searchParams.get("date");
      const from = url.searchParams.get("from") || date, to = url.searchParams.get("to") || date;
      const la = (iso) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date(iso));
      const list = from
        ? [...events(fid), ...poolCalendar(fid)].filter((e) => la(e.start) >= from && la(e.start) <= to).sort((a, b) => (a.start < b.start ? -1 : 1))
        : events(fid);
      return kinds.length ? list.filter((e) => kinds.includes(e.kind)) : list;
    }
    if (p === "/v1/auth/code") {
      if (!/@(g\.)?ucla\.edu$/i.test((body.email || "").trim())) throw fail(422, "use your UCLA email address (@ucla.edu or @g.ucla.edu)");
      return { status: "sent", expires_in_seconds: 600, dev_code: "123456" };
    }
    if (p === "/v1/auth/verify") {
      if (body.code !== "123456") throw fail(422, "that code is not right");
      tokenUser = "me"; return { token: "demo-token", expires_at: iso(Date.now() + 30 * 864e5) };
    }
    if ((m = p.match(/^\/v1\/facilities\/([^/]+)\/reports$/))) {
      if (token !== "demo-token") throw fail(401, "sign in with your UCLA email first");
      (reports[m[1]] = reports[m[1]] || []).push({ user: "me", at: Date.now(), level: body.level });
      return { status: "recorded", facility_id: m[1], level: body.level, reported: reported(m[1]) };
    }
    throw fail(404, "not found");
  };
})();