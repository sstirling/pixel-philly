// Pure functions for the live transit layer (viewer/transit.js): route
// shapes, snapping, motion, the El timetable and sprite choice. No DOM and
// no imports, so tests/test_transit_viewer.py can run them in Chromium.
//
// Units: map image pixels (the v18 Deep Zoom image), the same space as
// projection.js lonLatToPx. A shape is a route polyline from
// output/philly/transit/<gtfs>/routes/<route>.json (scripts/35_build_transit.py);
// "along" is the distance in map px from its start. GTFS shapes are
// directional (each direction of a route has its own), so moving forward on
// a shape means a larger "along".

export const MAX_SNAP_PX = 60;      // about 15-18 m: farther than that from every shape, a vehicle is off-route (detour, garage)
// Trains: TrainView positions sit a median 29 px from the GTFS track and a quarter
// are past 51 px (Nov. 18 recording), and rail corridors are several tracks wide
export const RAIL_SNAP_PX = 120;    // about 30-40 m
// Another line's track costs this much extra, so where lines share a corridor a
// train stays on its own line's shape
export const OTHER_LINE_PX = 15;
export const BACKTRACK_PX = 40;     // GPS jitter allowed backward along a shape before it counts as the wrong direction
export const MAX_GLIDE_PX = 6000;   // more than this in one update (about 1.5 km) is a jump, not a drive

// The map camera foreshortens the ground: one meter is 2.4 to 3.4 map px
// depending on its compass direction. Vehicle layout (car lengths, spacing,
// truck positions) and gliding speed are therefore worked out in ground
// meters. `inv` is the 2 x 2 matrix from map px back to ground meters (east,
// north): the inverse of sprites.json "ground_to_px" (37_vehicle_sprites.py).
// Ground level is affine on screen, so differences convert exactly.
const IDENTITY = [[1, 0], [0, 1]];

export function invert2([[a, b], [c, d]]) {
  const det = a * d - b * c;
  return [[d / det, -b / det], [-c / det, a / det]];
}

export function pxToGround(inv, x, y) {
  return [inv[0][0] * x + inv[0][1] * y, inv[1][0] * x + inv[1][1] * y];
}

// Compass bearing (degrees clockwise from north) of a map-px direction
export function bearingOf(inv, dx, dy) {
  const [e, n] = pxToGround(inv, dx, dy);
  return ((Math.atan2(e, n) * 180) / Math.PI + 360) % 360;
}

export function prepareShape(s, inv = IDENTITY) {
  const pts = s.pts;
  const n = pts.length / 2;
  const cum = new Float64Array(n);
  const cumM = new Float64Array(n);
  for (let i = 1; i < n; i++) {
    const dx = pts[2 * i] - pts[2 * i - 2], dy = pts[2 * i + 1] - pts[2 * i - 1];
    cum[i] = cum[i - 1] + Math.hypot(dx, dy);
    const [e, nn] = pxToGround(inv, dx, dy);
    cumM[i] = cumM[i - 1] + Math.hypot(e, nn);
  }
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) {
    x0 = Math.min(x0, pts[2 * i]); x1 = Math.max(x1, pts[2 * i]);
    y0 = Math.min(y0, pts[2 * i + 1]); y1 = Math.max(y1, pts[2 * i + 1]);
  }
  return { id: s.id, pts, cum, cumM, inv, length: cum[n - 1], tunnels: s.tunnels || [], bbox: [x0, y0, x1, y1] };
}

export const lengthM = (shape) => shape.cumM[shape.cumM.length - 1];

// Index pair and fraction where `value` falls in a cumulative array
function locate(arr, value) {
  let lo = 0, hi = arr.length - 1;
  const v = Math.max(0, Math.min(arr[hi], value));
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] <= v) lo = mid; else hi = mid;
  }
  const seg = arr[hi] - arr[lo];
  return [lo, hi, seg > 0 ? (v - arr[lo]) / seg : 0];
}

// Distance along a shape: map px <-> ground meters (same segments, so exact)
export function pxToM(shape, along) {
  const [lo, hi, t] = locate(shape.cum, along);
  return shape.cumM[lo] + (shape.cumM[hi] - shape.cumM[lo]) * t;
}
export function mToPx(shape, m) {
  const [lo, hi, t] = locate(shape.cumM, m);
  return shape.cum[lo] + (shape.cum[hi] - shape.cum[lo]) * t;
}

