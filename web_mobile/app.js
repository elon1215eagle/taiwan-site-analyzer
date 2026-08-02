const BUSINESS_TYPES = ["炸雞", "火鍋", "燒烤", "便當"];
const DEFAULT_COUNTY = "高雄市";
const COUNTIES = [
  "台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市",
  "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣",
  "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
  "台東縣", "澎湖縣", "金門縣", "連江縣"
];
const DISTRICTS_BY_COUNTY = globalThis.TAIWAN_DISTRICTS || {};
const ROLE_LABELS = { franchisee: "加盟主", developer: "區域開發人員", admin: "總部管理員" };
const STATUS_LABELS = {
  draft: "草稿", submitted: "已送審", needs_info: "待補件",
  evaluating: "評估中", closed: "已結案"
};
const state = {
  token: localStorage.getItem("gdo_token") || "",
  user: null,
  cases: [],
  users: [],
  currentReport: null,
  currentCase: null,
  refreshCandidateId: null,
  reverse: null
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

document.addEventListener("DOMContentLoaded", initialize);

async function initialize() {
  populateSelects();
  bindEvents();
  refreshIcons();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  if (!state.token) return showLogin();
  try {
    const response = await api("/api/auth/me");
    state.user = response.user;
    await enterApp();
  } catch {
    clearSession();
    showLogin();
  }
}

function populateSelects() {
  const businessOptions = BUSINESS_TYPES.map((item) => `<option value="${item}">${item}</option>`).join("");
  ["#businessSelect", "#reverseBusiness", "#caseBusiness"].forEach((id) => {
    $(id).innerHTML = businessOptions;
    $(id).value = "炸雞";
  });
  const countyOptions = `<option value="">請選擇</option>${COUNTIES.map((item) => `<option value="${item}">${item}</option>`).join("")}`;
  ["#addressCounty", "#countySelect", "#caseCounty"].forEach((id) => {
    $(id).innerHTML = countyOptions;
    $(id).value = DEFAULT_COUNTY;
  });
  populateDistrictSelect("#addressDistrict", DEFAULT_COUNTY, false);
  populateDistrictSelect("#districtInput", DEFAULT_COUNTY, true);
}

function populateDistrictSelect(selector, county, allowAll, selected = "") {
  const districts = DISTRICTS_BY_COUNTY[county] || [];
  const placeholder = allowAll ? "全部行政區（先排前三）" : "請選擇行政區";
  $(selector).innerHTML = `<option value="">${placeholder}</option>${districts
    .map((item) => `<option value="${item}">${item}</option>`)
    .join("")}`;
  if (selected && districts.includes(selected)) $(selector).value = selected;
}

function composeAddress() {
  return [$("#addressCounty").value, $("#addressDistrict").value, $("#addressDetail").value.trim()]
    .filter(Boolean)
    .join("");
}

function setAddressFields(address, fallbackCounty = "", fallbackDistrict = "") {
  const normalized = String(address || "").replaceAll("臺", "台").trim();
  const county = COUNTIES.find((item) => normalized.startsWith(item)) || fallbackCounty || DEFAULT_COUNTY;
  const afterCounty = normalized.startsWith(county) ? normalized.slice(county.length).trim() : normalized;
  const districts = DISTRICTS_BY_COUNTY[county] || [];
  const district = districts.find((item) => afterCounty.startsWith(item)) || fallbackDistrict || "";
  const detail = district && afterCounty.startsWith(district)
    ? afterCounty.slice(district.length).trim()
    : afterCounty;

  $("#addressCounty").value = county;
  populateDistrictSelect("#addressDistrict", county, false, district);
  $("#addressDetail").value = detail;
}

function bindEvents() {
  $("#loginForm").addEventListener("submit", login);
  $("#logoutButton").addEventListener("click", logout);
  $("#mobileMenuButton").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#addressCounty").addEventListener("change", () => {
    populateDistrictSelect("#addressDistrict", $("#addressCounty").value, false);
  });
  $("#countySelect").addEventListener("change", () => {
    populateDistrictSelect("#districtInput", $("#countySelect").value, true);
  });
  $("#addressForm").addEventListener("submit", analyzeAddress);
  $("#reverseForm").addEventListener("submit", runReverse);
  $("#newCaseButton").addEventListener("click", () => $("#caseForm").hidden = !$("#caseForm").hidden);
  $("#accountButton").addEventListener("click", () => $("#accountForm").hidden = !$("#accountForm").hidden);
  $("#accountForm").addEventListener("submit", createAccount);
  $("#caseForm").addEventListener("submit", createCase);
  $("#printButton").addEventListener("click", () => window.print());
}

