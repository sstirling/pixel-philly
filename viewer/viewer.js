// Pixel Philly prototype viewer.
//
// Loads output/<area>/tiles/<version>/map.json (written by
// scripts/16_build_tiles.py) and its Deep Zoom pyramid into OpenSeadragon.
// Pixel art is drawn crisp (no smoothing) at 1:1 and closer, and smooth
// when zoomed out, as tiny.london does. The view is kept in the URL hash so
// links can be shared. Address search uses the City of Philadelphia's AIS
// API and the lon/lat -> pixel fit in map.json (see projection.js).
//
// The photo layer (the renders the illustration was drawn from) is built by
// 16_build_tiles.py --with-photo but no longer shown: Stephen dropped the
// "Show photo" toggle and the AI badge from the bar on Nov. 5 (the AI note is
// in the credits footer and on about.html). Only the illustration is loaded.
//
// With no #x/y/z link, the map opens close in on Center City (START_VIEW), so
// the screen is filled with map detail rather than the edges of the data; the
// home button still shows the whole city.

import { inBounds, lonLatToPx } from "./projection.js";
import { createTransitLayer } from "./transit.js";
import { createWeatherLayer } from "./weather.js";
import { addInertia } from "./inertia.js";

const params = new URLSearchParams(location.search);
// Default: the accepted map (output/philly/FROZEN_v18.json, accepted Nov. 9,
// 2026: v17 plus the 3D-modeled Ben Franklin and Walt Whitman bridges).
// Older versions stay reachable with ?v=... (and ?area=...) where their tiles
// are served: locally, every version. The hosted site serves v18 only (v17
// was taken off the bucket Nov. 19, 2026, to stay in R2's free 10 GB).
const DEFAULT_VERSION = "v18";
let area = params.get("area") || "philly";
let version = params.get("v") || DEFAULT_VERSION;
// The offline copy (scripts/27_offline_copy.py) sets <html data-offline="1">:
// no request ever leaves the machine, so address search (City AIS API) is off
const offline = document.documentElement.dataset.offline === "1";
let base = `../output/${area}/tiles/${version}/`;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const status = document.getElementById("status");

// A version that isn't served here falls back to the current map, with a note,
// instead of a blank page (an old ?v=v17 link on the hosted site)
let mapRes = await fetch(base + "map.json");
let versionNote = "";
if (!mapRes.ok && (version !== DEFAULT_VERSION || area !== "philly")) {
  versionNote = `That map version (${area} ${version}) isn't available here, so this is the current map.`;
  area = "philly";
  version = DEFAULT_VERSION;
  base = `../output/${area}/tiles/${version}/`;
  mapRes = await fetch(base + "map.json");
}
const meta = await mapRes.json();
if (versionNote) status.textContent = versionNote;
// The live transit layer (transit.js) runs on v18 only: its building masks
// are v18's. Off in the offline copy (it needs the network) and with ?live=off.
const liveParam = params.get("live");
const transitOn = area === "philly" && version === "v18" && !offline && liveParam !== "off";
// map.json's credits are frozen with the map, so the transit credit is added here
const TRANSIT_CREDIT = " Live transit: vehicle positions and schedules from SEPTA; tunnels © OpenStreetMap contributors.";
// Live weather: the same places as transit (it needs the network). ?weather=off
// turns it off; ?weather=snow|rain|mix|storm (optionally ?intensity=light|heavy) shows it
// without data, for testing and demos.
const weatherParam = params.get("weather");
const weatherOn = area === "philly" && !offline && weatherParam !== "off";
const WEATHER_CREDIT = " Weather: National Weather Service.";
document.getElementById("credits").textContent = meta.credits + (transitOn ? TRANSIT_CREDIT : "") + (weatherOn ? WEATHER_CREDIT : "");
document.title = `Pixel Philly: ${meta.label}`;

// City Hall, at 4 map px per screen px: about 2 km of Center City across a
// laptop screen. y is nudged up so the tower, not its hidden base, is centered.
const START_VIEW = { lon: -75.16355, lat: 39.9524, dy: -300, z: 0.25 };

const viewer = OpenSeadragon({
  element: document.getElementById("map"),
  tileSources: base + (meta.layers?.illustration || meta.dzi),
  showNavigationControl: false, // our own accessible buttons below
  imageLoaderLimit: 16,
  maxZoomPixelRatio: 4, // up to 4 screen px per map px: pixel art stays readable
  visibilityRatio: 0.5,
  constrainDuringPan: true,
  animationTime: reduceMotion ? 0 : 0.8,
  springStiffness: reduceMotion ? 100 : 6.5,
  imageSmoothingEnabled: false,
  gestureSettingsMouse: { clickToZoom: false },
  // Inertia is our own (inertia.js): OpenSeadragon's touch flick can glide
  // backward after a pause, so it's off
  gestureSettingsTouch: { flickEnabled: false },
});
// A quick drag keeps gliding after release, for mouse, pen and touch (inertia.js)
addInertia(viewer, { reduceMotion });
document.getElementById("map").style.background = meta.background;

// Crisp pixels at 1:1 and closer; smooth when zoomed out so the shrunken
// pixel art doesn't shimmer.
// Image <-> viewport conversions go through the (only) image layer.
const base0 = () => viewer.world.getItemAt(0);

