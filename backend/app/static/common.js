
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? "{}" : JSON.stringify(body),
  });
  const t = await r.text();
  let data;
  try { data = JSON.parse(t); } catch { data = { 原文: t }; }
  if (!r.ok) throw new Error((data && (data.错误 || data.detail)) || t || String(r.status));
  return data;
}
function 行(html) {
  const tr = document.createElement("tr");
  tr.innerHTML = html;
  return tr;
}
function 徽章(文, 类) {
  const tone = 类 || 命运色(文);
  return `<span class="徽章 ${tone || ""}">${安全文本(文)}</span>`;
}
function 空态(文) { return `<p class="说明">${安全文本(文)}</p>`; }
function 安全文本(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
function 命运色(f) {
  if (["已入栏", "在栏", "已汇总", "对齐"].includes(f)) return "ok";
  if (["已坏点", "撕裂"].includes(f)) return "warn";
  if (["相符"].includes(f)) return "ok";
  if (["封印缺失", "指纹不符", "同票指纹异", "水位断票", "封后混入", "证据根不符", "占位缺失"].includes(f)) return "warn";
  return "";
}
function 短指纹(fp) {
  const s = String(fp || "");
  return s ? s.slice(0, 12) + "…" : "—";
}
function 空封状态徽章(态) {
  const ok = 态 === "相符";
  return 徽章(态 || "未知", ok ? "ok" : "warn");
}
function 空封裁决条HTML(裁) {
  if (!裁) return 空态("空封裁决暂不可用。");
  const ok = !!裁["裁决对齐"];
  const tone = ok ? "ok" : "warn";
  const 水 = 裁["水位对账"] || {};
  return `<div class="只读框 ${tone === "ok" ? "上距8" : ""}">
    ${徽章(ok ? "空封裁决·相符（绿）" : "空封裁决·异常（红）", ok ? "ok" : "warn")}
    &nbsp;<b>${安全文本(裁["接口"] || "空栏封印裁决")}</b>
    · 形态 <span class="铜字">${安全文本(裁["形态"] || "甲")}</span>
    · 空封 ${裁["空封数"] ?? 0} · 相符 ${裁["相符数"] ?? 0} · 异常 ${裁["异常数"] ?? 0}
    · 水位对账 ${水["对齐"] ? "同票齐" : "不平"}
    <div class="说明 上距8">${安全文本(裁["说明"] || "")}</div>
  </div>`;
}
async function 挂载空封裁决(elId) {
  const el = document.getElementById(elId);
  if (!el) return null;
  try {
    const 裁 = await getJSON("/api/空栏封印/裁决");
    el.innerHTML = 空封裁决条HTML(裁);
    return 裁;
  } catch (e) {
    el.innerHTML = 空态("空封裁决读取失败：" + e);
    return null;
  }
}
function 渲染水位(el, o) {
  if (!el) return;
  el.innerHTML = "";
  for (const [标, 键] of [["观测报文","观测报文"],["在栏","在栏"],["站点汇总","站点汇总"],["坏点","坏点"]]) {
    const d = document.createElement("div");
    d.className = "水卡";
    d.innerHTML = `<div class="数">${o[键] ?? 0}</div><div class="标">${标}</div>`;
    el.appendChild(d);
  }
}
function 渲染门槛(el, 规) {
  if (!el) return;
  const r = 规 || {};
  el.innerHTML = `
    <div class="门槛卡"><div class="k">当前栏</div><div class="v">${安全文本(r["当前栏号"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">PM25 上限</div><div class="v">${安全文本(r["PM25上限"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">PM25 下限</div><div class="v">${安全文本(r["PM25下限"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">标定偏移</div><div class="v">${安全文本(r["标定偏移上限"] || "—")}</div></div>
  `;
}
function 渲染批次表(el, rows, cols) {
  if (!el) return;
  if (!rows || !rows.length) {
    el.innerHTML = `<tr><td colspan="${cols.length}">${空态("尚无批次。")}</td></tr>`;
    return;
  }
  el.innerHTML = "";
  for (const r of rows) {
    const cells = cols.map((c) => `<td>${安全文本(r[c])}</td>`).join("");
    el.appendChild(行(cells));
  }
}
function 装载摘要文(r) {
  if (!r) return "";
  return `入流 ${r["入流"]||0} · 入栏 ${r["入栏"]||0} · 坏点 ${r["坏点"]||0} · 驳回 ${r["驳回"]||0}`;
}
function 结栏摘要文(r) {
  if (!r) return "";
  return `栏 ${r["栏号"]||"?"} · 汇总 ${r["汇总数"]||0} · 缓冲消耗 ${r["缓冲消耗"]||0}`;
}
function 贯验摘要文(r) {
  if (!r) return "";
  return `${r["是否对齐"]?"对齐":"撕裂"} · 在栏 ${r["在栏"]} · 汇总报文 ${r["汇总报文"]} · 坏点 ${r["坏点"]}`;
}
function 填命运字典(el, dict) {
  if (!el || !dict) return;
  el.innerHTML = Object.entries(dict).map(([k, v]) =>
    `<div class="只读框 上距8"><b class="铜字">${安全文本(k)}</b> · ${安全文本(v)}</div>`
  ).join("");
}
window.探栏 = {
  getJSON, postJSON, 行, 徽章, 空态, 安全文本, 命运色,
  渲染水位, 渲染门槛, 渲染批次表,
  装载摘要文, 结栏摘要文, 贯验摘要文, 填命运字典,
  短指纹, 空封状态徽章, 空封裁决条HTML, 挂载空封裁决,
};
