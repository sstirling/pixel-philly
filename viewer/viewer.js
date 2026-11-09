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

const params = new URLSearchParams(location.search);
// Default: the accepted map (output/philly/FROZEN_v17.json; v14, the frozen
// talk map, stays at ?v=v14). Older maps
// stay reachable with ?area=...&v=...
const area = params.get("area") || "philly";
const version = params.get("v") || "v17";
// The offline copy (scripts/27_offline_copy.py) sets <html data-offline="1">:
// no request ever leaves the machine, so address search (City AIS API) is off
const offline = document.documentElement.dataset.offline === "1";
const base = `../output/${area}/tiles/${version}/`;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const status = document.getElementById("status");

const meta = await (await fetch(base + "map.json")).json();
document.getElementById("credits").textContent = meta.credits;
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
});
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
