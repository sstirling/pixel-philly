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
  const color = new THREE.Color().setRGB(b.color[0] / 255, b.color[1] / 255, b.color[2] / 255, THREE.SRGBColorSpace);
  for (const g of geom.groups) {
    const slicePos = pos.slice(g.start * 3, (g.start + g.count) * 3);
    const sliceNrm = nrm.slice(g.start * 3, (g.start + g.count) * 3);
    if (g.materialIndex === 0) {
      roofParts.push([slicePos, sliceNrm]);
    } else {
      wallParts.push([slicePos, sliceNrm]);
      for (let i = 0; i < g.count; i++) wallColors.push(color.r, color.g, color.b);
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

window.renderFrame = (index, mode = "color") => {
  const f = sceneData.frames[index];
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
