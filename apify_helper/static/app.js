/* 短剧数据台前端：图表与首页筛选。依赖本地 chart.umd.min.js。 */
const PAL = {
  ours: '#2a78d6', rival: '#eb6834', other: '#4a3aa7',
  cat: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'],
  seqLight: '#9ec5f4', seq: '#2a78d6', grid: '#e1e0d9', muted: '#898781', ink2: '#52514e',
};
if (window.Chart) {
  Chart.defaults.font.family = '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif';
  Chart.defaults.color = PAL.muted;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.tooltip.backgroundColor = '#1f2328';
  Chart.defaults.plugins.tooltip.padding = 10;
}

const data = () => { const el = document.getElementById('data'); return el ? JSON.parse(el.textContent) : {}; };
const fmtNum = v => v == null ? '—' : Math.abs(v) >= 1e8 ? (v / 1e8).toFixed(2) + '亿' : Math.abs(v) >= 1e4 ? (v / 1e4).toFixed(1) + '万' : Math.round(v).toLocaleString();
const fmtPct = (v, d = 0) => v == null ? '—' : (v * 100).toFixed(d) + '%';
const grpColor = g => g === '自家' ? PAL.ours : g === '竞品' ? PAL.rival : PAL.other;
const shortT = t => (t || '').slice(5, 16);

/* 付费墙竖线：在最后一集免费和第一集付费之间画虚线 */
const paywallPlugin = {
  id: 'paywall',
  afterDraw(chart, _a, opts) {
    if (!opts || !opts.ep) return;
    const idx = chart.data.labels.indexOf(String(opts.ep));
    if (idx < 0 || idx + 1 >= chart.data.labels.length) return;
    const x = (chart.scales.x.getPixelForValue(idx) + chart.scales.x.getPixelForValue(idx + 1)) / 2;
    const { top, bottom } = chart.chartArea, ctx = chart.ctx;
    ctx.save(); ctx.strokeStyle = PAL.rival; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    ctx.fillStyle = PAL.rival; ctx.font = '11px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText('付费墙', x + 4, top + 12); ctx.restore();
  },
};

function baseOpts({ yfmt = fmtNum, legend = false, paywall = null, indexAxis = 'x', ymax } = {}) {
  return {
    responsive: true, maintainAspectRatio: false, indexAxis,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: legend, position: 'top', align: 'end' },
      paywall: { ep: paywall },
      tooltip: { callbacks: { label: c => ` ${c.dataset.label || ''}: ${c.dataset.fmt ? c.dataset.fmt(c.raw) : yfmt(c.raw)}` } },
    },
    scales: {
      x: { grid: { display: false }, border: { color: PAL.grid }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
      y: { beginAtZero: true, max: ymax, grid: { color: PAL.grid }, border: { display: false }, ticks: { callback: v => yfmt(v), maxTicksLimit: 6 } },
    },
  };
}
const line = (color, label, values, extra = {}) => ({
  label, data: values, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: values.length > 40 ? 0 : 3,
  pointHoverRadius: 5, tension: 0.2, spanGaps: true, ...extra,
});
const mk = (id, cfg) => { const el = document.getElementById(id); return el ? new Chart(el, cfg) : null; };

/* ---------- 首页 ---------- */
function initIndex() {
  const d = data();
  if (d.trend && d.trend.length) {
    const days = [...new Set(d.trend.map(r => r.d))].sort();
    const grps = [...new Set(d.trend.map(r => r.grp))].sort((a, b) => (a === '自家' ? -1 : b === '自家' ? 1 : a.localeCompare(b)));
    const ds = grps.map(g => line(grpColor(g), g, days.map(day => { const r = d.trend.find(x => x.d === day && x.grp === g); return r ? r.play : null; })));
    mk('trendChart', { type: 'line', data: { labels: days.map(x => x.slice(5)), datasets: ds }, options: baseOpts({ legend: grps.length > 1 }) });
  }
  if (d.top && d.top.length) {
    mk('topChart', {
      type: 'bar',
      data: { labels: d.top.map(t => t.title.length > 14 ? t.title.slice(0, 13) + '…' : t.title),
        datasets: [{ label: '日增量', data: d.top.map(t => t.delta), backgroundColor: d.top.map(t => grpColor(t.grp)), borderRadius: 4, barThickness: 18 }] },
      options: { ...baseOpts({ indexAxis: 'y' }), onClick: (_e, els) => { if (els.length) location.href = '/series/' + d.top[els[0].index].sid; },
        scales: { x: { grid: { color: PAL.grid }, ticks: { callback: fmtNum, maxTicksLimit: 6 } }, y: { grid: { display: false } } } },
    });
  }
  // 筛选 / 排序 / 搜索
  const cards = [...document.querySelectorAll('#cards .card')];
  let grp = '', q = '';
  const sortSel = document.getElementById('sortSel');
  const apply = () => {
    cards.forEach(c => c.classList.toggle('hide', (grp && c.dataset.grp !== grp) || (q && !c.dataset.title.includes(q))));
    const key = sortSel.value;
    const num = c => { const v = parseFloat(c.dataset[key]); return Number.isNaN(v) ? -Infinity : v; };
    const cmp = (a, b) => key === 'title' ? a.dataset.title.localeCompare(b.dataset.title)
      : key === 'added' ? b.dataset.added.localeCompare(a.dataset.added) : num(b) - num(a);
    cards.sort(cmp).forEach(c => c.parentNode.appendChild(c));
  };
  document.querySelectorAll('#grpChips .chip').forEach(ch => ch.onclick = () => {
    document.querySelectorAll('#grpChips .chip').forEach(x => x.classList.remove('on')); ch.classList.add('on'); grp = ch.dataset.grp; apply();
  });
  sortSel.onchange = apply;
  document.getElementById('searchBox').oninput = e => { q = e.target.value.trim().toLowerCase(); apply(); };
  apply();
}