// Position and screen direction (radians, atan2 of dy, dx) at `along`, clamped to the shape
export function pointAt(shape, along) {
  const { pts, cum } = shape;
  const n = cum.length;
  const a = Math.max(0, Math.min(shape.length, along));
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= a) lo = mid; else hi = mid;
  }
  const seg = cum[hi] - cum[lo] || 1;
  const t = (a - cum[lo]) / seg;
  const x0 = pts[2 * lo], y0 = pts[2 * lo + 1], x1 = pts[2 * hi], y1 = pts[2 * hi + 1];
  return { x: x0 + (x1 - x0) * t, y: y0 + (y1 - y0) * t, angle: Math.atan2(y1 - y0, x1 - x0),
           bearing: bearingOf(shape.inv || IDENTITY, x1 - x0, y1 - y0) };
}

export function projectOnto(shape, x, y) {
  const { pts, cum } = shape;
  let best = Infinity, bestAlong = 0;
  for (let i = 0; i + 1 < cum.length; i++) {
    const ax = pts[2 * i], ay = pts[2 * i + 1], bx = pts[2 * i + 2], by = pts[2 * i + 3];
    const dx = bx - ax, dy = by - ay;
    const ll = dx * dx + dy * dy || 1e-9;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / ll));
    const d = Math.hypot(ax + dx * t - x, ay + dy * t - y);
    if (d < best) { best = d; bestAlong = cum[i] + t * Math.sqrt(ll); }
  }
  return { dist: best, along: bestAlong };
}

// Snap a reported position onto one of its route's shapes. A vehicle that was
// already on a shape prefers to stay on it and to move forward: two
// directions of a route often share a street, and only the shape it is
// already moving along tells them apart. Returns {shape, along, dist} or
// null when no shape is within maxPx.
// Options: maxPx (RAIL_SNAP_PX for trains); others, shapes of other lines a
// vehicle may also be on (trains run through Center City onto other lines'
// track, and TrainView's line label can name the line a train runs next),
// each costing OTHER_LINE_PX more than the vehicle's own.
export function snap(shapes, x, y, prev = null, { maxPx = MAX_SNAP_PX, others = [] } = {}) {
  let best = null, bestCost = Infinity;
  const own = new Set(shapes);
  for (const s of own.size === shapes.length && !others.length ? shapes : [...shapes, ...others.filter((o) => !own.has(o))]) {
    const [x0, y0, x1, y1] = s.bbox;
    if (x < x0 - maxPx || x > x1 + maxPx || y < y0 - maxPx || y > y1 + maxPx) continue;
    const p = projectOnto(s, x, y);
    if (p.dist > maxPx) continue;
    let cost = p.dist + (own.has(s) ? 0 : OTHER_LINE_PX);
    if (prev && prev.shape) {
      if (prev.shape.id === s.id) cost += p.along < prev.along - BACKTRACK_PX ? 80 : -5;
      else cost += 10;
    }
    if (cost < bestCost) { bestCost = cost; best = { shape: s, along: p.along, dist: p.dist }; }
  }
  return best;
}

export function inTunnel(shape, along) {
  for (const [a, b] of shape.tunnels) if (along >= a && along <= b) return true;
  return false;
}

// --- motion between updates ---------------------------------------------------------
// A position is {x, y, bearing} plus, when snapped, {shape, along}. bearing is
// the compass direction the vehicle faces (degrees clockwise from north).
export function positionOf(snapped, x, y, bearing) {
  if (snapped) return { ...pointAt(snapped.shape, snapped.along), shape: snapped.shape, along: snapped.along };
  return { x, y, bearing };
}

export const HOP_PX = 30; // shorter moves (snapping onto the road, GPS jitter) don't turn a vehicle

