// ===== マスタ定義 =====

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

const SEAT_OPTIONS = [
  { value: "open", label: "オープンシート" },
  { value: "booth", label: "ブース" },
  { value: "amuse", label: "アミューズシート" },
  { value: "private", label: "個室" },
];

// ナイトパックは8時間("8"キー)と12時間("A"キー)の2種類が別プランとして存在する。
const PLAN_OPTIONS = [
  { value: "night_pack_8", label: "ナイトパック(8時間)", shortLabel: "ナイト8h", type: "night_pack", hours: 8 },
  { value: "night_pack_12", label: "ナイトパック(12時間)", shortLabel: "ナイト12h", type: "night_pack", hours: 12 },
  { value: "3", label: "3時間パック", shortLabel: "3h", type: "hourly" },
  { value: "6", label: "6時間パック", shortLabel: "6h", type: "hourly" },
  { value: "9", label: "9時間パック", shortLabel: "9h", type: "hourly" },
  { value: "12", label: "12時間パック", shortLabel: "12h", type: "hourly" },
  { value: "15", label: "15時間パック", shortLabel: "15h", type: "hourly" },
  { value: "18", label: "18時間パック", shortLabel: "18h", type: "hourly" },
  { value: "21", label: "21時間パック", shortLabel: "21h", type: "hourly" },
  { value: "24", label: "24時間パック", shortLabel: "24h", type: "hourly" },
];

const TOP_N_CARDS = 50;

let allStores = [];
let flatRows = []; // ロング形式: 1行 = 店舗×座席タイプ×プラン
let viewMode = "card"; // "card" | "table" | "map"
let leafletMap = null; // Leafletマップインスタンス（地図モード初回表示時に遅延生成）
let mapMarkerLayer = null; // マーカーをまとめるレイヤ（再描画時にまとめて差し替える）

// ===== データ読み込み・フラット化 =====

async function init() {
  const res = await fetch("data/stores.json");
  allStores = await res.json();

  document.getElementById("updatedAt").textContent = new Date().toLocaleDateString("ja-JP");

  flatRows = buildFlatRows(allStores);

  setupExclusiveChipGroup("prefFilters", buildPrefOptions(), onFilterChange);
  setupExclusiveChipGroup("seatFilters", SEAT_OPTIONS, onFilterChange);
  setupExclusiveChipGroup("planFilters", PLAN_OPTIONS, onFilterChange);
  populateFacilityFilters();
  renderAll();

  document.getElementById("priceMax").addEventListener("input", onFilterChange);
  document.getElementById("keyword").addEventListener("input", onFilterChange);
  for (const radio of document.querySelectorAll('input[name="facilityMode"]')) {
    radio.addEventListener("change", onFilterChange);
  }

  document.getElementById("modeCardBtn").addEventListener("click", () => setViewMode("card"));
  document.getElementById("modeTableBtn").addEventListener("click", () => setViewMode("table"));
  document.getElementById("modeMapBtn").addEventListener("click", () => setViewMode("map"));
}

function getFacilityMode() {
  return document.querySelector('input[name="facilityMode"]:checked').value; // "and" | "or"
}

function buildPrefOptions() {
  const present = new Set(allStores.map(s => s.pref));
  const ordered = PREF_ORDER.filter(p => present.has(p));
  for (const p of present) if (!PREF_ORDER.includes(p)) ordered.push(p);
  return ordered.map(p => ({ value: p, label: p }));
}

function looksLikeMoney(str) {
  if (typeof str !== "string") return false;
  return /[¥$€]/.test(str) || /^[\d,]+$/.test(str.trim());
}

