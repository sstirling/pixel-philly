// Live weather on the map: falling pixel snow or rain when it's snowing or
// raining in Philadelphia, and nothing otherwise (Stephen, Nov. 18: "nothing
// spectacular").
//
// Data: live/weather.json, written every 5 minutes by the Cloudflare Worker
// (worker/septa-live.js) from the National Weather Service's latest
// observation at Philadelphia International Airport (KPHL), or locally by
// scripts/38_live_feed.py. {"observed", "kind": "snow"|"rain"|"mix"|null,
// "intensity": "light"|"moderate"|"heavy"|null, "text", "temp_c", "night",
// "thunder"}.
//
// The same file feeds a small temperature badge in the top-right corner
// (Stephen, Nov. 19), drawn in a pixel font so it matches the map.
//
// Drawing: one canvas over the map, in screen space, so weather looks the
// same at every zoom. Particles are 1 px streaks (rain) and 2-3 px squares
// (snow), like the map's pixel art. Thunderstorms (Stephen, Nov. 19) darken
// the wash and add a pixel lightning bolt every 6-16 seconds with a soft,
// brief brightening: far below WCAG 2.3.1's limit of three flashes a second,
// and none at all with reduced motion. The
// animation loop runs only while there is weather to draw and the tab is
// visible, and never with prefers-reduced-motion.

export const POLL_MS = 5 * 60 * 1000;
export const STALE_S = 2 * 3600; // an observation older than this isn't "now"
// Particles per 1920 x 1080 window, scaled to the window's area. The map is
// busy, so fewer than a few hundred barely show (tried 60-300 first, Nov. 18)
const DENSITY = { light: 220, moderate: 450, heavy: 850 };
// A faint wash over the whole map, so the weather reads at a glance: cool gray
// for rain, a pale haze for snow (alpha by intensity)
const WASH = { rain: [70, 82, 100], snow: [235, 240, 248], mix: [150, 160, 175], storm: [34, 40, 58] };
const WASH_ALPHA = { light: 0.06, moderate: 0.1, heavy: 0.15 };
const STORM_EXTRA = 0.08; // a thunderstorm's wash is darker than plain rain's
// Lightning: seconds between strikes, how long the bolt shows, and the soft
// brightening (peak alpha of a pale wash, fading with this time constant)
const STRIKE_GAP_S = [6, 16];
const BOLT_MS = 160;
const FLASH_PEAK = 0.12, FLASH_TAU_MS = 140;
const LABEL = { snow: "snow", rain: "rain", mix: "rain and snow" };

// What to draw for a weather record at nowS (unix s): {kind, intensity, thunder} or null
export function activeWeather(rec, nowS) {
  if (!rec || !(rec.kind || rec.thunder) || rec.observed == null || nowS - rec.observed > STALE_S) return null;
  return { kind: rec.kind || null, intensity: rec.intensity || "moderate", thunder: !!rec.thunder };
}

// "Light snow at Philadelphia International Airport." for the status line
export function describeWeather(w) {
  if (!w) return "";
  let text;
  if (!w.kind) text = "thunder";
  else {
    const level = w.intensity === "moderate" ? "" : `${w.intensity} `;
    text = `${level}${LABEL[w.kind] || w.kind}${w.thunder ? " and thunder" : ""}`;
  }
  text += " at Philadelphia International Airport.";
  return text[0].toUpperCase() + text.slice(1);
}

// Is the sun down at Philadelphia International Airport at unix time nowS?
// The badge's sun or moon comes from this, not from NWS: its reports sometimes
// arrive without the day/night icon (Nov. 19, 2026, after dark, which showed a
// sun), and a report can be up to 2 hours old. Solar elevation from the
// standard low-precision formulas (Astronomical Almanac, about 0.01 degree
// accuracy); "down" is below -0.833 degrees, the usual sunrise/sunset
// definition (refraction plus the sun's radius).
const KPHL_LAT = 39.8721, KPHL_LON = -75.2411;
export function sunIsDown(nowS, lat = KPHL_LAT, lon = KPHL_LON) {
  const rad = Math.PI / 180;
  const d = nowS / 86400 + 2440587.5 - 2451545.0; // days since J2000
  const g = (357.529 + 0.98560028 * d) * rad;     // mean anomaly
  const q = 280.459 + 0.98564736 * d;             // mean longitude, degrees
  const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 0.00000036 * d) * rad;      // obliquity
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = (18.697374558 + 24.06570982441908 * d) * 15; // degrees
  const ha = (gmst + lon) * rad - ra;
  const elev = Math.asin(Math.sin(lat * rad) * Math.sin(dec) + Math.cos(lat * rad) * Math.cos(dec) * Math.cos(ha));
  return elev / rad < -0.833;
}

