// Run in the page context of tiktokdramacenter.com/analytics/content-performance
// (after the page fully loads). Walks the React fiber tree and returns the
// institution daily series as a JSON string. Chunk the result if it exceeds
// the ~1000-char tool output limit: run once storing to window.__dump, then
// read window.__dump.slice(i, i+1000) repeatedly.
const rootEl = [...document.querySelectorAll('*')].find(el => Object.keys(el).some(k => k.startsWith('__reactContainer$')));
const rootKey = Object.keys(rootEl).find(k => k.startsWith('__reactContainer$'));
let queue = [rootEl[rootKey]], seen = new Set();
let daily = null;
const isDaily = a => Array.isArray(a) && a.length && a[0] && a[0].eventDate && a[0].metrics && !a[0].collectionID;
let n = 0;
while (queue.length && n < 50000) {
  const f = queue.shift(); n++;
  if (!f || seen.has(f)) continue; seen.add(f);
  try {
    for (const c of [f.memoizedProps, f.memoizedState]) {
      if (!c || typeof c !== 'object') continue;
      const vals = [c, ...Object.values(c).filter(v => v && typeof v === 'object')];
      for (const v of vals) {
        if (isDaily(v) && (!daily || v.length > daily.length)) daily = v;
        if (typeof v === 'object') for (const vv of Object.values(v))
          if (isDaily(vv) && (!daily || vv.length > daily.length)) daily = vv;
      }
    }
  } catch (e) {}
  if (f.child) queue.push(f.child);
  if (f.sibling) queue.push(f.sibling);
}
window.__dump = JSON.stringify({daily});
`length=${window.__dump.length} days=${daily ? daily.length : 0}`