async function login(event) {
  event.preventDefault();
  $("#loginError").textContent = "";
  setBusy(true, "正在登入");
  try {
    const response = await api("/api/auth/login", {
      method: "POST",
      body: {
        email: $("#loginEmail").value.trim(),
        password: $("#loginPassword").value
      },
      authenticate: false
    });
    state.token = response.token;
    state.user = response.user;
    localStorage.setItem("gdo_token", state.token);
    await enterApp();
  } catch (error) {
    $("#loginError").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function enterApp() {
  resetWorkspaceState();
  $("#loginView").hidden = true;
  $("#appView").hidden = false;
  $("#userName").textContent = state.user.name;
  $("#userRole").textContent = ROLE_LABELS[state.user.role] || state.user.role;
  $("#userAvatar").textContent = state.user.name.slice(0, 1).toUpperCase();
  $("#accountButton").hidden = state.user.role !== "admin";
  await Promise.all([loadCases(), loadNotifications()]);
  refreshIcons();
}

function showLogin() {
  $("#appView").hidden = true;
  $("#loginView").hidden = false;
  refreshIcons();
}

function logout() {
  clearSession();
  showLogin();
}

function clearSession() {
  state.token = "";
  state.user = null;
  resetWorkspaceState();
  localStorage.removeItem("gdo_token");
}

function resetWorkspaceState() {
  state.cases = [];
  state.users = [];
  state.currentReport = null;
  state.currentCase = null;
  state.refreshCandidateId = null;
  state.reverse = null;

  $("#caseList").innerHTML = "";
  $("#caseDetail").innerHTML = "";
  $("#notificationList").innerHTML = "";
  $("#notificationBadge").hidden = true;
  $("#notificationBadge").textContent = "0";
  $("#reportResult").hidden = true;
  $("#reportResult").innerHTML = "";
  $("#reverseResult").hidden = true;
  $("#reverseResult").innerHTML = "";
  $("#accountForm").hidden = true;
  $("#caseForm").hidden = true;

  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === "address"));
  $$(".view").forEach((view) => view.classList.toggle("active-view", view.id === "addressView"));
}

function switchView(viewName) {
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewName));
  $$(".view").forEach((view) => view.classList.remove("active-view"));
  $(`#${viewName}View`).classList.add("active-view");
  $(".sidebar").classList.remove("open");
  if (viewName === "cases") loadCases();
  if (viewName === "notifications") loadNotifications();
  refreshIcons();
}