// Options: maxPx, how far a vehicle may be from a shape to count as on it
// (RAIL_SNAP_PX for trains); track: a vehicle that only exists on track (a
// train), which never makes a straight-line move. A train's cars are laid out
// along the track, so on a straight line it would collapse into one car facing
// the line (Nov. 18: 60% of train frames in a replay of live data).
export function planMove(from, to, inv = IDENTITY, { maxPx = MAX_SNAP_PX, track = false } = {}) {
  if (from.shape && to.shape) {
    // From where the vehicle is now, measured along the shape it is moving onto: the
    // same shape, or another one on the same track (a train through Center City onto
    // another line, or the other direction's shape after a wrong first guess)
    let a0 = from.along;
    if (from.shape !== to.shape) {
      const p = projectOnto(to.shape, from.x, from.y);
      a0 = p.dist <= maxPx ? p.along : null;
    }
    if (a0 !== null && to.along >= a0 && to.along - a0 <= MAX_GLIDE_PX) {
      // Glide at a steady ground speed, so a vehicle doesn't speed up on screen
      // when the road turns toward a less foreshortened direction
      return { kind: "along", shape: to.shape, m0: pxToM(to.shape, a0), m1: pxToM(to.shape, to.along), end: to };
    }
    if (a0 !== null && a0 - to.along <= BACKTRACK_PX) {
      // A small step backward is GPS jitter: hold still on the track
      const m = pxToM(to.shape, a0);
      return { kind: "along", shape: to.shape, m0: m, m1: m, end: { ...pointAt(to.shape, a0), shape: to.shape, along: a0 } };
    }
  }
  const dx = to.x - from.x, dy = to.y - from.y;
  const dist = Math.hypot(dx, dy);
  if (dist > MAX_GLIDE_PX || track) return { kind: "jump", end: to };
  // Facing: the road's direction when the vehicle lands on its route; else
  // the direction it moves, unless the move is only a short hop
  const bearing = to.shape ? to.bearing : dist > HOP_PX ? bearingOf(inv, dx, dy) : (from.bearing ?? to.bearing);
  return { kind: "line", x0: from.x, y0: from.y, bearing, end: to.shape ? to : { ...to, bearing } };
}

// A position caught partway through a straight move onto a route (the next
// update came before the move finished) gets that route attached, at the
// nearest point, so the following move glides along the route instead of
// starting another straight line.
export function onRoute(pos, move, maxPx = MAX_SNAP_PX) {
  const shape = move && move.end && move.end.shape;
  if (pos.shape || !shape) return pos;
  const p = projectOnto(shape, pos.x, pos.y);
  return p.dist <= maxPx ? { ...pos, shape, along: p.along } : pos;
}

// Where a move is at fraction f (0..1) of its time
export function motionAt(m, f) {
  if (f >= 1 || m.kind === "jump") return m.end;
  const t = Math.max(0, f);
  if (m.kind === "along") {
    const along = mToPx(m.shape, m.m0 + (m.m1 - m.m0) * t);
    return { ...pointAt(m.shape, along), shape: m.shape, along };
  }
  return { x: m.x0 + (m.end.x - m.x0) * t, y: m.y0 + (m.end.y - m.y0) * t, bearing: m.bearing };
}

// --- the El timetable ------------------------------------------------------------------
// el_schedule.json: patterns [{shape, stops: [[s after first departure, px along], ...]}],
// trips [[pattern, first departure s after midnight, service id]], services {"YYYYMMDD": [ids]}.

const NY = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hourCycle: "h23",
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });

// The service day and seconds since midnight in Philadelphia
export function nyClock(date) {
  const p = Object.fromEntries(NY.formatToParts(date).map((x) => [x.type, x.value]));
  return { ymd: `${p.year}${p.month}${p.day}`, secs: +p.hour * 3600 + +p.minute * 60 + +p.second + date.getMilliseconds() / 1000 };
}

function shiftYmd(ymd, days) {
  const d = new Date(Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8) + days));
  return d.toISOString().slice(0, 10).replaceAll("-", "");
}
const weekday = (ymd) => new Date(Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8))).getUTCDay();

// The services for a day. Past the end of the timetable (SEPTA publishes a
// new one every few weeks), use the last day it covers that falls on the same
// weekday, and say so.
export function servicesFor(schedule, ymd) {
  if (schedule.services[ymd]) return { ids: schedule.services[ymd], fallback: null };
  const days = Object.keys(schedule.services).sort();
  const same = days.filter((d) => weekday(d) === weekday(ymd));
  const pick = same.length ? same[same.length - 1] : days[days.length - 1];
  return { ids: pick ? schedule.services[pick] : [], fallback: pick || null };
}

