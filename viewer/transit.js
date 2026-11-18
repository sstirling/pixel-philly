// Live SEPTA transit on the map: buses, trolleys and Regional Rail from
// SEPTA's live feeds, and Market-Frankford El trains from the timetable.
//
// Data flow:
// - live/vehicles.json: written every 15 s by a Cloudflare Worker
//   (worker/septa-live.js) on the hosted site, or by scripts/38_live_feed.py
//   on a local server (output/live/vehicles.json).
// - output/philly/transit/<gtfs>/: route shapes in map px, tunnels and the El
//   timetable (scripts/35_build_transit.py); sprites.png (37_vehicle_sprites.py).
// - output/philly/overlays/v18/occlusion: building masks (36_build_occlusion.py).
//
// Drawing: one <canvas> over OpenSeadragon's, redrawn every animation frame
// while the layer is on. Vehicles appear only zoomed in (MIN_SCALE), as
// sprites at the map's own scale, drawn on a scratch canvas and then erased
// wherever the building mask is white: a vehicle at street level under a
// building pixel is behind that building.
//
// Motion: on each update a vehicle is snapped onto its route's shape and
// glides there from where it is drawn, over the 15 s until the next update,
// so what you see runs about one update behind SEPTA's reports. Vehicles in
// tunnels and outside the city line aren't drawn.

import { lonLatToPx } from "./projection.js";
import {
  carLayout, describe, elTrains, extendBack, hiddenByTree, inTunnel, invert2, isPlaceholder, MAX_SNAP_PX, motionAt, onRoute, planMove,
  pointInPolygon, positionOf, prepareShape, RAIL_SNAP_PX, snap, trackCars,
} from "./transit_core.js";

export const GTFS_RELEASE = "v202611010";
const POLL_MS = 15000;
const GLIDE_MS = 15000;
const STALE_S = 120;
// Below this many screen px per map px nothing is drawn: the layer is
// something to come across when zoomed in, not a citywide dashboard (Stephen,
// Nov. 14). At 0.12 a bus is about 5 screen px long.
const MIN_SCALE = 0.12;
const HIT_PX = 14;
const MASK_CACHE = 400;
// Trees (overlays/v18/trees, scripts/40_build_tree_mask.py) hide vehicles only
// zoomed in: below this a bus is a few px long and per-car work isn't worth it
const TREE_MIN_SCALE = 0.3;
const TREE_CACHE = 120; // full-resolution tiles, 256 KB each decoded

