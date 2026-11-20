// Pixel Philly live transit feed: a Cloudflare Worker on a one-minute cron.
//
// SEPTA's live feeds send no CORS header, so a browser on
// pixelphilly.sstirling.com can't read them directly. This Worker fetches
// them four times a minute (15 s apart), keeps only vehicles on the map and
// writes one small JSON file to the R2 bucket that hosts the map:
//   live/vehicles.json  (served at https://pixelphilly.sstirling.com/live/vehicles.json)
// Every viewer then reads that one cached file, so SEPTA sees 4 requests a
// minute however many people are watching, and viewer traffic never counts
// against Worker limits.
//
// Feeds (no key needed; https://www3.septa.org/developer/):
// - TransitViewAll: buses and trolleys, with GPS heading and a report time.
// - TrainView: Regional Rail; no heading (the viewer takes direction from the track).
// The Market-Frankford El and the Broad Street Line are in neither feed; the
// viewer places El trains from the timetable instead.
//
// Output: {"fetched": unix s, "vehicles": [[source, route, id, lon, lat,
//   heading|null, late min|null, destination, report time unix s, cars|null], ...]}
// source "tv" (TransitView: route is the route id) or "rr" (TrainView: route
// is the line name, e.g. "Trenton").
//
// If a feed fails, the last good file is left in place; the viewer warns when
// it's more than two minutes old.
//
// Weather: every 5 minutes it also writes live/weather.json from the National
// Weather Service's latest observation at Philadelphia International Airport
// (public domain, https://www.weather.gov/documentation/services-web-api):
//   {"fetched", "observed" (unix s), "station", "kind": "snow"|"rain"|"mix"|null,
//    "intensity": "light"|"moderate"|"heavy"|null, "text",
//    "temp_c" (as reported, or null), "night" (true|false|null), "thunder" (true|false)}
// The viewer animates rain or snow from it, and draws nothing otherwise, and
// shows the temperature in a small pixel badge. A
// weather failure never touches vehicles.json.
//
// Setup (Cloudflare dashboard, no build step): see README "Live transit layer".
// Bindings: an R2 bucket binding named BUCKET -> pixel-philly. Trigger: cron "* * * * *".
// The only export is the default handler object: Workers treat other named
// exports of the main module as entrypoints, so helpers stay unexported.
// Tests: tests/test_live_feed.py runs normalize() in Chromium against saved
// SEPTA responses and checks it matches scripts/38_live_feed.py;
// tests/test_weather.py does the same for weatherKind() and weatherRecord().

const TRANSITVIEW = "https://www3.septa.org/api/TransitViewAll/index.php";
const TRAINVIEW = "https://www3.septa.org/api/TrainView/index.php";
// The v18 map's lon/lat extent (map.json fit.bounds_wgs84); the viewer
// also drops vehicles outside the city line
const BOUNDS = [-75.28399636541867, 39.86480815125875, -74.94781362117637, 40.141246179090835];
const MAX_REPORT_AGE_S = 300; // a bus that hasn't reported in 5 minutes is likely out of service
const POLLS_PER_RUN = 4;
const POLL_INTERVAL_MS = 15000;
const STATION = "KPHL";
const WEATHER_URL = `https://api.weather.gov/stations/${STATION}/observations/latest`;
const WEATHER_EVERY_MIN = 5; // KPHL reports hourly, plus special reports when the weather changes
// METAR present-weather codes. Falling snow, snow grains and ice pellets are
// drawn as snow; rain, drizzle and unknown precipitation as rain. Fog, mist
// and haze draw nothing; thunder is flagged separately (weatherThunder) and gets
// its own storm look.
const SNOW = new Set(["SN", "SG", "PL"]);
const RAIN = new Set(["RA", "DZ", "UP"]);
const DESCRIPTORS = new Set(["MI", "PR", "BC", "DR", "BL", "SH", "TS", "FZ"]);
const LEVELS = [null, "light", "moderate", "heavy"];

