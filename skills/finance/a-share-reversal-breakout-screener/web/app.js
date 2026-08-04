(function () {
  "use strict";

  var STAGES = ["早期", "确认", "观察", "过热"];
  var COLORS = {
    up: "#ff4d57",
    down: "#22d3c5",
    grid: "#202a38",
    text: "#8593a6",
    cross: "#71809a",
    ma5: "#e8edf4",
    ma10: "#f4c95d",
    ma20: "#ec6be5",
    ma60: "#4d8dff",
    ma120: "#50d890"
  };

  var state = {
    payload: null,
    stage: "早期",
    query: "",
    sort: "secondary_score",
    elasticOnly: false,
    filters: {
      heat: "all",
      trend: "all",
      style: "all",
      limit: "all",
      risk: "all",
      minScore: null,
      maxRsi: null,
      maxDistance: null,
      minBreakout: null,
      minVolume: null,
      focus: "all",
      industry: "all",
      longTrend: "all",
      volumeStructure: "all",
      fundamental: "all",
      announcement: "all",
      minSecondary: null,
      minIndustryRank: null,
      minRs20: null,
      minStockIndustry: null,
      minBreakout60: null,
      minMa60Slope: null
    },
    klineCache: new Map(),
    miniCharts: [],
    largeChart: null,
    observer: null
  };

  var elements = {
    reportMeta: document.getElementById("reportMeta"),
    summary: document.getElementById("summary"),
    stageTabs: document.getElementById("stageTabs"),
    presetSelect: document.getElementById("presetSelect"),
    searchInput: document.getElementById("searchInput"),
    sortSelect: document.getElementById("sortSelect"),
    elasticOnly: document.getElementById("elasticOnly"),
    heatFilter: document.getElementById("heatFilter"),
    trendFilter: document.getElementById("trendFilter"),
    styleFilter: document.getElementById("styleFilter"),
    limitFilter: document.getElementById("limitFilter"),
    riskFilter: document.getElementById("riskFilter"),
    minScoreFilter: document.getElementById("minScoreFilter"),
    maxRsiFilter: document.getElementById("maxRsiFilter"),
    maxDistanceFilter: document.getElementById("maxDistanceFilter"),
    minBreakoutFilter: document.getElementById("minBreakoutFilter"),
    minVolumeFilter: document.getElementById("minVolumeFilter"),
    focusFilter: document.getElementById("focusFilter"),
    industryFilter: document.getElementById("industryFilter"),
    longTrendFilter: document.getElementById("longTrendFilter"),
    volumeStructureFilter: document.getElementById("volumeStructureFilter"),
    fundamentalFilter: document.getElementById("fundamentalFilter"),
    announcementFilter: document.getElementById("announcementFilter"),
    minSecondaryFilter: document.getElementById("minSecondaryFilter"),
    minIndustryRankFilter: document.getElementById("minIndustryRankFilter"),
    minRs20Filter: document.getElementById("minRs20Filter"),
    minStockIndustryFilter: document.getElementById("minStockIndustryFilter"),
    minBreakout60Filter: document.getElementById("minBreakout60Filter"),
    minMa60SlopeFilter: document.getElementById("minMa60SlopeFilter"),
    activeFilterCount: document.getElementById("activeFilterCount"),
    filterSummary: document.getElementById("filterSummary"),
    resetFilters: document.getElementById("resetFilters"),
    visibleCount: document.getElementById("visibleCount"),
    stockGrid: document.getElementById("stockGrid"),
    emptyState: document.getElementById("emptyState"),
    template: document.getElementById("stockCardTemplate"),
    dialog: document.getElementById("chartDialog"),
    dialogCode: document.getElementById("dialogCode"),
    dialogTitle: document.getElementById("dialogTitle"),
    dialogMetrics: document.getElementById("dialogMetrics"),
    dialogClose: document.getElementById("dialogClose"),
    largeChart: document.getElementById("largeChart"),
    largeTooltip: document.getElementById("largeTooltip")
  };

  function number(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "—";
    }
    return Number(value).toFixed(digits === undefined ? 2 : digits);
  }

  function signed(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "—";
    }
    var numeric = Number(value);
    return (numeric > 0 ? "+" : "") + numeric.toFixed(digits === undefined ? 2 : digits) + "%";
  }

  function volume(value) {
    var numeric = Number(value || 0);
    if (numeric >= 100000000) return (numeric / 100000000).toFixed(2) + "亿";
    if (numeric >= 10000) return (numeric / 10000).toFixed(1) + "万";
    return numeric.toFixed(0);
  }

  function finiteOrNull(value) {
    if (value === "" || value === null || value === undefined) return null;
    var numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function emptyFilters() {
    return {
      heat: "all",
      trend: "all",
      style: "all",
      limit: "all",
      risk: "all",
      minScore: null,
      maxRsi: null,
      maxDistance: null,
      minBreakout: null,
      minVolume: null,
      focus: "all",
      industry: "all",
      longTrend: "all",
      volumeStructure: "all",
      fundamental: "all",
      announcement: "all",
      minSecondary: null,
      minIndustryRank: null,
      minRs20: null,
      minStockIndustry: null,
      minBreakout60: null,
      minMa60Slope: null
    };
  }

  function syncFilterControls() {
    elements.searchInput.value = state.query;
    elements.sortSelect.value = state.sort;
    elements.elasticOnly.checked = state.elasticOnly;
    elements.heatFilter.value = state.filters.heat;
    elements.trendFilter.value = state.filters.trend;
    elements.styleFilter.value = state.filters.style;
    elements.limitFilter.value = state.filters.limit;
    elements.riskFilter.value = state.filters.risk;
    elements.minScoreFilter.value = state.filters.minScore === null ? "" : state.filters.minScore;
    elements.maxRsiFilter.value = state.filters.maxRsi === null ? "" : state.filters.maxRsi;
    elements.maxDistanceFilter.value = state.filters.maxDistance === null ? "" : state.filters.maxDistance;
    elements.minBreakoutFilter.value = state.filters.minBreakout === null ? "" : state.filters.minBreakout;
    elements.minVolumeFilter.value = state.filters.minVolume === null ? "" : state.filters.minVolume;
    elements.focusFilter.value = state.filters.focus;
    elements.industryFilter.value = state.filters.industry;
    elements.longTrendFilter.value = state.filters.longTrend;
    elements.volumeStructureFilter.value = state.filters.volumeStructure;
    elements.fundamentalFilter.value = state.filters.fundamental;
    elements.announcementFilter.value = state.filters.announcement;
    elements.minSecondaryFilter.value = state.filters.minSecondary === null ? "" : state.filters.minSecondary;
    elements.minIndustryRankFilter.value = state.filters.minIndustryRank === null ? "" : state.filters.minIndustryRank;
    elements.minRs20Filter.value = state.filters.minRs20 === null ? "" : state.filters.minRs20;
    elements.minStockIndustryFilter.value = state.filters.minStockIndustry === null ? "" : state.filters.minStockIndustry;
    elements.minBreakout60Filter.value = state.filters.minBreakout60 === null ? "" : state.filters.minBreakout60;
    elements.minMa60SlopeFilter.value = state.filters.minMa60Slope === null ? "" : state.filters.minMa60Slope;
  }

  function applyPreset(name) {
    state.query = "";
    state.elasticOnly = false;
    state.stage = "全部";
    state.filters = emptyFilters();
    state.sort = "secondary_score";
    if (name === "technical") {
      state.filters.heat = "正常";
      state.filters.minScore = 85;
      state.filters.maxRsi = 75;
      state.filters.maxDistance = 10;
      state.filters.minBreakout = 0.98;
      state.filters.minVolume = 1.2;
      state.sort = "score";
    } else if (name === "focus") {
      state.filters.focus = "核心观察";
    }
    elements.presetSelect.value = name;
    syncFilterControls();
    renderTabs();
    renderCards();
  }

  function markManual() {
    elements.presetSelect.value = "manual";
  }

  function create(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function tag(text, className) {
    return create("span", "tag" + (className ? " " + className : ""), text);
  }

  function metric(label, value) {
    var box = create("div", "metric");
    box.appendChild(create("span", "", label));
    box.appendChild(create("b", "", value));
    return box;
  }

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (response) {
      if (!response.ok) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          throw new Error(payload.error || ("HTTP " + response.status));
        });
      }
      return response.json();
    });
  }

  function loadKline(code) {
    if (!state.klineCache.has(code)) {
      state.klineCache.set(
        code,
        fetchJson("/api/kline?code=" + encodeURIComponent(code) + "&limit=181")
      );
    }
    return state.klineCache.get(code);
  }

  function tooltipHtml(bar) {
    var color = Number(bar.pct_chg) >= 0 ? COLORS.up : COLORS.down;
    var lines = [
      "<b>" + bar.trade_date + "</b>",
      '<div class="tooltip-grid">',
      "<span>开盘</span><b>" + number(bar.open) + "</b>",
      "<span>最高</span><b>" + number(bar.high) + "</b>",
      "<span>最低</span><b>" + number(bar.low) + "</b>",
      "<span>收盘</span><b>" + number(bar.close) + "</b>",
      '<span>涨跌</span><b style="color:' + color + '">' + signed(bar.pct_chg) + "</b>",
      "<span>振幅</span><b>" + number(bar.amplitude) + "%</b>",
      "<span>成交量</span><b>" + volume(bar.volume) + "</b>",
      '<span style="color:' + COLORS.ma5 + '">MA5</span><b>' + number(bar.ma5) + "</b>",
      '<span style="color:' + COLORS.ma10 + '">MA10</span><b>' + number(bar.ma10) + "</b>",
      '<span style="color:' + COLORS.ma20 + '">MA20</span><b>' + number(bar.ma20) + "</b>",
      '<span style="color:' + COLORS.ma60 + '">MA60</span><b>' + number(bar.ma60) + "</b>",
      '<span style="color:' + COLORS.ma120 + '">MA120</span><b>' + number(bar.ma120) + "</b>",
      "</div>"
    ];
    return lines.join("");
  }

  function InteractiveChart(canvas, tooltip, options) {
    this.canvas = canvas;
    this.tooltip = tooltip;
    this.options = options || {};
    this.bars = [];
    this.visibleCount = this.options.compact ? 72 : 120;
    this.endIndex = -1;
    this.hoverIndex = null;
    this.dragging = false;
    this.dragStartX = 0;
    this.dragStartEnd = 0;
    this.layout = null;
    this.boundMove = this.onMove.bind(this);
    this.boundLeave = this.onLeave.bind(this);
    this.boundWheel = this.onWheel.bind(this);
    this.boundDown = this.onDown.bind(this);
    this.boundUp = this.onUp.bind(this);
    this.boundDouble = this.reset.bind(this);
    this.canvas.addEventListener("mousemove", this.boundMove);
    this.canvas.addEventListener("mouseleave", this.boundLeave);
    this.canvas.addEventListener("wheel", this.boundWheel, { passive: false });
    this.canvas.addEventListener("mousedown", this.boundDown);
    this.canvas.addEventListener("dblclick", this.boundDouble);
    window.addEventListener("mouseup", this.boundUp);
    this.resizeObserver = new ResizeObserver(this.draw.bind(this));
    this.resizeObserver.observe(this.canvas);
  }

  InteractiveChart.prototype.setData = function (bars) {
    this.bars = bars || [];
    this.endIndex = this.bars.length - 1;
    this.visibleCount = Math.min(this.visibleCount, this.bars.length);
    this.hoverIndex = null;
    this.draw();
    this.emitSelected(this.endIndex);
  };

  InteractiveChart.prototype.destroy = function () {
    this.resizeObserver.disconnect();
    this.canvas.removeEventListener("mousemove", this.boundMove);
    this.canvas.removeEventListener("mouseleave", this.boundLeave);
    this.canvas.removeEventListener("wheel", this.boundWheel);
    this.canvas.removeEventListener("mousedown", this.boundDown);
    this.canvas.removeEventListener("dblclick", this.boundDouble);
    window.removeEventListener("mouseup", this.boundUp);
  };

  InteractiveChart.prototype.reset = function () {
    this.visibleCount = Math.min(this.options.compact ? 72 : 120, this.bars.length);
    this.endIndex = this.bars.length - 1;
    this.hoverIndex = null;
    this.hideTooltip();
    this.draw();
    this.emitSelected(this.endIndex);
  };

  InteractiveChart.prototype.emitSelected = function (index) {
    if (this.options.onSelect && this.bars[index]) {
      this.options.onSelect(this.bars[index]);
    }
  };

  InteractiveChart.prototype.onDown = function (event) {
    if (!this.options.zoomable) return;
    this.dragging = true;
    this.dragStartX = event.clientX;
    this.dragStartEnd = this.endIndex;
    this.canvas.style.cursor = "grabbing";
  };

  InteractiveChart.prototype.onUp = function () {
    this.dragging = false;
    this.canvas.style.cursor = "crosshair";
  };

  InteractiveChart.prototype.onWheel = function (event) {
    if (!this.options.zoomable || !this.bars.length) return;
    event.preventDefault();
    var delta = event.deltaY > 0 ? 10 : -10;
    this.visibleCount = Math.max(30, Math.min(this.bars.length, this.visibleCount + delta));
    this.draw();
  };

  InteractiveChart.prototype.onMove = function (event) {
    if (!this.layout || !this.bars.length) return;
    var rect = this.canvas.getBoundingClientRect();
    var x = event.clientX - rect.left;
    var y = event.clientY - rect.top;

    if (this.dragging && this.options.zoomable) {
      var shifted = Math.round((this.dragStartX - event.clientX) / this.layout.step);
      var minimumEnd = Math.max(this.visibleCount - 1, 0);
      this.endIndex = Math.max(
        minimumEnd,
        Math.min(this.bars.length - 1, this.dragStartEnd + shifted)
      );
      this.hoverIndex = null;
      this.hideTooltip();
      this.draw();
      return;
    }

    var layout = this.layout;
    if (x < layout.left || x > layout.right || y < layout.top || y > layout.volumeBottom) {
      this.onLeave();
      return;
    }
    var localIndex = Math.floor((x - layout.left) / layout.step);
    var index = Math.max(layout.start, Math.min(layout.end, layout.start + localIndex));
    if (index !== this.hoverIndex) {
      this.hoverIndex = index;
      this.draw();
      this.emitSelected(index);
    }
    this.showTooltip(index, x, y);
  };

  InteractiveChart.prototype.onLeave = function () {
    if (this.dragging) return;
    this.hoverIndex = null;
    this.hideTooltip();
    this.draw();
    this.emitSelected(this.endIndex);
  };

  InteractiveChart.prototype.showTooltip = function (index, x, y) {
    var bar = this.bars[index];
    if (!bar || !this.tooltip) return;
    this.tooltip.innerHTML = tooltipHtml(bar);
    this.tooltip.style.display = "block";
    var host = this.canvas.parentElement;
    var width = this.tooltip.offsetWidth || 200;
    var height = this.tooltip.offsetHeight || 190;
    var left = x + 14;
    var top = y + 12;
    if (left + width > host.clientWidth - 8) left = x - width - 14;
    if (top + height > host.clientHeight - 8) top = host.clientHeight - height - 8;
    this.tooltip.style.left = Math.max(8, left) + "px";
    this.tooltip.style.top = Math.max(8, top) + "px";
  };

  InteractiveChart.prototype.hideTooltip = function () {
    if (this.tooltip) this.tooltip.style.display = "none";
  };

  InteractiveChart.prototype.draw = function () {
    var rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var ratio = Math.max(1, window.devicePixelRatio || 1);
    var pixelWidth = Math.round(rect.width * ratio);
    var pixelHeight = Math.round(rect.height * ratio);
    if (this.canvas.width !== pixelWidth || this.canvas.height !== pixelHeight) {
      this.canvas.width = pixelWidth;
      this.canvas.height = pixelHeight;
    }
    var ctx = this.canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = "#080c13";
    ctx.fillRect(0, 0, rect.width, rect.height);
    if (!this.bars.length) return;

    var end = Math.min(this.endIndex, this.bars.length - 1);
    var count = Math.min(this.visibleCount, end + 1);
    var start = Math.max(0, end - count + 1);
    var visible = this.bars.slice(start, end + 1);
    var left = this.options.compact ? 6 : 14;
    var right = rect.width - (this.options.compact ? 48 : 64);
    var top = 10;
    var priceBottom = Math.floor(rect.height * .76);
    var volumeTop = priceBottom + 10;
    var volumeBottom = rect.height - 22;
    var step = (right - left) / Math.max(visible.length, 1);
    var bodyWidth = Math.max(1, Math.min(this.options.compact ? 5 : 8, step * .62));

    var prices = [];
    visible.forEach(function (bar) {
      prices.push(Number(bar.high), Number(bar.low));
      ["ma5", "ma10", "ma20", "ma60", "ma120"].forEach(function (key) {
        if (bar[key] !== null && bar[key] !== undefined) prices.push(Number(bar[key]));
      });
    });
    var minPrice = Math.min.apply(null, prices);
    var maxPrice = Math.max.apply(null, prices);
    var padding = Math.max((maxPrice - minPrice) * .08, maxPrice * .005);
    minPrice -= padding;
    maxPrice += padding;
    var priceSpan = Math.max(maxPrice - minPrice, .0001);
    var maxVolume = Math.max.apply(null, visible.map(function (bar) { return Number(bar.volume || 0); }));
    var yPrice = function (value) {
      return top + (maxPrice - Number(value)) / priceSpan * (priceBottom - top);
    };

    ctx.lineWidth = 1;
    ctx.strokeStyle = COLORS.grid;
    ctx.fillStyle = COLORS.text;
    ctx.font = "10px -apple-system, sans-serif";
    ctx.textAlign = "left";
    for (var grid = 0; grid <= 4; grid += 1) {
      var gy = top + (priceBottom - top) * grid / 4;
      ctx.beginPath();
      ctx.moveTo(left, gy + .5);
      ctx.lineTo(right, gy + .5);
      ctx.stroke();
      var priceLabel = maxPrice - priceSpan * grid / 4;
      ctx.fillText(number(priceLabel, 2), right + 5, gy + 3);
    }
    ctx.beginPath();
    ctx.moveTo(left, volumeTop - 5);
    ctx.lineTo(right, volumeTop - 5);
    ctx.stroke();

    visible.forEach(function (bar, localIndex) {
      var x = left + step * localIndex + step / 2;
      var up = Number(bar.close) >= Number(bar.open);
      var color = up ? COLORS.up : COLORS.down;
      var openY = yPrice(bar.open);
      var closeY = yPrice(bar.close);
      var highY = yPrice(bar.high);
      var lowY = yPrice(bar.low);
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x + .5, highY);
      ctx.lineTo(x + .5, lowY);
      ctx.stroke();
      var bodyTop = Math.min(openY, closeY);
      var bodyHeight = Math.max(1, Math.abs(closeY - openY));
      if (up) {
        ctx.strokeRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
      } else {
        ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
      }
      var volumeHeight = maxVolume > 0
        ? Number(bar.volume || 0) / maxVolume * Math.max(1, volumeBottom - volumeTop)
        : 0;
      ctx.globalAlpha = .55;
      ctx.fillRect(x - bodyWidth / 2, volumeBottom - volumeHeight, bodyWidth, volumeHeight);
      ctx.globalAlpha = 1;
    });

    [
      ["ma5", COLORS.ma5],
      ["ma10", COLORS.ma10],
      ["ma20", COLORS.ma20],
      ["ma60", COLORS.ma60],
      ["ma120", COLORS.ma120]
    ].forEach(function (definition) {
      ctx.strokeStyle = definition[1];
      ctx.lineWidth = 1.25;
      ctx.beginPath();
      var started = false;
      visible.forEach(function (bar, localIndex) {
        var value = bar[definition[0]];
        if (value === null || value === undefined) return;
        var x = left + step * localIndex + step / 2;
        var y = yPrice(value);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      if (started) ctx.stroke();
    });

    ctx.fillStyle = COLORS.text;
    ctx.textAlign = "center";
    [0, Math.floor((visible.length - 1) / 2), visible.length - 1].forEach(function (localIndex) {
      var bar = visible[localIndex];
      if (!bar) return;
      var x = left + step * localIndex + step / 2;
      ctx.fillText(bar.trade_date.slice(5), x, rect.height - 6);
    });

    this.layout = {
      left: left,
      right: right,
      top: top,
      priceBottom: priceBottom,
      volumeBottom: volumeBottom,
      step: step,
      start: start,
      end: end,
      yPrice: yPrice
    };

    if (this.hoverIndex !== null && this.hoverIndex >= start && this.hoverIndex <= end) {
      var hoverBar = this.bars[this.hoverIndex];
      var hoverLocal = this.hoverIndex - start;
      var hoverX = left + step * hoverLocal + step / 2;
      var hoverY = yPrice(hoverBar.close);
      ctx.save();
      ctx.strokeStyle = COLORS.cross;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(hoverX, top);
      ctx.lineTo(hoverX, volumeBottom);
      ctx.moveTo(left, hoverY);
      ctx.lineTo(right, hoverY);
      ctx.stroke();
      ctx.restore();
      ctx.fillStyle = "#2a3547";
      ctx.fillRect(right, hoverY - 9, rect.width - right, 18);
      ctx.fillStyle = "#f3f6fa";
      ctx.textAlign = "left";
      ctx.fillText(number(hoverBar.close), right + 4, hoverY + 3);
    }
  };

  function allCandidates() {
    var result = [];
    STAGES.forEach(function (stage) {
      result = result.concat(state.payload.groups[stage] || []);
    });
    return result;
  }

  function filteredCandidates() {
    var rows = state.stage === "全部"
      ? allCandidates()
      : (state.payload.groups[state.stage] || []).slice();
    var query = state.query.trim().toLowerCase();
    if (query) {
      rows = rows.filter(function (item) {
        return String(item.code).toLowerCase().includes(query)
          || String(item.name).toLowerCase().includes(query);
      });
    }
    if (state.elasticOnly) {
      rows = rows.filter(function (item) { return item.high_elasticity; });
    }
    if (state.filters.heat !== "all") {
      rows = rows.filter(function (item) { return item.heat === state.filters.heat; });
    }
    if (state.filters.trend !== "all") {
      rows = rows.filter(function (item) { return item.trend === state.filters.trend; });
    }
    if (state.filters.style !== "all") {
      rows = rows.filter(function (item) { return item.style === state.filters.style; });
    }
    if (state.filters.focus !== "all") {
      rows = rows.filter(function (item) { return item.focus_tier === state.filters.focus; });
    }
    if (state.filters.industry !== "all") {
      rows = rows.filter(function (item) { return item.industry === state.filters.industry; });
    }
    if (state.filters.longTrend !== "all") {
      rows = rows.filter(function (item) { return item.long_trend === state.filters.longTrend; });
    }
    if (state.filters.volumeStructure !== "all") {
      rows = rows.filter(function (item) { return item.volume_structure === state.filters.volumeStructure; });
    }
    if (state.filters.fundamental === "usable") {
      rows = rows.filter(function (item) {
        return item.fundamental_status !== "数据缺失" && !item.fundamental_hard_risk;
      });
    } else if (state.filters.fundamental !== "all") {
      rows = rows.filter(function (item) {
        return item.fundamental_status === state.filters.fundamental;
      });
    }
    if (state.filters.announcement === "clean") {
      rows = rows.filter(function (item) { return item.announcement_risk === false; });
    } else if (state.filters.announcement === "flagged") {
      rows = rows.filter(function (item) { return item.announcement_risk === true; });
    } else if (state.filters.announcement === "missing") {
      rows = rows.filter(function (item) { return item.announcement_risk === null; });
    }
    if (state.filters.limit === "yes") {
      rows = rows.filter(function (item) { return item.limit_up; });
    } else if (state.filters.limit === "no") {
      rows = rows.filter(function (item) { return !item.limit_up; });
    }
    if (state.filters.risk === "clean") {
      rows = rows.filter(function (item) {
        return item.risks === "未触发脚本内主要风险阈值";
      });
    } else if (state.filters.risk === "flagged") {
      rows = rows.filter(function (item) {
        return item.risks !== "未触发脚本内主要风险阈值";
      });
    }
    if (state.filters.minScore !== null) {
      rows = rows.filter(function (item) {
        return Number(item.score) >= state.filters.minScore;
      });
    }
    if (state.filters.maxRsi !== null) {
      rows = rows.filter(function (item) {
        return item.rsi6 !== null && Number(item.rsi6) <= state.filters.maxRsi;
      });
    }
    if (state.filters.maxDistance !== null) {
      rows = rows.filter(function (item) {
        return item.distance_ma20_pct !== null
          && Number(item.distance_ma20_pct) <= state.filters.maxDistance;
      });
    }
    if (state.filters.minBreakout !== null) {
      rows = rows.filter(function (item) {
        return item.breakout_ratio !== null
          && Number(item.breakout_ratio) >= state.filters.minBreakout;
      });
    }
    if (state.filters.minVolume !== null) {
      rows = rows.filter(function (item) {
        return item.volume_ratio !== null
          && Number(item.volume_ratio) >= state.filters.minVolume;
      });
    }
    if (state.filters.minSecondary !== null) {
      rows = rows.filter(function (item) {
        return Number(item.secondary_score) >= state.filters.minSecondary;
      });
    }
    if (state.filters.minIndustryRank !== null) {
      rows = rows.filter(function (item) {
        return item.industry_rank_pct !== null
          && Number(item.industry_rank_pct) >= state.filters.minIndustryRank;
      });
    }
    if (state.filters.minRs20 !== null) {
      rows = rows.filter(function (item) {
        return item.rs20_benchmark_pct !== null
          && Number(item.rs20_benchmark_pct) >= state.filters.minRs20;
      });
    }
    if (state.filters.minStockIndustry !== null) {
      rows = rows.filter(function (item) {
        return item.stock_vs_industry_20d_pct !== null
          && Number(item.stock_vs_industry_20d_pct) >= state.filters.minStockIndustry;
      });
    }
    if (state.filters.minBreakout60 !== null) {
      rows = rows.filter(function (item) {
        return item.breakout_60d_ratio !== null
          && Number(item.breakout_60d_ratio) >= state.filters.minBreakout60;
      });
    }
    if (state.filters.minMa60Slope !== null) {
      rows = rows.filter(function (item) {
        return item.ma60_slope_10d_pct !== null
          && Number(item.ma60_slope_10d_pct) >= state.filters.minMa60Slope;
      });
    }
    var key = state.sort;
    rows.sort(function (a, b) {
      if (key === "code") return String(a.code).localeCompare(String(b.code));
      return Number(b[key] || 0) - Number(a[key] || 0);
    });
    return rows;
  }

  function activeFilterDescriptions() {
    var descriptions = [];
    if (state.query.trim()) descriptions.push("搜索=" + state.query.trim());
    if (state.elasticOnly) descriptions.push("高弹性");
    if (state.filters.heat !== "all") descriptions.push("heat=" + state.filters.heat);
    if (state.filters.trend !== "all") descriptions.push("trend=" + state.filters.trend);
    if (state.filters.style !== "all") descriptions.push("style=" + state.filters.style);
    if (state.filters.focus !== "all") descriptions.push("二次层级=" + state.filters.focus);
    if (state.filters.industry !== "all") descriptions.push("行业=" + state.filters.industry);
    if (state.filters.longTrend !== "all") descriptions.push("长周期=" + state.filters.longTrend);
    if (state.filters.volumeStructure !== "all") descriptions.push("量价=" + state.filters.volumeStructure);
    if (state.filters.fundamental !== "all") descriptions.push("基本面=" + state.filters.fundamental);
    if (state.filters.announcement !== "all") descriptions.push("公告=" + state.filters.announcement);
    if (state.filters.limit === "yes") descriptions.push("仅涨停");
    if (state.filters.limit === "no") descriptions.push("排除涨停");
    if (state.filters.risk === "clean") descriptions.push("无主要风险");
    if (state.filters.risk === "flagged") descriptions.push("有风险提示");
    if (state.filters.minScore !== null) descriptions.push("分数≥" + state.filters.minScore);
    if (state.filters.maxRsi !== null) descriptions.push("RSI≤" + state.filters.maxRsi);
    if (state.filters.maxDistance !== null) descriptions.push("MA20乖离≤" + state.filters.maxDistance + "%");
    if (state.filters.minBreakout !== null) descriptions.push("突破比≥" + state.filters.minBreakout);
    if (state.filters.minVolume !== null) descriptions.push("量能≥" + state.filters.minVolume + "x");
    if (state.filters.minSecondary !== null) descriptions.push("二次分≥" + state.filters.minSecondary);
    if (state.filters.minIndustryRank !== null) descriptions.push("行业强度≥" + state.filters.minIndustryRank + "%");
    if (state.filters.minRs20 !== null) descriptions.push("RS20≥" + state.filters.minRs20 + "%");
    if (state.filters.minStockIndustry !== null) descriptions.push("超行业≥" + state.filters.minStockIndustry + "%");
    if (state.filters.minBreakout60 !== null) descriptions.push("60日突破≥" + state.filters.minBreakout60);
    if (state.filters.minMa60Slope !== null) descriptions.push("MA60斜率≥" + state.filters.minMa60Slope + "%");
    return descriptions;
  }

  function updateFilterStatus() {
    var descriptions = activeFilterDescriptions();
    elements.activeFilterCount.textContent = descriptions.length + "项已启用";
    elements.activeFilterCount.classList.toggle("active", descriptions.length > 0);
    elements.filterSummary.textContent = descriptions.length
      ? "当前：" + descriptions.join(" · ")
      : "未启用指标筛选";
  }

  function populateIndustryOptions() {
    elements.industryFilter.querySelectorAll("option:not(:first-child)").forEach(function (option) {
      option.remove();
    });
    (state.payload.industries || []).forEach(function (industry) {
      var option = document.createElement("option");
      option.value = industry;
      option.textContent = industry;
      elements.industryFilter.appendChild(option);
    });
  }

  function renderSummary() {
    elements.summary.textContent = "";
    var totalCard = create("div", "summary-card");
    totalCard.appendChild(create("span", "", "全部候选"));
    totalCard.appendChild(create("strong", "", String(state.payload.total)));
    elements.summary.appendChild(totalCard);
    var focusCard = create("div", "summary-card");
    focusCard.dataset.stage = "核心观察";
    focusCard.appendChild(create("span", "", "二次精选"));
    focusCard.appendChild(create(
      "strong", "", String((state.payload.focus_counts || {})["核心观察"] || 0)
    ));
    focusCard.addEventListener("click", function () { applyPreset("focus"); });
    elements.summary.appendChild(focusCard);
    STAGES.forEach(function (stage) {
      var card = create("div", "summary-card");
      card.dataset.stage = stage;
      card.appendChild(create("span", "", stage));
      card.appendChild(create("strong", "", String(state.payload.counts[stage] || 0)));
      card.addEventListener("click", function () {
        markManual();
        state.stage = stage;
        renderTabs();
        renderCards();
      });
      elements.summary.appendChild(card);
    });
  }

  function renderTabs() {
    elements.stageTabs.textContent = "";
    ["早期", "确认", "观察", "过热", "全部"].forEach(function (stage) {
      var count = stage === "全部" ? state.payload.total : state.payload.counts[stage];
      var button = create("button", "stage-tab" + (state.stage === stage ? " active" : ""));
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", state.stage === stage ? "true" : "false");
      button.appendChild(document.createTextNode(stage));
      button.appendChild(create("b", "", String(count || 0)));
      button.addEventListener("click", function () {
        markManual();
        state.stage = stage;
        renderTabs();
        renderCards();
      });
      elements.stageTabs.appendChild(button);
    });
  }

  function renderCard(candidate) {
    var fragment = elements.template.content.cloneNode(true);
    var card = fragment.querySelector(".stock-card");
    card.dataset.code = candidate.code;
    card.querySelector(".stock-name").textContent = candidate.name;
    card.querySelector(".stock-code").textContent = candidate.code;
    card.querySelector(".score-badge").textContent = candidate.score;
    card.querySelector(".last-price").textContent = number(candidate.close);
    var pct = card.querySelector(".pct-change");
    pct.textContent = signed(candidate.pct_chg);
    pct.classList.add(Number(candidate.pct_chg) >= 0 ? "up" : "down");
    card.querySelector(".trade-date").textContent = candidate.trade_date;
    card.querySelector(".reasons").textContent = candidate.reasons;
    card.querySelector(".secondary-evidence").textContent = [
      "二次评分 " + candidate.secondary_score,
      "行业 " + (candidate.industry || "未分类"),
      "行业强度 " + number(candidate.industry_rank_pct, 0) + "%",
      "RS20 " + signed(candidate.rs20_benchmark_pct, 1),
      "超行业 " + signed(candidate.stock_vs_industry_20d_pct, 1),
      "长周期 " + candidate.long_trend
    ].join("；");
    card.querySelector(".fundamental-notes").textContent =
      "基本面：" + candidate.fundamental_status + "；" + candidate.fundamental_notes;
    card.querySelector(".announcement-notes").textContent =
      "公告：" + candidate.announcement_notes;
    card.querySelector(".risks").textContent = candidate.risks;

    var tags = card.querySelector(".stock-tags");
    tags.appendChild(tag(candidate.stage));
    tags.appendChild(tag(candidate.trend));
    tags.appendChild(tag(candidate.style));
    tags.appendChild(tag(candidate.focus_tier, candidate.focus_tier === "核心观察" ? "focus" : ""));
    tags.appendChild(tag(candidate.industry || "未分类"));
    tags.appendChild(tag(candidate.long_trend));
    tags.appendChild(tag(
      "基本面" + candidate.fundamental_status,
      candidate.fundamental_hard_risk ? "risk" : candidate.fundamental_status === "正常" ? "good" : ""
    ));
    if (candidate.announcement_risk === true) tags.appendChild(tag("公告风险", "risk"));
    if (candidate.high_elasticity) tags.appendChild(tag("高弹性", "elastic"));
    if (candidate.limit_up) tags.appendChild(tag("涨停", "limit"));
    if (candidate.heat !== "正常") tags.appendChild(tag(candidate.heat, candidate.heat === "过热" ? "hot" : ""));

    var metrics = card.querySelector(".card-metrics");
    metrics.appendChild(metric("RSI6", number(candidate.rsi6, 1)));
    metrics.appendChild(metric("突破比", number(candidate.breakout_ratio, 3)));
    metrics.appendChild(metric("MA20乖离", number(candidate.distance_ma20_pct, 1) + "%"));
    metrics.appendChild(metric("量能", number(candidate.volume_ratio, 2) + "x"));
    metrics.appendChild(metric("换手", number(candidate.turnover, 2) + "%"));
    metrics.appendChild(metric("回撤", number(candidate.max_drawdown_pct, 1) + "%"));
    metrics.appendChild(metric("流通市值", number(candidate.float_cap_yi, 0) + "亿"));
    metrics.appendChild(metric("5日涨幅", signed(candidate.return_5d_pct, 1)));
    metrics.appendChild(metric("二次评分", String(candidate.secondary_score)));
    metrics.appendChild(metric("行业强度", number(candidate.industry_rank_pct, 0) + "%"));
    metrics.appendChild(metric("RS20", signed(candidate.rs20_benchmark_pct, 1)));
    metrics.appendChild(metric("超行业", signed(candidate.stock_vs_industry_20d_pct, 1)));
    metrics.appendChild(metric("MA60斜率", signed(candidate.ma60_slope_10d_pct, 1)));
    metrics.appendChild(metric("60日突破", number(candidate.breakout_60d_ratio, 3)));
    metrics.appendChild(metric("量价结构", candidate.volume_structure));
    metrics.appendChild(metric("基本面", candidate.fundamental_status));

    var wrap = card.querySelector(".mini-chart-wrap");
    wrap.dataset.code = candidate.code;
    wrap._candidate = candidate;
    wrap.addEventListener("click", function () { openLarge(candidate); });
    wrap.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openLarge(candidate);
      }
    });
    return fragment;
  }

  function destroyMiniCharts() {
    state.miniCharts.forEach(function (chart) { chart.destroy(); });
    state.miniCharts = [];
    if (state.observer) state.observer.disconnect();
  }

  function renderCards() {
    if (!state.payload) return;
    destroyMiniCharts();
    var rows = filteredCandidates();
    updateFilterStatus();
    elements.stockGrid.textContent = "";
    elements.visibleCount.textContent = rows.length + "只";
    elements.emptyState.hidden = rows.length > 0;
    var batch = document.createDocumentFragment();
    rows.forEach(function (candidate) { batch.appendChild(renderCard(candidate)); });
    elements.stockGrid.appendChild(batch);

    state.observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        state.observer.unobserve(entry.target);
        loadMiniChart(entry.target);
      });
    }, { rootMargin: "500px 0px" });
    elements.stockGrid.querySelectorAll(".mini-chart-wrap").forEach(function (wrap) {
      state.observer.observe(wrap);
    });
  }

  function loadMiniChart(wrap) {
    var code = wrap.dataset.code;
    var canvas = wrap.querySelector(".mini-chart");
    var tooltip = wrap.querySelector(".chart-tooltip");
    var status = wrap.querySelector(".chart-status");
    loadKline(code).then(function (payload) {
      status.style.display = "none";
      var chart = new InteractiveChart(canvas, tooltip, { compact: true, zoomable: false });
      chart.setData(payload.bars);
      state.miniCharts.push(chart);
    }).catch(function (error) {
      status.textContent = "日K加载失败：" + error.message;
    });
  }

  function dialogMetricText(bar) {
    if (!bar) return "";
    return [
      bar.trade_date,
      "开 " + number(bar.open),
      "高 " + number(bar.high),
      "低 " + number(bar.low),
      "收 " + number(bar.close),
      "涨跌 " + signed(bar.pct_chg),
      "振幅 " + number(bar.amplitude) + "%",
      "成交量 " + volume(bar.volume),
      "MA5 " + number(bar.ma5),
      "MA10 " + number(bar.ma10),
      "MA20 " + number(bar.ma20),
      "MA60 " + number(bar.ma60),
      "MA120 " + number(bar.ma120)
    ].join("　");
  }

  function openLarge(candidate) {
    elements.dialogCode.textContent = candidate.code + " · " + candidate.stage + " · " + candidate.score + "分";
    elements.dialogTitle.textContent = candidate.name;
    elements.dialogMetrics.textContent = "正在加载日K…";
    elements.largeTooltip.style.display = "none";
    if (!elements.dialog.open) elements.dialog.showModal();
    loadKline(candidate.code).then(function (payload) {
      if (state.largeChart) state.largeChart.destroy();
      state.largeChart = new InteractiveChart(elements.largeChart, elements.largeTooltip, {
        compact: false,
        zoomable: true,
        onSelect: function (bar) {
          elements.dialogMetrics.textContent = dialogMetricText(bar);
        }
      });
      state.largeChart.setData(payload.bars);
    }).catch(function (error) {
      elements.dialogMetrics.textContent = "日K加载失败：" + error.message;
    });
  }

  function closeDialog() {
    if (state.largeChart) {
      state.largeChart.destroy();
      state.largeChart = null;
    }
    if (elements.dialog.open) elements.dialog.close();
  }

  function bindControls() {
    elements.presetSelect.addEventListener("change", function (event) {
      applyPreset(event.target.value);
    });
    elements.searchInput.addEventListener("input", function (event) {
      markManual();
      state.query = event.target.value;
      renderCards();
    });
    elements.sortSelect.addEventListener("change", function (event) {
      markManual();
      state.sort = event.target.value;
      renderCards();
    });
    elements.elasticOnly.addEventListener("change", function (event) {
      markManual();
      state.elasticOnly = event.target.checked;
      renderCards();
    });
    [
      [elements.heatFilter, "heat"],
      [elements.trendFilter, "trend"],
      [elements.styleFilter, "style"],
      [elements.limitFilter, "limit"],
      [elements.riskFilter, "risk"],
      [elements.focusFilter, "focus"],
      [elements.industryFilter, "industry"],
      [elements.longTrendFilter, "longTrend"],
      [elements.volumeStructureFilter, "volumeStructure"],
      [elements.fundamentalFilter, "fundamental"],
      [elements.announcementFilter, "announcement"]
    ].forEach(function (binding) {
      binding[0].addEventListener("change", function (event) {
        markManual();
        state.filters[binding[1]] = event.target.value;
        renderCards();
      });
    });
    [
      [elements.minScoreFilter, "minScore"],
      [elements.maxRsiFilter, "maxRsi"],
      [elements.maxDistanceFilter, "maxDistance"],
      [elements.minBreakoutFilter, "minBreakout"],
      [elements.minVolumeFilter, "minVolume"],
      [elements.minSecondaryFilter, "minSecondary"],
      [elements.minIndustryRankFilter, "minIndustryRank"],
      [elements.minRs20Filter, "minRs20"],
      [elements.minStockIndustryFilter, "minStockIndustry"],
      [elements.minBreakout60Filter, "minBreakout60"],
      [elements.minMa60SlopeFilter, "minMa60Slope"]
    ].forEach(function (binding) {
      binding[0].addEventListener("input", function (event) {
        markManual();
        state.filters[binding[1]] = finiteOrNull(event.target.value);
        renderCards();
      });
    });
    elements.resetFilters.addEventListener("click", function () {
      applyPreset("manual");
    });
    elements.dialogClose.addEventListener("click", closeDialog);
    elements.dialog.addEventListener("click", function (event) {
      if (event.target === elements.dialog) closeDialog();
    });
    elements.dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeDialog();
    });
  }

  function showFatal(error) {
    elements.reportMeta.textContent = "加载失败：" + error.message;
    elements.reportMeta.style.color = COLORS.up;
    elements.emptyState.hidden = false;
    elements.emptyState.textContent = "无法读取筛选结果，请确认本地服务日志。";
  }

  bindControls();
  fetchJson("/api/groups").then(function (payload) {
    state.payload = payload;
    elements.reportMeta.textContent =
      "数据日 " + (payload.data_date || "—")
      + " · " + payload.report
      + " · 共 " + payload.total + " 只"
      + " · 核心观察 " + ((payload.focus_counts || {})["核心观察"] || 0) + " 只";
    renderSummary();
    populateIndustryOptions();
    applyPreset(((payload.focus_counts || {})["核心观察"] || 0) > 0 ? "focus" : "technical");
  }).catch(showFatal);
}());
