// Pixel Philly prototype viewer.
//
// Loads output/<area>/tiles/<version>/map.json (written by
// scripts/16_build_tiles.py) and its Deep Zoom pyramid into OpenSeadragon.
// Pixel art is drawn crisp (no smoothing) at 1:1 and closer, and smooth
// when zoomed out, as tiny.london does. The view is kept in the URL hash so
// links can be shared. Address search uses the City of Philadelphia's AIS
// API and the lon/lat -> pixel fit in map.json (see projection.js).
//
// When map.json lists a "photo" layer (16_build_tiles.py --with-photo), a
// toggle switches between the illustration and the render it was drawn from:
// the 2024 aerial photos on 3D buildings, from the same camera, so the two
// line up pixel for pixel. The label and credits switch with it so the photo
// is never mistaken for AI output, or the illustration for a photo.

import { inBounds, lonLatToPx } from "./projection.js";

const params = new URLSearchParams(location.search);
const area = params.get("area") || "downtown";
const version = params.get("v") || "v3";
const base = `../output/${area}/tiles/${version}/`;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const status = document.getElementById("status");

const meta = await (await fetch(base + "map.json")).json();
document.getElementById("credits").textContent = meta.credits;
document.title = `Pixel Philly: ${meta.label}`;

const viewer = OpenSeadragon({
  element: document.getElementById("map"),
  tileSources: meta.layers?.photo
    ? [{ tileSource: base + meta.layers.illustration }, { tileSource: base + meta.layers.photo, opacity: 0 }]
    : base + meta.dzi,
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
// Image <-> viewport conversions go through the illustration layer: with two
// layers loaded, OpenSeadragon's viewport-wide conversions are ambiguous.
// (Both layers are the same size at the same place, so either would do.)
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
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) ? { x, y, z, layer: h.get("layer") } : null;
}
function goTo({ x, y, z }, immediately = false) {
  const vp = viewer.viewport;
  vp.zoomTo(base0().imageToViewportZoom(z), null, immediately);
  vp.panTo(base0().imageToViewportCoordinates(x, y), immediately);
}
viewer.addHandler("open", () => {
  const start = readHash();
  if (start) goTo(start, true);
  if (start?.layer === "photo") showPhoto(true);
  updateSmoothing();
});
viewer.addHandler("animation-finish", () => {
  const vp = viewer.viewport;
  if (!base0()) return;
  const c = base0().viewportToImageCoordinates(vp.getCenter());
  const z = base0().viewportToImageZoom(vp.getZoom());
  const layer = photoShown ? "&layer=photo" : "";
  history.replaceState(null, "", `#x=${Math.round(c.x)}&y=${Math.round(c.y)}&z=${z.toFixed(3)}${layer}`);
});

// --- illustration / photo toggle ---------------------------------------------
const toggle = document.getElementById("layer-toggle");
const badge = document.querySelector(".badge");
const credits = document.getElementById("credits");
let photoShown = false;
function showPhoto(on) {
  const photo = viewer.world.getItemAt(1);
  if (!photo) return;
  photoShown = on;
  photo.setOpacity(on ? 1 : 0);
  toggle.setAttribute("aria-pressed", String(on));
  toggle.textContent = on ? "Show illustration" : "Show photo";
  badge.textContent = on ? "2024 aerial photo on 3D model" : "AI-generated illustration";
  badge.classList.toggle("photo", on);
  credits.textContent = on ? meta.photo_credits : meta.credits;
  document.getElementById("credits-summary").textContent =
    on ? "Photo layer (source for the AI) · credits" : "AI-generated prototype · credits";
  viewer.raiseEvent("animation-finish"); // refresh the shareable link
}
if (meta.layers?.photo) {
  toggle.hidden = false;
  toggle.onclick = () => showPhoto(!photoShown);
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