// El trains running at `date`: [{trip index, shape id, along}]. Trips that
// started the day before and run past midnight (GTFS times past 24:00) count too.
export function elTrains(schedule, date) {
  const { ymd, secs } = nyClock(date);
  const out = [];
  let fallback = null;
  for (const [day, t] of [[ymd, secs], [shiftYmd(ymd, -1), secs + 86400]]) {
    const svc = servicesFor(schedule, day);
    if (day === ymd) fallback = svc.fallback;
    const ids = new Set(svc.ids);
    schedule.trips.forEach(([pi, t0, sid], i) => {
      if (!ids.has(sid)) return;
      const stops = schedule.patterns[pi].stops;
      const tt = t - t0;
      if (tt < 0 || tt > stops[stops.length - 1][0]) return;
      let k = 0;
      while (k + 1 < stops.length - 1 && stops[k + 1][0] <= tt) k++;
      const [ta, da] = stops[k], [tb, db] = stops[k + 1] || stops[k];
      const f = tb > ta ? Math.min(1, (tt - ta) / (tb - ta)) : 1;
      out.push({ trip: i, shape: schedule.patterns[pi].shape, along: da + (db - da) * f });
    });
  }
  return { trains: out, fallback };
}

// --- sprites and cars -----------------------------------------------------------------------
export function pickByBearing(sprites, bearing) {
  let best = sprites[0], bd = Infinity;
  for (const s of sprites) {
    let d = Math.abs(s.bearing - bearing) % 360;
    if (d > 180) d = 360 - d;
    if (d < bd) { bd = d; best = s; }
  }
  return best;
}

// Lay out a vehicle (or a train of `cars`) on its track, the way a real one
// sits: every car is length_m long with gap_m between cars, measured along
// the track in meters; each car rests on two trucks (or axles) at the
// fractions kind.trucks of its length; it faces along the chord between them
// and is drawn at their midpoint. On a straight track that is the track
// direction; on a curve the car cuts slightly inside the curve and turns
// smoothly, and a bus turning a corner faces between the two streets.
// centerAlong (map px) is the lead car's middle. Returns
// [{x, y, bearing, sprite, along}] with along the car's middle in map px.
export function carLayout(shape, centerAlong, kind, cars, inv = shape.inv || IDENTITY) {
  const L = kind.length_m, gap = kind.gap_m || 0;
  const [tf, tr] = kind.trucks || [0.2, 0.8];
  const out = [];
  const front0 = pxToM(shape, centerAlong) + L / 2;
  for (let k = 0; k < cars; k++) {
    const front = front0 - k * (L + gap);
    if (front - L * tr < 0) break; // the rest of the train hasn't entered the map
    const pf = pointAt(shape, mToPx(shape, front - L * tf));
    const pr = pointAt(shape, mToPx(shape, front - L * tr));
    const dx = pf.x - pr.x, dy = pf.y - pr.y;
    const bearing = Math.hypot(dx, dy) > 1e-6 ? bearingOf(inv, dx, dy) : pf.bearing;
    out.push({ x: (pf.x + pr.x) / 2, y: (pf.y + pr.y) / 2, bearing, sprite: pickByBearing(kind.sprites, bearing),
               along: mToPx(shape, front - L / 2) });
  }
  return out;
}

