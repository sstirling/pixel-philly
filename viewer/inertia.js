// Map inertia: a quick drag keeps gliding after release, slowing to a stop
// (a regular request; added Nov. 22, 2026).
//
// Why not OpenSeadragon's own "flick": it samples the pointer every 50 ms and
// takes the glide's direction from only the last sample while smoothing its
// speed over several. A drag that pauses just before release gets direction 0
// (to the right) and leftover speed, so the map lurches backward (2 of 8 test
// drags, Nov. 22). Touch screens have had that by default. Here direction and
// speed come from the same recent movement, and a pause means no glide.
//
// The glide distance is velocity x MOMENTUM_S (OpenSeadragon's default
// momentum, so it feels like its touch flick), eased by the viewer's own
// spring, the same easing as zooming. Off with prefers-reduced-motion.

export const WINDOW_MS = 100;   // velocity from the movement in the last 100 ms before release
export const STOP_MS = 100;     // no movement in the last 100 ms = the pointer stopped: no glide (50 ms missed quick flicks in testing, Nov. 22)
export const STILL_PX = 2;      // positions within 2 px of where the pointer ended count as standing still
export const MIN_SPEED = 120;   // px/s; slower drags don't glide (OpenSeadragon's flickMinSpeed)
export const MOMENTUM_S = 0.25; // glide = velocity x this
export const MAX_GLIDE_PX = 1200; // a cap, so one jittery sample can't throw the map across the city

// The glide for a drag, in screen px [dx, dy] (the direction the pointer moved),
// or null for none. samples: [t ms, x px, y px] pointer positions, oldest first;
// releaseT: when the pointer was released (same clock).
export function glide(samples, releaseT) {
  if (!samples || samples.length < 2) return null;
  // The last sample where the pointer was still moving: a pointer held still
  // can keep reporting the same spot, which isn't movement
  let end = samples.length - 1;
  const [, ex, ey] = samples[end];
  while (end > 0 && Math.hypot(samples[end - 1][1] - ex, samples[end - 1][2] - ey) <= STILL_PX) end--;
  const last = samples[end];
  if (releaseT - last[0] > STOP_MS) return null;
  let first = last;
  for (let i = end - 1; i >= 0 && last[0] - samples[i][0] <= WINDOW_MS; i--) first = samples[i];
  const dt = (last[0] - first[0]) / 1000;
  if (dt < 0.008) return null; // too little movement to measure
  const vx = (last[1] - first[1]) / dt, vy = (last[2] - first[2]) / dt;
  const speed = Math.hypot(vx, vy);
  if (speed < MIN_SPEED) return null;
  const k = Math.min(MOMENTUM_S, MAX_GLIDE_PX / speed);
  return [vx * k, vy * k];
}

// Attach to an OpenSeadragon viewer. Its own flick should be off
// (flickEnabled: false in every gestureSettings*), as it is by default for a
// mouse and pen; viewer.js turns it off for touch too.
export function addInertia(viewer, { reduceMotion = false } = {}) {
  if (reduceMotion) return;
  let samples = [], pinched = false, zoomDrag = false, lastRelease = -1e9;
  // Times come from the pointer events themselves (the same clock as
  // performance.now()), so a busy moment on the page, such as tiles decoding,
  // doesn't make a quick flick look like a pause
  const now = (e) => (e && e.originalEvent && e.originalEvent.timeStamp > 0 ? e.originalEvent.timeStamp : performance.now());
  const record = (e) => {
    const t = now(e);
    samples.push([t, e.position.x, e.position.y]);
    while (samples.length > 2 && t - samples[0][0] > WINDOW_MS * 2) samples.shift();
  };
  viewer.addHandler("canvas-press", (e) => {
    samples = [];
    pinched = false;
    // A touch press right after a tap starts OpenSeadragon's double-tap-drag
    // zoom; that drag zooms, so it mustn't glide
    zoomDrag = e.pointerType === "touch" && now(e) - lastRelease < 300;
    record(e);
  });
  viewer.addHandler("canvas-pinch", () => { pinched = true; });
  viewer.addHandler("canvas-drag", record);
  viewer.addHandler("canvas-release", (e) => { lastRelease = now(e); });
  viewer.addHandler("canvas-drag-end", (e) => {
    const g = !pinched && !zoomDrag && glide(samples, now(e));
    samples = [];
    if (!g) return;
    const vp = viewer.viewport;
    const c = vp.pixelFromPoint(vp.getCenter(false));
    // Dragging moves the map with the pointer, so the view center moves the other way
    vp.panTo(vp.pointFromPixel(new OpenSeadragon.Point(c.x - g[0], c.y - g[1])), false);
    vp.applyConstraints();
  });
}