// --- temperature badge ---------------------------------------------------------
// A 3 x 5 bitmap font: each glyph is five rows, "1" = a lit pixel. Only the
// characters the badge uses.
const FONT = {
  "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
  "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
  "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
  "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "001", "001", "001"],
  "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
  "-": ["000", "000", "111", "000", "000"], "°": ["010", "101", "010", "000", "000"],
  F: ["111", "100", "110", "100", "100"], P: ["110", "101", "110", "100", "100"],
  H: ["101", "101", "111", "101", "101"], L: ["100", "100", "100", "100", "111"],
};
// 9 x 9 icons. Letters are palette colors (ICON_COLORS); "." is empty.
const ICONS = {
  sun: ["....y....", ".y.....y.", "...ooo...", "..oyyyo..", "y.oyyyo.y", "..oyyyo..", "...ooo...", ".y.....y.", "....y...."],
  moon: ["...yyy...", "..yy.....", ".yy......", ".yy......", ".yy......", ".yy......", "..yy.....", "...yyy...", "........."],
  cloud: [".........", "...ggg...", "..gwwwg..", ".gwwwwwgg", "gwwwwwwwg", "gwwwwwwwg", ".ggggggg.", ".........", "........."],
  rain: ["...ggg...", "..gwwwg..", ".gwwwwwgg", "gwwwwwwwg", ".ggggggg.", ".........", ".b..b..b.", "b..b..b..", "........."],
  snow: ["...ggg...", "..gwwwg..", ".gwwwwwgg", "gwwwwwwwg", ".ggggggg.", ".........", ".s...s...", "...s...s.", ".s...s..."],
  storm: ["...ggg...", "..gwwwg..", ".gwwwwwgg", "gwwwwwwwg", ".ggggggg.", "....yo...", "...yo....", "..yyyyo..", "....yo..."],
  fog: [".........", "ggggggg..", ".........", "..ggggggg", ".........", "ggggggg..", ".........", "..ggggggg", "........."],
};
// Chosen to read on the light and the dark panel alike
const ICON_COLORS = { y: "#e8a317", o: "#b86e00", g: "#6b7686", w: "#e4e9f0", b: "#2f7fd6", s: "#8fb3dc" };

const SVG_NS = "http://www.w3.org/2000/svg";

// An <svg> of square pixels: rows of characters, color(ch) gives each fill
// (null = empty), with crisp edges. Each pixel is `scale` CSS px, unless the
// CSS variable `sizeVar` says otherwise (viewer.css shrinks them on phones).
function pixelSvg(rows, scale, color, sizeVar) {
  const h = rows.length, w = Math.max(...rows.map((r) => r.length));
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("width", w * scale);
  svg.setAttribute("height", h * scale);
  svg.style.width = `calc(${w} * var(${sizeVar}, ${scale}px))`;
  svg.style.height = `calc(${h} * var(${sizeVar}, ${scale}px))`;
  svg.setAttribute("shape-rendering", "crispEdges");
  svg.setAttribute("aria-hidden", "true");
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    const fill = color(ch);
    if (!fill) return;
    const r = document.createElementNS(SVG_NS, "rect");
    r.setAttribute("x", x); r.setAttribute("y", y); r.setAttribute("width", 1); r.setAttribute("height", 1);
    r.setAttribute("fill", fill);
    svg.appendChild(r);
  }));
  return svg;
}

// Rows for a string in the 3 x 5 font, one blank column between glyphs
export function textRows(str) {
  const glyphs = [...str].map((c) => FONT[c]).filter(Boolean);
  return [0, 1, 2, 3, 4].map((y) => glyphs.map((g) => g[y]).join("0"));
}

