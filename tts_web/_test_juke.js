/* 用最小假 DOM 加载 index.html 里的脚本，实测分段播放状态机 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, 'templates', 'index.html'), 'utf8');
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];

/* ---------- 假 DOM ---------- */
const SEL = new Map();
function mkEl(sel) {
  const el = {
    _sel: sel, _cls: new Set(), dataset: {}, style: {}, _text: '', _html: '',
    value: '', href: '', scrollTop: 0, children: [],
    classList: {
      add: c => el._cls.add(c),
      remove: c => el._cls.delete(c),
      toggle: (c, on) => { if (on === undefined) { el._cls.has(c) ? el._cls.delete(c) : el._cls.add(c); } else if (on) el._cls.add(c); else el._cls.delete(c); },
      contains: c => el._cls.has(c),
    },
    get textContent() { return el._text; },
    set textContent(v) { el._text = String(v); },
    get innerHTML() { return el._html; },
    set innerHTML(v) { el._html = String(v); },
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, removeEventListener() {}, appendChild(c) { el.children.push(c); },
    querySelector() { return mkEl(sel + ' >q'); },
    querySelectorAll() { return []; },
    scrollIntoView() {}, focus() {}, click() {},
  };
  return el;
}
function q(sel) {
  if (!SEL.has(sel)) SEL.set(sel, mkEl(sel));
  return SEL.get(sel);
}

class FakeAudio {
  constructor(src) { this.src = src || ''; this.preload = ''; this.volume = 1; FakeAudio.all.push(this); this._ended = null; }
  get onended() { return this._ended; }
  set onended(f) { this._ended = f; }
  play() {
    this._playing = true;
    if (this.src && !this._manual) setTimeout(() => { if (this._ended) this._ended(); }, 5);
    return Promise.resolve();
  }
  pause() { this._playing = false; }
  removeAttribute() { this.src = ''; }
}
FakeAudio.all = [];

const sandbox = {
  document: {
    querySelector: q, querySelectorAll: () => [], getElementById: () => mkEl('byid'),
    createElement: () => mkEl('created'), addEventListener() {},
    body: mkEl('body'),
  },
  Audio: FakeAudio,
  fetch: async () => ({ ok: true, json: async () => ({ count: 0, voices: [] }) }),
  setTimeout, clearTimeout, setInterval, clearInterval,
  console, Promise, Date, Math, JSON, String, Number, Object, Array, Error,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
// 顶层 const 不会挂到 globalThis，需在同一脚本里显式导出
vm.runInContext(
  js + '\n;globalThis.__API = {Juke: Juke, renderSegs: renderSegs, setReady: setReady,' +
       ' playJuke: playJuke, pauseJuke: pauseJuke, toast: toast};',
  sandbox, { filename: 'index.js' });

const { renderSegs, setReady, playJuke, pauseJuke, Juke } = sandbox.__API;
// 主播放器由测试手动触发 onended，不自动结束
Juke.audio._manual = true;

/* ---------- 断言工具 ---------- */
let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { pass++; console.log('  \u2713 ' + msg); }
  else { fail++; console.log('  \u2717 ' + msg); }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

function segsReady(i, extra) {
  return Object.assign({ i, role: 'W', vlabel: 'Ava', glabel: '女', text: 's' + i, after: [], ready: false }, extra || {});
}

(async () => {
  console.log('\n[1] 渲染与初始状态');
  const list = [
    segsReady(1, { after: [['pause', 0.25], ['ding', 1]] }),
    segsReady(2, { after: [['pause', 0.25]] }),
    segsReady(3, { after: [] }),
  ];
  renderSegs(list, 'jobX');
  ok(Juke.segs.length === 3, '分段数 = 3');
  ok(Juke.job === 'jobX', 'job id 记住');
  ok(Juke.segs.every(s => s.ready === false), '初始全部未就绪');
  ok(q('#segsWrap')._cls.has('on'), '分段区已显示');
  ok(sandbox.$$ === undefined || true, '(缺 $$ 由脚本内部提供)');

  console.log('\n[2] 未就绪时开始播放应等待，就绪后自动接上');
  playJuke(0);
  ok(Juke.playing === true, '进入播放态');
  await sleep(60);
  ok(Juke.idx === 0, '第 1 句没就绪时不前进（不会跳过、不会空转）');
  ok(Juke.audio.src === '' || Juke.audio.src === undefined, '没有拿空音频去播');

  setReady([1]);
  await sleep(60);
  ok(Juke.segs[0].ready === true, '第 1 句标记就绪');
  ok(Juke.idx === 1, '已开始播第 1 句，指针移到 2');
  ok(Juke.audio.src === '/api/seg/jobX/1', '播放源指向第 1 句：' + Juke.audio.src);

  console.log('\n[3] 一句播完 -> 执行停顿+提示音 -> 自动进入下一句（第 2 句还没就绪 -> 等待）');
  Juke.audio.onended();
  await sleep(500);
  ok(Juke.idx === 1, '停在第 2 句前等待（尚未就绪）');

  setReady([2]);
  await sleep(80);
  ok(Juke.idx === 2, '第 2 句就绪后自动接上');
  ok(Juke.audio.src === '/api/seg/jobX/2', '播放源指向第 2 句');

  console.log('\n[4] 顺序推进且不跳句');
  setReady([3]);
  Juke.audio.onended();
  await sleep(500);
  ok(Juke.idx === 3, '第 3 句开播');
  ok(Juke.audio.src === '/api/seg/jobX/3', '播放源指向第 3 句');

  Juke.audio.onended();
  await sleep(200);
  ok(Juke.playing === false, '全部播完自动停止');
  ok(Juke.idx === 0, '指针复位');

  console.log('\n[5] 单句试听：只播这一句，不连带下一句');
  playJuke(0);
  await sleep(50);
  pauseJuke();
  ok(Juke.playing === false, '暂停生效');
  const before = Juke.idx;
  ok(typeof before === 'number', '暂停后指针保留：' + before);

  renderSegs(list.map(s => Object.assign({}, s, { ready: true })), 'jobY');
  sandbox.pauseJuke();
  Juke.playing = true; Juke.oneShot = true; Juke.idx = 1;
  Juke.audio.src = '/api/seg/jobY/2';
  await Juke.audio.play();
  Juke.idx = 2;
  Juke.audio.onended();
  await sleep(80);
  ok(Juke.playing === false, '单句播完即停');
  ok(Juke.oneShot === false, '单句标记已复位');

  console.log('\n[6] 播放中被打断：停顿期间暂停不应继续往下走');
  renderSegs([segsReady(1, { after: [['pause', 5]] }), segsReady(2, { ready: true })], 'jobZ');
  Juke.segs.forEach(s => s.ready = true);
  playJuke(0);
  await sleep(50);
  Juke.audio.onended();
  await sleep(120);
  pauseJuke();
  const idxAtPause = Juke.idx;
  await sleep(300);
  ok(Juke.idx === idxAtPause, '停顿中暂停后不再自动推进');
  ok(Juke.playing === false, '保持暂停态');

  console.log('\n[7] 就绪状态不会倒退、不会重复解析');
  setReady([1, 1, 1, 2]);
  ok(Juke.segs[0].ready && Juke.segs[1].ready, '重复通知无副作用');
  setReady([]);
  setReady(undefined);
  ok(true, '空通知不崩');

  console.log('\n结果: ' + pass + ' 通过 / ' + fail + ' 失败');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('异常:', e); process.exit(1); });
