// Lon/lat -> map image pixels, evaluating the cubic fitted in
// src/pixelphilly/viewer_geo.py (same term order). tests/test_viewer.py
// checks this against the Python projection.
export function lonLatToPx(fit, lon, lat) {
  const u = (lon - fit.lon0) / fit.su;
  const v = (lat - fit.lat0) / fit.sv;
  const t = [1, u, v, u * u, u * v, v * v, u * u * u, u * u * v, u * v * v, v * v * v];
  let x = 0, y = 0;
  for (let i = 0; i < t.length; i++) {
    x += fit.cx[i] * t[i];
    y += fit.cy[i] * t[i];
  }
  return [x, y];
}

export function inBounds(fit, lon, lat) {
  const [w, s, e, n] = fit.bounds_wgs84;
  return lon >= w && lon <= e && lat >= s && lat <= n;
}