// データ衛生: ネスト(店舗→座席タイプ→プラン)を「孫1件=1レコード」に展開する。
// 比較値列は平日価格のみ。休日価格は表示用の付帯情報(weekend_surcharge)として保持する。
function buildFlatRows(stores) {
  const rows = [];
  for (const s of stores) {
    if (s.price_source !== "json" && s.price_source !== "vision_ai") continue;
    if (!s.price) continue;
    // 防衛フィルタ: 名称列が数字のみ、またはカテゴリ列に金額型の値が混入していたら除外
    if (/^\d+$/.test(s.store_name)) continue;
    if (looksLikeMoney(s.pref) || looksLikeMoney(s.city)) continue;

    for (const cat of s.price.categories) {
      const seatOpt = SEAT_OPTIONS.find(o => o.value === cat.category);
      if (!seatOpt || looksLikeMoney(seatOpt.label)) continue;

      for (const plan of PLAN_OPTIONS) {
        if (looksLikeMoney(plan.label)) continue;
        const weekdayPrice = getPlanPrice(cat, plan, "weekday");
        if (weekdayPrice == null) continue;
        const weekendPrice = getPlanPrice(cat, plan, "weekend");

        rows.push({
          store_code: s.store_code,
          store_name: s.store_name,
          pref: s.pref,
          city: s.city || "",
          access: s.access || [],
          detail_url: s.detail_url,
          status: s.price_source,
          facilities: storeFacilities(s),
          seat_value: seatOpt.value,
          seat_label: seatOpt.label,
          plan_value: plan.value,
          plan_label: plan.label,
          weekday_price: weekdayPrice,
          weekend_surcharge: weekendPrice != null ? weekendPrice - weekdayPrice : null,
        });
      }
    }
  }
  return rows;
}

function getPlanPrice(category, plan, dayType) {
  if (plan.type === "night_pack") {
    const pack = category.night_packs.find(np => np.hours === plan.hours);
    if (!pack) return null;
    const fee = dayType === "weekend" ? pack.weekend_taxfee : pack.weekday_taxfee;
    return fee != null ? fee : null;
  }
  const hourly = dayType === "weekend" ? category.weekend_hourly_taxfee : category.weekday_hourly_taxfee;
  return hourly[plan.value] != null ? hourly[plan.value] : null;
}

function storeFacilities(store) {
  return FACILITY_GROUPS.flatMap(g => store[g.key] || []);
}

// ===== 「すべて」排他ロジック付き複数選択チップ =====

function setupExclusiveChipGroup(containerId, options, onChange) {
  const wrap = document.getElementById(containerId);
  wrap.innerHTML = "";

  const allChip = document.createElement("label");
  allChip.className = "chip chip-all";
  allChip.innerHTML = `<input type="checkbox" value="__ALL__" checked> すべて`;
  wrap.appendChild(allChip);

  for (const opt of options) {
    const label = document.createElement("label");
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(opt.value)}"> ${escapeHtml(opt.label)}`;
    wrap.appendChild(label);
  }

  wrap.addEventListener("change", (e) => {
    const allCheckbox = wrap.querySelector('input[value="__ALL__"]');
    const individualCheckboxes = [...wrap.querySelectorAll('input:not([value="__ALL__"])')];

    if (e.target === allCheckbox) {
      if (allCheckbox.checked) individualCheckboxes.forEach(cb => { cb.checked = false; });
    } else if (e.target.checked) {
      allCheckbox.checked = false;
    }

    // 個別が1つも選ばれていない状態は「すべて」と同義なので、すべてに戻す
    if (!individualCheckboxes.some(cb => cb.checked)) allCheckbox.checked = true;

    onChange();
  });
}

function getSelectedValues(containerId) {
  const wrap = document.getElementById(containerId);
  const allChecked = wrap.querySelector('input[value="__ALL__"]').checked;
  if (allChecked) return []; // 空配列 = フィルタしない
  return [...wrap.querySelectorAll('input:checked')].map(cb => cb.value);
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
    label.querySelector("input").addEventListener("change", onFilterChange);
    wrap.appendChild(label);
  }
}

function getSelectedFacilities() {
  return [...document.querySelectorAll("#facilityFilters input:checked")].map(el => el.value);
}

function onFilterChange() {
  renderAll();
}

function setViewMode(mode) {
  viewMode = mode;
  document.getElementById("modeCardBtn").classList.toggle("active", mode === "card");
  document.getElementById("modeTableBtn").classList.toggle("active", mode === "table");
  document.getElementById("modeMapBtn").classList.toggle("active", mode === "map");
  document.getElementById("cardResults").classList.toggle("hidden", mode !== "card");
  document.getElementById("tableResults").classList.toggle("hidden", mode !== "table");
  document.getElementById("mapResults").classList.toggle("hidden", mode !== "map");
  renderResults();
}