// Track behind the start of a shape. Six Regional Rail lines' shapes start at
// 30th Street, so a train there sat at its shape's very start and carLayout
// had nowhere to put its trailing cars: only the lead car was drawn (Nov. 18).
// The track that leads into the start is another shape passing within
// EXTEND_JOIN_PX of it in the same direction; up to EXTEND_BACK_M of it is
// prepended to a copy of the shape, stored as shape.ext = {shape, offset (px
// where the original starts), from (the other shape's id)}. trackCars uses
// it. The original shape is unchanged, so snapping and gliding aren't.
export const EXTEND_BACK_M = 300;   // longer than an 8-car train (8 x 26.9 m)
const EXTEND_JOIN_PX = 20;
export function extendBack(shape, candidates, inv = shape.inv || IDENTITY) {
  const s0 = pointAt(shape, 0);
  let best = null;
  for (const o of candidates) {
    if (o === shape) continue;
    const p = projectOnto(o, s0.x, s0.y);
    if (p.dist > EXTEND_JOIN_PX || p.along < 1) continue;
    let da = Math.abs(pointAt(o, p.along).angle - s0.angle) % (2 * Math.PI);
    if (Math.min(da, 2 * Math.PI - da) > Math.PI / 6) continue; // the other direction's track
    if (!best || p.along > best.along) best = { o, along: p.along }; // the most track behind
  }
  if (!best) return shape;
  const { o, along } = best;
  const a0 = mToPx(o, Math.max(0, pxToM(o, along) - EXTEND_BACK_M));
  const start = pointAt(o, a0);
  const pts = [start.x, start.y];
  for (let i = 0; i < o.cum.length; i++) if (o.cum[i] > a0 && o.cum[i] < along) pts.push(o.pts[2 * i], o.pts[2 * i + 1]);
  const head = pts.length / 2;
  pts.push(...shape.pts);
  const ext = prepareShape({ id: `${shape.id}<${o.id}`, pts, tunnels: [] }, inv);
  const offset = ext.cum[head];
  ext.tunnels = [
    ...o.tunnels.filter(([a, b]) => b > a0 && a < along).map(([a, b]) => [Math.max(a, a0) - a0, Math.min(b, along) - a0]),
    ...shape.tunnels.map(([a, b]) => [a + offset, b + offset]),
  ];
  shape.ext = { shape: ext, offset, from: o.id };
  return shape;
}

// The cars of a vehicle at `pos` that can be seen: laid out on its track
// (carLayout), less any car whose middle is in a tunnel when hideTunnels is
// set. Each car is checked on its own, so a train going into a tunnel loses
// its cars one by one (Nov. 18: the whole train vanished when its lead car
// went underground west of the river). Off its route, a vehicle is one car
// facing its bearing.
export function trackCars(pos, kind, n, inv = IDENTITY, hideTunnels = false) {
  if (!pos.shape) return [{ x: pos.x, y: pos.y, bearing: pos.bearing ?? 0, sprite: pickByBearing(kind.sprites, pos.bearing ?? 0) }];
  // On the shape extended back (extendBack), when there is one: the same track
  // from the original start on, so the lead car is in the same place
  const ext = pos.shape.ext;
  const shape = ext ? ext.shape : pos.shape;
  const cars = carLayout(shape, pos.along + (ext ? ext.offset : 0), kind, n, inv);
  return hideTunnels ? cars.filter((c) => !inTunnel(shape, c.along)) : cars;
}

// TrainView reports trains it can't locate at one fixed point in Suburban
// Station, even when their current stop is miles away (7 of 24 trains in
// tests/fixtures/septa/trainview.json). SEPTA doesn't document it; it was
// observed in the feed. Compared at 5 decimal places (about 1 m), since the
// feed is rounded to 6.
export const PLACEHOLDER = [-75.1677778, 39.9538889];
export function isPlaceholder(lon, lat) {
  return Math.round(lon * 1e5) === Math.round(PLACEHOLDER[0] * 1e5) && Math.round(lat * 1e5) === Math.round(PLACEHOLDER[1] * 1e5);
}

// Trees: a tree mask pixel at map y `py` stores d, how many map px below it its
// trunk stands (0 = no tree; scripts/40_build_tree_mask.py). The map looks down
// at 45°, so a canopy hangs over what is just behind it on screen. It hides a
// vehicle whose ground point is at groundY only when the trunk is at or below
// that point: in front of the vehicle, nearer the viewer.
export function hiddenByTree(d, py, groundY) {
  return d > 0 && py + d >= groundY;
}

export function pointInPolygon(flat, x, y) {
  let inside = false;
  const n = flat.length / 2;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = flat[2 * i], yi = flat[2 * i + 1], xj = flat[2 * j], yj = flat[2 * j + 1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// "Route 23 bus to Center City, 3 min. late" (AP style; lateness straight from SEPTA)
export function describe(v) {
  const late = v.late === null || v.late === undefined ? "" :
    v.late === 0 ? ", on time" : v.late > 0 ? `, ${v.late} min. late` : `, ${-v.late} min. early`;
  const to = v.dest ? ` to ${v.dest}` : "";
  if (v.kind === "el") return "Market-Frankford Line train (scheduled position; SEPTA publishes no live El locations)";
  if (v.kind === "rail") return `${v.line} Line train ${v.id}${to}${late}`;
  return `Route ${v.route} ${v.kind === "trolley" ? "trolley" : "bus"}${to}${late}`;
}