/* ---------- 剧详情 ---------- */
function initSeries() {
  const d = data();
  if (!d.eps || !d.eps.length) return;
  const labels = d.eps.map(e => String(e.ep));
  mk('epPlayChart', {
    type: 'bar', plugins: [paywallPlugin],
    data: { labels, datasets: [
      { label: '免费集', data: d.eps.map(e => e.preview ? e.play : null), backgroundColor: PAL.seqLight, borderRadius: 4, skipNull: true },
      { label: '付费集', data: d.eps.map(e => e.preview ? null : e.play), backgroundColor: PAL.seq, borderRadius: 4, skipNull: true },
    ] },
    options: { ...baseOpts({ legend: true, paywall: d.paywall }), scales: { ...baseOpts().scales, x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, grid: { color: PAL.grid }, ticks: { callback: fmtNum, maxTicksLimit: 6 } } } },
  });
  const retDs = [line(PAL.ours, d.title, d.eps.map(e => e.ret), { fmt: v => fmtPct(v, 1) })];
  if (d.cmp) retDs.push(line(PAL.rival, d.cmp.title, labels.map(l => { const r = d.cmp.eps.find(e => String(e.ep) === l); return r ? r.ret : null; }), { fmt: v => fmtPct(v, 1), borderDash: [6, 3] }));
  mk('retChart', { type: 'line', plugins: [paywallPlugin], data: { labels, datasets: retDs },
    options: baseOpts({ yfmt: v => fmtPct(v, 0), legend: retDs.length > 1, paywall: d.paywall }) });
  mk('engChart', { type: 'line', plugins: [paywallPlugin],
    data: { labels, datasets: [
      line(PAL.cat[0], '互动率', d.eps.map(e => e.eng), { fmt: v => fmtPct(v, 2) }),
      line(PAL.cat[2], '收藏率', d.eps.map(e => e.collect), { fmt: v => fmtPct(v, 2) }),
    ] },
    options: baseOpts({ yfmt: v => fmtPct(v, 1), legend: true, paywall: d.paywall }) });
  if (d.trend && d.trend.length > 1) {
    mk('trendChart', { type: 'line', data: { labels: d.trend.map(r => shortT(r.t)), datasets: [line(PAL.ours, '总播放', d.trend.map(r => r.play))] },
      options: baseOpts() });
  }
}

/* ---------- 集详情 ---------- */
function initEpisode() {
  const d = data();
  if (d.hist && d.hist.length > 1) {
    const labels = d.hist.map(r => shortT(r.t));
    mk('playHist', { type: 'line', data: { labels, datasets: [line(PAL.ours, '播放', d.hist.map(r => r.play))] }, options: baseOpts() });
    const keys = [['digg', '点赞'], ['comment', '评论'], ['share', '分享'], ['collect', '收藏']];
    const base = d.hist[0];
    mk('engIdx', { type: 'line',
      data: { labels, datasets: keys.map(([k, name], i) => line(PAL.cat[i], name, d.hist.map(r => base[k] ? r[k] / base[k] * 100 : null), { fmt: v => v == null ? '—' : v.toFixed(1) })) },
      options: baseOpts({ yfmt: v => v.toFixed(0), legend: true }) });
  }
  if (d.deltas && d.deltas.length) {
    mk('deltaChart', { type: 'bar',
      data: { labels: d.deltas.map(r => r.d.slice(5)), datasets: [{ label: '播放日增', data: d.deltas.map(r => r.play), backgroundColor: PAL.seq, borderRadius: 4, barThickness: 18 }] },
      options: baseOpts() });
  }
}

/* ---------- 抓取状态轮询：任务结束时自动刷新页面 ---------- */
(function pollStatus() {
  const pill = document.getElementById('jobpill');
  let wasRunning = false;
  const tick = async () => {
    try {
      const r = await (await fetch('/api/status', { cache: 'no-store' })).json();
      pill.hidden = !r.running;
      if (r.running) pill.textContent = `抓取中… ${r.elapsed || 0}s`;
      if (wasRunning && !r.running) location.reload();
      wasRunning = r.running;
    } catch (_) { /* 服务重启中，忽略 */ }
  };
  tick(); setInterval(tick, 5000);
})();