// ===== 検索・比較ロジック（固定順）=====
// 1.比較軸(平日価格固定) 2.カテゴリ絞り込み 3.null除外 4.しきい値 5.昇順ソート 6.サマリー

function buildFilteredRows() {
  const prefs = getSelectedValues("prefFilters");
  const seats = getSelectedValues("seatFilters");
  const plans = getSelectedValues("planFilters");
  const facilities = getSelectedFacilities();
  const facilityMode = getFacilityMode();
  const keyword = document.getElementById("keyword").value.trim();
  const priceMaxRaw = document.getElementById("priceMax").value.trim();
  const priceMax = priceMaxRaw ? Number(priceMaxRaw) : null;

  let rows = flatRows.filter(r => {
    if (prefs.length && !prefs.includes(r.pref)) return false;
    if (seats.length && !seats.includes(r.seat_value)) return false;
    if (plans.length && !plans.includes(r.plan_value)) return false;
    if (keyword && !(r.store_name.includes(keyword) || r.city.includes(keyword))) return false;
    if (facilities.length) {
      const matchesFacilities = facilityMode === "or"
        ? facilities.some(f => r.facilities.includes(f))
        : facilities.every(f => r.facilities.includes(f));
      if (!matchesFacilities) return false;
    }
    if (r.weekday_price == null) return false; // 表示値null除外
    if (priceMax != null && r.weekday_price > priceMax) return false; // しきい値
    return true;
  });

  rows.sort((a, b) => a.weekday_price - b.weekday_price); // 昇順固定
  return rows;
}

function buildSummary(rows) {
  if (rows.length === 0) return { min: null, count: 0, avg: null };
  const prices = rows.map(r => r.weekday_price);
  const min = Math.min(...prices);
  const avg = Math.round(prices.reduce((a, b) => a + b, 0) / prices.length);
  return { min, count: rows.length, avg };
}

// 行(店舗×座席×プラン)を店舗単位に重複除去する。rowsは既に価格昇順なので、
// 各店舗の最初の出現＝その店舗内での最安行になる。
function dedupeStoresInOrder(rows) {
  const seen = new Set();
  const stores = [];
  for (const r of rows) {
    if (seen.has(r.store_code)) continue;
    seen.add(r.store_code);
    const store = allStores.find(s => s.store_code === r.store_code);
    if (store) stores.push(store);
  }
  return stores;
}

// ===== 条件チップ表示 =====

function renderConditionChips() {
  const chips = [];
  const addGroup = (containerId, label) => {
    const values = getSelectedValues(containerId);
    for (const v of values) {
      const optEl = document.querySelector(`#${containerId} input[value="${CSS.escape(v)}"]`);
      const text = optEl ? optEl.closest("label").textContent.trim() : v;
      chips.push({ text: `${label}:${text}`, clear: () => uncheckOne(containerId, v) });
    }
  };
  addGroup("prefFilters", "都道府県");
  addGroup("seatFilters", "座席");
  addGroup("planFilters", "プラン");
  const selectedFacilities = getSelectedFacilities();
  const facilityModeLabel = getFacilityMode() === "or" ? "または" : "かつ";
  for (const f of selectedFacilities) {
    const prefix = selectedFacilities.length > 1 ? `設備(${facilityModeLabel}):` : "設備:";
    chips.push({ text: `${prefix}${f}`, clear: () => uncheckFacility(f) });
  }
  const priceMax = document.getElementById("priceMax").value.trim();
  if (priceMax) chips.push({ text: `予算:¥${Number(priceMax).toLocaleString()}以下`, clear: () => { document.getElementById("priceMax").value = ""; onFilterChange(); } });
  const keyword = document.getElementById("keyword").value.trim();
  if (keyword) chips.push({ text: `キーワード:${keyword}`, clear: () => { document.getElementById("keyword").value = ""; onFilterChange(); } });

  const wrap = document.getElementById("conditionChips");
  if (chips.length === 0) {
    wrap.innerHTML = '<span class="no-condition">絞り込み条件なし（全件表示中）</span>';
    return;
  }
  wrap.innerHTML = chips.map((c, i) => `<span class="condition-chip" data-i="${i}">${escapeHtml(c.text)} <button type="button" aria-label="解除">×</button></span>`).join("");
  [...wrap.querySelectorAll(".condition-chip button")].forEach((btn, i) => {
    btn.addEventListener("click", () => chips[i].clear());
  });
}

