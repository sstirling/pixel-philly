// Isometric render of one area from City of Philadelphia open data.
//
// scripts/05_build_scene.py writes the scene JSON this page loads; the
// camera basis and per-frame frustums in it come from
// src/pixelphilly/projection.py, so Python and WebGL agree to the pixel.
//
// Coordinates: three.js x = local east, y = up, z = -(local north), meters.
//
// Look: ground and roofs use the aerial photo unlit (MeshBasicMaterial), so
// they keep the photo's true colors and its own baked-in shadows. Walls are
// lit by a sun roughly matching the photo's shadows, tinted with each
// building's mean roof color, because the aerial has no façade imagery.
//
// The page exposes window.renderFrame(index, mode) -> PNG data URL, which
// scripts/06_render.py calls once per frame. mode "mask" draws buildings
// white on black for the alignment check in scripts/09_check_alignment.py.

import * as THREE from "./vendor/three.module.min.js";

const params = new URLSearchParams(location.search);
const scenePath = params.get("scene");

const sceneData = await (await fetch(`/${scenePath}`)).json();
const size = sceneData.frame_px;

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(size, size);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const background = new THREE.Color(0xbfc8d2);

// --- camera -------------------------------------------------------------
const cam = sceneData.camera;
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, cam.near, cam.far);
camera.position.fromArray(cam.position);
camera.up.fromArray(cam.up);
camera.lookAt(new THREE.Vector3().fromArray(cam.target));

// --- ground texture -----------------------------------------------------
const { u: cu, v: cv } = sceneData.ground.uv_poly;
// Local (east, north) meters -> texture UV: the quadratic fitted in
// 05_build_scene.py, terms [e, n, 1, e^2, e*n, n^2]
const poly = (c, e, n) => c[0] * e + c[1] * n + c[2] + c[3] * e * e + c[4] * e * n + c[5] * n * n;
const uvAt = (e, n) => [poly(cu, e, n), poly(cv, e, n)];

const texture = await new THREE.TextureLoader().loadAsync(`/${sceneData.ground.image}`);
const maxTex = renderer.capabilities.maxTextureSize;
if (Math.max(texture.image.width, texture.image.height) > maxTex) {
  // WebGL would silently downscale or drop the texture; fail loudly instead.
  throw new Error(`ground texture ${texture.image.width}px exceeds this GPU's ${maxTex}px limit`);
}
texture.colorSpace = THREE.SRGBColorSpace;
texture.anisotropy = renderer.capabilities.getMaxAnisotropy();

function setUVsFromPosition(geometry) {
  const pos = geometry.attributes.position;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    const [u, v] = uvAt(pos.getX(i), -pos.getZ(i));
    uv[2 * i] = u;
    uv[2 * i + 1] = v;
  }
  geometry.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
}

const [e0, n0, e1, n1] = sceneData.ground.extent_m;
// Subdivided so the curved UV mapping is followed closely (UVs are only
// interpolated linearly inside each triangle); 64 cells is ~45 m per cell.
const groundGeom = new THREE.PlaneGeometry(e1 - e0, n1 - n0, 64, 64);
groundGeom.rotateX(-Math.PI / 2);
groundGeom.translate((e0 + e1) / 2, 0, -(n0 + n1) / 2);
setUVsFromPosition(groundGeom);
const aerialMat = new THREE.MeshBasicMaterial({ map: texture });
const ground = new THREE.Mesh(groundGeom, aerialMat);
scene.add(ground);

// --- buildings ----------------------------------------------------------
// Each footprint is extruded, then its triangles are split by ExtrudeGeometry's
// groups (0 = caps, 1 = walls) into two merged meshes. Two draw calls instead
// of ~9,000 keeps each frame fast even on a software renderer.
const roofParts = [];
const wallParts = [];
const wallColors = [];
// Façades from property records (05_build_scene.py "facades": "opa"; see
// src/pixelphilly/facades.py). Only when some building has one, so scenes
// without façade data render exactly as before.
const facadeOn = sceneData.buildings.some((b) => b.facade);
const wallFacade = []; // per vertex: style id (0 = none), floor height m, bay spacing m, band flags
const wallWindow = []; // per vertex: window color
const wallTop = []; // per vertex: the building part's height (cornice)
const wallFront = []; // per vertex: up to two street-facing directions (east, north); zeros = every wall

function shapeFromRings(rings) {
  const toVec = ([e, n]) => new THREE.Vector2(e, n);
  const shape = new THREE.Shape(rings[0].map(toVec));
  for (const hole of rings.slice(1)) shape.holes.push(new THREE.Path(hole.map(toVec)));
  return shape;
}

