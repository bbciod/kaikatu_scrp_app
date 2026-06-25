const FACILITY_GROUPS = [
  { key: "service", label: "設備・サービス" },
  { key: "roomtype", label: "席・部屋タイプ" },
  { key: "karaoke", label: "カラオケ" },
  { key: "darts", label: "ダーツ" },
  { key: "billiards", label: "ビリヤード" },
];

// 北海道から沖縄までの都道府県コード順（JIS X 0401）
const PREF_ORDER = [
  "北海道",
  "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
  "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
  "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
  "岐阜県", "静岡県", "愛知県", "三重県",
  "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
  "鳥取県", "島根県", "岡山県", "広島県", "山口県",
  "徳島県", "香川県", "愛媛県", "高知県",
  "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
  "沖縄県",
];

// ナイトパックは8時間("8"キー)と12時間("A"キー)の2種類が別プランとして存在する。
// 利用時間・プランは複数選択可能（チェックした中から最安のものを各店舗ごとに採用する）。
const DURATION_OPTIONS = [
  { value: "night_pack_8", label: "ナイトパック(8時間)", type: "night_pack", hours: 8 },
  { value: "night_pack_12", label: "ナイトパック(12時間)", type: "night_pack", hours: 12 },
  { value: "3", label: "3時間パック", type: "hourly" },
  { value: "6", label: "6時間パック", type: "hourly" },
  { value: "9", label: "9時間パック", type: "hourly" },
  { value: "12", label: "12時間パック", type: "hourly" },
  { value: "15", label: "15時間パック", type: "hourly" },
  { value: "18", label: "18時間パック", type: "hourly" },
  { value: "21", label: "21時間パック", type: "hourly" },
  { value: "24", label: "24時間パック", type: "hourly" },
];

let allStores = [];
const compareSet = new Map(); // store_code -> store
let visibleStores = []; // 現在表示中（フィルタ後・最大300件）の店舗。全選択チェックボックスの対象。

async function init() {
  const res = await fetch("data/stores.json");
  allStores = await res.json();

  document.getElementById("updatedAt").textContent = new Date().toLocaleDateString("ja-JP");

  populatePrefFilters();
  populateFacilityFilters();
  populateDurationFilters();
  render();

  const rerenderInputs = ["keyword", "priceMax"];
  for (const id of rerenderInputs) {
    document.getElementById(id).addEventListener("input", render);
  }
  // 比較表の列(座席タイプ・曜日)もこれらに依存するため、両方再描画する
  const rerenderSelects = ["sortSelect", "seatCategory", "dayTypeSelect"];
  for (const id of rerenderSelects) {
    document.getElementById(id).addEventListener("change", () => {
      render();
      renderCompare();
    });
  }

  document.getElementById("clearCompare").addEventListener("click", clearAllCompare);
  document.getElementById("clearCompareTop").addEventListener("click", clearAllCompare);

  document.getElementById("selectAllCheckbox").addEventListener("change", (e) => {
    if (e.target.checked) {
      for (const s of visibleStores) compareSet.set(s.store_code, s);
    } else {
      for (const s of visibleStores) compareSet.delete(s.store_code);
    }
    render();
    renderCompare();
  });
}

function clearAllCompare() {
  compareSet.clear();
  renderCompare();
  render();
}

function populateDurationFilters() {
  const wrap = document.getElementById("durationFilters");
  for (const opt of DURATION_OPTIONS) {
    const label = document.createElement("label");
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(opt.value)}"> ${escapeHtml(opt.label)}`;
    label.querySelector("input").addEventListener("change", () => { render(); renderCompare(); });
    wrap.appendChild(label);
  }
}

function getSelectedDurations() {
  const values = [...document.querySelectorAll("#durationFilters input:checked")].map(el => el.value);
  // 未選択時はすべてのプランの中から最安を採用する
  return values.length ? DURATION_OPTIONS.filter(o => values.includes(o.value)) : DURATION_OPTIONS;
}

function populatePrefFilters() {
  const presentPrefs = new Set(allStores.map(s => s.pref));
  const prefs = PREF_ORDER.filter(p => presentPrefs.has(p));
  for (const p of presentPrefs) {
    if (!PREF_ORDER.includes(p)) prefs.push(p); // 想定外の表記はリスト末尾に保持
  }
  const wrap = document.getElementById("prefFilters");
  for (const pref of prefs) {
    const label = document.createElement("label");
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(pref)}"> ${escapeHtml(pref)}`;
    label.querySelector("input").addEventListener("change", render);
    wrap.appendChild(label);
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
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(facility)}"> ${escapeHtml(facility)}`;
    label.querySelector("input").addEventListener("change", () => { render(); renderCompare(); });
    wrap.appendChild(label);
  }
}

function getSelectedPrefs() {
  return [...document.querySelectorAll("#prefFilters input:checked")].map(el => el.value);
}

function getSelectedFacilities() {
  return [...document.querySelectorAll("#facilityFilters input:checked")].map(el => el.value);
}