function uncheckOne(containerId, value) {
  const wrap = document.getElementById(containerId);
  const cb = wrap.querySelector(`input[value="${CSS.escape(value)}"]`);
  if (cb) {
    cb.checked = false;
    cb.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function uncheckFacility(value) {
  const cb = document.querySelector(`#facilityFilters input[value="${CSS.escape(value)}"]`);
  if (cb) { cb.checked = false; onFilterChange(); }
}

// ===== 描画 =====

function renderAll() {
  renderConditionChips();
  renderResults();
}

function renderResults() {
  const rows = buildFilteredRows();
  const summary = buildSummary(rows);

  document.getElementById("summaryMin").textContent = summary.min != null ? `¥${summary.min.toLocaleString()}` : "—";
  document.getElementById("summaryCount").textContent = `${summary.count} 件`;
  document.getElementById("summaryAvg").textContent = summary.avg != null ? `¥${summary.avg.toLocaleString()}` : "—";

  if (viewMode === "card") {
    renderCardResults(rows);
  } else if (viewMode === "table") {
    renderTableResults(rows);
  } else {
    renderMapResults(rows);
  }
}

function renderCardResults(rows) {
  const top = rows.slice(0, TOP_N_CARDS);
  const wrap = document.getElementById("cardResults");
  if (top.length === 0) {
    wrap.innerHTML = '<p class="empty-note">条件に一致する結果がありません。</p>';
    return;
  }
  wrap.innerHTML = top.map((r, i) => `
    <div class="result-card-outer">
      <div class="result-card">
        <div class="rank-badge">${i + 1}</div>
        <div class="card-body">
          <h3>${escapeHtml(r.store_name)}${renderStatusBadge(r.status)}</h3>
          <p class="card-sub">${escapeHtml(r.pref)}${escapeHtml(r.city)}</p>
          ${r.access && r.access.length ? `<p class="card-access">🚶 ${r.access.map(a => escapeHtml(a)).join("／")}</p>` : ""}
          <div class="tag-list">
            <span class="tag tag-emphasis">${escapeHtml(r.seat_label)}</span>
            <span class="tag tag-emphasis">${escapeHtml(r.plan_label)}</span>
            ${r.facilities.slice(0, 4).map(f => `<span class="tag">${escapeHtml(f)}</span>`).join("")}
          </div>
        </div>
        <div class="card-price">
          <div class="price-main">¥${r.weekday_price.toLocaleString()}</div>
          ${r.weekend_surcharge != null && r.weekend_surcharge !== 0 ? `<div class="price-sub">休日 +¥${r.weekend_surcharge.toLocaleString()}</div>` : ""}
          <a href="${r.detail_url}" target="_blank" rel="noopener">公式サイト</a>
        </div>
      </div>
      <details class="card-detail">
        <summary>詳しく見る</summary>
        ${buildStoreDetailHtml(r.store_code)}
      </details>
    </div>
  `).join("");
}

// カードの「詳しく見る」展開部分: 住所・電話番号・全設備・座席タイプ別の料金表を表示する。
function buildStoreDetailHtml(storeCode) {
  const store = allStores.find(s => s.store_code === storeCode);
  if (!store) return "";

  const facilities = storeFacilities(store);
  const facilitiesHtml = facilities.length
    ? `<div class="tag-list">${facilities.map(f => `<span class="tag">${escapeHtml(f)}</span>`).join("")}</div>`
    : "<p class=\"empty-note\">設備情報なし</p>";

  let priceTableHtml = "<p class=\"empty-note\">料金情報なし</p>";
  if (store.price && store.price.categories.length) {
    const planSet = PLAN_OPTIONS.filter(p => ["night_pack_8", "night_pack_12", "3", "24"].includes(p.value));
    const rowsHtml = store.price.categories.map(cat => {
      const seatOpt = SEAT_OPTIONS.find(o => o.value === cat.category);
      const cells = planSet.map(plan => {
        const price = getPlanPrice(cat, plan, "weekday");
        return `<td>${price != null ? "¥" + price.toLocaleString() : "<span class=\"na\">-</span>"}</td>`;
      }).join("");
      return `<tr><th>${escapeHtml(seatOpt ? seatOpt.label : cat.category)}</th>${cells}</tr>`;
    }).join("");
    priceTableHtml = `
      <table class="card-detail-table">
        <thead><tr><th>座席</th>${planSet.map(p => `<th>${escapeHtml(p.shortLabel)}</th>`).join("")}</tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  }

  const aiNotice = store.price_source === "vision_ai"
    ? '<p class="price-note ai-notice">⚠ 料金はAI（Gemini）が料金画像から自動で読み取った参考値です。誤りを含む可能性があります。</p>'
    : "";

  return `
    <p class="card-detail-meta">${escapeHtml(store.address || "")}${store.tel ? " ／ TEL: " + escapeHtml(store.tel) : ""}</p>
    ${aiNotice}
    ${priceTableHtml}
    <p class="card-detail-label">設備・サービス</p>
    ${facilitiesHtml}
  `;
}

// 一覧表モード: 選択操作なしで、条件に合う店舗をそのまま比較表（縦=店舗、横=プラン別価格+設備）として表示する。
function renderTableResults(rows) {
  const stores = dedupeStoresInOrder(rows);
  document.getElementById("resultCount").textContent = `${stores.length} 件`;

  const wrap = document.getElementById("tableResults");
  if (stores.length === 0) {
    wrap.querySelector(".table-scroll").innerHTML = '<p class="empty-note">条件に一致する結果がありません。</p>';
    return;
  }

  const columns = [...buildComparePriceColumns(), ...buildCompareFacilityColumns()];

  let html = '<table class="compare-grid"><thead><tr><th>店舗</th>';
  for (const col of columns) {
    html += `<th class="${col.selected ? "col-selected" : ""}">${col.shortLabel ? escapeHtml(col.shortLabel) : escapeHtml(col.label)}</th>`;
  }
  html += "</tr></thead><tbody>";

  for (const s of stores) {
    html += `<tr><th class="row-store-name"><a href="${s.detail_url}" target="_blank" rel="noopener">${escapeHtml(s.store_name)}</a>${renderStatusBadge(s.price_source)}<br><small>${escapeHtml(s.pref)}${escapeHtml(s.city || "")}</small></th>`;
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
  wrap.querySelector(".table-scroll").innerHTML = html;
}

// ===== 地図モード =====

// 地図・ポップアップで表示するプラン群。ユーザーが選択していればそれを、未選択(すべて)なら
// 代表的な3プラン(ナイト8h/12h/24h)を既定表示にする（表モードの列既定と揃える）。
function getPlansForMap() {
  const planValues = getSelectedValues("planFilters");
  return planValues.length
    ? PLAN_OPTIONS.filter(p => planValues.includes(p.value))
    : PLAN_OPTIONS.filter(p => ["night_pack_8", "night_pack_12", "24"].includes(p.value));
}

// 店舗内の全座席カテゴリ（座席フィルタ選択時はそれに限定）から、指定プランの最安平日料金を求める。
function getStorePlanPrice(store, plan, seats) {
  if ((store.price_source !== "json" && store.price_source !== "vision_ai") || !store.price) return null;
  const categories = seats.length
    ? store.price.categories.filter(c => seats.includes(c.category))
    : store.price.categories;
  let best = null;
  for (const c of categories) {
    const price = getPlanPrice(c, plan, "weekday");
    if (price != null && (best == null || price < best)) best = price;
  }
  return best;
}

function renderMapResults(rows) {
  const stores = dedupeStoresInOrder(rows);
  document.getElementById("resultCount").textContent = `${stores.length} 件`;

  // 非表示divで初期化するとサイズが0になるため、地図モードに切替わってから初期化する。
  if (leafletMap === null) {
    leafletMap = L.map("leafletMap").setView([36.5, 138.0], 5); // 日本全体
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(leafletMap);
    mapMarkerLayer = L.layerGroup().addTo(leafletMap);
  }
  // 非表示中にリサイズされているとタイルがずれるため、表示直後にサイズ再計算する。
  setTimeout(() => leafletMap.invalidateSize(), 0);

  mapMarkerLayer.clearLayers();

  const plans = getPlansForMap();
  const seats = getSelectedValues("seatFilters");
  const bounds = [];

  for (const s of stores) {
    if (s.lat == null || s.lng == null) continue; // 座標が無い店舗はピンを立てない

    // 選択中プランごとの料金一覧を作る
    const priceEntries = [];
    for (const plan of plans) {
      const price = getStorePlanPrice(s, plan, seats);
      if (price != null) {
        priceEntries.push({ label: plan.shortLabel, price });
      }
    }

    // ピンには選択中の全プランをプラン名付きで縦に積んで表示する
    const pinHtml = priceEntries.length
      ? priceEntries.map(e =>
          `<span class="price-pin-row">` +
          `<span class="price-pin-plan">${escapeHtml(e.label)}</span>` +
          `<span class="price-pin-yen">¥${e.price.toLocaleString()}</span>` +
          `</span>`
        ).join("")
      : '<span class="price-pin-row"><span class="price-pin-yen">—</span></span>';
    const icon = L.divIcon({
      className: "price-pin-wrap",
      html: `<span class="price-pin">${pinHtml}</span>`,
      iconSize: null,
    });

    const priceHtml = priceEntries.length
      ? `<ul class="map-popup-prices">${priceEntries.map(e =>
          `<li>${escapeHtml(e.label)}: ¥${e.price.toLocaleString()}</li>`).join("")}</ul>`
      : '<p class="map-popup-noprice">選択中プランの料金情報なし</p>';
    const aiBadge = s.price_source === "vision_ai" ? '<span class="ai-badge" title="AI画像読み取り（参考値）">AI</span>' : "";
    const popupHtml = `
      <div class="map-popup">
        <strong>${escapeHtml(s.store_name)}</strong>${aiBadge}
        <div class="map-popup-sub">${escapeHtml(s.pref)}${escapeHtml(s.city || "")}</div>
        ${s.access && s.access.length ? `<div class="map-popup-access">🚶 ${s.access.map(a => escapeHtml(a)).join("／")}</div>` : ""}
        ${priceHtml}
        <a href="${s.detail_url}" target="_blank" rel="noopener">公式サイト</a>
      </div>
    `;

    L.marker([s.lat, s.lng], { icon }).bindPopup(popupHtml).addTo(mapMarkerLayer);
    bounds.push([s.lat, s.lng]);
  }

  if (bounds.length) {
    leafletMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
  }
}

function renderStatusBadge(status) {
  if (status === "vision_ai") return ' <span class="ai-badge" title="AI画像読み取り（参考値）">AI</span>';
  return "";
}

// ===== 一覧表の列定義（料金プラン列・設備列） =====

function buildComparePriceColumns() {
  const seats = getSelectedValues("seatFilters");
  const planValues = getSelectedValues("planFilters");
  const plans = planValues.length
    ? PLAN_OPTIONS.filter(p => planValues.includes(p.value))
    : PLAN_OPTIONS.filter(p => ["night_pack_8", "night_pack_12", "24"].includes(p.value));

  return plans.map(plan => ({
    label: plan.label,
    shortLabel: plan.shortLabel,
    selected: planValues.includes(plan.value),
    isPrice: true,
    getValue: store => getStorePlanPrice(store, plan, seats),
  }));
}

// 設備列は「選択中の設備」のみを表示する（未選択なら設備列は出さず、価格列だけのコンパクトな表にする）
function buildCompareFacilityColumns() {
  const selectedFacilities = getSelectedFacilities();
  return selectedFacilities.map(f => ({
    label: f,
    selected: true,
    isPrice: false,
    getValue: store => storeFacilities(store).includes(f),
  }));
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();