for (const b of sceneData.buildings) {
  const shapes = b.polys.map(shapeFromRings);
  const geom = new THREE.ExtrudeGeometry(shapes, { depth: b.h, bevelEnabled: false });
  // Shapes are drawn in (east, north); extrusion runs along +z. Rotating -90°
  // about x maps north to -z and the extrusion to +y (up).
  geom.rotateX(-Math.PI / 2);
  const pos = geom.attributes.position.array;
  const nrm = geom.attributes.normal.array;
  const f = b.facade;
  const rgb = f ? f.w : b.color;
  const color = new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
  const win = f ? new THREE.Color().setRGB(f.g[0] / 255, f.g[1] / 255, f.g[2] / 255, THREE.SRGBColorSpace) : null;
  for (const g of geom.groups) {
    const slicePos = pos.slice(g.start * 3, (g.start + g.count) * 3);
    const sliceNrm = nrm.slice(g.start * 3, (g.start + g.count) * 3);
    if (g.materialIndex === 0) {
      roofParts.push([slicePos, sliceNrm]);
    } else {
      wallParts.push([slicePos, sliceNrm]);
      for (let i = 0; i < g.count; i++) wallColors.push(color.r, color.g, color.b);
      if (facadeOn) {
        for (let i = 0; i < g.count; i++) {
          if (f) {
            wallFacade.push(f.s, f.f, f.p, f.b);
            wallWindow.push(win.r, win.g, win.b);
            wallFront.push(...(f.d || [0, 0, 0, 0]));
          } else {
            wallFacade.push(0, 1, 1, 0);
            wallWindow.push(0, 0, 0);
            wallFront.push(0, 0, 0, 0);
          }
          wallTop.push(b.h);
        }
      }
    }
  }
  geom.dispose();
}

function merged(parts) {
  const n = parts.reduce((s, [p]) => s + p.length, 0);
  const pos = new Float32Array(n);
  const nrm = new Float32Array(n);
  let o = 0;
  for (const [p, q] of parts) {
    pos.set(p, o);
    nrm.set(q, o);
    o += p.length;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  return g;
}

const roofGeom = merged(roofParts);
setUVsFromPosition(roofGeom);
const roofs = new THREE.Mesh(roofGeom, aerialMat);

const wallGeom = merged(wallParts);
wallGeom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(wallColors), 3));
const wallMat = new THREE.MeshLambertMaterial({ vertexColors: true });
if (facadeOn) {
  wallGeom.setAttribute("facadeA", new THREE.BufferAttribute(new Float32Array(wallFacade), 4));
  wallGeom.setAttribute("facadeWin", new THREE.BufferAttribute(new Float32Array(wallWindow), 3));
  wallGeom.setAttribute("facadeTop", new THREE.BufferAttribute(new Float32Array(wallTop), 1));
  wallGeom.setAttribute("facadeFront", new THREE.BufferAttribute(new Float32Array(wallFront), 4));
  // Procedural façade, no textures or UVs: the floor comes from world
  // height / floor height, the bay from the position along the wall (world
  // x/z projected on the wall's horizontal direction, from its normal).
  // Windows per floor and bay (dark panes with a 1 px lighter sill); band
  // flags (facades.BAND_*): 1 storefront (bulkhead, glass with mullions,
  // dark sign band), 2 porch (light porch-roof trim at about one floor, a
  // shadowed recess with thin posts per bay), 4 cornice (dark strip at the
  // roofline), 8 glass curtain wall (wide panes, thin mullions). Storefront
  // and porch go on street-facing walls only (facade "d", from the City's
  // street centerlines; without it, every wall). Paint only: geometry,
  // masks and alignment are unchanged, and a detail appears only where the
  // property record (or OSM) says the building has it
  wallMat.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        `#include <common>
attribute vec4 facadeA;
attribute vec3 facadeWin;
attribute float facadeTop;
attribute vec4 facadeFront;
varying vec4 vFacadeFront;
varying vec4 vFacade;
varying vec3 vFacadeWin;
varying float vFacadeTop;
varying vec3 vFacadePos;
varying vec3 vFacadeN;`,
      )
      .replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
