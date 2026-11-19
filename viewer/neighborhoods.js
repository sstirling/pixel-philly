// Neighborhood prints page: one card per neighborhood from
// output/philly/prints/v18/index.json (scripts/41_neighborhood_prints.py),
// sorted A-Z, with a filter box. Each card links the three downloads with
// their pixel sizes and file sizes. A thumbnail opens a larger preview
// (preview.webp, 1,920 x 1,080) in a modal dialog.

const BASE = "../output/philly/prints/v18/";
const grid = document.getElementById("grid");
const filter = document.getElementById("filter");
const count = document.getElementById("count");
const dialog = document.getElementById("preview");
let opener = null; // the thumbnail that opened the preview, to return focus to

const fmt = new Intl.NumberFormat("en-US");
// AP style: "0.5 square mile", "2.9 square miles"
export function areaText(sqmi) {
  const v = sqmi < 1 ? sqmi.toFixed(2).replace(/0$/, "") : sqmi.toFixed(1);
  return `${v} square ${Number(v) === 1 || sqmi < 1 ? "mile" : "miles"}`;
}
export function mbText(bytes) {
  const mb = bytes / 1e6;
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  for (const k of kids) e.append(k);
  return e;
}

function downloads(n) {
  const f = n.files;
  const link = (file, label) => {
    const v = f[file];
    return el("li", {}, el("a", { href: `${BASE}${n.slug}/${file}`, download: `pixel-philly-${n.slug}-${file}` },
      el("span", {}, label), el("span", { class: "size" }, `${fmt.format(v.width)} x ${fmt.format(v.height)} · ${mbText(v.bytes)}`)));
  };
  return [link("print.jpg", "Print"), link("desktop.jpg", "Desktop"), link("phone.jpg", "Phone")];
}

function openPreview(n, button) {
  const img = document.getElementById("preview-img");
  const v = n.files["preview.webp"] || n.files["desktop.jpg"];
  img.src = `${BASE}${n.slug}/${n.files["preview.webp"] ? "preview.webp" : "desktop.jpg"}`;
  img.width = v.width; img.height = v.height;
  img.alt = `${n.name}, drawn as isometric pixel art and cut out along its boundary.`;
  document.getElementById("preview-title").textContent = n.name;
  document.getElementById("preview-dl").replaceChildren(...downloads(n));
  opener = button;
  dialog.showModal();
}

function card(n) {
  const f = n.files;
  const thumb = el("img", { src: `${BASE}${n.slug}/thumb.webp`, width: f["thumb.webp"].width, height: f["thumb.webp"].height,
    loading: "lazy", decoding: "async", alt: `${n.name}, drawn as isometric pixel art and cut out along its boundary.` });
  const open = el("button", { type: "button", class: "thumb", "aria-label": `Larger preview of ${n.name}` }, thumb);
  open.addEventListener("click", () => openPreview(n, open));
  const li = el("li", { "data-name": n.name.toLowerCase() },
    el("article", { class: "card" },
      open,
      el("div", { class: "body" },
        el("h2", {}, n.name),
        el("p", { class: "area" }, areaText(n.sqmi)),
        el("ul", { class: "dl", "aria-label": `Downloads for ${n.name}` }, ...downloads(n)))));
  return li;
}

function apply(total) {
  const q = filter.value.trim().toLowerCase();
  let shown = 0;
  for (const li of grid.children) {
    const hit = !q || li.dataset.name.includes(q);
    li.hidden = !hit;
    shown += hit;
  }
  count.textContent = q ? `${shown} of ${total} neighborhoods` : `${total} neighborhoods`;
}

async function main() {
  try {
    const r = await fetch(BASE + "index.json");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const hoods = (await r.json()).neighborhoods.sort((a, b) => a.name.localeCompare(b.name));
    grid.append(...hoods.map(card));
    filter.addEventListener("input", () => apply(hoods.length));
    apply(hoods.length);
  } catch (err) {
    count.textContent = "The neighborhood list couldn't be loaded. Try again in a moment.";
  }
}

if (dialog) {
  // Escape closes a modal dialog natively; also the close button, the picture
  // and any click outside it (on the backdrop the click lands on the dialog itself)
  document.getElementById("preview-close").addEventListener("click", () => dialog.close());
  document.getElementById("preview-img").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => { opener?.focus(); opener = null; });
}

if (grid) main();
