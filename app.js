const BASE = "https://gc.nh.gov/rsa/html";

function normalize(s) {
  return (s || "").trim().toLowerCase().replace(/\s+/g, "");
}

function parseRSA(input) {
  let s = normalize(input);
  if (s.startsWith("rsa")) s = s.slice(3);

  // chapter like 225-a or 540-a ; optional :section like 24 or 24-a
  const m = s.match(/^(\d+(?:-[a-z])?)(?::([0-9a-z-]+))?$/i);
  if (!m) throw new Error("Could not parse. Try '225-A:24' or 'RSA 225-A'.");

  return { chapter: m[1].toLowerCase(), section: m[2] ? m[2].toLowerCase() : null };
}

function chapterToken(ch) {
  // '225-a' => [225, 1] ; '225' => [225,0]
  const m = ch.toUpperCase().match(/^(\d+)(?:-([A-Z]+))?$/);
  if (!m) throw new Error("Bad chapter format: " + ch);
  const base = parseInt(m[1], 10);
  const suf = m[2] || "";
  let n = 0;
  for (const c of suf) n = n * 26 + (c.charCodeAt(0) - 64);
  return [base, n];
}

function inRange(ch, start, end) {
  const x = chapterToken(ch);
  const a = chapterToken(start);
  const b = chapterToken(end);
  return (a[0] < x[0] || (a[0] === x[0] && a[1] <= x[1])) &&
         (x[0] < b[0] || (x[0] === b[0] && x[1] <= b[1]));
}

async function loadMapping() {
  const r = await fetch("./data/chapter_to_title.json", { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load mapping JSON.");
  return await r.json();
}

function folderForChapter(chapter, payload) {
  const direct = payload.chapter_to_title?.[chapter];
  if (direct) return direct;

  for (const tr of (payload.title_ranges || [])) {
    if (inRange(chapter, tr.start.toLowerCase(), tr.end.toLowerCase())) return tr.folder;
  }
  return null;
}

function buildUrl(chapter, section, folder) {
  if (!folder) throw new Error("Could not determine title folder for chapter " + chapter);
  if (section) return `${BASE}/${folder}/${chapter}/${chapter}-${section}.htm`;
  return `${BASE}/${folder}/${chapter}/${chapter}-mrg.htm`;
}

async function go() {
  const out = document.getElementById("out");
  out.textContent = "";

  try {
    const { chapter, section } = parseRSA(document.getElementById("rsa").value);
    const payload = await loadMapping();
    const folder = folderForChapter(chapter, payload);
    const url = buildUrl(chapter, section, folder);

    out.innerHTML = `Opening: <a href="${url}" target="_blank" rel="noreferrer">${url}</a>`;
    window.open(url, "_blank");
  } catch (e) {
    out.textContent = e.message || String(e);
  }
}

document.getElementById("go").addEventListener("click", go);
document.getElementById("rsa").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") go();
});