vFacade = facadeA;
vFacadeWin = facadeWin;
vFacadeTop = facadeTop;
vFacadeFront = facadeFront;
vFacadePos = (modelMatrix * vec4(transformed, 1.0)).xyz;
vFacadeN = normal;`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
varying vec4 vFacade;
varying vec3 vFacadeWin;
varying float vFacadeTop;
varying vec3 vFacadePos;
varying vec3 vFacadeN;
varying vec4 vFacadeFront;
bool facadeIsFront() {
  // three.js z = -north, so the wall's (east, north) normal is (x, -z)
  vec2 n = normalize(vec2(vFacadeN.x, -vFacadeN.z) + 1e-6);
  if (dot(abs(vFacadeFront), vec4(1.0)) < 1e-3) return true;
  return dot(n, vFacadeFront.xy) > 0.7 || dot(n, vFacadeFront.zw) > 0.7;
}
vec3 facadeColor(vec3 wall) {
  float fh = vFacade.y;
  float sp = vFacade.z;
  int bands = int(vFacade.w + 0.5);
  float y = vFacadePos.y;
  float fl = floor(y / fh);
  float yf = y - fl * fh; // meters above this floor's base
  vec2 t = normalize(vec2(-vFacadeN.z, vFacadeN.x) + 1e-6);
  float fx = fract(dot(vFacadePos.xz, t) / sp);
  vec3 c = wall;
  vec3 trim = mix(wall, vec3(0.86, 0.86, 0.82), 0.75);
  bool front = facadeIsFront();
  if ((bands & 8) != 0) {
    if (fx > 0.08 && fx < 0.92 && yf > 0.12 * fh && yf < 0.92 * fh) c = vFacadeWin;
  } else {
    float w0 = 0.3 * fh, w1 = 0.75 * fh;
    if (fx > 0.3 && fx < 0.7 && yf > w0 && yf < w1) c = vFacadeWin * 0.8;
    else if (fx > 0.27 && fx < 0.73 && yf > w0 - 0.25 && yf <= w0) c = min(wall * 1.4, vec3(1.0)); // sill
  }
  if ((bands & 1) != 0 && fl < 0.5 && front) {
    if (yf < 0.45) c = wall * 0.55; // bulkhead
    else if (yf < 0.72 * fh) {
      bool mullion = fx < 0.03 || fx > 0.97 || abs(fx - 0.5) < 0.03;
      c = mullion ? wall * 0.35 : min(vFacadeWin * 1.45, vec3(1.0));
    } else if (yf < 0.95 * fh) c = mix(wall, vec3(0.12, 0.14, 0.16), 0.7); // sign band
  }
  if ((bands & 2) != 0 && fl < 0.5 && front) {
    if (yf > 0.70 * fh && yf < 0.98 * fh) c = trim; // porch roof
    else if (yf > 0.66 * fh && yf <= 0.70 * fh) c = wall * 0.35; // its shadow line
    else if (yf <= 0.66 * fh) {
      c = wall * 0.55; // shadowed recess
      if (fx > 0.3 && fx < 0.7 && yf > 0.15 * fh && yf < 0.6 * fh) c = vFacadeWin * 0.6;
      if (fx < 0.3 / sp) c = trim; // a thin post per bay
    }
  }
  if ((bands & 4) != 0 && y > vFacadeTop - 0.5) c = wall * 0.62;
  return c;
}`,
      )
      .replace(
        "#include <color_fragment>",
        `#include <color_fragment>
if (vFacade.x > 0.5) diffuseColor.rgb = facadeColor(vColor);`,
      );
  };
}
const walls = new THREE.Mesh(wallGeom, wallMat);
scene.add(roofs, walls);

// --- trees --------------------------------------------------------------
// Stylized canopies (low-poly balls) at inventory points, sized from trunk
// diameter in 05_build_scene.py. They give the image model volume to draw;
// they are not measured crown shapes.
const treeGeom = new THREE.IcosahedronGeometry(1, 1);
const treeMat = new THREE.MeshLambertMaterial({ flatShading: true });
const trees = new THREE.InstancedMesh(treeGeom, treeMat, sceneData.trees.length);
const m = new THREE.Matrix4();
const tint = new THREE.Color();
// Fixed seed so every run renders identical trees
let seed = 12345;
const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
sceneData.trees.forEach(([e, n, r], i) => {
  m.compose(
    new THREE.Vector3(e, 1.5 + r * 1.1, -n),
    new THREE.Quaternion(),
    new THREE.Vector3(r, r * 0.9, r),
  );
  trees.setMatrixAt(i, m);
  tint.setHSL(0.27 + rand() * 0.06, 0.35 + rand() * 0.15, 0.3 + rand() * 0.08, THREE.SRGBColorSpace);
  trees.setColorAt(i, tint);
});
scene.add(trees);

// --- light (walls and trees only; aerial surfaces are unlit) -------------
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
// From the south-southeast and fairly high, close to the shadows in the
// spring 2024 aerials, so lit walls agree with the photo's shadows.
sun.position.set(300, 700, 600);
scene.add(sun);

// --- modes and frame rendering ------------------------------------------
const maskMat = new THREE.MeshBasicMaterial({ color: 0xffffff });

function setMode(mode) {
  const mask = mode === "mask";
  ground.visible = !mask;
  trees.visible = !mask;
  scene.overrideMaterial = mask ? maskMat : null;
  scene.background = mask ? new THREE.Color(0x000000) : background;
  renderer.setClearColor(mask ? 0x000000 : background);
}

window.renderFrame = (index, mode = "color") => window.renderView(sceneData.frames[index], mode);

// Render any orthographic view of the same camera: {left, right, top,
// bottom} in view-space meters (see projection.Frame.frustum). The canvas is
// always frame_px square, so a narrower frustum is a zoomed-in view. Used by
// 13_build_trainset.py for shifted crops and 2x zoomed quarters.
window.renderView = (f, mode = "color") => {
  setMode(mode);
  // Antialiasing would blur the mask's edges into grey; the check thresholds
  // at 50%, which recovers the same boundary either way.
  camera.left = f.left;
  camera.right = f.right;
  camera.top = f.top;
  camera.bottom = f.bottom;
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);
  return renderer.domElement.toDataURL("image/png");
};

const gl = renderer.getContext();
const dbg = gl.getExtension("WEBGL_debug_renderer_info");
window.rendererInfo = {
  gpu: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "unknown",
  maxTexture: gl.getParameter(gl.MAX_TEXTURE_SIZE),
  frames: sceneData.frames.length,
  buildings: sceneData.buildings.length,
  trees: sceneData.trees.length,
};
window.sceneReady = true;
