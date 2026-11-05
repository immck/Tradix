/* ================= Canvas K 线图表引擎 ================= */
(function () {
  const UP = "#2fe3a4";
  const DOWN = "#ff5b76";
  const GRID = "rgba(148,170,205,0.075)";
  const TEXT = "#8b98ad";
  const MUTED = "#5f6d84";
  const MONO = '11px "JetBrains Mono", Consolas, monospace';
  const MONO_SM = '10px "JetBrains Mono", Consolas, monospace';

  const fmt = (v, digits) => {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    if (digits !== undefined) return v.toFixed(digits);
    const a = Math.abs(v);
    if (a >= 10000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
    if (a >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
    if (a >= 100) return v.toFixed(2);
    if (a >= 1) return v.toFixed(3);
    return v.toFixed(5);
  };

  const fmtVol = (v) => {
    if (!v && v !== 0) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
    return v.toFixed(0);
  };

  class KChart {
    constructor(canvas, tipEl) {
      this.cv = canvas;
      this.ctx = canvas.getContext("2d");
      this.tip = tipEl;
      this.data = null;
      this.cfg = { showBB: true, showEMA: true, panel: "macd" };
      this.view = { start: 0, count: 140 };
      this.hover = -1;
      this.drag = null;
      this.lastPointer = null;
      this.fmtCache = {};
      this._bind();
      this._resize();
      if (window.ResizeObserver) {
        new ResizeObserver(() => { this._resize(); this.draw(); }).observe(canvas.parentElement);
      } else {
        window.addEventListener("resize", () => { this._resize(); this.draw(); });
      }
    }

    setConfig(cfg) { Object.assign(this.cfg, cfg); this.draw(); }

    setData(chart) {
      this.data = chart;
      const n = chart && chart.candles ? chart.candles.length : 0;
      const show = Math.min(n, 150);
      this.view = { start: Math.max(0, n - show), count: show || 1 };
      this.hover = -1;
      this.tip.classList.add("hidden");
      this.draw();
    }

    /* ---------------- 交互 ---------------- */
    _bind() {
      const cv = this.cv;
      cv.addEventListener("mousemove", (e) => {
        const r = cv.getBoundingClientRect();
        this.lastPointer = { x: e.clientX - r.left, y: e.clientY - r.top };
        if (this.drag) {
          const dx = this.lastPointer.x - this.drag.x;
          const slot = this._slot();
          const shift = Math.round(-dx / slot);
          const start = Math.max(0, Math.min(this.data.candles.length - this.view.count, this.drag.start + shift));
          if (start !== this.view.start) { this.view.start = start; this.draw(); }
          return;
        }
        this._hoverAt(this.lastPointer.x, this.lastPointer.y);
      });
      cv.addEventListener("mouseleave", () => {
        this.hover = -1; this.drag = null;
        this.tip.classList.add("hidden");
        this.draw();
      });
      cv.addEventListener("mousedown", (e) => {
        if (!this.data) return;
        const r = cv.getBoundingClientRect();
        this.drag = { x: e.clientX - r.left, start: this.view.start };
        cv.style.cursor = "grabbing";
      });
      window.addEventListener("mouseup", () => { this.drag = null; cv.style.cursor = "crosshair"; });
      cv.addEventListener("dblclick", () => {
        if (!this.data) return;
        const n = this.data.candles.length;
        const show = Math.min(n, 150);
        this.view = { start: n - show, count: show };
        this.draw();
      });
      cv.addEventListener("wheel", (e) => {
        if (!this.data) return;
        e.preventDefault();
        const n = this.data.candles.length;
        const r = cv.getBoundingClientRect();
        const px = e.clientX - r.left;
        const rect = this._rects();
        const frac = Math.max(0, Math.min(1, (px - rect.price.x) / rect.price.w));
        const anchor = this.view.start + frac * this.view.count;
        const factor = 1 + (e.deltaY > 0 ? 0.14 : -0.14);
        let count = Math.round(this.view.count * factor);
        count = Math.max(35, Math.min(n, count));
        let start = Math.round(anchor - frac * count);
        start = Math.max(0, Math.min(n - count, start));
        this.view = { start, count };
        this.draw();
      }, { passive: false });
    }

    _hoverAt(px, py) {
      if (!this.data) return;
      const rect = this._rects();
      if (px < rect.price.x || px > rect.price.x + rect.price.w) {
        this.hover = -1; this.tip.classList.add("hidden"); this.draw(); return;
      }
      const slot = this._slot();
      const idx = Math.floor((px - rect.price.x) / slot) + this.view.start;
      const clamped = Math.max(this.view.start, Math.min(this.view.start + this.view.count - 1, idx));
      this.hover = clamped;
      this._showTip(px, py, clamped);
      this.draw();
    }

    _showTip(px, py, i) {
      const d = this.data;
      const c = d.candles[i];
      if (!c) return;
      const [t, o, h, l, cl, v] = c;
      const prev = i > 0 ? d.candles[i - 1][4] : o;
      const chg = cl - prev;
      const pct = prev ? (chg / prev) * 100 : 0;
      const cls = chg >= 0 ? "up" : "down";
      const sign = chg >= 0 ? "+" : "";
      let html = `<div class="tt">${this._time(t, true)}</div>`;
      html += `<div class="tr"><span>开</span><b>${fmt(o)}</b></div>`;
      html += `<div class="tr"><span>高</span><b>${fmt(h)}</b></div>`;
      html += `<div class="tr"><span>低</span><b>${fmt(l)}</b></div>`;
      html += `<div class="tr"><span>收</span><b class="${cls}">${fmt(cl)}</b></div>`;
      html += `<div class="tr"><span>涨跌</span><b class="${cls}">${sign}${pct.toFixed(2)}%</b></div>`;
      html += `<div class="tr"><span>成交</span><b>${fmtVol(v)}</b></div>`;
      if (d.ema20 && d.ema20[i] != null) {
        html += `<div class="tr" style="margin-top:4px"><span style="color:#f6b64b">EMA20</span><b>${fmt(d.ema20[i])}</b></div>`;
      }
      if (d.ema50 && d.ema50[i] != null) {
        html += `<div class="tr"><span style="color:#6aa6ff">EMA50</span><b>${fmt(d.ema50[i])}</b></div>`;
      }
      if (d.ema200 && d.ema200[i] != null) {
        html += `<div class="tr"><span style="color:#b28cff">EMA200</span><b>${fmt(d.ema200[i])}</b></div>`;
      }
      if (d.macd_dif && d.macd_dif[i] != null && d.macd_dea[i] != null) {
        html += `<div class="tr" style="margin-top:4px"><span>MACD</span><b>${d.macd_dif[i].toFixed(3)} / ${d.macd_dea[i].toFixed(3)}</b></div>`;
      }
      if (d.rsi && d.rsi[i] != null) {
        html += `<div class="tr"><span>RSI14</span><b>${d.rsi[i].toFixed(1)}</b></div>`;
      }
      this.tip.innerHTML = html;
      this.tip.classList.remove("hidden");
      const tw = this.tip.offsetWidth || 190;
      const th = this.tip.offsetHeight || 160;
      let left = px + 16;
      let top = py + 14;
      if (left + tw > this.W - 8) left = px - tw - 14;
      if (top + th > this.H - 8) top = Math.max(4, py - th - 12);
      this.tip.style.left = left + "px";
      this.tip.style.top = top + "px";
    }

    _resize() {
      const rect = this.cv.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.W = Math.max(300, rect.width);
      this.H = Math.max(240, rect.height);
      this.cv.width = Math.round(this.W * dpr);
      this.cv.height = Math.round(this.H * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    _rects() {
      const padL = 8, padR = this.W < 560 ? 58 : 66, padT = 30, padB = 22;
      const priceH = Math.max(120, this.H - padT - padB - 62 - (this.cfg.panel === "none" ? 0 : 92) - 14);
      const price = { x: padL, y: padT, w: this.W - padL - padR, h: priceH };
      const vol = { x: padL, y: price.y + price.h + 12, w: price.w, h: 48 };
      const panel = { x: padL, y: vol.y + vol.h + 12, w: price.w, h: Math.max(0, this.H - padB - (vol.y + vol.h + 12)) };
      return { price, vol, panel, padR };
    }

    _slot() { return this._rects().price.w / Math.max(1, this.view.count); }

    _x(i) { const r = this._rects(); return r.price.x + (i - this.view.start + 0.5) * (r.price.w / this.view.count); }

    _time(t, full) {
      const d = this.data;
      const tz = d.tz || "UTC";
      const tf = d.tf;
      try {
        if (tf === "1d" || tf === "1w" || tf === "1M") {
          const opt = full
            ? { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }
            : { timeZone: tz, month: "2-digit", day: "2-digit" };
          const key = JSON.stringify(opt);
          this.fmtCache[key] = this.fmtCache[key] || new Intl.DateTimeFormat("zh-CN", opt);
          return this.fmtCache[key].format(new Date(t * 1000));
        }
        const opt = full
          ? { timeZone: tz, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
          : tf === "15m" || tf === "30m"
            ? { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false }
            : { timeZone: tz, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false };
        const key = JSON.stringify(opt);
        this.fmtCache[key] = this.fmtCache[key] || new Intl.DateTimeFormat("zh-CN", opt);
        return this.fmtCache[key].format(new Date(t * 1000));
      } catch (e) {
        return new Date(t * 1000).toISOString().slice(full ? 0 : 11, full ? 16 : 16).replace("T", " ");
      }
    }

    /* ---------------- 主绘制 ---------------- */
    draw() {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.W, this.H);
      if (!this.data || !this.data.candles || this.data.candles.length < 3) {
        ctx.fillStyle = MUTED; ctx.font = MONO; ctx.textAlign = "center";
        ctx.fillText("暂无行情数据", this.W / 2, this.H / 2);
        return;
      }
      const d = this.data;
      const n = d.candles.length;
      const start = Math.max(0, Math.min(n - 2, this.view.start));
      const end = Math.min(n, start + this.view.count);
      this.view.start = start;
      this.view.count = end - start;

      const r = this._rects();
      const rows = d.candles.slice(start, end);

      let lo = Infinity, hi = -Infinity;
      for (const c of rows) { if (c[3] < lo) lo = c[3]; if (c[2] > hi) hi = c[2]; }
      if (this.cfg.showEMA) {
        for (const arr of [d.ema20, d.ema50, d.ema200]) {
          if (!arr) continue;
          for (let i = start; i < end; i++) { const v = arr[i]; if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } }
        }
      }
      if (this.cfg.showBB && d.bb_up) {
        for (let i = start; i < end; i++) {
          if (d.bb_up[i] != null) { hi = Math.max(hi, d.bb_up[i]); lo = Math.min(lo, d.bb_low[i]); }
        }
      }
      const pad = (hi - lo) * 0.08 || hi * 0.01;
      lo -= pad; hi += pad;
      const yOf = (p) => r.price.y + (hi - p) / (hi - lo) * r.price.h;
      const tags = this._tagList(r, yOf);

      // 网格
      ctx.font = MONO_SM; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      const gridN = 5;
      for (let i = 0; i <= gridN; i++) {
        const p = lo + (hi - lo) * i / gridN;
        const y = Math.round(yOf(p)) + 0.5;
        ctx.strokeStyle = GRID; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(r.price.x, y); ctx.lineTo(r.price.x + r.price.w, y); ctx.stroke();
        if (!tags.some((t) => Math.abs(t.y - y) < 9)) {
          ctx.fillStyle = MUTED;
          ctx.fillText(fmt(p), r.price.x + r.price.w + 8, y);
        }
      }

      // 时间轴刻度
      const tickN = Math.max(3, Math.min(7, Math.floor(r.price.w / 110)));
      ctx.textAlign = "center";
      for (let k = 0; k < tickN; k++) {
        const idx = start + Math.round((end - start - 1) * (k + 0.5) / tickN);
        const x = this._x(idx);
        ctx.strokeStyle = GRID;
        ctx.beginPath(); ctx.moveTo(x, r.price.y); ctx.lineTo(x, r.price.y + r.price.h + 56); ctx.stroke();
        ctx.fillStyle = MUTED;
        const tx = Math.max(22, Math.min(this.W - 22, x));
        ctx.fillText(this._time(d.candles[idx][0]), tx, this.H - 9);
      }

      // 布林带
      if (this.cfg.showBB && d.bb_up) {
        ctx.beginPath();
        let started = false;
        for (let i = start; i < end; i++) {
          const v = d.bb_up[i]; if (v == null) continue;
          const x = this._x(i); const y = yOf(v);
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        }
        for (let i = end - 1; i >= start; i--) {
          const v = d.bb_low[i]; if (v == null) continue;
          ctx.lineTo(this._x(i), yOf(v));
        }
        ctx.closePath();
        ctx.fillStyle = "rgba(106,166,255,0.042)"; ctx.fill();
        ctx.strokeStyle = "rgba(106,166,255,0.3)"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
        for (const arr of [d.bb_up, d.bb_low]) {
          ctx.beginPath(); let st = false;
          for (let i = start; i < end; i++) {
            const v = arr[i]; if (v == null) continue;
            const x = this._x(i), y = yOf(v);
            if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y);
          }
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }

      // 关键价位 / 交易计划：只画线，标签统一放到右侧价格轴，避免遮挡
      const drawLine = (price, color, dash) => {
        if (!price || price < lo || price > hi) return;
        const y = Math.round(yOf(price)) + 0.5;
        ctx.save();
        ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash(dash || [5, 4]);
        ctx.beginPath(); ctx.moveTo(r.price.x, y); ctx.lineTo(r.price.x + r.price.w, y); ctx.stroke();
        ctx.restore();
      };
      if (d.plan && d.plan.bias !== "neutral") {
        const long = d.plan.bias === "long";
        if (d.plan.entry_lo && d.plan.entry_hi) {
          const ya = yOf(Math.max(d.plan.entry_lo, d.plan.entry_hi));
          const yb = yOf(Math.min(d.plan.entry_lo, d.plan.entry_hi));
          if (yb > r.price.y && ya < r.price.y + r.price.h) {
            ctx.fillStyle = long ? "rgba(47,227,164,0.075)" : "rgba(255,91,118,0.075)";
            ctx.fillRect(r.price.x, Math.max(r.price.y, ya), r.price.w, Math.min(r.price.y + r.price.h, yb) - Math.max(r.price.y, ya));
          }
        }
        drawLine(d.plan.stop, "rgba(255,91,118,0.5)", [4, 4]);
        drawLine(d.plan.t1, "rgba(47,227,164,0.45)", [2, 4]);
        if (d.plan.t2) drawLine(d.plan.t2, "rgba(47,227,164,0.24)", [2, 4]);
      }
      (d.levels.resistances || []).slice(0, 3).forEach((lv) => drawLine(lv.price, "rgba(255,105,130,0.26)", [6, 5]));
      (d.levels.supports || []).slice(0, 3).forEach((lv) => drawLine(lv.price, "rgba(58,222,170,0.26)", [6, 5]));

      // 成交量
      let vmax = 0;
      for (let i = start; i < end; i++) vmax = Math.max(vmax, d.candles[i][5]);
      const slot = r.price.w / this.view.count;
      const vw = Math.max(1, slot * 0.6);
      for (let i = start; i < end; i++) {
        const c = d.candles[i];
        const x = this._x(i);
        const h = vmax ? (c[5] / vmax) * (r.vol.h - 4) : 0;
        ctx.fillStyle = c[4] >= c[1] ? "rgba(47,227,164,0.5)" : "rgba(255,91,118,0.5)";
        ctx.fillRect(x - vw / 2, r.vol.y + r.vol.h - h, vw, h);
      }
      if (d.vol_ma20) {
        ctx.beginPath(); let st = false;
        for (let i = start; i < end; i++) {
          const v = d.vol_ma20[i]; if (v == null) continue;
          const x = this._x(i), y = r.vol.y + r.vol.h - (vmax ? (v / vmax) * (r.vol.h - 4) : 0);
          if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = "rgba(246,182,75,0.55)"; ctx.lineWidth = 1; ctx.stroke();
      }
      ctx.fillStyle = MUTED; ctx.font = MONO_SM; ctx.textAlign = "left";
      ctx.fillText("VOL", r.vol.x + 2, r.vol.y + 8);

      // K 线
      for (let i = start; i < end; i++) {
        const c = d.candles[i];
        const up = c[4] >= c[1];
        const col = up ? UP : DOWN;
        const x = this._x(i);
        const yH = yOf(c[2]), yL = yOf(c[3]), yO = yOf(c[1]), yC = yOf(c[4]);
        ctx.strokeStyle = col; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, yH); ctx.lineTo(Math.round(x) + 0.5, yL); ctx.stroke();
        const top = Math.min(yO, yC), hgt = Math.max(1, Math.abs(yC - yO));
        ctx.fillStyle = col;
        ctx.fillRect(x - vw / 2, top, vw, hgt);
      }

      // EMA
      if (this.cfg.showEMA) {
        const lines = [
          [d.ema20, "#f6b64b", 1.2],
          [d.ema50, "#6aa6ff", 1.2],
          [d.ema200, "#b28cff", 1.3],
        ];
        for (const [arr, color, w] of lines) {
          if (!arr) continue;
          ctx.beginPath(); let st = false;
          for (let i = start; i < end; i++) {
            const v = arr[i]; if (v == null) continue;
            const x = this._x(i), y = yOf(v);
            if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y);
          }
          ctx.strokeStyle = color; ctx.lineWidth = w; ctx.globalAlpha = 0.92; ctx.stroke(); ctx.globalAlpha = 1;
        }
      }

      // 摆动点标注（间距不足时只画点，避免堆叠）
      const swings = d.swings || [];
      let lastHigh = null, lastLow = null, lastLabelX = -999;
      for (const s of swings) {
        const idx = d.candles.findIndex((c) => c[0] === s.t);
        if (idx < start || idx >= end) continue;
        const x = this._x(idx);
        const isHigh = s.type === "high";
        const y = yOf(s.price);
        let label;
        if (isHigh) { label = lastHigh != null && s.price > lastHigh ? "HH" : "LH"; lastHigh = s.price; }
        else { label = lastLow != null && s.price < lastLow ? "LL" : "HL"; lastLow = s.price; }
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = isHigh ? "rgba(255,91,118,0.85)" : "rgba(47,227,164,0.85)";
        ctx.fill();
        if (Math.abs(x - lastLabelX) < 40) continue;
        lastLabelX = x;
        ctx.font = MONO_SM; ctx.fillStyle = isHigh ? "rgba(255,150,168,0.9)" : "rgba(120,235,200,0.85)";
        ctx.textAlign = "center"; ctx.textBaseline = isHigh ? "bottom" : "top";
        ctx.fillText(label, x, isHigh ? y - 6 : y + 6);
      }

      // 最新价虚线 + 右侧价格标签
      const lastC = d.candles[n - 1];
      const lastY = yOf(lastC[4]);
      if (lastY > r.price.y && lastY < r.price.y + r.price.h) {
        ctx.save();
        ctx.setLineDash([2, 3]);
        ctx.strokeStyle = lastC[4] >= lastC[1] ? "rgba(47,227,164,0.55)" : "rgba(255,91,118,0.55)";
        ctx.beginPath(); ctx.moveTo(r.price.x, Math.round(lastY) + 0.5); ctx.lineTo(r.price.x + r.price.w, Math.round(lastY) + 0.5); ctx.stroke();
        ctx.restore();
      }
      this._paintTags(tags, r);

      // 指标副图
      if (this.cfg.panel === "macd") this._drawMACD(r.panel, start, end);
      else if (this.cfg.panel === "rsi") this._drawRSI(r.panel, start, end);

      // 顶部图例
      this._drawTopLegend(start, end);

      // 十字光标
      if (this.hover >= start && this.hover < end) {
        const c = d.candles[this.hover];
        const x = this._x(this.hover);
        ctx.save();
        ctx.setLineDash([3, 3]); ctx.strokeStyle = "rgba(200,215,240,0.28)"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, r.price.y); ctx.lineTo(x, this.H - 22); ctx.stroke();
        if (this.lastPointer && this.lastPointer.y > r.price.y && this.lastPointer.y < r.price.y + r.price.h) {
          const y = this.lastPointer.y;
          ctx.beginPath(); ctx.moveTo(r.price.x, y); ctx.lineTo(r.price.x + r.price.w, y); ctx.stroke();
          const price = hi - (y - r.price.y) / r.price.h * (hi - lo);
          ctx.setLineDash([]);
          ctx.fillStyle = "rgba(30,42,62,0.95)";
          ctx.fillRect(r.price.x + r.price.w + 2, y - 9, 62, 18);
          ctx.strokeStyle = "rgba(148,170,205,0.3)"; ctx.strokeRect(r.price.x + r.price.w + 2, y - 9, 62, 18);
          ctx.fillStyle = "#c8d6ea"; ctx.font = MONO_SM; ctx.textAlign = "left"; ctx.textBaseline = "middle";
          ctx.fillText(fmt(price), r.price.x + r.price.w + 6, y);
        }
        // 底部时间标签
        ctx.setLineDash([]);
        const label = this._time(c[0], true);
        ctx.font = MONO_SM;
        const tw = ctx.measureText(label).width;
        const bx = Math.min(Math.max(r.price.x, x - tw / 2 - 5), r.price.x + r.price.w - tw - 10);
        ctx.fillStyle = "rgba(30,42,62,0.95)";
        ctx.fillRect(bx, this.H - 20, tw + 10, 16);
        ctx.fillStyle = "#c8d6ea"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
        ctx.fillText(label, bx + 5, this.H - 12);
        ctx.restore();
      }
    }

    _tagList(r, yOf) {
      const d = this.data;
      const tags = [];
      const add = (price, text, fg, bg) => {
        if (price === null || price === undefined || !isFinite(price)) return;
        const y = yOf(price);
        if (y < r.price.y - 6 || y > r.price.y + r.price.h + 6) return;
        tags.push({ y, text, fg, bg });
      };
      (d.levels.supports || []).slice(0, 2).forEach((lv, i) => add(lv.price, `S${i + 1} ${fmt(lv.price)}`, "#7ff0c8", "rgba(9,32,26,0.96)"));
      (d.levels.resistances || []).slice(0, 2).forEach((lv, i) => add(lv.price, `R${i + 1} ${fmt(lv.price)}`, "#ffb3c0", "rgba(40,13,19,0.96)"));
      if (d.plan && d.plan.bias !== "neutral") {
        add(d.plan.stop, `SL ${fmt(d.plan.stop)}`, "#ffb3c0", "rgba(40,13,19,0.96)");
        add(d.plan.t1, `T1 ${fmt(d.plan.t1)}`, "#7ff0c8", "rgba(9,32,26,0.96)");
      }
      const lastC = d.candles[d.candles.length - 1];
      add(lastC[4], fmt(lastC[4]), "#04110c", lastC[4] >= lastC[1] ? UP : DOWN);

      const top = r.price.y + 7, bot = r.price.y + r.price.h - 7;
      const dedup = [];
      for (const t of tags.sort((a, b) => b.y - a.y)) {
        if (dedup.some((x) => Math.abs(x.y - t.y) < 3)) continue;
        dedup.push(t);
      }
      const list = dedup.filter((t) => t.y >= top - 8 && t.y <= bot + 8).sort((a, b) => a.y - b.y);
      let prev = -1e9;
      for (const t of list) { t.y = Math.max(t.y, prev + 15); prev = t.y; }
      if (list.length) {
        const over = list[list.length - 1].y - bot;
        if (over > 0) for (const t of list) t.y -= over;
        const under = top - list[0].y;
        if (under > 0) for (const t of list) t.y += under;
      }
      return list;
    }

    _paintTags(list, r) {
      const ctx = this.ctx;
      ctx.font = '10px "JetBrains Mono", Consolas, monospace';
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      for (const t of list) {
        const w = Math.min(64, ctx.measureText(t.text).width + 9);
        const x = r.price.x + r.price.w + 2;
        ctx.fillStyle = t.bg;
        ctx.fillRect(x, t.y - 7.5, w, 15);
        ctx.strokeStyle = "rgba(255,255,255,0.14)"; ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, t.y - 7, w - 1, 14);
        ctx.fillStyle = t.fg;
        ctx.fillText(t.text, x + 4, t.y);
      }
    }

    _drawTopLegend(start, end) {
      const d = this.data;
      const i = this.hover >= start && this.hover < end ? this.hover : end - 1;
      const c = d.candles[i];
      const ctx = this.ctx;
      ctx.font = MONO_SM; ctx.textBaseline = "middle"; ctx.textAlign = "left";
      let x = 10;
      const up = c[4] >= c[1];
      ctx.fillStyle = up ? UP : DOWN;
      const txt = `${this._time(c[0], true)}  O ${fmt(c[1])}  H ${fmt(c[2])}  L ${fmt(c[3])}  C ${fmt(c[4])}`;
      ctx.fillText(txt, x, 12);
      x += ctx.measureText(txt).width + 18;
      const emas = [["EMA20", d.ema20, "#f6b64b"], ["EMA50", d.ema50, "#6aa6ff"], ["EMA200", d.ema200, "#b28cff"]];
      if (this.cfg.showEMA) {
        for (const [name, arr, color] of emas) {
          if (!arr || arr[i] == null) continue;
          ctx.fillStyle = color;
          const s = `${name} ${fmt(arr[i])}`;
          ctx.fillText(s, x, 12);
          x += ctx.measureText(s).width + 12;
        }
      }
      if (d.rsi && d.rsi[i] != null) {
        ctx.fillStyle = "#b28cff";
        ctx.fillText(`RSI ${d.rsi[i].toFixed(1)}`, x, 12);
      }
    }

    _drawMACD(rect, start, end) {
      if (!this.data.macd_dif || rect.h < 30) return;
      const d = this.data, ctx = this.ctx;
      let hi = 0, lo = 0;
      for (let i = start; i < end; i++) {
        for (const arr of [d.macd_dif, d.macd_dea, d.macd_hist]) {
          const v = arr[i]; if (v == null) continue;
          hi = Math.max(hi, v); lo = Math.min(lo, v);
        }
      }
      if (hi === lo) { hi = 1; lo = -1; }
      const pad = (hi - lo) * 0.12;
      hi += pad; lo -= pad;
      const yOf = (v) => rect.y + (hi - v) / (hi - lo) * rect.h;

      ctx.strokeStyle = GRID; ctx.beginPath();
      const zero = yOf(0);
      ctx.moveTo(rect.x, zero); ctx.lineTo(rect.x + rect.w, zero); ctx.stroke();

      const slot = rect.w / this.view.count;
      const bw = Math.max(1, slot * 0.55);
      for (let i = start; i < end; i++) {
        const v = d.macd_hist[i]; if (v == null) continue;
        const x = this._x(i);
        const y = yOf(v);
        ctx.fillStyle = v >= 0 ? "rgba(47,227,164,0.55)" : "rgba(255,91,118,0.55)";
        ctx.fillRect(x - bw / 2, Math.min(y, zero), bw, Math.max(1, Math.abs(y - zero)));
      }
      const line = (arr, color, w) => {
        ctx.beginPath(); let st = false;
        for (let i = start; i < end; i++) {
          const v = arr[i]; if (v == null) continue;
          const x = this._x(i), y = yOf(v);
          if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = color; ctx.lineWidth = w; ctx.stroke();
      };
      line(d.macd_dif, "#6aa6ff", 1.2);
      line(d.macd_dea, "#f6b64b", 1.2);
      ctx.font = MONO_SM; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillStyle = "#6aa6ff"; ctx.fillText("MACD", rect.x + 2, rect.y + 2);
      ctx.fillStyle = MUTED;
      const i = this.hover >= start && this.hover < end ? this.hover : end - 1;
      if (d.macd_dif[i] != null) {
        ctx.fillText(`DIF ${d.macd_dif[i].toFixed(2)}  DEA ${d.macd_dea[i].toFixed(2)}  HIST ${d.macd_hist[i].toFixed(2)}`, rect.x + 46, rect.y + 2);
      }
    }

    _drawRSI(rect, start, end) {
      if (!this.data.rsi || rect.h < 30) return;
      const d = this.data, ctx = this.ctx;
      const yOf = (v) => rect.y + (100 - v) / 100 * rect.h;
      for (const lv of [30, 50, 70]) {
        ctx.strokeStyle = lv === 50 ? GRID : "rgba(148,170,205,0.13)";
        ctx.setLineDash(lv === 50 ? [] : [3, 4]);
        ctx.beginPath(); ctx.moveTo(rect.x, yOf(lv)); ctx.lineTo(rect.x + rect.w, yOf(lv)); ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(47,227,164,0.06)"; ctx.fillRect(rect.x, yOf(70), rect.w, yOf(30) - yOf(70));
      ctx.beginPath(); let st = false;
      for (let i = start; i < end; i++) {
        const v = d.rsi[i]; if (v == null) continue;
        const x = this._x(i), y = yOf(v);
        if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "#b28cff"; ctx.lineWidth = 1.3; ctx.stroke();
      ctx.font = MONO_SM; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillStyle = "#b28cff"; ctx.fillText("RSI 14", rect.x + 2, rect.y + 2);
      const i = this.hover >= start && this.hover < end ? this.hover : end - 1;
      if (d.rsi[i] != null) {
        ctx.fillStyle = MUTED; ctx.fillText(`${d.rsi[i].toFixed(1)}`, rect.x + 48, rect.y + 2);
        ctx.fillStyle = "rgba(148,170,205,0.45)";
        ctx.fillText("70", rect.x + rect.w + 4, yOf(70) - 5);
        ctx.fillText("30", rect.x + rect.w + 4, yOf(30) - 5);
      }
    }
  }

  window.KChart = KChart;
})();
