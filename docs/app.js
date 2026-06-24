const FACILITY_GROUPS = [
  { key: "service", label: "設備・サービス" },
  { key: "roomtype", label: "席・部屋タイプ" },
  { key: "karaoke", label: "カラオケ" },
  { key: "darts", label: "ダーツ" },
  { key: "billiards", label: "ビリヤード" },
];

let allStores = [];
const compareSet = new Map(); // store_code -> store

async function init() {
  const res = await fetch("data/stores.json");
  allStores = await res.json();

  document.getElementById("updatedAt").textContent = new Date().toLocaleDateString("ja-JP");

  populatePrefSelect();
  populateFacilityFilters();
  render();

  document.getElementById("prefSelect").addEventListener("change", render);
  document.getElementById("keyword").addEventListener("input", render);
  document.getElementById("clearCompare").addEventListener("click", () => {
    compareSet.clear();
    renderCompare();
    render();
  });
}

function populatePrefSelect() {
  const prefs = [...new Set(allStores.map(s => s.pref))].sort();
  const select = document.getElementById("prefSelect");
  for (const p of prefs) {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    select.appendChild(opt);
  }
}

function populateFacilityFilters() {
  const allFacilities = new Set();
  for (const s of allStores) {
    for (const g of FACILITY_GROUPS) {
      for (const f of s[g.key] || []) allFacilities.add(f);
    }
  }
  const wrap = document.getElementById("facilityFilters");
  for (const facility of [...allFacilities].sort()) {
    const label = document.createElement("label");
    label.className = "facility-chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(facility)}"> ${escapeHtml(facility)}`;
    label.querySelector("input").addEventListener("change", render);
    wrap.appendChild(label);
  }
}

function getSelectedFacilities() {
  return [...document.querySelectorAll("#facilityFilters input:checked")].map(el => el.value);
}

function storeFacilities(store) {
  return FACILITY_GROUPS.flatMap(g => store[g.key] || []);
}

function filterStores() {
  const pref = document.getElementById("prefSelect").value;
  const keyword = document.getElementById("keyword").value.trim();
  const facilities = getSelectedFacilities();

  return allStores.filter(s => {
    if (pref && s.pref !== pref) return false;
    if (keyword && !(s.store_name.includes(keyword) || (s.city || "").includes(keyword))) return false;
    if (facilities.length) {
      const have = new Set(storeFacilities(s));
      if (!facilities.every(f => have.has(f))) return false;
    }
    return true;
  });
}

function render() {
  const filtered = filterStores();
  document.getElementById("resultCount").textContent = `${filtered.length} 件 / 全${allStores.length}件`;

  const tbody = document.getElementById("storeTableBody");
  tbody.innerHTML = "";
  for (const s of filtered.slice(0, 300)) {
    const tr = document.createElement("tr");
    const mainFacilities = storeFacilities(s).slice(0, 6);
    tr.innerHTML = `
      <td><input type="checkbox" data-code="${s.store_code}" ${compareSet.has(s.store_code) ? "checked" : ""}></td>
      <td>${escapeHtml(s.store_name)}</td>
      <td>${escapeHtml(s.pref)}</td>
      <td>${escapeHtml(s.city || "")}</td>
      <td><div class="tag-list">${mainFacilities.map(f => `<span class="tag">${escapeHtml(f)}</span>`).join("")}</div></td>
      <td><a href="${s.detail_url}" target="_blank" rel="noopener">公式</a></td>
    `;
    tr.querySelector("input[type=checkbox]").addEventListener("change", (e) => {
      if (e.target.checked) {
        compareSet.set(s.store_code, s);
      } else {
        compareSet.delete(s.store_code);
      }
      renderCompare();
    });
    tbody.appendChild(tr);
  }
}

function renderCompare() {
  const section = document.getElementById("compareSection");
  const stores = [...compareSet.values()];
  if (stores.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  const allFacilities = [...new Set(stores.flatMap(storeFacilities))].sort();
  const tableWrap = document.getElementById("compareTableWrap");
  let html = "<table><thead><tr><th>項目</th>";
  for (const s of stores) html += `<th>${escapeHtml(s.store_name)}<br><small>${escapeHtml(s.pref)}${escapeHtml(s.city || "")}</small></th>`;
  html += "</tr></thead><tbody>";
  for (const f of allFacilities) {
    html += `<tr><td>${escapeHtml(f)}</td>`;
    for (const s of stores) {
      const has = storeFacilities(s).includes(f);
      html += `<td class="${has ? "yes" : "no"}">${has ? "○" : "−"}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  tableWrap.innerHTML = html;

  const pricesWrap = document.getElementById("comparePrices");
  pricesWrap.innerHTML = stores.map(s => `
    <div class="price-card">
      <h3>${escapeHtml(s.store_name)}</h3>
      ${s.price_image_url ? `<img src="${s.price_image_url}" alt="${escapeHtml(s.store_name)}の料金表" loading="lazy">` : "<p>料金画像なし</p>"}
      ${s.price_ocr_text ? `<div class="ocr">${escapeHtml(s.price_ocr_text)}</div>` : ""}
    </div>
  `).join("");
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();