// What the badge shows for a weather record at nowS (unix s), or null when
// there's no fresh temperature: {f (whole degrees F), icon, text}
export function tempReading(rec, nowS) {
  if (!rec || typeof rec.temp_c !== "number" || rec.observed == null || nowS - rec.observed > STALE_S) return null;
  const f = Math.round(rec.temp_c * 9 / 5 + 32);
  const desc = String(rec.text || "");
  let icon;
  if (rec.thunder) icon = "storm";
  else if (rec.kind === "rain") icon = "rain";
  else if (rec.kind === "snow" || rec.kind === "mix") icon = "snow";
  else if (/fog|mist|haze|smoke/i.test(desc)) icon = "fog";
  else if (/cloudy|overcast/i.test(desc) && !/partly/i.test(desc)) icon = "cloud";
  else icon = sunIsDown(nowS) ? "moon" : "sun";
  return { f, icon, text: desc };
}

// Fills `el` with the badge for a reading, or hides it
export function renderTemp(el, reading) {
  if (!el) return;
  if (!reading) { el.hidden = true; el.replaceChildren(); el.removeAttribute("title"); return; }
  const label = `${reading.f}°F${reading.text ? `, ${reading.text.toLowerCase()}` : ""}, at Philadelphia International Airport`;
  const icon = pixelSvg(ICONS[reading.icon], 3, (c) => ICON_COLORS[c] || null, "--temp-icon-px");
  icon.classList.add("temp-icon");
  const temp = pixelSvg(textRows(`${reading.f}°F`), 4, (c) => (c === "1" ? "currentColor" : null), "--temp-text-px");
  const where = pixelSvg(textRows("PHL"), 2, (c) => (c === "1" ? "currentColor" : null), "--temp-where-px");
  where.classList.add("temp-where");
  const words = document.createElement("span");
  words.className = "visually-hidden";
  words.textContent = label;
  const stack = document.createElement("span");
  stack.className = "temp-stack";
  stack.append(temp, where);
  el.replaceChildren(icon, stack, words);
  el.title = label[0].toUpperCase() + label.slice(1);
  el.hidden = false;
}

