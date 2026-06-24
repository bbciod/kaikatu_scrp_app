const FACILITY_GROUPS = [
  { key: "service", label: "設備・サービス" },
  { key: "roomtype", label: "席・部屋タイプ" },
  { key: "karaoke", label: "カラオケ" },
  { key: "darts", label: "ダーツ" },
  { key: "billiards", label: "ビリヤード" },
];

let allStores = [];
const compareSet = new Map(); // store_code -> store

function getMinNightPack(store) {
  return store.price && store.price.min_night_pack_taxfee != null ? store.price.min_night_pack_taxfee : null;
}

function getMinBasic(store) {
  return store.price && store.price.min_basic_taxfee != null ? store.price.min_basic_taxfee : null;
}

async function init() {
  const res = await fetch("data/stores.json");
  allStores = await res.json();

  document.getElementById("updatedAt").textContent = new Date().toLocaleDateString("ja-JP");

  populatePrefFilters();
  populateFacilityFilters();
  render();
  renderDetailPriceSearch();

  document.getElementById("keyword").addEventListener("input", () => {
    render();
    renderDetailPriceSearch();
  });
  document.getElementById("priceMax").addEventListener("input", render);
  document.getElementById("sortSelect").addEventListener("change", render);
  document.getElementById("clearCompare").addEventListener("click", () => {
    compareSet.clear();
    renderCompare();
    render();
    renderDetailPriceSearch();
  });

  document.getElementById("seatCategory").addEventListener("change", renderDetailPriceSearch);
  document.getElementById("durationSelect").addEventListener("change", renderDetailPriceSearch);
  document.getElementById("dayTypeSelect").addEventListener("change", renderDetailPriceSearch);
}

function populatePrefFilters() {
  const prefs = [...new Set(allStores.map(s => s.pref))].sort();
  const wrap = document.getElementById("prefFilters");
  for (const pref of prefs) {
    const label = document.createElement("label");
    label.className = "facility-chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(pref)}"> ${escapeHtml(pref)}`;
    label.querySelector("input").addEventListener("change", () => {
      render();
      renderDetailPriceSearch();
    });
    wrap.appendChild(label);
  }
}

function getSelectedPrefs() {
  return [...document.querySelectorAll("#prefFilters input:checked")].map(el => el.value);
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
  const prefs = getSelectedPrefs();
  const keyword = document.getElementById("keyword").value.trim();
  const facilities = getSelectedFacilities();
  const priceMaxRaw = document.getElementById("priceMax").value.trim();
  const priceMax = priceMaxRaw ? Number(priceMaxRaw) : null;
  const sortKey = document.getElementById("sortSelect").value;

  let result = allStores.filter(s => {
    if (prefs.length && !prefs.includes(s.pref)) return false;
    if (keyword && !(s.store_name.includes(keyword) || (s.city || "").includes(keyword))) return false;
    if (facilities.length) {
      const have = new Set(storeFacilities(s));
      if (!facilities.every(f => have.has(f))) return false;
    }
    if (priceMax != null) {
      const nightPack = getMinNightPack(s);
      if (nightPack == null || nightPack > priceMax) return false;
    }
    return true;
  });

  if (sortKey === "price_asc" || sortKey === "price_desc") {
    result = result.slice().sort((a, b) => {
      const pa = getMinNightPack(a);
      const pb = getMinNightPack(b);
      if (pa == null && pb == null) return 0;
      if (pa == null) return 1; // 料金不明は末尾
      if (pb == null) return -1;
      return sortKey === "price_asc" ? pa - pb : pb - pa;
    });
  }

  return result;
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
      <td>${formatPriceCell(s)}</td>
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

function formatPriceCell(store) {
  if (store.price_source === "json") {
    const nightPack = getMinNightPack(store);
    const basic = getMinBasic(store);
    const parts = [];
    if (nightPack != null) parts.push(`ナイトパック ¥${nightPack.toLocaleString()}〜`);
    else if (basic != null) parts.push(`基本料金 ¥${basic.toLocaleString()}〜`);
    return parts.join(" / ") || "—";
  }
  if (store.price_source === "image") return "画像のみ（数値化不可）";
  return "情報なし";
}

function renderPriceDetail(store) {
  if (store.price_source === "json" && store.price && store.price.categories.length) {
    const rows = store.price.categories.map(c => {
      const nightWeekday = Object.values(c.weekday_night_pack_taxfee)[0];
      const nightWeekend = Object.values(c.weekend_night_pack_taxfee)[0];
      return `
        <tr>
          <td>${escapeHtml(c.label)}</td>
          <td>¥${c.weekday_basic_taxfee ?? "-"}（${c.weekday_basic_time ?? "?"}分）</td>
          <td>¥${c.weekday_hourly_taxfee["24"] ?? "-"}</td>
          <td>${nightWeekday != null ? "¥" + nightWeekday : "-"}</td>
          <td>${nightWeekend != null ? "¥" + nightWeekend : "-"}</td>
        </tr>`;
    }).join("");
    return `
      <table class="price-detail-table">
        <thead><tr><th>座席</th><th>基本料金(平日)</th><th>24時間(平日)</th><th>ナイトパック(平日)</th><th>ナイトパック(休日)</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="price-note">${store.price.night_pack_start_time ?? ""}〜${store.price.night_pack_end_time ?? ""} の利用が対象（店舗・座席により異なる場合があります）</p>
    `;
  }
  if (store.price_source === "image") {
    return `
      ${store.price_image_url ? `<img src="${store.price_image_url}" alt="${escapeHtml(store.store_name)}の料金表" loading="lazy">` : ""}
      ${store.price_ocr_text ? `<div class="ocr">${escapeHtml(store.price_ocr_text)}</div>` : "<p class=\"price-note\">OCRテキストなし</p>"}
    `;
  }
  return "<p>料金情報を取得できませんでした</p>";
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
      ${renderPriceDetail(s)}
    </div>
  `).join("");
}