const num = (v) => {
  const x = typeof v === "number" ? v : parseFloat(v);
  return Number.isFinite(x) ? x : null;
};
const round6 = (x) => Math.round(x * 1e6) / 1e6;
// SEPTA reports 998/999 minutes late when it has no estimate
const lateness = (v) => {
  const x = num(v);
  return x === null || Math.abs(x) > 600 ? null : x;
};
const inside = (lon, lat, b) => lon >= b[0] && lon <= b[2] && lat >= b[1] && lat <= b[3];
// TrainView reports trains it can't locate at one fixed point in Suburban
// Station, even when their current stop is miles away (observed, not
// documented; 7 of 24 trains in tests/fixtures/septa/trainview.json). Those
// aren't positions, so they're dropped. Compared at 5 decimal places (~1 m).
const PLACEHOLDER = [-75.1677778, 39.9538889];
const isPlaceholder = (lon, lat) =>
  Math.round(lon * 1e5) === Math.round(PLACEHOLDER[0] * 1e5) && Math.round(lat * 1e5) === Math.round(PLACEHOLDER[1] * 1e5);

function normalize(transitView, trainView, nowS, bounds = BOUNDS) {
  const vehicles = [];
  for (const group of transitView?.routes || []) {
    for (const [route, list] of Object.entries(group)) {
      for (const v of list || []) {
        const lon = num(v.lng), lat = num(v.lat), ts = num(v.timestamp);
        if (lon === null || lat === null || !inside(lon, lat, bounds)) continue;
        if (ts !== null && nowS - ts > MAX_REPORT_AGE_S) continue;
        vehicles.push(["tv", String(v.route_id || route), String(v.VehicleID ?? v.label ?? ""), round6(lon), round6(lat),
          num(v.heading), lateness(v.late), String(v.destination || ""), ts ?? nowS, null]);
      }
    }
  }
  for (const t of Array.isArray(trainView) ? trainView : []) {
    const lon = num(t.lon), lat = num(t.lat);
    if (lon === null || lat === null || !inside(lon, lat, bounds) || isPlaceholder(lon, lat)) continue;
    const consist = String(t.consist || "").split(",").filter((c) => c.trim()).length;
    vehicles.push(["rr", String(t.line || ""), String(t.trainno || ""), round6(lon), round6(lat),
      null, lateness(t.late), String(t.dest || ""), nowS, consist || null]);
  }
  vehicles.sort((a, b) => (a[0] + a[2] < b[0] + b[2] ? -1 : a[0] + a[2] > b[0] + b[2] ? 1 : 0));
  return { fetched: nowS, vehicles };
}

// [kind, intensity] for an NWS presentWeather list (same as weather_kind in
// scripts/38_live_feed.py). Only rawString is read (e.g. "-SN", "+TSRA",
// "RASN"). Weather in the vicinity (VC) and blowing or drifting snow (BL, DR:
// lifted off the ground, not falling) don't count.
function weatherKind(presentWeather) {
  let snow = false, rain = false, level = 0;
  for (const item of presentWeather || []) {
    const raw = String((item && item.rawString) || "").trim().toUpperCase();
    if (!raw || raw.startsWith("VC")) continue;
    const lvl = raw[0] === "-" ? 1 : raw[0] === "+" ? 3 : 2;
    let code = raw.replace(/^[+-]+/, "");
    let lifted = false;
    while (DESCRIPTORS.has(code.slice(0, 2))) {
      lifted = lifted || code.startsWith("BL") || code.startsWith("DR");
      code = code.slice(2);
    }
    if (lifted) continue;
    const found = [];
    for (let i = 0; i < code.length; i += 2) found.push(code.slice(i, i + 2));
    const s = found.some((c) => SNOW.has(c)), r = found.some((c) => RAIN.has(c));
    if (s || r) { snow = snow || s; rain = rain || r; level = Math.max(level, lvl); }
  }
  const kind = snow && rain ? "mix" : snow ? "snow" : rain ? "rain" : null;
  return [kind, kind ? LEVELS[level] : null];
}