async function analyzeAddress(event) {
  event.preventDefault();
  const payload = {
    location: composeAddress(),
    business_type: $("#businessSelect").value,
    monthly_rent: optionalNumber($("#rentInput").value),
    area_ping: optionalNumber($("#areaInput").value)
  };
  setBusy(true, "正在取得市場證據");
  try {
    const response = await api("/api/market-report", { method: "POST", body: payload });
    state.currentReport = response.json;
    renderReport(response.json);
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

function renderReport(report) {
  $("#addressState").hidden = true;
  $("#printButton").hidden = false;
  const score = report.scorecard;
  const property = report.property;
  const rings = report.geo_scope.ring_counts || [];
  $("#reportResult").hidden = false;
  $("#reportResult").innerHTML = `
    <section class="decision-band">
      <div class="score-gauge" style="--score:${number(score.overall_score)}">
        <div><strong>${display(score.overall_score)}</strong><span>選址初篩分數</span></div>
      </div>
      <div class="decision-copy">
        <span class="decision-chip">${escapeHtml(score.decision)}</span>
        <h2>${escapeHtml(report.summary.title)}</h2>
        <p>${escapeHtml(report.summary.conclusion)}</p>
      </div>
      <div class="confidence-block">
        <div class="confidence-head"><span>資料信心度</span><strong>${display(score.confidence_score)}%</strong></div>
        <div class="progress"><i style="width:${number(score.confidence_score)}%"></i></div>
        <small>${escapeHtml(report.summary.data_status)}</small>
      </div>
    </section>

    <section class="section">
      <div class="section-heading"><h2>店面與市場摘要</h2><p>正式分析半徑 ${report.radius_km} 公里</p></div>
      <div class="metric-grid">
        ${metric("月租金", money(property.monthly_rent), property.monthly_rent ? "候選物件輸入" : "待補資料")}
        ${metric("坪數", property.area_ping ? `${property.area_ping} 坪` : "待補資料", "候選物件輸入")}
        ${metric("每坪租金", property.rent_per_ping ? `${money(property.rent_per_ping)}／坪` : "待補資料", "月租金 ÷ 坪數")}
        ${metric("同類店家", report.summary.same_type_count === null ? "資料不足" : `${report.summary.same_type_count} 間`, `餐飲共 ${display(report.summary.all_food_count)} 間`)}
      </div>
    </section>

    <section class="section">
      <div class="section-heading"><h2>五大評分構面</h2><p>${escapeHtml(score.model_version)}</p></div>
      <div class="dimension-grid">
        ${score.dimensions.map(dimensionRow).join("")}
      </div>
      <p class="empty-note">${escapeHtml(score.score_notice)}</p>
    </section>

    <section class="section">
      <div class="section-heading"><h2>圈層與同業分布</h2><p>${escapeHtml(report.market_map.source)}</p></div>
      ${renderMap(report.market_map, report.business_type)}
      <div class="ring-grid">${rings.map(ringItem).join("")}</div>
    </section>

    <section class="section">
      <div class="section-heading"><h2>商圈活動指標</h2><p>道路車流不等於現場行人流量</p></div>
      <div class="metric-grid">
        ${metric("汽車觀測值", displayMetric(report.road_traffic.average_car_flow), "TDX VD")}
        ${metric("機車觀測值", displayMetric(report.road_traffic.average_motorcycle_flow), "TDX VD")}
        ${metric("平均速度", displayMetric(report.road_traffic.average_speed, " km/h"), `${report.road_traffic.station_count} 個測站`)}
        ${metric("最近測站", displayMetric(report.road_traffic.nearest_station_distance_km, " km"), report.road_traffic.status)}
      </div>
      <p class="empty-note">${escapeHtml(report.road_traffic.interpretation)}</p>
    </section>

    <section class="section">
      <div class="section-heading"><h2>市場客單價帶</h2><p>非實際交易客單價</p></div>
      ${report.average_ticket_distribution.available
        ? `<div class="metric-grid">${metric("市場價格帶", report.average_ticket_distribution.position, "公開價位證據")}</div>`
        : `<p class="empty-note">未取得公開菜單價格或價位等級，本次不產生客單價數字。</p>`}
      <p>${escapeHtml(report.average_ticket_distribution.basis)}</p>
    </section>

    <section class="section">
      <div class="section-heading"><h2>營收情境推估</h2><p>非真實營收或實際月營收分布</p></div>
      ${renderRevenue(report.revenue_scenarios)}
    </section>

    <section class="section">
      <div class="section-heading"><h2>主要同類競品</h2><p>依競爭威脅排序，最多 3 家</p></div>
      ${report.top_competitors.length
        ? `<div class="competitor-grid">${report.top_competitors.map(competitorCard).join("")}</div>`
        : `<p class="empty-note">正式半徑內未取得足夠的直接競品證據。</p>`}
    </section>

    <section class="section">
      <div class="section-heading"><h2>相鄰替代競品</h2><p>不補入同類競品前三名</p></div>
      ${report.adjacent_competitors.length
        ? `<div class="competitor-grid">${report.adjacent_competitors.map(competitorCard).join("")}</div>`
        : `<p class="empty-note">未列出相鄰替代競品。</p>`}
    </section>

    <section class="section">
      <div class="section-heading"><h2>好評、差評與市場缺口</h2><p>${escapeHtml(report.review_summary.data_status)}</p></div>
      <div class="metric-grid">
        ${textMetric("好評主題", report.review_summary.positive)}
        ${textMetric("差評主題", report.review_summary.negative)}
      </div>
    </section>

    <section class="section">
      <div class="section-heading"><h2>資料來源與版本</h2><p>${formatDate(report.analyzed_at)}</p></div>
      ${evidenceTable(report)}
      <p class="empty-note">分析識別碼 ${escapeHtml(report.analysis_id)}｜資料截至 ${escapeHtml(report.data_as_of)}｜契約 ${escapeHtml(report.contract_version)}</p>
    </section>

    <div class="save-strip">
      <select id="saveCaseSelect" aria-label="選擇案件">
        <option value="">選擇要保存的選址案件</option>
        ${state.cases.map((item) => `<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("")}
      </select>
      <button id="saveCandidateButton" class="button primary" type="button"><i data-lucide="save"></i>${state.refreshCandidateId ? "保存新版報告" : "保存候選店面"}</button>
    </div>
  `;
  $("#saveCandidateButton").addEventListener("click", saveCurrentCandidate);
  refreshIcons();
}

function dimensionRow(item) {
  const score = item.available ? number(item.score) : 0;
  return `
    <div class="dimension-row">
      <span>${escapeHtml(item.label)} <small>${item.weight}%</small></span>
      <div class="dimension-track"><i style="width:${score}%"></i></div>
      <strong>${item.available ? score : "—"}</strong>
    </div>`;
}

function renderMap(map, businessType) {
  if (map.center_lat === null || map.center_lon === null) {
    return `<p class="empty-note">候選地址座標未取得，無法呈現地圖。</p>`;
  }
  const lat = Number(map.center_lat);
  const lon = Number(map.center_lon);
  const delta = 0.025;
  const bbox = [lon - delta, lat - delta, lon + delta, lat + delta].join(",");
  const url = `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${lat},${lon}`;
  return `
    <div class="map-shell">
      <iframe title="候選地址周邊地圖" src="${url}" loading="lazy"></iframe>
      ${map.points.map((point) => `<span class="map-dot ${point.kind === "direct" ? "direct" : ""}" style="left:${number(point.x)}%;top:${number(point.y)}%" title="${escapeHtml(point.name)}"></span>`).join("")}
      <span class="map-pin"><i data-lucide="map-pin"></i></span>
      <div class="map-legend"><span>${escapeHtml(businessType)}</span><span>其他餐飲</span></div>
    </div>`;
}

function ringItem(item) {
  return `<div class="ring-item"><span>${item.radius_km} 公里</span><strong>${item.same_type_count} 間同類</strong><small>${item.all_food_count} 間餐飲</small></div>`;
}

function renderRevenue(revenue) {
  if (!revenue.available) return `<p class="empty-note">${escapeHtml(revenue.basis)}</p>`;
  return `
    <div class="scenario-grid">
      ${revenue.scenarios.map((item) => `
        <article class="scenario">
          <span>${escapeHtml(item.label)}情境</span>
          <strong>${money(item.monthly_revenue)}</strong>
          <p>日訂單 ${item.daily_orders} 筆</p>
          <p>客單 ${money(item.ticket)}</p>
          <p>每月 ${item.monthly_operating_days} 個營業日</p>
        </article>`).join("")}
    </div>
    <p class="empty-note">${escapeHtml(revenue.basis)}${revenue.onsite_flow_included ? "" : " 尚未納入現場行人流量，信心度已降低。"}</p>`;
}

function competitorCard(item) {
  return `
    <article class="competitor-card">
      <span class="rank">${item.rank}</span>
      <h3>${escapeHtml(item.name)}</h3>
      <div class="tag-row">
        <span class="tag gold">${escapeHtml(item.competitor_level)}</span>
        <span class="tag">評分 ${display(item.rating)}</span>
        <span class="tag">評論 ${display(item.user_ratings_total)}</span>
        <span class="tag red">${item.distance_km === null ? "距離不足" : `${item.distance_km} km`}</span>
      </div>
      <small>${escapeHtml(item.address || "地址未取得")}</small>
      <p><strong>競爭優勢：</strong>${escapeHtml(item.strength)}</p>
      <p><strong>主要風險：</strong>${escapeHtml(item.risk)}</p>
      ${reviewBlock("好評", item.review_positive, item.positive_snippets)}
      ${reviewBlock("差評", item.review_negative, item.negative_snippets)}
      ${item.maps_url ? `<a class="text-link" href="${escapeHtml(item.maps_url)}" target="_blank" rel="noreferrer"><i data-lucide="external-link"></i>開啟地圖</a>` : ""}
    </article>`;
}

function reviewBlock(title, themes, snippets) {
  if ((!themes || !themes.length) && (!snippets || !snippets.length)) return "";
  return `
    <p><strong>${title}：</strong>${(themes || []).map(escapeHtml).join("；")}</p>
    ${(snippets || []).map((text) => `<div class="quote">「${escapeHtml(text)}」</div>`).join("")}`;
}

function textMetric(title, items) {
  return `<article class="metric"><span>${escapeHtml(title)}</span><strong>${items.length ? items.map(escapeHtml).join("、") : "資料不足"}</strong><small>${items.length ? "依評論文字彙整" : "未套用通用模板"}</small></article>`;
}

function evidenceTable(report) {
  const rows = Object.entries(report.evidence_status.sources).map(([key, item]) => `
    <tr>
      <td>${escapeHtml(sourceLabel(key))}</td>
      <td><span class="status-dot ${item.status}"></span>${escapeHtml(item.status_label)}</td>
      <td>${escapeHtml(item.source)}</td>
      <td>${escapeHtml(item.retrieved_at || "—")}</td>
    </tr>`).join("");
  return `<div class="table-scroll"><table class="evidence-table"><thead><tr><th>證據</th><th>狀態</th><th>來源</th><th>取得時間</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function saveCurrentCandidate() {
  if (state.refreshCandidateId) {
    setBusy(true, "正在保存新版報告");
    try {
      const response = await api("/api/workspace/candidates/report", {
        method: "POST",
        body: { candidate_id: state.refreshCandidateId, report: state.currentReport }
      });
      state.refreshCandidateId = null;
      toast(`已保存第 ${response.version.version_number} 版報告。`);
      await loadCases();
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
    return;
  }
  const caseId = Number($("#saveCaseSelect").value);
  if (!caseId) return toast("請先選擇案件。");
  setBusy(true, "正在保存候選店面");
  try {
    await api("/api/workspace/candidates", {
      method: "POST",
      body: {
        case_id: caseId,
        address: state.currentReport.input_location,
        monthly_rent: state.currentReport.property.monthly_rent,
        area_ping: state.currentReport.property.area_ping,
        report: state.currentReport
      }
    });
    await loadCases();
    toast("候選店面已保存。");
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

async function runReverse(event) {
  event.preventDefault();
  const payload = {
    business_type: $("#reverseBusiness").value,
    county: $("#countySelect").value,
    district: $("#districtInput").value
  };
  if (!payload.county) return toast("請選擇縣市。");
  setBusy(true, "正在排名候選區域");
  try {
    const response = await api("/api/recommend", { method: "POST", body: payload });
    state.reverse = response.json;
    renderReverse(response.json);
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

function renderReverse(data) {
  $("#reverseState").hidden = true;
  $("#reverseResult").hidden = false;
  const isDistrict = data.stage === "district";
  $("#reverseResult").innerHTML = `
    <section class="section">
      <div class="section-heading">
        <h2>${isDistrict ? "行政區優先排序" : `${escapeHtml(data.geo_scope.district)}道路熱點`}</h2>
        <p>${escapeHtml(data.overall_conclusion)}</p>
      </div>
      ${data.recommendations.length
        ? `<div class="reverse-grid">${data.recommendations.map((item) => reverseCard(item, isDistrict)).join("")}</div>`
        : `<p class="empty-note">${escapeHtml(data.warnings.join("；") || "資料不足，未產生推薦。")}</p>`}
    </section>
    ${data.warnings.length ? `<p class="empty-note">${data.warnings.map(escapeHtml).join("；")}</p>` : ""}
  `;
  $$(".drill-area").forEach((button) => button.addEventListener("click", () => {
    $("#districtInput").value = button.dataset.district;
    $("#reverseForm").requestSubmit();
  }));
  $$(".analyze-area").forEach((button) => button.addEventListener("click", () => {
    setAddressFields(button.dataset.location, data.geo_scope?.county, data.geo_scope?.district);
    $("#businessSelect").value = data.business_type;
    switchView("address");
    $("#addressDetail").focus();
  }));
  refreshIcons();
}

function reverseCard(item, isDistrict) {
  return `
    <article class="reverse-card">
      <small>No.${item.rank}｜信心度 ${display(item.confidence_score)}%</small>
      <h3>${escapeHtml(item.area)}</h3>
      <div class="reverse-score"><strong>${item.fit_score}</strong><span>／100</span></div>
      <p>${escapeHtml(item.reason)}</p>
      ${item.population ? `<p>人口證據：${Number(item.population).toLocaleString("zh-TW")} 人</p>` : ""}
      <div class="reverse-actions">
        ${isDistrict
          ? `<button class="button primary small drill-area" type="button" data-district="${escapeHtml(item.area)}"><i data-lucide="zoom-in"></i>查看道路熱點</button>`
          : `<button class="button primary small analyze-area" type="button" data-location="${escapeHtml(item.candidate_location)}"><i data-lucide="map-pin"></i>帶入地址分析</button>`}
        ${item.maps_url ? `<a class="button secondary small" href="${escapeHtml(item.maps_url)}" target="_blank" rel="noreferrer"><i data-lucide="map"></i>地圖</a>` : ""}
      </div>
    </article>`;
}

async function loadCases() {
  if (!state.token) return;
  try {
    const response = await api("/api/workspace/cases");
    state.cases = response.cases;
    renderCases();
  } catch (error) {
    toast(error.message);
  }
}

function renderCases() {
  const container = $("#caseList");
  if (!state.cases.length) {
    container.innerHTML = `<p class="empty-note">目前沒有選址案件。</p>`;
    return;
  }
  container.innerHTML = state.cases.map((item) => `
    <article class="case-card">
      <header><h3>${escapeHtml(item.title)}</h3><span class="status-chip">${escapeHtml(STATUS_LABELS[item.status] || item.status)}</span></header>
      <p>${escapeHtml(item.business_type)}｜${escapeHtml(item.county || "未指定縣市")}</p>
      <p>${item.candidate_count} 個候選店面｜負責人 ${escapeHtml(item.owner_name)}</p>
      <button class="button secondary small open-case" type="button" data-case-id="${item.id}"><i data-lucide="folder-open"></i>開啟案件</button>
    </article>`).join("");
  $$(".open-case").forEach((button) => button.addEventListener("click", () => openCase(Number(button.dataset.caseId))));
  refreshIcons();
}

async function createCase(event) {
  event.preventDefault();
  try {
    await api("/api/workspace/cases", {
      method: "POST",
      body: {
        title: $("#caseTitle").value.trim(),
        business_type: $("#caseBusiness").value,
        county: $("#caseCounty").value
      }
    });
    event.target.reset();
    $("#caseForm").hidden = true;
    await loadCases();
    toast("選址案件已建立。");
  } catch (error) {
    toast(error.message);
  }
}

async function createAccount(event) {
  event.preventDefault();
  try {
    await api("/api/workspace/users", {
      method: "POST",
      body: {
        name: $("#accountName").value.trim(),
        email: $("#accountEmail").value.trim(),
        role: $("#accountRole").value,
        password: $("#accountPassword").value
      }
    });
    event.target.reset();
    $("#accountForm").hidden = true;
    await loadUsers();
    toast("帳號已建立。");
  } catch (error) {
    toast(error.message);
  }
}

async function loadUsers() {
  if (state.user?.role !== "admin") return;
  const response = await api("/api/workspace/users");
  state.users = response.users;
}

async function openCase(caseId) {
  setBusy(true, "正在開啟案件");
  try {
    await loadUsers();
    const response = await api(`/api/workspace/cases/${caseId}`);
    state.currentCase = response.case;
    renderCaseDetail(response.case);
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

function renderCaseDetail(caseData) {
  const candidates = caseData.candidates || [];
  $("#caseDetail").innerHTML = `
    <section class="case-detail">
      <div class="case-detail-header">
        <div><h2>${escapeHtml(caseData.title)}</h2><p>${escapeHtml(caseData.business_type)}｜${escapeHtml(STATUS_LABELS[caseData.status] || caseData.status)}</p></div>
        <button class="icon-button close-detail" title="關閉案件" aria-label="關閉案件"><i data-lucide="x"></i></button>
      </div>
      <div class="candidate-list">
        ${candidates.length ? candidates.map(candidateRow).join("") : `<p class="empty-note">此案件尚未保存候選店面。</p>`}
      </div>
      ${assignmentForm(caseData)}
      ${candidates.length ? `<button id="compareCandidates" class="button secondary" type="button"><i data-lucide="columns-3"></i>比較已勾選店面</button>` : ""}
      <div id="comparisonResult"></div>
      ${candidates.length ? surveyForm(candidates) : ""}
      ${reviewForm(caseData)}
      ${caseData.comments.length ? `<section class="section"><div class="section-heading"><h2>案件意見</h2></div>${caseData.comments.map((item) => `<p><strong>${escapeHtml(item.author_name)}</strong>：${escapeHtml(item.body)} <small>${formatDate(item.created_at)}</small></p>`).join("")}</section>` : ""}
    </section>`;
  $(".close-detail").addEventListener("click", () => $("#caseDetail").innerHTML = "");
  if ($("#compareCandidates")) $("#compareCandidates").addEventListener("click", compareCandidates);
  if ($("#assignmentForm")) $("#assignmentForm").addEventListener("submit", assignCase);
  $$(".refresh-candidate").forEach((button) => button.addEventListener("click", () => {
    const candidate = state.currentCase.candidates.find((item) => item.id === Number(button.dataset.id));
    if (!candidate) return;
    state.refreshCandidateId = candidate.id;
    setAddressFields(candidate.address);
    $("#rentInput").value = candidate.monthly_rent ?? "";
    $("#areaInput").value = candidate.area_ping ?? "";
    $("#businessSelect").value = state.currentCase.business_type;
    switchView("address");
    $("#addressDetail").focus();
  }));
  if ($("#surveyForm")) $("#surveyForm").addEventListener("submit", saveSurvey);
  if ($("#reviewForm")) $("#reviewForm").addEventListener("submit", updateCaseStatus);
  refreshIcons();
  $("#caseDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function assignCase(event) {
  event.preventDefault();
  try {
    const response = await api("/api/workspace/assign", {
      method: "POST",
      body: {
        case_id: state.currentCase.id,
        developer_user_id: Number($("#developerAssignment").value)
      }
    });
    state.currentCase = response.case;
    renderCaseDetail(response.case);
    await loadCases();
    toast("案件已指派。");
  } catch (error) {
    toast(error.message);
  }
}

function assignmentForm(caseData) {
  if (state.user.role !== "admin") return "";
  const developers = state.users.filter((item) => item.role === "developer" && item.active);
  if (!developers.length) return `<p class="empty-note">尚未建立區域開發人員帳號。</p>`;
  return `
    <form id="assignmentForm" class="review-form">
      <label>區域開發人員<select id="developerAssignment">${developers.map((item) => `<option value="${item.id}" ${item.id === caseData.developer_user_id ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select></label>
      <span></span>
      <button class="button secondary" type="submit"><i data-lucide="user-check"></i>指派案件</button>
    </form>`;
}

function candidateRow(item) {
  const score = item.report?.scorecard?.overall_score;
  const confidence = item.report?.scorecard?.confidence_score;
  return `
    <div class="candidate-row">
      <input class="candidate-check" type="checkbox" value="${item.id}" aria-label="選取 ${escapeHtml(item.address)}">
      <div><strong>${escapeHtml(item.address)}</strong><small>${escapeHtml(item.report?.scorecard?.decision || "尚無報告")}</small></div>
      <span>分數<br><strong>${display(score)}</strong></span>
      <span>信心度<br><strong>${display(confidence)}%</strong></span>
      <span>每坪租金<br><strong>${item.report?.property?.rent_per_ping ? money(item.report.property.rent_per_ping) : "—"}</strong></span>
      <button class="icon-button refresh-candidate" data-id="${item.id}" type="button" title="重新分析" aria-label="重新分析 ${escapeHtml(item.address)}"><i data-lucide="refresh-cw"></i></button>
    </div>`;
}

function compareCandidates() {
  const ids = $$(".candidate-check:checked").map((item) => Number(item.value)).slice(0, 3);
  if (ids.length < 2) return toast("請勾選 2 至 3 個候選店面。");
  const selected = state.currentCase.candidates.filter((item) => ids.includes(item.id));
  const rows = [
    ["地址", (item) => item.address],
    ["篩選結論", (item) => item.report?.scorecard?.decision],
    ["綜合分數", (item) => item.report?.scorecard?.overall_score],
    ["資料信心度", (item) => `${display(item.report?.scorecard?.confidence_score)}%`],
    ["月租金", (item) => money(item.monthly_rent)],
    ["坪數", (item) => item.area_ping ? `${item.area_ping} 坪` : "—"],
    ["每坪租金", (item) => money(item.report?.property?.rent_per_ping)],
    ["同類競品", (item) => `${display(item.report?.summary?.same_type_count)} 間`],
    ["市場客單價帶", (item) => item.report?.average_ticket_distribution?.position || "資料不足"],
    ["基準營收情境", (item) => money(item.report?.revenue_scenarios?.scenarios?.[1]?.monthly_revenue)]
  ];
  $("#comparisonResult").innerHTML = `
    <section class="section"><div class="section-heading"><h2>候選店面比較</h2><p>最多 3 個候選店面</p></div>
    <div class="table-scroll"><table class="compare-table">
      <thead><tr><th>指標</th>${selected.map((item) => `<th>${escapeHtml(item.address)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(([label, getter]) => `<tr><th>${label}</th>${selected.map((item) => `<td>${escapeHtml(getter(item) ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div></section>`;
}

function surveyForm(candidates) {
  return `
    <form id="surveyForm" class="survey-form">
      <label>候選店面<select id="surveyCandidate">${candidates.map((item) => `<option value="${item.id}">${escapeHtml(item.address)}</option>`).join("")}</select></label>
      <label>現勘紀錄<textarea id="surveyNotes" placeholder="照片以外的現場觀察"></textarea></label>
      <label>單次人流數<input id="surveyCount" type="number" min="0" inputmode="numeric"></label>
      <label>照片<input id="surveyPhoto" type="file" accept="image/*"></label>
      <button class="button primary" type="submit"><i data-lucide="clipboard-check"></i>保存現勘</button>
    </form>`;
}

async function saveSurvey(event) {
  event.preventDefault();
  try {
    const candidateId = Number($("#surveyCandidate").value);
    const onsiteCount = optionalNumber($("#surveyCount").value);
    const photos = [];
    const file = $("#surveyPhoto").files[0];
    if (file) photos.push(await fileToDataUrl(file));
    await api("/api/workspace/surveys", {
      method: "POST",
      body: {
        candidate_id: candidateId,
        onsite_count: onsiteCount,
        notes: $("#surveyNotes").value.trim(),
        photos
      }
    });
    const candidate = state.currentCase.candidates.find((item) => item.id === candidateId);
    if (candidate && onsiteCount !== null) {
      const reportResponse = await api("/api/market-report", {
        method: "POST",
        body: {
          location: candidate.address,
          business_type: state.currentCase.business_type,
          monthly_rent: candidate.monthly_rent,
          area_ping: candidate.area_ping,
          onsite_count: onsiteCount
        }
      });
      await api("/api/workspace/candidates/report", {
        method: "POST",
        body: { candidate_id: candidateId, report: reportResponse.json }
      });
    }
    event.target.reset();
    await openCase(state.currentCase.id);
    toast("現勘紀錄已保存，報告信心度已更新。");
  } catch (error) {
    toast(error.message);
  }
}

function reviewForm(caseData) {
  const actions = [];
  if (caseData.status === "draft") actions.push(["submit", "送交評估"]);
  if (state.user.role !== "franchisee") {
    actions.push(["evaluate", "繼續評估"], ["needs_info", "要求補件"]);
  }
  if (state.user.role === "admin") actions.push(["close", "結案"]);
  if (!actions.length) return "";
  return `
    <form id="reviewForm" class="review-form">
      <label>案件動作<select id="reviewAction">${actions.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></label>
      <label>處理意見<textarea id="reviewComment"></textarea></label>
      <button class="button warning" type="submit"><i data-lucide="send"></i>更新案件</button>
    </form>`;
}

async function updateCaseStatus(event) {
  event.preventDefault();
  try {
    const response = await api("/api/workspace/review", {
      method: "POST",
      body: {
        case_id: state.currentCase.id,
        action: $("#reviewAction").value,
        comment: $("#reviewComment").value.trim()
      }
    });
    state.currentCase = response.case;
    renderCaseDetail(response.case);
    await loadCases();
    toast("案件狀態已更新。");
  } catch (error) {
    toast(error.message);
  }
}

async function loadNotifications() {
  if (!state.token) return;
  try {
    const response = await api("/api/workspace/notifications");
    renderNotifications(response.notifications);
  } catch (error) {
    toast(error.message);
  }
}

function renderNotifications(items) {
  const unread = items.filter((item) => !item.read_at).length;
  $("#notificationBadge").hidden = unread === 0;
  $("#notificationBadge").textContent = unread;
  $("#notificationList").innerHTML = items.length
    ? items.map((item) => `
      <article class="notification ${item.read_at ? "" : "unread"}">
        <div><p>${escapeHtml(item.message)}</p><small>${formatDate(item.created_at)}</small></div>
        ${item.read_at ? "" : `<button class="button secondary small read-notification" data-id="${item.id}" type="button">標記已讀</button>`}
      </article>`).join("")
    : `<p class="empty-note">目前沒有站內通知。</p>`;
  $$(".read-notification").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/workspace/notifications/read", {
      method: "POST",
      body: { notification_id: Number(button.dataset.id) }
    });
    await loadNotifications();
  }));
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (options.authenticate !== false && state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/auth/login") {
      clearSession();
      showLogin();
    }
    throw new Error(data.message || "系統暫時無法完成操作。");
  }
  return data;
}

function metric(label, value, note) {
  return `<article class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;
}

function sourceLabel(value) {
  return ({ geocoding: "地址定位", restaurants: "店家市場", reviews: "競品評論", traffic: "道路車流" })[value] || value;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "—";
  return `NT$ ${Math.round(Number(value)).toLocaleString("zh-TW")}`;
}

function display(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function displayMetric(value, suffix = "") {
  return value === null || value === undefined ? "資料不足" : `${value}${suffix}`;
}

function number(value) {
  const result = Number(value);
  return Number.isFinite(result) ? result : 0;
}

function optionalNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-TW", { hour12: false });
}

function fileToDataUrl(file) {
  if (file.size > 1_800_000) return Promise.reject(new Error("單張照片請小於 1.8 MB。"));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("照片讀取失敗。"));
    reader.readAsDataURL(file);
  });
}

function setBusy(active, message = "") {
  $("#busyOverlay").hidden = !active;
  if (active && message) $("#busyOverlay strong").textContent = message;
}

let toastTimer;
function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => $("#toast").hidden = true, 3800);
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