function updateSmoothing() {
  if (!base0()) return;
  const z = base0().viewportToImageZoom(viewer.viewport.getZoom(true));
  viewer.drawer.setImageSmoothingEnabled(z < 1);
}
viewer.addHandler("animation", updateSmoothing);
viewer.addHandler("animation-finish", updateSmoothing);

// --- deep links: #x=<image px>&y=<image px>&z=<image zoom> ---------------
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  const x = parseFloat(h.get("x")), y = parseFloat(h.get("y")), z = parseFloat(h.get("z"));
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) ? { x, y, z } : null;
}
function goTo({ x, y, z }, immediately = false) {
  const vp = viewer.viewport;
  vp.zoomTo(base0().imageToViewportZoom(z), null, immediately);
  vp.panTo(base0().imageToViewportCoordinates(x, y), immediately);
}
viewer.addHandler("open", () => {
  const start = readHash();
  if (start) goTo(start, true);
  else if (inBounds(meta.fit, START_VIEW.lon, START_VIEW.lat)) {
    const [x, y] = lonLatToPx(meta.fit, START_VIEW.lon, START_VIEW.lat);
    goTo({ x, y: y + START_VIEW.dy, z: START_VIEW.z }, true);
  }
  updateSmoothing();
});
viewer.addHandler("animation-finish", () => {
  const vp = viewer.viewport;
  if (!base0()) return;
  const c = base0().viewportToImageCoordinates(vp.getCenter());
  const z = base0().viewportToImageZoom(vp.getZoom());
  history.replaceState(null, "", `#x=${Math.round(c.x)}&y=${Math.round(c.y)}&z=${z.toFixed(3)}`);
});

// --- live transit -----------------------------------------------------------
// Always on, with no button in the bar: vehicles are something to come across
// when zoomed in (Stephen, Nov. 14). The status line keeps SEPTA's update time.
// ?live=off turns the layer off.
// The hosted site reads live/vehicles.json from the bucket (worker/septa-live.js
// writes it); a local server reads output/live/vehicles.json from
// scripts/38_live_feed.py.
if (transitOn) {
  const local = liveParam === "local" || ["localhost", "127.0.0.1"].includes(location.hostname);
  const transit = createTransitLayer(viewer, {
    meta, root: "../", liveUrl: local ? "../output/live/vehicles.json" : "../live/vehicles.json",
    status: document.getElementById("transit-status"), reduceMotion,
  });
  viewer.addHandler("open", () => transit.setOn(true));
}

// --- live weather -------------------------------------------------------------
// Falling snow or rain when it's snowing or raining at the airport; nothing
// otherwise (weather.js). Also the temperature badge: top-right corner, or in
// the bar's title row on phones.
// Same local/hosted file locations as transit.
if (weatherOn) {
  const local = liveParam === "local" || ["localhost", "127.0.0.1"].includes(location.hostname);
  // ?weather=storm is rain with thunder and lightning
  const forced = ["snow", "rain", "mix", "storm"].includes(weatherParam)
    ? { kind: weatherParam === "storm" ? "rain" : weatherParam,
        intensity: ["light", "heavy"].includes(params.get("intensity")) ? params.get("intensity") : "moderate",
        thunder: weatherParam === "storm" }
    : null;
  // The badge sits top right on wide screens; on phones it moves into the
  // bar's title row (viewer.css), so it doesn't add a box over the map
  const temp = document.getElementById("temp");
  const narrow = matchMedia("(max-width: 880px)");
  const placeTemp = () => (narrow.matches ? document.querySelector(".bar .title").append(temp)
                                          : document.getElementById("map").before(temp));
  placeTemp();
  narrow.addEventListener("change", placeTemp);
  createWeatherLayer(viewer.container, {
    url: local ? "../output/live/weather.json" : "../live/weather.json",
    status: document.getElementById("weather-status"), reduceMotion, force: forced,
    badge: document.getElementById("temp"),
  });
}

// --- controls ---------------------------------------------------------------
document.getElementById("zoom-in").onclick = () => viewer.viewport.zoomBy(1.6);
document.getElementById("zoom-out").onclick = () => viewer.viewport.zoomBy(1 / 1.6);
document.getElementById("home").onclick = () => viewer.viewport.goHome();

// --- address search -----------------------------------------------------------
let pin = null;
document.getElementById("search").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  if (offline) {
    status.textContent = "Address search needs the internet (City of Philadelphia AIS); it is off in this offline copy.";
    return;
  }
  status.textContent = "Searching…";
  try {
    const r = await fetch(`https://api.phila.gov/ais/v1/search/${encodeURIComponent(q)}`);
    const data = r.ok ? await r.json() : null;
    const feat = data?.features?.[0];
    if (!feat) { status.textContent = `No match for “${q}”.`; return; }
    const [lon, lat] = feat.geometry.coordinates;
    if (!inBounds(meta.fit, lon, lat)) {
      status.textContent = `${feat.properties.street_address} is outside this map.`;
      return;
    }
    const [x, y] = lonLatToPx(meta.fit, lon, lat);
    goTo({ x, y, z: 1 });
    if (pin) viewer.removeOverlay(pin);
    pin = document.createElement("div");
    pin.className = "pin";
    pin.setAttribute("aria-hidden", "true");
    viewer.addOverlay({ element: pin, location: base0().imageToViewportCoordinates(x, y),
                        placement: OpenSeadragon.Placement.CENTER });
    status.textContent = `${feat.properties.street_address} (pin marks street level).`;
  } catch (err) {
    status.textContent = "Search is unavailable right now.";
  }
});