// Is there a thunderstorm at the station (same as weather_thunder in
// scripts/38_live_feed.py)? Any report with the TS descriptor ("TSRA", "+TSRA",
// "TS"); a storm in the vicinity ("VCTS") doesn't count, as for rain and snow.
function weatherThunder(presentWeather) {
  for (const item of presentWeather || []) {
    let code = String((item && item.rawString) || "").trim().toUpperCase().replace(/^[+-]+/, "");
    if (code.startsWith("VC")) continue;
    while (DESCRIPTORS.has(code.slice(0, 2))) {
      if (code.startsWith("TS")) return true;
      code = code.slice(2);
    }
  }
  return false;
}

// What live/weather.json holds, from an NWS observation response
function weatherRecord(observation, nowS) {
  const props = (observation && observation.properties) || {};
  const ts = props.timestamp ? Date.parse(props.timestamp) : NaN;
  const [kind, intensity] = weatherKind(props.presentWeather);
  return { fetched: nowS, observed: Number.isFinite(ts) ? Math.floor(ts / 1000) : null, station: STATION, kind, intensity,
           text: String(props.textDescription || ""), temp_c: tempC(props.temperature), night: isNight(props.icon),
           thunder: weatherThunder(props.presentWeather) };
}

// Degrees Celsius as NWS reports them, unrounded; null when missing or when
// NWS quality control marks the value as failed ("X")
function tempC(t) {
  if (!t || typeof t.value !== "number" || !Number.isFinite(t.value) || t.qualityControl === "X") return null;
  return t.value;
}

// NWS's icon URL says day or night (".../icons/land/night/skc?size=medium")
function isNight(icon) {
  const m = /\/land\/(day|night)\//.exec(String(icon || ""));
  return m ? m[1] === "night" : null;
}

async function pollWeather(env) {
  const obs = await getJson(WEATHER_URL);
  await env.BUCKET.put("live/weather.json", JSON.stringify(weatherRecord(obs, Math.floor(Date.now() / 1000))), {
    httpMetadata: { contentType: "application/json", cacheControl: "public, max-age=60" },
  });
}

async function getJson(url) {
  const r = await fetch(url, { headers: { "User-Agent": "pixel-philly live map (https://github.com/sstirling/pixel-philly)" },
                               cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function pollOnce(env) {
  const [tv, rr] = await Promise.all([getJson(TRANSITVIEW), getJson(TRAINVIEW)]);
  const out = normalize(tv, rr, Math.floor(Date.now() / 1000));
  await env.BUCKET.put("live/vehicles.json", JSON.stringify(out), {
    httpMetadata: { contentType: "application/json", cacheControl: "public, max-age=10" },
  });
  return out.vehicles.length;
}

export default {
  async scheduled(event, env, ctx) {
    if (new Date(event.scheduledTime).getUTCMinutes() % WEATHER_EVERY_MIN === 0) {
      try {
        await pollWeather(env);
      } catch (err) {
        console.log(`weather failed: ${err}`); // keep the last good file
      }
    }
    for (let i = 0; i < POLLS_PER_RUN; i++) {
      const started = Date.now();
      try {
        await pollOnce(env);
      } catch (err) {
        console.log(`poll ${i} failed: ${err}`); // keep the last good file
      }
      if (i < POLLS_PER_RUN - 1) {
        await new Promise((res) => setTimeout(res, Math.max(0, POLL_INTERVAL_MS - (Date.now() - started))));
      }
    }
  },
  // Visiting the Worker's own URL reports how fresh the file is. It never
  // polls SEPTA or writes, so nobody can run up requests or bucket writes.
  async fetch(request, env) {
    const obj = await env.BUCKET.get("live/vehicles.json");
    if (!obj) return new Response("no live/vehicles.json yet: the cron trigger hasn't run (allow up to 15 minutes after adding it)\n");
    const data = await obj.json();
    const age = Math.round(Date.now() / 1000 - data.fetched);
    return new Response(`ok: live/vehicles.json has ${data.vehicles.length} vehicles, fetched ${age} s ago\n`);
  },
};