function storeFacilities(store) {
  return FACILITY_GROUPS.flatMap(g => store[g.key] || []);
}

function getCategoryPrice(category, durationOption, dayType) {
  if (durationOption.type === "night_pack") {
    const pack = category.night_packs.find(np => np.hours === durationOption.hours);
    if (!pack) return null;
    const fee = dayType === "weekend" ? pack.weekend_taxfee : pack.weekday_taxfee;
    return fee != null ? fee : null;
  }
  const hourly = dayType === "weekend" ? category.weekend_hourly_taxfee : category.weekday_hourly_taxfee;
  return hourly[durationOption.value] != null ? hourly[durationOption.value] : null;
}

function getConditionPrice(store, seatCategory, durationOptions, dayType) {
  if ((store.price_source !== "json" && store.price_source !== "vision_ai") || !store.price) return null;
  const categories = seatCategory
    ? store.price.categories.filter(c => c.category === seatCategory)
    : store.price.categories;
  let best = null;
  for (const durationOption of durationOptions) {
    for (const c of categories) {
      const price = getCategoryPrice(c, durationOption, dayType);
      if (price != null && (best == null || price < best.price)) {
        best = { price, category: c, duration: durationOption };
      }
    }
  }
  return best;
}

function getConditions() {
  return {
    seatCategory: document.getElementById("seatCategory").value,
    durations: getSelectedDurations(),
    dayType: document.getElementById("dayTypeSelect").value,
  };
}

function buildResultRows() {
  const prefs = getSelectedPrefs();
  const facilities = getSelectedFacilities();
  const keyword = document.getElementById("keyword").value.trim();
  const priceMaxRaw = document.getElementById("priceMax").value.trim();
  const priceMax = priceMaxRaw ? Number(priceMaxRaw) : null;
  const sortKey = document.getElementById("sortSelect").value;
  const { seatCategory, durations, dayType } = getConditions();

  const rows = [];
  for (const s of allStores) {
    if (prefs.length && !prefs.includes(s.pref)) continue;
    if (keyword && !(s.store_name.includes(keyword) || (s.city || "").includes(keyword))) continue;
    if (facilities.length) {
      const have = new Set(storeFacilities(s));
      if (!facilities.every(f => have.has(f))) continue;
    }
    const priced = getConditionPrice(s, seatCategory, durations, dayType);
    if (priceMax != null && (priced == null || priced.price > priceMax)) continue;
    rows.push({ store: s, priced });
  }

  rows.sort((a, b) => {
    const pa = a.priced ? a.priced.price : null;
    const pb = b.priced ? b.priced.price : null;
    if (pa == null && pb == null) return 0;
    if (pa == null) return 1; // 料金不明は末尾
    if (pb == null) return -1;
    return sortKey === "price_desc" ? pb - pa : pa - pb;
  });

  return rows;
}

function render() {
  const rows = buildResultRows();
  document.getElementById("resultCount").textContent = `${rows.length} 件 / 全${allStores.length}件`;
  const visibleRows = rows.slice(0, 300);
  visibleStores = visibleRows.map(r => r.store);

  const tbody = document.getElementById("storeTableBody");
  tbody.innerHTML = "";
  for (const { store: s, priced } of visibleRows) {
    const tr = document.createElement("tr");
    const mainFacilities = storeFacilities(s).slice(0, 5);
    tr.innerHTML = `
      <td><input type="checkbox" data-code="${s.store_code}" ${compareSet.has(s.store_code) ? "checked" : ""}></td>
      <td>${escapeHtml(s.store_name)}</td>
      <td>${escapeHtml(s.pref)}</td>
      <td>${escapeHtml(s.city || "")}</td>
      <td>${priced ? escapeHtml(priced.category.label) : "—"}</td>
      <td>${formatPriceCell(s, priced)}</td>
      <td>${priced ? escapeHtml(priced.duration.label) : "—"}</td>
      <td><div class="tag-list">${mainFacilities.map(f => `<span class="tag">${escapeHtml(f)}</span>`).join("")}</div></td>
      <td><a href="${s.detail_url}" target="_blank" rel="noopener">公式</a></td>
    `;
    tr.querySelector("input[type=checkbox]").addEventListener("change", (e) => {
      if (e.target.checked) {
        compareSet.set(s.store_code, s);
      } else {
        compareSet.delete(s.store_code);
      }
      updateSelectAllCheckboxState();
      renderCompare();
    });
    tbody.appendChild(tr);
  }
  updateSelectAllCheckboxState();
}

function updateSelectAllCheckboxState() {
  const checkbox = document.getElementById("selectAllCheckbox");
  const visibleCount = visibleStores.length;
  const checkedCount = visibleStores.filter(s => compareSet.has(s.store_code)).length;
  checkbox.checked = visibleCount > 0 && checkedCount === visibleCount;
  checkbox.indeterminate = checkedCount > 0 && checkedCount < visibleCount;
}

