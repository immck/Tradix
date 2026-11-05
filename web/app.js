/* ================= Tradix 前端逻辑 ================= */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const UP = "#2fe3a4", DOWN = "#ff5b76", AMBER = "#f6b64b";

  const state = {
    symbol: "BTC",
    market: "auto",
    tf: "1d",
    data: null,
    loading: false,
    auto: true,
    timer: null,
    watch: [],
    watchInfo: {},
    panel: localStorage.getItem("tradix.panel") || "macd",
    bb: localStorage.getItem("tradix.bb") !== "0",
    ema: localStorage.getItem("tradix.ema") !== "0",
  };

  const DEFAULT_WATCH = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "NVDA", "AAPL", "TSLA"];

  const UNIVERSE = [
    ["BTC", "比特币", "crypto"], ["ETH", "以太坊", "crypto"], ["SOL", "Solana", "crypto"],
    ["BNB", "BNB", "crypto"], ["XRP", "瑞波", "crypto"], ["DOGE", "狗狗币", "crypto"],
    ["ADA", "Cardano", "crypto"], ["AVAX", "Avalanche", "crypto"], ["LINK", "Chainlink", "crypto"],
    ["TON", "Toncoin", "crypto"], ["SUI", "Sui", "crypto"], ["APT", "Aptos", "crypto"],
    ["ARB", "Arbitrum", "crypto"], ["OP", "Optimism", "crypto"], ["PEPE", "Pepe", "crypto"],
    ["WIF", "dogwifhat", "crypto"], ["NEAR", "NEAR", "crypto"], ["INJ", "Injective", "crypto"],
    ["TIA", "Celestia", "crypto"], ["SEI", "Sei", "crypto"], ["LTC", "莱特币", "crypto"],
    ["BCH", "比特现金", "crypto"], ["DOT", "波卡", "crypto"], ["ATOM", "Cosmos", "crypto"],
    ["UNI", "Uniswap", "crypto"], ["AAVE", "Aave", "crypto"], ["FIL", "Filecoin", "crypto"],
    ["ORDI", "Ordinals", "crypto"], ["WLD", "Worldcoin", "crypto"], ["TAO", "Bittensor", "crypto"],
    ["NVDA", "英伟达", "us"], ["AAPL", "苹果", "us"], ["TSLA", "特斯拉", "us"],
    ["MSFT", "微软", "us"], ["GOOGL", "谷歌", "us"], ["AMZN", "亚马逊", "us"],
    ["META", "Meta", "us"], ["AMD", "超威半导体", "us"], ["INTC", "英特尔", "us"],
    ["NFLX", "奈飞", "us"], ["COIN", "Coinbase", "us"], ["MSTR", "MicroStrategy", "us"],
    ["HOOD", "Robinhood", "us"], ["PLTR", "Palantir", "us"], ["SMCI", "超微电脑", "us"],
    ["QQQ", "纳指100ETF", "us"], ["SPY", "标普500ETF", "us"], ["IBIT", "比特币ETF", "us"],
    ["600519", "贵州茅台", "cn"], ["300750", "宁德时代", "cn"], ["002594", "比亚迪", "cn"],
    ["601318", "中国平安", "cn"], ["000858", "五粮液", "cn"], ["688981", "中芯国际", "cn"],
  ];

  /* ---------------- 工具 ---------------- */
  function fmtPrice(v) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    const a = Math.abs(v);
    if (a >= 10000) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
    if (a >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
    if (a >= 100) return v.toFixed(2);
    if (a >= 1) return v.toFixed(3);
    return Number(v.toPrecision(6)).toString();
  }
  function fmtVol(v) {
    if (!v && v !== 0) return "—";
    const a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
    if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
    return v.toFixed(0);
  }
  function pct(v, digits) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(digits === undefined ? 2 : digits) + "%";
  }
  function cls(v) { return v > 0 ? "up" : v < 0 ? "down" : ""; }
  function scoreCls(v) { return v >= 18 ? "bull" : v <= -18 ? "bear" : "neutral"; }
  function scoreColor(v) { return v >= 18 ? UP : v <= -18 ? DOWN : AMBER; }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function toast(msg, err) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (err ? " err" : "");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.add("hidden"), 3600);
  }

  /* ---------------- 初始化 ---------------- */
  function init() {
    const savedWatch = localStorage.getItem("tradix.watch");
    try { state.watch = savedWatch ? JSON.parse(savedWatch) : DEFAULT_WATCH.slice(); }
    catch (_) { state.watch = DEFAULT_WATCH.slice(); }
    if (!Array.isArray(state.watch)) state.watch = DEFAULT_WATCH.slice();
    state.watch = [...new Set(state.watch.filter(s => typeof s === "string" && s.trim()))];

    const q = new URLSearchParams(location.search);
    state.symbol = (q.get("symbol") || localStorage.getItem("tradix.symbol") || "BTC").toUpperCase();
    state.tf = q.get("tf") || localStorage.getItem("tradix.tf") || "1d";
    state.market = q.get("market") || "auto";
    if (!["1h", "4h", "1d", "1w"].includes(state.tf)) state.tf = "1d";
    if (!["auto", "crypto", "us", "cn"].includes(state.market)) state.market = "auto";

    $("symbolInput").value = state.symbol;
    setSeg("tfSeg", "tf", state.tf);
    setSeg("marketSeg", "market", state.market);
    $("indSeg").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.ind === state.panel));
    $("bbToggle").checked = state.bb;
    $("emaToggle").checked = state.ema;

    state.chart = new KChart($("kline"), $("chartTip"));
    state.chart.setConfig({ showBB: state.bb, showEMA: state.ema, panel: state.panel });

    bind();
    renderWatch();
    load(state.symbol, { silent: false });
    scheduleAuto();
  }

  function setSeg(id, key, val) {
    $(id).querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset[key] === val));
  }

  /* ---------------- 事件 ---------------- */
  function bind() {
    $("symbolInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        closeSuggest();
        const v = e.target.value.trim();
        if (v) load(v);
      } else if (e.key === "Escape") closeSuggest();
    });
    $("symbolInput").addEventListener("input", (e) => showSuggest(e.target.value.trim()));
    $("symbolInput").addEventListener("blur", () => setTimeout(closeSuggest, 180));

    document.querySelectorAll("#tfSeg button").forEach((b) =>
      b.addEventListener("click", () => {
        state.tf = b.dataset.tf;
        setSeg("tfSeg", "tf", state.tf);
        localStorage.setItem("tradix.tf", state.tf);
        load(state.symbol, { silent: true });
      })
    );
    document.querySelectorAll("#marketSeg button").forEach((b) =>
      b.addEventListener("click", () => {
        state.market = b.dataset.market;
        setSeg("marketSeg", "market", state.market);
        load(state.symbol, { silent: true });
      })
    );
    document.querySelectorAll("#indSeg button").forEach((b) =>
      b.addEventListener("click", () => {
        state.panel = b.dataset.ind;
        document.querySelectorAll("#indSeg button").forEach((x) => x.classList.toggle("on", x === b));
        localStorage.setItem("tradix.panel", state.panel);
        state.chart.setConfig({ panel: state.panel });
      })
    );
    $("bbToggle").addEventListener("change", (e) => {
      state.bb = e.target.checked; localStorage.setItem("tradix.bb", state.bb ? "1" : "0");
      state.chart.setConfig({ showBB: state.bb });
    });
    $("emaToggle").addEventListener("change", (e) => {
      state.ema = e.target.checked; localStorage.setItem("tradix.ema", state.ema ? "1" : "0");
      state.chart.setConfig({ showEMA: state.ema });
    });
    $("refreshBtn").addEventListener("click", () => {
      load(state.symbol, { silent: false });
    });
    $("autoToggle").addEventListener("change", (e) => {
      state.auto = e.target.checked;
      scheduleAuto();
    });
    $("addWatchBtn").addEventListener("click", () => {
      if (!state.data) return;
      const sym = state.data.meta.display;
      if (state.watch.includes(sym)) { toast("已在自选列表中"); return; }
      state.watch.push(sym);
      persistWatch();
      renderWatch();
      toast(`已加入自选：${sym}`);
      scan(false);
    });
    $("scanBtn").addEventListener("click", () => scan(true));
    $("quickChips").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (b) load(b.dataset.sym, { market: "auto" });
    });
    $("watchList").addEventListener("click", (e) => {
      const del = e.target.closest(".w-del");
      if (del) {
        e.stopPropagation();
        const sym = del.dataset.sym;
        state.watch = state.watch.filter((s) => s !== sym);
        persistWatch(); renderWatch(); return;
      }
      const item = e.target.closest(".watch-item");
      if (item) load(item.dataset.sym, { market: "auto" });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== $("symbolInput")) {
        e.preventDefault(); $("symbolInput").focus(); $("symbolInput").select();
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.auto) scheduleAuto();
    });
  }

  function persistWatch() {
    localStorage.setItem("tradix.watch", JSON.stringify(state.watch));
  }

  function scheduleAuto() {
    if (state.timer) clearInterval(state.timer);
    if (!state.auto) return;
    state.timer = setInterval(() => {
      if (document.hidden || state.loading || !state.data) return;
      load(state.data.meta.symbol, { silent: true });
    }, 60000);
  }

  /* ---------------- 搜索建议 ---------------- */
  function showSuggest(q) {
    const box = $("suggestBox");
    if (!q) { closeSuggest(); return; }
    const uq = q.toUpperCase();
    let items = UNIVERSE.filter(([s, n]) => s.includes(uq) || n.toUpperCase().includes(uq));
    if (!items.length) items = [["" + uq, "直接分析该代码", "auto"]];
    box.innerHTML = items.slice(0, 8).map(([s, n, m]) =>
      `<button data-sym="${esc(s)}" data-market="${m}"><span style="color:${m === "crypto" ? UP : m === "us" ? "#6aa6ff" : AMBER}">${m === "crypto" ? "加密" : m === "us" ? "美股" : "A股"}</span><span>${esc(n)}</span></button>`
    ).join("");
    box.querySelectorAll("button").forEach((b) =>
      b.addEventListener("mousedown", (e) => {
        e.preventDefault();
        $("symbolInput").value = b.dataset.sym;
        closeSuggest();
        if (b.dataset.market !== "auto") {
          state.market = b.dataset.market;
          setSeg("marketSeg", "market", state.market);
        }
        load(b.dataset.sym);
      })
    );
    box.classList.remove("hidden");
  }
  function closeSuggest() { $("suggestBox").classList.add("hidden"); }

  /* ---------------- 数据加载 ---------------- */
  async function load(symbol, opts) {
    opts = opts || {};
    if (state.controller) state.controller.abort();
    const requestId = state.requestId = (state.requestId || 0) + 1;
    if (opts.market) state.market = opts.market;
    const isCN = state.market === "cn" || (state.market === "auto" && /^(?:(?:sh|sz|bj))?\d{6}(?:\.(?:sh|sz|bj))?$/i.test(symbol));
    if (isCN && !["1d", "1w", "1M"].includes(state.tf)) state.tf = "1d";
    const tf = state.tf, market = state.market;
    setSeg("tfSeg", "tf", tf);
    setSeg("marketSeg", "market", market);
    $("tfSeg").querySelectorAll("button").forEach(b => { b.disabled = isCN && !["1d", "1w", "1M"].includes(b.dataset.tf); });
    state.loading = true;
    state.symbol = symbol;
    if (!opts.silent) $("symbolInput").value = symbol;
    $("chartLoading").classList.remove("hidden");
    $("refreshBtn").classList.add("spin");
    const ctrl = new AbortController();
    state.controller = ctrl;
    const to = setTimeout(() => ctrl.abort(), 90000);
    try {
      const url = `api/analyze?symbol=${encodeURIComponent(symbol)}&market=${market}&tf=${tf}`;
      const res = await fetch(url, { signal: ctrl.signal });
      const json = await res.json();
      if (requestId !== state.requestId) return;
      if (!json.ok) throw new Error(json.error || "分析失败");
      const preserveView = state.data && state.data.meta.display === json.meta.display && state.data.meta.tf === json.meta.tf;
      state.data = json;
      state.loadedMarket = market;
      state.symbol = json.meta.display;
      localStorage.setItem("tradix.symbol", json.meta.display);
      localStorage.setItem("tradix.tf", tf);
      history.replaceState(null, "", `?symbol=${encodeURIComponent(json.meta.display)}&tf=${tf}&market=${market}`);
      renderAll(json, preserveView);
      if (!opts.silent) toast(`已更新 ${json.meta.display} · ${json.meta.tf_label}`);
      if (!state.scanned) { state.scanned = true; setTimeout(() => scan(false), 400); }
    } catch (err) {
      if (requestId !== state.requestId) return;
      const msg = err.name === "AbortError" ? "请求超时，请检查网络或行情源" : (err.message || "加载失败");
      toast(msg, true);
      if (!state.data) $("summaryText").textContent = "加载失败：" + msg;
      else {
        state.symbol = state.data.meta.display;
        state.tf = state.data.meta.tf;
        state.market = state.loadedMarket;
        setSeg("tfSeg", "tf", state.tf);
        setSeg("marketSeg", "market", state.market);
        $("tfSeg").querySelectorAll("button").forEach(b => {
          b.disabled = state.data.meta.market === "cn" && !["1d", "1w", "1M"].includes(b.dataset.tf);
        });
      }
    } finally {
      clearTimeout(to);
      if (requestId !== state.requestId) return;
      state.loading = false;
      $("chartLoading").classList.add("hidden");
      $("refreshBtn").classList.remove("spin");
      $("symbolInput").value = state.symbol;
    }
  }

  /* ---------------- 渲染 ---------------- */
  function renderAll(d, preserveView) {
    renderQuote(d);
    renderGauge(d);
    renderMatrix(d);
    renderMtf(d);
    renderSignals(d);
    renderRisks(d);
    renderPlan(d);
    renderLevels(d);
    renderPerf(d);
    state.chart.setData(d.chart, preserveView);
    document.title = `${d.meta.display} ${fmtPrice(d.quote.price)} · TRADIX`;
    renderWatch();
  }

  function renderQuote(d) {
    const q = d.quote, m = d.meta, a = d.analysis;
    $("qDisplay").textContent = m.display;
    $("qName").textContent = m.name && m.name !== m.display ? m.name : "";
    $("qMarket").textContent = m.market_label;
    $("qMarket").className = "tag" + (m.market === "crypto" ? "" : " ghost");
    $("qTf").textContent = m.tf_label;
    $("qStatus").textContent = m.last_closed ? "K线已收盘" : "K线未收盘";
    $("qStatus").className = "tag " + (m.last_closed ? "ghost" : "warn");
    $("qStale").hidden = !m.stale;
    $("qPrice").textContent = fmtPrice(q.price);
    $("qPrice").style.color = q.chg_pct > 0 ? UP : q.chg_pct < 0 ? DOWN : "var(--txt)";
    $("qChg").textContent = `${pct(q.chg_pct)}  ${q.chg >= 0 ? "+" : ""}${fmtPrice(q.chg)}`;
    $("qChg").className = "chg " + cls(q.chg_pct);
    $("qHigh").textContent = fmtPrice(q.high);
    $("qLow").textContent = fmtPrice(q.low);
    $("qVol").textContent = m.market === "crypto" ? fmtVol(q.volume_usd) + " " + m.currency : fmtVol(q.volume);
    $("qAtr").textContent = a.volatility.atr_pct + "%";
    $("qSource").textContent = m.source || "—";
    const t = new Date((m.fetched_at || m.last_t) * 1000);
    $("qTime").textContent = "数据 " + t.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    $("qTime").title = "最后一根 K 线：" + new Date(m.last_t * 1000).toLocaleString("zh-CN");
  }

  function renderPerf(d) {
    const p = d.analysis.perf || {};
    const row = $("perfRow");
    const items = [
      ["5根", p.d5], ["20根", p.d20], ["60根", p.d60], ["120根", p.d120],
      ["区间位置", d.analysis.range_pos, "%", true],
    ];
    row.innerHTML = items.map(([label, v, suffix, raw]) => {
      if (v === null || v === undefined) return `<span>${label}<b>—</b></span>`;
      if (raw) return `<span>${label}<b>${v.toFixed(0)}%</b></span>`;
      return `<span>${label}<b class="${cls(v)}">${pct(v)}</b></span>`;
    }).join("") + `<span style="margin-left:auto;color:var(--muted)">${esc(d.analysis.structure.label)} · ${esc(d.analysis.trend.ma_state)}</span>`;
  }

  function renderGauge(d) {
    const a = d.analysis, o = d.overall;
    const s = a.score;
    const n = Math.max(0, Math.min(1, (s + 100) / 200));
    const L = Math.PI * 88;
    const arc = $("gaugeArc");
    arc.style.strokeDasharray = `${(n * L).toFixed(1)} ${L.toFixed(1)}`;
    const theta = Math.PI * (1 - n);
    $("gaugeDot").setAttribute("cx", (110 + 88 * Math.cos(theta)).toFixed(1));
    $("gaugeDot").setAttribute("cy", (110 - 88 * Math.sin(theta)).toFixed(1));
    $("gaugeDot").setAttribute("fill", scoreColor(s));
    $("gaugeScore").textContent = (s > 0 ? "+" : "") + s.toFixed(1);
    $("gaugeScore").style.color = scoreColor(s);

    const vt = $("gaugeVerdict");
    vt.textContent = a.verdict;
    vt.className = "verdict-badge " + scoreCls(s);
    $("gaugeConf").textContent = Math.round(a.confidence) + "%";
    $("overallScore").textContent = (o.score > 0 ? "+" : "") + o.score.toFixed(0) + " · " + o.resonance;
    $("summaryText").textContent = a.summary;

    const chips = [
      `<span>ADX ${a.trend.adx ?? "—"}</span>`,
      `<span>RSI ${a.momentum.rsi ?? "—"}</span>`,
      `<span>ATR ${a.volatility.atr_pct}%</span>`,
      `<span>量比 ${a.volume.ratio}</span>`,
      `<span>R² ${a.trend.r2}</span>`,
    ];
    if (a.momentum.divergence && a.momentum.divergence.length) chips.push(`<span style="color:${AMBER}">${a.momentum.divergence[0].name}</span>`);
    $("overallStrip").innerHTML = chips.join("");
  }

  function renderMatrix(d) {
    const comps = d.analysis.components;
    $("matrixSub").textContent = "8 因子加权 · 满分 ±100";
    $("matrixList").innerHTML = comps.map((c) => {
      const s = Math.max(-100, Math.min(100, c.score));
      const w = Math.abs(s) / 2;
      const bar = s >= 0
        ? `<i class="pos" style="width:${w}%;"></i>`
        : `<i class="neg" style="width:${w}%;"></i>`;
      return `<div class="mrow" title="${esc(c.detail)}">
        <span class="mlabel">${esc(c.label)}</span>
        <div class="mbar">${bar}</div>
        <span class="mstate" style="color:${scoreColor(c.score)}">${esc(c.state)}</span>
      </div>`;
    }).join("");
  }

  function renderMtf(d) {
    const items = d.mtf || [];
    const o = d.overall;
    const badge = $("mtfBadge");
    badge.textContent = o.resonance;
    badge.className = "badge " + (o.resonance.includes("共振") || o.resonance.includes("一致") ? (o.score >= 0 ? "bull" : "bear") : "neutral");

    const all = [...items, { tf: d.meta.tf, label: d.meta.tf_label, score: d.analysis.score, verdict: d.analysis.verdict_short, current: true }];
    const order = { "1h": 0, "4h": 1, "1d": 2, "1w": 3 };
    all.sort((a, b) => (order[a.tf] ?? 9) - (order[b.tf] ?? 9));

    $("mtfList").innerHTML = all.map((m) => {
      const sc = m.score;
      const has = sc !== null && sc !== undefined;
      const w = has ? Math.min(50, Math.abs(sc) / 2) : 0;
      const bar = has
        ? (sc >= 0 ? `<i style="width:${w}%;background:${UP};opacity:.8"></i>` : `<i style="width:${w}%;background:${DOWN};opacity:.8;transform:translateX(-100%)"></i>`)
        : "";
      return `<div class="mtf-item" style="${m.current ? "border-color:rgba(47,227,164,.3)" : ""}">
        <div class="mh"><span>${esc(m.label)}${m.current ? " · 当前" : ""}</span><span>${has ? (m.score >= 0 ? "▲" : "▼") : "—"}</span></div>
        <div class="mv" style="color:${has ? scoreColor(sc) : "var(--muted)"}">${has ? (sc > 0 ? "+" : "") + sc.toFixed(0) : "—"}</div>
        <div class="ms">${esc(m.stale ? "缓存 · 不计入共振" : m.verdict || (m.error ? "数据不足" : "—"))}</div>
        <div class="mtrk">${bar}</div>
      </div>`;
    }).join("");
    $("mtfFoot").textContent = o.detail ? `各周期评分：${o.detail}。共振度 ${o.aligned || 0}/${o.total || 0}。` : "";
  }

  function renderSignals(d) {
    const sigs = d.analysis.signals || [];
    $("signalCount").textContent = sigs.length ? `${sigs.length} 条` : "无";
    if (!sigs.length) {
      $("signalList").innerHTML = `<div class="empty-tip">当前没有突出的技术信号</div>`;
      return;
    }
    $("signalList").innerHTML = sigs.map((s) =>
      `<div class="sig ${s.type}"><div><div class="st">${esc(s.title)}</div><div class="sd">${esc(s.detail)}</div></div></div>`
    ).join("");
  }

  function renderRisks(d) {
    const risks = d.analysis.risks || [];
    $("riskList").innerHTML = risks.length
      ? risks.map((r) => `<div class="risk-item ${esc(r.level)}"><span class="rd"></span><span>${esc(r.text)}</span></div>`).join("")
      : `<div class="empty-tip">暂无特别风险项</div>`;
  }

  function renderPlan(d) {
    const p = d.plan;
    const badge = $("planBias");
    badge.textContent = p.bias === "long" ? "做多" : p.bias === "short" ? "做空" : "观望";
    badge.className = "badge " + (p.bias === "long" ? "bull" : p.bias === "short" ? "bear" : "neutral");

    if (p.bias === "neutral") {
      $("planBody").innerHTML = `
        <div class="plan-wait">
          <div class="big">${esc(p.title)}</div>
          <p>${esc(p.note)}</p>
          <div class="plan-grid">
            <div class="pcell"><span>向上关注</span><b style="color:${UP}">${fmtPrice(p.watch_up)}</b></div>
            <div class="pcell"><span>向下关注</span><b style="color:${DOWN}">${fmtPrice(p.watch_down)}</b></div>
          </div>
          ${p.trigger ? `<div class="plan-trigger">触发条件：${esc(p.trigger)}</div>` : ""}
        </div>`;
      return;
    }
    const qc = p.quality === "good" ? "good" : p.quality === "ok" ? "ok" : "poor";
    const qlabel = p.quality === "good" ? "盈亏比健康" : p.quality === "ok" ? "盈亏比一般" : "盈亏比不足";
    $("planBody").innerHTML = `
      <div class="plan-hero">
        <div class="ttl">${esc(p.title)}</div>
        <div class="rr ${qc}">${qlabel} · <b>${p.rr}</b> R</div>
      </div>
      <div class="plan-grid">
        <div class="pcell entry"><span>进场区间</span><b>${fmtPrice(p.entry_lo)} – ${fmtPrice(p.entry_hi)}</b></div>
        <div class="pcell stop"><span>止损（${p.risk_pct}%）</span><b>${fmtPrice(p.stop)}</b></div>
        <div class="pcell target"><span>目标 T1</span><b>${fmtPrice(p.t1)}</b></div>
        <div class="pcell target"><span>目标 T2</span><b>${fmtPrice(p.t2)}</b></div>
      </div>
      ${p.trigger ? `<div class="plan-trigger">执行方式：${esc(p.trigger)}</div>` : ""}
      <p class="plan-note">${esc(p.note)}<br/>${esc(p.invalidation)}</p>`;
  }

  function renderLevels(d) {
    const a = d.analysis, price = d.quote.price || a.price;
    const res = (a.levels.resistances || []).slice().sort((x, y) => y.price - x.price);
    const sup = (a.levels.supports || []).slice();
    const row = (lv, kind, i) => {
      const dist = ((lv.price / price - 1) * 100);
      return `<div class="lv ${kind}">
        <span class="lp" style="color:${kind === "res" ? "#ff8fa0" : UP}">${kind === "res" ? "R" : "S"}${i + 1} ${fmtPrice(lv.price)}</span>
        <div class="lbar"><i style="width:${Math.max(8, lv.strength)}%"></i></div>
        <span class="ld">${dist >= 0 ? "+" : ""}${dist.toFixed(2)}%</span>
      </div>`;
    };
    let html = "";
    if (!res.length) html += `<div class="lv-empty">上方无明显结构阻力（创新高区域）</div>`;
    res.forEach((lv, i) => { html += row(lv, "res", res.length - 1 - i); });
    html += `<div class="lv now"><span class="lp">现价</span><div style="font-family:var(--mono);font-size:12px;color:var(--txt)">${fmtPrice(price)}</div><span class="ld">当前</span></div>`;
    if (!sup.length) html += `<div class="lv-empty">下方无明显结构支撑（创新低区域）</div>`;
    sup.forEach((lv, i) => { html += row(lv, "sup", i); });
    $("levelList").innerHTML = html;
  }

  /* ---------------- 自选 ---------------- */
  function renderWatch() {
    const box = $("watchList");
    if (!state.watch.length) {
      box.innerHTML = `<div class="empty-tip">自选为空，点击右上角 ＋ 添加</div>`;
      return;
    }
    box.innerHTML = state.watch.map((sym) => {
      const info = state.watchInfo[sym] || {};
      const chg = info.chg_pct;
      const sc = info.score;
      return `<div class="watch-item ${state.data && state.data.meta.display === sym ? "active" : ""}" data-sym="${esc(sym)}">
        <span class="w-sym">${esc(sym.replace("/USDT", ""))}<small>${esc(info.name || (info.market === "crypto" ? "加密货币" : info.market === "cn" ? "A股" : info.market === "us" ? "美股" : ""))}</small></span>
        <span class="w-chg ${cls(chg)}">${chg === undefined ? "" : pct(chg)}</span>
        <span class="w-score" style="${sc !== undefined ? "color:" + scoreColor(sc) + ";background:rgba(255,255,255,.04)" : ""}">${sc !== undefined ? (sc > 0 ? "+" : "") + sc.toFixed(0) : ""}</span>
        <button class="w-del" data-sym="${esc(sym)}" title="移除">×</button>
      </div>`;
    }).join("");
  }

  async function scan(notify) {
    if (!state.watch.length) return;
    if (state.scanning) return;
    state.scanning = true;
    $("scanBtn").disabled = true;
    const symbols = state.watch.slice(), tf = state.tf;
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 90000);
    try {
      if (notify) toast("正在扫描自选…");
      const items = [];
      for (let start = 0; start < symbols.length; start += 10) {
        const batch = symbols.slice(start, start + 10);
        const res = await fetch(`api/scan?symbols=${encodeURIComponent(batch.join(","))}&tf=${tf}`, { signal: ctrl.signal });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || "扫描失败");
        items.push(...json.items);
        json.items.forEach((it, index) => {
          if (!it.error) state.watchInfo[batch[index]] = it;
        });
      }
      renderWatch();
      if (notify) {
        const ok = items.filter((x) => !x.error).length;
        toast(`扫描完成：${ok}/${items.length} 个品种`);
      }
    } catch (e) {
      if (notify) toast("扫描失败：" + e.message, true);
    } finally {
      clearTimeout(timeout);
      state.scanning = false;
      $("scanBtn").disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