// force: {kind, intensity} to draw without data (?weather=snow, for testing and demos)
// badge: the element for the temperature (renderTemp), or null
export function createWeatherLayer(container, { url, status = null, reduceMotion = false, force = null, badge = null }) {
  const canvas = document.createElement("canvas");
  canvas.className = "weather-layer";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);
  let current = null, raf = 0, last = 0, timer = null;
  let parts = [];
  let nextStrike = 0, strikeAt = -1e9, bolt = []; // lightning: ms (rAF clock) and the bolt's pixels

  function rand(a, b) { return a + Math.random() * (b - a); }

  function spawn(kind, w, h, anywhere) {
    const snow = kind === "snow";
    return {
      snow,
      x: rand(-40, w + 40),
      y: anywhere ? rand(0, h) : rand(-30, -2),
      // Snow drifts down slowly and sways; rain falls fast at a slant
      vy: snow ? rand(35, 80) : rand(650, 950),
      vx: snow ? rand(-14, 14) : rand(-150, -110),
      size: snow ? (Math.random() < 0.35 ? 4 : 3) : Math.round(rand(12, 20)),
      phase: rand(0, Math.PI * 2),
    };
  }

  function reset() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const n = current.kind ? Math.round(DENSITY[current.intensity] * (w * h) / (1920 * 1080)) : 0;
    parts = [];
    for (let i = 0; i < n; i++) {
      const kind = current.kind === "mix" ? (i % 2 ? "snow" : "rain") : current.kind;
      parts.push(spawn(kind, w, h, true));
    }
  }

  function frame(t) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, last ? (t - last) / 1000 : 0); // no leap after a pause
    last = t;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      reset();
    }
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const [r, gg, b] = WASH[current.thunder ? "storm" : current.kind] || WASH.rain;
    const washA = (WASH_ALPHA[current.intensity] ?? 0.1) + (current.thunder ? STORM_EXTRA : 0);
    g.fillStyle = `rgba(${r}, ${gg}, ${b}, ${washA})`;
    g.fillRect(0, 0, w, h);
    if (current.thunder) lightning(g, t, w, h);
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i];
      p.y += p.vy * dt;
      p.x += (p.vx + (p.snow ? Math.sin(t / 900 + p.phase) * 10 : 0)) * dt;
      if (p.y > h + 20 || p.x < -60 || p.x > w + 60) { parts[i] = spawn(p.snow ? "snow" : "rain", w, h, false); continue; }
      const x = Math.round(p.x), y = Math.round(p.y);
      if (p.snow) {
        // A white square with a dark edge below and right, so it shows on light roofs
        g.fillStyle = "rgba(30, 38, 56, 0.55)";
        g.fillRect(x + 1, y + 1, p.size, p.size);
        g.fillStyle = "#ffffff";
        g.fillRect(x, y, p.size, p.size);
      } else {
        // A slanted streak drawn as single pixels, along the direction of fall
        g.fillStyle = "rgba(225, 236, 250, 0.8)";
        const sx = p.vx / p.vy;
        for (let k = 0; k < p.size; k++) g.fillRect(Math.round(x - sx * k), y - k, 1, 1);
      }
    }
  }

  // A jagged bolt from the top of the window to a point 30-60% down, as runs
  // of whole pixels, with one short fork
  function makeBolt(w, h) {
    const px = [];
    let x = rand(w * 0.15, w * 0.85), y = 0;
    const end = rand(h * 0.3, h * 0.6);
    let fork = null;
    while (y < end) {
      const run = Math.round(rand(6, 16)), dx = Math.random() < 0.5 ? -1 : 1;
      for (let i = 0; i < run && y < end; i++) { px.push([Math.round(x), Math.round(y)]); y += 2; x += dx * rand(0, 1.6); }
      if (!fork && y > end * 0.4) fork = [x, y];
    }
    if (fork) {
      let [fx, fy] = fork; const dx = x > fork[0] ? -1 : 1;
      for (let i = 0; i < 18; i++) { px.push([Math.round(fx), Math.round(fy)]); fy += 2; fx += dx * 1.4; }
    }
    return px;
  }

  function lightning(g, t, w, h) {
    if (!nextStrike) nextStrike = t + rand(1, 4) * 1000; // the first strike comes soon after the storm starts
    if (t >= nextStrike) {
      strikeAt = t;
      bolt = makeBolt(w, h);
      nextStrike = t + rand(...STRIKE_GAP_S) * 1000;
    }
    const age = t - strikeAt;
    if (age < 0 || age > 6 * FLASH_TAU_MS) return;
    // Soft brightening of the whole window, fading fast
    g.fillStyle = `rgba(235, 240, 255, ${FLASH_PEAK * Math.exp(-age / FLASH_TAU_MS)})`;
    g.fillRect(0, 0, w, h);
    if (age > BOLT_MS) return;
    // The bolt: a 2 px white core with a pale blue edge
    g.fillStyle = "rgba(170, 195, 255, 0.7)";
    for (const [x, y] of bolt) g.fillRect(x - 1, y - 1, 4, 4);
    g.fillStyle = "#ffffff";
    for (const [x, y] of bolt) g.fillRect(x, y, 2, 2);
  }

  function start() {
    if (raf || !current || reduceMotion || document.hidden) return;
    last = 0;
    nextStrike = 0;
    canvas.width = 0; // forces a resize and a fresh set of particles
    raf = requestAnimationFrame(frame);
  }
  function stop() {
    cancelAnimationFrame(raf);
    raf = 0;
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  }

  function set(w) {
    const changed = JSON.stringify(w) !== JSON.stringify(current);
    current = w;
    if (status) status.textContent = describeWeather(w);
    if (!w) stop();
    else if (changed) { stop(); start(); }
  }

  async function poll() {
    try {
      const r = await fetch(url, { cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const rec = await r.json();
      if (!force) set(activeWeather(rec, Date.now() / 1000));
      renderTemp(badge, tempReading(rec, Date.now() / 1000));
    } catch {
      if (!force) set(null); // no weather file (or no network): draw nothing
      renderTemp(badge, null);
    }
  }

  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  // A forced animation (?weather=snow) still polls for the real temperature,
  // but its animation never changes
  if (force) set(force);
  poll(); timer = setInterval(poll, POLL_MS);
  return { canvas, set, running: () => raf !== 0, stopPolling: () => clearInterval(timer) };
}