function formatPriceCell(store, priced) {
  if (priced) {
    const aiTag = store.price_source === "vision_ai" ? ' <span class="ai-badge" title="AI画像読み取り（参考値）">AI</span>' : "";
    return `¥${priced.price.toLocaleString()}${aiTag}`;
  }
  if (store.price_source === "image") return "画像のみ（数値化不可）";
  return "情報なし";
}

function getDurationPriceForStore(store, durationOption, seatCategory, dayType) {
  if ((store.price_source !== "json" && store.price_source !== "vision_ai") || !store.price) return null;
  const categories = seatCategory
    ? store.price.categories.filter(c => c.category === seatCategory)
    : store.price.categories;
  let best = null;
  for (const c of categories) {
    const price = getCategoryPrice(c, durationOption, dayType);
    if (price != null && (best == null || price < best)) best = price;
  }
  return best;
}

function buildComparePriceColumns() {
  const seatCategory = document.getElementById("seatCategory").value;
  const dayType = document.getElementById("dayTypeSelect").value;
  const selectedValues = [...document.querySelectorAll("#durationFilters input:checked")].map(el => el.value);
  // 何も選んでいない場合は代表的なプラン（ナイトパック2種・24時間パック）をデフォルト表示する
  const durations = selectedValues.length
    ? DURATION_OPTIONS.filter(o => selectedValues.includes(o.value))
    : DURATION_OPTIONS.filter(o => ["night_pack_8", "night_pack_12", "24"].includes(o.value));
  return durations.map(d => ({
    key: `price:${d.value}`,
    label: d.label,
    selected: selectedValues.includes(d.value),
    isPrice: true,
    getValue: store => getDurationPriceForStore(store, d, seatCategory, dayType),
  }));
}

function buildCompareFacilityColumns(stores) {
  const selectedFacilities = getSelectedFacilities();
  const allFacilities = new Set(stores.flatMap(storeFacilities));
  const otherFacilities = [...allFacilities].filter(f => !selectedFacilities.includes(f)).sort();
  const ordered = [...selectedFacilities, ...otherFacilities];
  return ordered.map(f => ({
    key: `facility:${f}`,
    label: f,
    selected: selectedFacilities.includes(f),
    isPrice: false,
    getValue: store => storeFacilities(store).includes(f),
  }));
}

function renderCompare() {
  const section = document.getElementById("compareSection");
  const stores = [...compareSet.values()];
  if (stores.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  const priceColumns = buildComparePriceColumns();
  const facilityColumns = buildCompareFacilityColumns(stores);
  const columns = [...priceColumns, ...facilityColumns];

  let html = "<table class=\"compare-grid\"><thead><tr><th>店舗</th>";
  for (const col of columns) {
    html += `<th class="${col.selected ? "col-selected" : ""}">${escapeHtml(col.label)}</th>`;
  }
  html += "</tr></thead><tbody>";

  for (const s of stores) {
    html += `<tr><th class="row-store-name">${escapeHtml(s.store_name)}<br><small>${escapeHtml(s.pref)}${escapeHtml(s.city || "")}</small>${renderStoreSourceBadge(s)}</th>`;
    for (const col of columns) {
      const cls = col.selected ? "col-selected" : "";
      if (col.isPrice) {
        const price = col.getValue(s);
        html += `<td class="${cls}">${price != null ? "¥" + price.toLocaleString() : "<span class=\"na\">-</span>"}</td>`;
      } else {
        const has = col.getValue(s);
        html += `<td class="${cls} ${has ? "yes" : "no"}">${has ? "○" : "−"}</td>`;
      }
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  document.getElementById("compareTableWrap").innerHTML = html;

  const imageOnlyStores = stores.filter(s => s.price_source === "image" || s.price_source === "vision_ai");
  document.getElementById("comparePrices").innerHTML = imageOnlyStores.map(s => `
    <div class="price-card">
      <h3>${escapeHtml(s.store_name)}</h3>
      ${s.price_source === "vision_ai"
        ? `<p class="price-note ai-notice">⚠ 上の表の料金はAI（Gemini）が料金画像から自動で読み取った参考値です。誤りを含む可能性があるため、正式な料金は<a href="${s.price_image_url}" target="_blank" rel="noopener">元の料金画像</a>または公式サイトでご確認ください。</p>`
        : `<img src="${s.price_image_url}" alt="${escapeHtml(s.store_name)}の料金表" loading="lazy">
           ${s.price_ocr_text ? `<div class="ocr">${escapeHtml(s.price_ocr_text)}</div>` : "<p class=\"price-note\">OCRテキストなし</p>"}`
      }
    </div>
  `).join("");
}

function renderStoreSourceBadge(store) {
  if (store.price_source === "vision_ai") return ' <span class="ai-badge" title="AI画像読み取り（参考値）">AI</span>';
  if (store.price_source === "image") return ' <span class="ai-badge image-badge" title="料金は画像のみ。下部参照">画像</span>';
  return "";
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();