export function createTransitLayer(viewer, { meta, root, liveUrl, button = null, status, reduceMotion }) {
  const staticBase = `${root}output/philly/transit/${GTFS_RELEASE}/`;
  const overlayBase = `${root}output/philly/overlays/v18/`;
  const canvas = document.createElement("canvas");
  canvas.className = "transit-layer";
  canvas.setAttribute("aria-hidden", "true");
  viewer.container.appendChild(canvas);
  const scratch = document.createElement("canvas");
  const tip = document.createElement("div");
  tip.className = "transit-tip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  viewer.container.appendChild(tip);

  let on = false, timer = null, raf = 0;
  let index = null, sprites = null, sheet = null, occlusion = null, schedule = null;
  let inv = null; // map px -> ground meters (vehicles are laid out in meters; see transit_core.js)
  const shapes = new Map();       // route id -> [prepared shapes] (or a pending Promise)
  const vehicles = new Map();     // "tv:1234" -> state
  const masks = new Map();        // "level/x_y" -> canvas (alpha = building) or "loading"/"missing"
  let trees = null;               // trees.json, or null when there is no tree mask
  const treeTiles = new Map();    // "x_y" -> Uint8Array (trunk distance per px) or "loading"/"missing"
  const cut = document.createElement("canvas"); // one car at a time, with tree pixels erased
  let lastFetched = 0, lastError = null, elFallback = null, drawn = [];

  const tiled = () => viewer.world.getItemAt(0);

  // --- static data ---------------------------------------------------------------
  async function loadStatic() {
    const get = async (url) => { const r = await fetch(url); if (!r.ok) throw new Error(url); return r.json(); };
    [index, sprites, occlusion, schedule] = await Promise.all([
      get(staticBase + "routes.json"), get(`${root}output/philly/transit/sprites.json`),
      get(overlayBase + "occlusion.json"), get(staticBase + "el_schedule.json")]);
    inv = invert2(sprites.ground_to_px);
    // Optional: without it vehicles are simply drawn over trees
    trees = await fetch(overlayBase + "trees/trees.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (trees) trees.have = new Set(trees.tiles);
    sheet = new Image();
    sheet.src = `${root}output/philly/transit/sprites.png`;
    await sheet.decode();
    // The El, and every Regional Rail line: a train may be on any line's track
    await Promise.all(["L1", ...new Set(Object.values(index.rail_lines))].map(routeShapes));
    // Shapes that start mid-network (six lines start at 30th Street) get the track
    // that leads into them, so a train at the start keeps its trailing cars
    const rail = railShapes();
    for (const s of rail) extendBack(s, rail, inv);
  }
  const railShapes = () => [...new Set(Object.values(index.rail_lines))].flatMap((r) => shapesNow(r) || []);

  function routeShapes(rid) {
    const have = shapes.get(rid);
    if (Array.isArray(have)) return Promise.resolve(have);
    if (have) return have;
    const p = fetch(`${staticBase}routes/${encodeURIComponent(rid)}.json`)
      .then((r) => (r.ok ? r.json() : { shapes: [] }))
      .then((d) => { const list = d.shapes.map((sh) => prepareShape(sh, inv)); shapes.set(rid, list); return list; })
      .catch(() => { shapes.set(rid, []); return []; });
    shapes.set(rid, p);
    return p;
  }
  const shapesNow = (rid) => (Array.isArray(shapes.get(rid)) ? shapes.get(rid) : null);

  // --- live updates ------------------------------------------------------------------
  async function poll() {
    try {
      const r = await fetch(liveUrl, { cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      lastError = null;
      if (data.fetched !== lastFetched) {
        // Load the shapes of every route in this update first (about 1.5 MB in
        // all, once), so vehicles are on their routes from their first frame
        const rids = new Set(data.vehicles.map(([src, route]) => (src === "rr" ? index.rail_lines[route] : route)));
        await Promise.all([...rids].filter((r) => r && index.routes[r] && !shapesNow(r)).map(routeShapes));
        apply(data);
      }
    } catch (err) {
      lastError = err;
    }
    updateStatus();
  }

  function apply(data) {
    lastFetched = data.fetched;
    const now = performance.now();
    const seen = new Set();
    for (const [src, route, id, lon, lat, heading, late, dest, ts, cars] of data.vehicles) {
      const rid = src === "rr" ? index.rail_lines[route] : route;
      const info = index.routes[rid];
      const kind = src === "rr" ? "rail" : info?.kind === "trolley" ? "trolley" : "bus";
      if (info?.kind === "el" || (info === undefined && src === "tv" && /^B\d/.test(route))) continue;
      if (src === "rr" && isPlaceholder(lon, lat)) continue; // not a real position (see transit_core.js)
      const [x, y] = lonLatToPx(meta.fit, lon, lat);
      if (!pointInPolygon(index.city, x, y)) continue;
      const key = `${src}:${id}`;
      seen.add(key);
      let v = vehicles.get(key);
      const list = rid ? shapesNow(rid) : null;
      // No new report: nothing to do, unless the route's shapes arrived since
      // and the vehicle can now be snapped onto its route in place
      if (v && v.ts === ts && v.lon === lon && v.lat === lat && (v.motion.end.shape || !list)) continue;
      if (rid && !list) routeShapes(rid); // snapped from the next update on
      // Trains snap farther off the track and onto any line's track; a train is
      // drawn only on track, never on a straight line (transit_core.js planMove)
      const opts = kind === "rail" ? { maxPx: RAIL_SNAP_PX, others: railShapes(), track: true } : { maxPx: MAX_SNAP_PX };
      const prevPos = v ? onRoute(motionAt(v.motion, (now - v.t0) / GLIDE_MS), v.motion, opts.maxPx) : null;
      const snapped = list ? snap(list, x, y, prevPos, opts) : null;
      // Off-route vehicles face SEPTA's GPS heading (a compass bearing) or keep their last one
      const bearing = heading !== null ? heading : prevPos?.bearing ?? 0;
      const target = positionOf(snapped, x, y, bearing);
      const fields = { kind, route, rid, id, lon, lat, ts, late, dest, line: route, color: info?.color || "#555",
                       cars: kind === "rail" ? Math.min(cars || 4, 8) : 1 };
      if (!v) {
        v = { ...fields, motion: { kind: "jump", end: target }, t0: now };
        vehicles.set(key, v);
      } else {
        Object.assign(v, fields);
        v.motion = reduceMotion ? { kind: "jump", end: target } : planMove(prevPos, target, inv, opts);
        v.t0 = now;
      }
    }
    for (const key of vehicles.keys()) if (!seen.has(key)) vehicles.delete(key);
  }

  function updateStatus() {
    if (!on) return;
    const age = Date.now() / 1000 - lastFetched;
    let text;
    if (!lastFetched) text = lastError ? "Live transit is unavailable right now." : "Loading live transit…";
    else {
      const t = new Date(lastFetched * 1000).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit",
        second: "2-digit", timeZone: "America/New_York" }).replace("AM", "a.m.").replace("PM", "p.m.");
      // AP style: "p.m." ends the sentence without a second period
      text = `SEPTA vehicles updated at ${t} El trains show scheduled positions.`;
      if (!/\.$/.test(t)) text = text.replace(`${t} El`, `${t}. El`);
      if (age > STALE_S) text = `SEPTA's live data hasn't updated since ${t}; vehicles may be out of date.`;
    }
    if (elFallback) text += " (El timetable past its end date: using the last matching day.)";
    status.textContent = text;
  }

  // --- drawing -------------------------------------------------------------------------
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = viewer.container.clientWidth, h = viewer.container.clientHeight;
    for (const c of [canvas, scratch]) {
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
        c.width = Math.round(w * dpr);
        c.height = Math.round(h * dpr);
      }
    }
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    return { w, h, dpr };
  }

  function maskTile(level, x, y) {
    const key = `${level}/${x}_${y}`;
    const have = masks.get(key);
    if (have) return typeof have === "string" ? null : have;
    masks.set(key, "loading");
    const img = new Image();
    img.onload = () => {
      // White = building. Turn it into alpha so destination-out erases there only.
      const c = document.createElement("canvas");
      c.width = img.width; c.height = img.height;
      const g = c.getContext("2d", { willReadFrequently: true }); // read once on the CPU, no GPU readback
      g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height);
      for (let i = 0; i < d.data.length; i += 4) { d.data[i + 3] = d.data[i]; d.data[i] = d.data[i + 1] = d.data[i + 2] = 0; }
      g.putImageData(d, 0, 0);
      masks.set(key, c);
      if (masks.size > MASK_CACHE) masks.delete(masks.keys().next().value);
    };
    img.onerror = () => masks.set(key, "missing");
    img.src = `${overlayBase}occlusion_files/${level}/${x}_${y}.png`;
    return null;
  }

  // --- trees ------------------------------------------------------------------------------
  // Each tree pixel stores how far below it, in map px, its tree's trunk stands
  // (0 = no tree). The map looks down at 45°, so a canopy hangs over whatever is
  // just behind it on screen: a tree hides a car only when its trunk is at or
  // below the car's ground point. A bus passing a tree on the far sidewalk stays
  // in front of it; one under a near-side tree is hidden.
  function treeTile(tx, ty) {
    const key = `${tx}_${ty}`;
    if (!trees.have.has(key)) return null;
    const have = treeTiles.get(key);
    if (have) return typeof have === "string" ? null : have;
    treeTiles.set(key, "loading");
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.width; c.height = img.height;
      const g = c.getContext("2d", { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      const out = new Uint8Array(c.width * c.height);
      for (let i = 0; i < out.length; i++) out[i] = d[4 * i];
      treeTiles.set(key, out);
      if (treeTiles.size > TREE_CACHE) treeTiles.delete(treeTiles.keys().next().value);
    };
    img.onerror = () => treeTiles.set(key, "missing");
    img.src = `${overlayBase}trees/trees_files/${trees.level}/${key}.png`;
    return null;
  }

  // The car's sprite with the pixels trees hide erased, on `cut` (sprite px are
  // map px), or null when no tree hides any of it
  function treeCut(it) {
    const s = it.sprite, size = trees.tile_size;
    const x0 = Math.round(it.mx - s.ax), y0 = Math.round(it.my - s.ay);
    let hidden = null;
    for (let y = 0; y < s.h; y++) {
      const py = y0 + y;
      for (let x = 0; x < s.w; x++) {
        const px = x0 + x;
        const t = treeTile(Math.floor(px / size), Math.floor(py / size));
        if (!t) continue;
        const d = t[(py % size) * size + (px % size)];
        if (hiddenByTree(d, py, it.my)) {
          hidden = hidden || new Uint8ClampedArray(s.w * s.h * 4);
          hidden[4 * (y * s.w + x) + 3] = 255;
        }
      }
    }
    if (!hidden) return null;
    cut.width = s.w; cut.height = s.h;
    const g = cut.getContext("2d", { willReadFrequently: true });
    g.putImageData(new ImageData(hidden, s.w, s.h), 0, 0);
    g.globalCompositeOperation = "source-out"; // the sprite, only where no tree is
    g.drawImage(sheet, s.x, s.y, s.w, s.h, 0, 0, s.w, s.h);
    g.globalCompositeOperation = "source-over";
    return cut;
  }

  function frame() {
    raf = on ? requestAnimationFrame(frame) : 0;
    const item = tiled();
    if (!item || !index || !sheet) return;
    const { w, h, dpr } = resize();
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const p0 = item.imageToViewerElementCoordinates(new OpenSeadragon.Point(0, 0));
    const p1 = item.imageToViewerElementCoordinates(new OpenSeadragon.Point(1000, 0));
    const scale = (p1.x - p0.x) / 1000;
    if (scale < MIN_SCALE) { drawn = []; canvas.dataset.drawn = "0"; return; } // zoomed out: nothing to draw
    const toScreen = (x, y) => [p0.x + x * scale, p0.y + y * scale];
    const margin = 80 * Math.max(scale, 0.1) + 10;
    const visible = (sx, sy) => sx > -margin && sy > -margin && sx < w + margin && sy < h + margin;
    const now = performance.now();

    // Everything to draw this frame: [{sx, sy, sprite, color, info}]
    const items = [];
    const kinds = sprites.kinds;
    for (const v of vehicles.values()) {
      const pos = motionAt(v.motion, (now - v.t0) / GLIDE_MS);
      if (v.kind === "rail" && !pos.shape) continue; // a train off every track is a data error
      // On its route, a vehicle sits on the track like a real one, each car hidden on
      // its own in a tunnel (buses aren't: their routes cross tunneled rail)
      for (const c of trackCars(pos, kinds[v.kind], v.cars, inv, v.kind !== "bus")) {
        const [sx, sy] = toScreen(c.x, c.y);
        if (visible(sx, sy)) items.push({ sx, sy, mx: c.x, my: c.y, sprite: c.sprite, color: v.color, v });
      }
    }
    const el = elTrains(schedule, new Date());
    elFallback = el.fallback;
    const elShapes = shapesNow("L1") || [];
    for (const t of el.trains) {
      const shape = elShapes.find((s) => s.id === t.shape);
      if (!shape) continue;
      const v = { kind: "el", color: index.routes.L1?.color || "#0097D6" };
      for (const c of carLayout(shape, t.along, kinds.el, kinds.el.cars, inv)) {
        if (inTunnel(shape, c.along)) continue;
        const [sx, sy] = toScreen(c.x, c.y);
        if (!pointInPolygon(index.city, c.x, c.y) || !visible(sx, sy)) continue;
        items.push({ sx, sy, mx: c.x, my: c.y, sprite: c.sprite, color: v.color, v });
      }
    }
    drawn = items;
    canvas.dataset.drawn = String(items.length);
    canvas.transitItems = items; // for browser checks (scripts and tests), not used by the page
    if (!items.length) return;

    // Sprites, back to front (farther from the viewer = higher on screen)
    items.sort((a, b) => a.sy - b.sy);
    const g = scratch.getContext("2d");
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = "source-over";
    g.clearRect(0, 0, scratch.width, scratch.height);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.imageSmoothingEnabled = scale < 1;
    const treesNow = trees && scale >= TREE_MIN_SCALE;
    for (const it of items) {
      const { sx, sy, sprite: s } = it;
      const c = treesNow ? treeCut(it) : null;
      if (c) g.drawImage(c, 0, 0, s.w, s.h, sx - s.ax * scale, sy - s.ay * scale, s.w * scale, s.h * scale);
      else g.drawImage(sheet, s.x, s.y, s.w, s.h, sx - s.ax * scale, sy - s.ay * scale, s.w * scale, s.h * scale);
    }
    // Erase behind buildings: the mask level closest to the screen scale
    const top = Math.max(...occlusion.levels);
    const drop = Math.min(occlusion.levels.length - 1, Math.max(0, Math.floor(Math.log2(1 / scale))));
    const level = top - drop;
    const span = occlusion.tile_size * 2 ** drop; // map px per mask tile
    const ix0 = Math.max(0, Math.floor(-p0.x / scale / span)), iy0 = Math.max(0, Math.floor(-p0.y / scale / span));
    const ix1 = Math.min(Math.ceil(occlusion.width / span) - 1, Math.floor((w - p0.x) / scale / span));
    const iy1 = Math.min(Math.ceil(occlusion.height / span) - 1, Math.floor((h - p0.y) / scale / span));
    g.globalCompositeOperation = "destination-out";
    g.imageSmoothingEnabled = scale * 2 ** drop < 1;
    for (let ty = iy0; ty <= iy1; ty++) {
      for (let tx = ix0; tx <= ix1; tx++) {
        const m = maskTile(level, tx, ty);
        if (!m) continue;
        const [sx, sy] = toScreen(tx * span, ty * span);
        g.drawImage(m, sx, sy, m.width * 2 ** drop * scale, m.height * 2 ** drop * scale);
      }
    }
    g.globalCompositeOperation = "source-over";
    ctx.drawImage(scratch, 0, 0);
  }

  // --- tap or click a vehicle -------------------------------------------------------------
  viewer.addHandler("canvas-click", (e) => {
    if (!on || !e.quick) return;
    const { x, y } = e.position;
    // Only vehicles that can be seen: one hidden behind a building is skipped
    const dpr = window.devicePixelRatio || 1;
    const seen = (it) => {
      const r = Math.max(1, Math.round(3 * dpr));
      const d = canvas.getContext("2d").getImageData(Math.round(it.sx * dpr) - r, Math.round(it.sy * dpr) - r, 2 * r + 1, 2 * r + 1).data;
      for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true;
      return false;
    };
    let best = null, bd = HIT_PX;
    for (const it of drawn) {
      const d = Math.hypot(it.sx - x, it.sy - y);
      if (d < bd && seen(it)) { bd = d; best = it; }
    }
    if (!best) { tip.hidden = true; return; }
    tip.textContent = describe(best.v);
    tip.style.left = `${Math.round(best.sx)}px`;
    tip.style.top = `${Math.round(best.sy)}px`;
    tip.hidden = false;
  });
  viewer.addHandler("canvas-drag", () => { tip.hidden = true; });

  // --- on and off --------------------------------------------------------------------------
  let ready = null;
  async function setOn(value) {
    on = value;
    button?.setAttribute("aria-pressed", String(on));
    canvas.hidden = !on;
    tip.hidden = true;
    if (!on) {
      clearInterval(timer); timer = null;
      cancelAnimationFrame(raf); raf = 0;
      status.textContent = "";
      return;
    }
    updateStatus();
    try {
      ready = ready || loadStatic();
      await ready;
    } catch (err) {
      ready = null;
      status.textContent = "Live transit is unavailable right now.";
      return;
    }
    if (!on) return;
    poll();
    timer = timer || setInterval(poll, POLL_MS);
    if (!raf) raf = requestAnimationFrame(frame);
  }
  button?.addEventListener("click", () => setOn(!on)); // optional: the hosted page has no toggle
  // Pause polling while the tab is hidden
  document.addEventListener("visibilitychange", () => {
    if (!on) return;
    if (document.hidden) { clearInterval(timer); timer = null; }
    else if (!timer) { poll(); timer = setInterval(poll, POLL_MS); }
  });
  return { setOn };
}