function getCategoryPrice(category, duration, dayType) {
  if (duration === "night_pack") {
    const packs = dayType === "weekend" ? category.weekend_night_pack_taxfee : category.weekday_night_pack_taxfee;
    const values = Object.values(packs);
    return values.length ? Math.min(...values) : null;
  }
  const hourly = dayType === "weekend" ? category.weekend_hourly_taxfee : category.weekday_hourly_taxfee;
  return hourly[duration] != null ? hourly[duration] : null;
}

function getDetailPrice(store, seatCategory, duration, dayType) {
  if (store.price_source !== "json" || !store.price) return null;
  const categories = seatCategory
    ? store.price.categories.filter(c => c.category === seatCategory)
    : store.price.categories;
  let best = null;
  let bestCategory = null;
  for (const c of categories) {
    const price = getCategoryPrice(c, duration, dayType);
    if (price != null && (best == null || price < best)) {
      best = price;
      bestCategory = c;
    }
  }
  return best != null ? { price: best, category: bestCategory } : null;
}

function renderDetailPriceSearch() {
  const seatCategory = document.getElementById("seatCategory").value;
  const duration = document.getElementById("durationSelect").value;
  const dayType = document.getElementById("dayTypeSelect").value;
  const prefs = getSelectedPrefs();
  const keyword = document.getElementById("keyword").value.trim();

  const rows = [];
  for (const s of allStores) {
    if (prefs.length && !prefs.includes(s.pref)) continue;
    if (keyword && !(s.store_name.includes(keyword) || (s.city || "").includes(keyword))) continue;
    const result = getDetailPrice(s, seatCategory, duration, dayType);
    if (result == null) continue;
    rows.push({ store: s, price: result.price, category: result.category });
  }
  rows.sort((a, b) => a.price - b.price);

  document.getElementById("detailResultCount").textContent = `${rows.length} 件（料金が取得できている店舗のみ）`;

  const tbody = document.getElementById("detailPriceTableBody");
  tbody.innerHTML = "";
  for (const row of rows.slice(0, 300)) {
    const s = row.store;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" data-code="${s.store_code}" ${compareSet.has(s.store_code) ? "checked" : ""}></td>
      <td>${escapeHtml(s.store_name)}</td>
      <td>${escapeHtml(s.pref)}</td>
      <td>${escapeHtml(s.city || "")}</td>
      <td>${escapeHtml(row.category.label)}</td>
      <td>¥${row.price.toLocaleString()}</td>
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

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();
