'use strict';
/* Geometry harness for the Requisições floating action bar.
 *
 * Runs the REAL script extracted from templates/admin_requisicoes.html against a
 * minimal DOM whose only layout model is the width contract declared in
 * static/css/components/actions-float.css (plus the `.act-count` rule inlined in
 * the template).  Nothing about positioning is reimplemented here: `left` comes
 * from the shipped `positionFor`.
 *
 * Why a hand-built DOM: the repo has no browser automation and no node_modules,
 * and jsdom performs no layout (offsetWidth would be 0 there anyway).  The width
 * model below is therefore the honest substitute -- it is derived from CSS the
 * test also asserts, so a CSS change that invalidates it is caught.
 *
 * Usage:  node requisicoes_floating_bar_harness.js <repo-root>
 * Output: one JSON document on stdout (see SCENARIOS at the bottom).
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = process.argv[2] || path.resolve(__dirname, '..', '..');
const TPL = path.join(REPO, 'templates', 'admin_requisicoes.html');
const CSS_FILE = path.join(REPO, 'static', 'css', 'components', 'actions-float.css');

// ---------------------------------------------------------------- CSS model --
/* Parsed, not hardcoded, so the harness fails loudly if the contract moves. */
function readCssContract(){
  const css = fs.readFileSync(CSS_FILE, 'utf8');
  const num = (re, label) => {
    const m = css.match(re);
    if (!m) throw new Error(`actions-float.css: cannot read ${label}`);
    return parseFloat(m[1]);
  };
  return {
    btn: num(/--pedido-float-btn:\s*(\d+(?:\.\d+)?)px/, '--pedido-float-btn'),
    gap: num(/display:\s*flex;\s*gap:\s*(\d+(?:\.\d+)?)px/, 'flex gap'),
    padX: num(/padding:\s*\d+(?:\.\d+)?px\s+(\d+(?:\.\d+)?)px;\s*border:/, 'bar padding-x'),
    border: num(/border:\s*(\d+(?:\.\d+)?)px solid var\(--border-strong\)/, 'bar border'),
    barH: 34,
    // `.act-count` lives inline in the template (min-width 22px + margin-right 2px).
    countW: 22,
    countMargin: 2,
  };
}
const CSS = readCssContract();

// -------------------------------------------------------------------- DOM ----
const TRACE = [];

function parseAttrs(str){
  const attrs = {};
  const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'))?/g;
  let m;
  while ((m = re.exec(str))) attrs[m[1]] = m[2] !== undefined ? m[2] : (m[3] !== undefined ? m[3] : '');
  return attrs;
}

function parseHTML(html, doc){
  const roots = [];
  const stack = [];
  const re = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*?)?)(\/?)>/g;
  let m;
  while ((m = re.exec(html))){
    if (m[1] === '/'){ stack.pop(); continue; }
    const el = new Element(m[2].toLowerCase(), doc);
    for (const [k, v] of Object.entries(parseAttrs(m[3] || ''))) el.setAttribute(k, v);
    const parent = stack[stack.length - 1];
    if (parent) parent.appendChild(el); else roots.push(el);
    if (m[4] !== '/') stack.push(el);
  }
  return roots;
}

class ClassList {
  constructor(el){ this.el = el; }
  _set(){ return new Set((this.el._attrs.class || '').split(/\s+/).filter(Boolean)); }
  _write(s){ this.el._attrs.class = Array.from(s).join(' '); }
  add(c){ const s = this._set(); s.add(c); this._write(s); }
  remove(c){ const s = this._set(); s.delete(c); this._write(s); }
  contains(c){ return this._set().has(c); }
  toggle(c, on){ on ? this.add(c) : this.remove(c); }
}

class Element {
  constructor(tag, ownerDocument){
    this.tagName = tag.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.parentElement = null;
    this._attrs = {};
    this._listeners = {};
    this.classList = new ClassList(this);
    this.dataset = {};
    this.__rect = null;
    const self = this;
    this.style = new Proxy({}, {
      set(t, k, v){
        t[k] = v;
        if (self.id === 'pedido-actions-float' && k === 'left'){
          // Records the width the shipped code measured at positioning time.
          TRACE.push({ kind: 'position', left: parseFloat(v), measuredWidth: self.offsetWidth, buttons: self.visibleChildren() });
        }
        return true;
      },
      get(t, k){ return t[k]; },
    });
  }
  get id(){ return this._attrs.id || ''; }
  set id(v){ this._attrs.id = v; }
  get className(){ return this._attrs.class || ''; }
  set className(v){ this._attrs.class = v; }
  setAttribute(k, v){
    this._attrs[k] = String(v);
    if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = String(v);
  }
  getAttribute(k){ return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k){ delete this._attrs[k]; }
  get hidden(){ return ['', 'true', 'hidden'].includes(this._attrs.hidden); }
  set hidden(v){ if (v) this._attrs.hidden = ''; else delete this._attrs.hidden; }
  appendChild(c){ c.parentElement = this; this.children.push(c); return c; }
  set innerHTML(html){ this.children = []; for (const n of parseHTML(html, this.ownerDocument)) this.appendChild(n); this._html = html; }
  get innerHTML(){ return this._html || ''; }
  set textContent(v){ this._text = String(v); }
  get textContent(){ return this._text || ''; }
  _walk(fn){ fn(this); for (const c of this.children) c._walk(fn); }
  _matches(sel){
    sel = sel.trim();
    const tag = (sel.match(/^([a-zA-Z]*)/) || ['', ''])[1];
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    for (const t of (sel.slice(tag.length).match(/(\.[-\w]+|#[-\w]+|\[[^\]]+\])/g) || [])){
      if (t[0] === '.'){ if (!this.classList.contains(t.slice(1))) return false; }
      else if (t[0] === '#'){ if (this.id !== t.slice(1)) return false; }
      else {
        const inner = t.slice(1, -1);
        const eq = inner.indexOf('=');
        if (eq === -1){ if (this.getAttribute(inner) === null) return false; }
        else if (this.getAttribute(inner.slice(0, eq)) !== inner.slice(eq + 1).replace(/^["']|["']$/g, '')) return false;
      }
    }
    return true;
  }
  querySelector(sel){
    for (const c of this.children){
      if (c._matches(sel)) return c;
      const deep = c.querySelector(sel);
      if (deep) return deep;
    }
    return null;
  }
  querySelectorAll(sel){ const out = []; this._walk(n => { if (n !== this && n._matches(sel)) out.push(n); }); return out; }
  closest(sel){ let n = this; while (n){ if (n._matches(sel)) return n; n = n.parentElement; } return null; }
  addEventListener(type, fn){ (this._listeners[type] ||= []).push(fn); }
  dispatch(type, evt){ for (const fn of (this._listeners[type] || [])) fn(evt); }

  /* --- layout (actions-float.css contract) --- */
  isDisplayNone(){ return this.hidden || this.style.display === 'none'; }
  visibleChildren(){
    return this.children.filter(c => !c.isDisplayNone())
      .map(c => c.getAttribute('data-action') || c.getAttribute('data-role') || c.tagName.toLowerCase());
  }
  childWidth(){
    if (this.classList.contains('act-btn')) return CSS.btn;
    if (this.classList.contains('act-count')) return CSS.countW + CSS.countMargin;
    return 0;
  }
  /* Exact (possibly fractional) border-box width, as getBoundingClientRect
     reports it.  `barWidthDelta` models a bar whose layout width is not an whole
     number of CSS pixels -- what a transform, a fractional device pixel ratio or
     subpixel border rendering produces in a real engine. */
  exactWidth(){
    if (this.id !== 'pedido-actions-float') return 0;
    const vis = this.children.filter(c => !c.isDisplayNone());
    const chrome = 2 * CSS.border + 2 * CSS.padX;
    if (!vis.length) return chrome;
    const content = vis.reduce((a, c) => a + c.childWidth(), 0) + CSS.gap * (vis.length - 1);
    return chrome + content + (this.ownerDocument.__barWidthDelta || 0);
  }
  // Browsers round offsetWidth to an integer; the harness must too, otherwise
  // the offsetWidth-vs-rect.width containment hazard becomes untestable.
  get offsetWidth(){ return this.id === 'pedido-actions-float' ? Math.round(this.exactWidth()) : 0; }
  get offsetHeight(){ return this.id === 'pedido-actions-float' ? CSS.barH : 0; }
  getBoundingClientRect(){
    if (this.__rect) return { ...this.__rect };
    if (this.id === 'pedido-actions-float'){
      const left = parseFloat(this.style.left ?? '0') || 0;
      const top = parseFloat(this.style.top ?? '0') || 0;
      const width = this.exactWidth(), height = this.offsetHeight;
      return { left, top, width, height, right: left + width, bottom: top + height };
    }
    return { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 };
  }
}

class Doc extends Element {
  constructor(){
    super('#document', null);
    this.ownerDocument = this;
    this.body = this.appendChild(new Element('body', this));
  }
  createElement(tag){ return new Element(tag, this); }
  getElementById(id){ let hit = null; this._walk(n => { if (!hit && n.id === id) hit = n; }); return hit; }
  querySelector(sel){ return sel.startsWith('#') ? this.getElementById(sel.slice(1)) : super.querySelector(sel); }
}

// ---------------------------------------------------------------- template ---
function extractFloatBarScript(){
  const src = fs.readFileSync(TPL, 'utf8');
  const i = src.indexOf('Barra flutuante de ações na lista de Requisições');
  if (i === -1) throw new Error('float-bar script marker not found in admin_requisicoes.html');
  let js = src.slice(src.lastIndexOf('<script>', i) + '<script>'.length, src.indexOf('</script>', i));
  js = js.replace(/\{\{\s*'true' if can_requisicoes_edit else 'false'\s*\}\}/g, 'true')
         .replace(/\{\{\s*'true' if can_requisicoes_full else 'false'\s*\}\}/g, 'true');
  if (/\{\{|\{%/.test(js)) throw new Error('unsubstituted Jinja remains in the extracted script');
  return js;
}

// ------------------------------------------------------------------- world ---
const ROW_LEFT = 100, ROW_RIGHT = 1300, ROW_H = 44, WRAP_RIGHT = 1400;

/* `rowRight` and `barWidthDelta` let a scenario place the row boundary and the
   bar width off whole-pixel positions, which is the normal case in a CSS grid. */
function buildWorld(rowSpecs, { rowRight = ROW_RIGHT, barWidthDelta = 0 } = {}){
  const document = new Doc();
  document.__barWidthDelta = barWidthDelta;

  const wrap = document.createElement('div');
  wrap.id = 'requisicoes-scroll-container';
  wrap.__rect = { left: ROW_LEFT, right: WRAP_RIGHT, top: 100, bottom: 800, width: WRAP_RIGHT - ROW_LEFT, height: 700 };
  document.body.appendChild(wrap);

  const list = document.createElement('div');
  list.id = 'requisicoes-list';
  wrap.appendChild(list);

  const rows = rowSpecs.map((spec, idx) => {
    const r = document.createElement('div');
    r.className = 'impresso-card';
    r.setAttribute('data-req-id', String(spec.id));
    r.setAttribute('data-status', spec.status);
    r.setAttribute('data-email-pending', spec.emailPending ? '1' : '0');
    r.setAttribute('data-delete-url', `/admin/requisicao/${spec.id}/excluir`);
    const top = 200 + idx * (ROW_H + 8);
    r.__rect = { left: ROW_LEFT, right: rowRight, top, bottom: top + ROW_H, width: rowRight - ROW_LEFT, height: ROW_H };
    list.appendChild(r);
    return r;
  });

  const selected = new Set();
  const api = {
    getSelectedRows: () => rows.filter(r => selected.has(r)),
    clearSelection: () => selected.clear(),
    __only: r => { selected.clear(); selected.add(r); },
    __add: r => selected.add(r),
    __clear: () => selected.clear(),
  };

  const timers = new Map();
  let tid = 1;
  const window = {
    document,
    requisicoesRowSelectionApi: api,
    // CSS sizes `.act-btn i` and `.act-btn > svg` identically (16px), so the
    // lucide <i> -> <svg> swap cannot change the bar's width.
    lucide: { createIcons(){} },
    __l: {},
    addEventListener(t, f){ (window.__l[t] ||= []).push(f); },
    location: { search: '', pathname: '/admin/requisicoes', href: '' },
    history: { replaceState(){} },
    setTimeout(fn){ const id = tid++; timers.set(id, fn); return id; },
    clearTimeout(id){ timers.delete(id); },
  };
  window.window = window;

  const ctx = vm.createContext({
    window, document,
    setTimeout: window.setTimeout, clearTimeout: window.clearTimeout,
    fetch: async () => ({ ok: false }),
    URLSearchParams, console, Number, Math, String, Array, Set, Map, JSON, parseInt, parseFloat, Object,
  });
  vm.runInContext(extractFloatBarScript(), ctx, { filename: 'admin_requisicoes.floatbar.js' });
  document.dispatch('DOMContentLoaded', {});

  const flush = () => {
    for (let g = 0; g < 50 && timers.size; g++){
      const pending = Array.from(timers.values());
      timers.clear();
      pending.forEach(fn => fn());
    }
  };

  return { document, window, wrap, rows, api, flush, rowRight, bar: document.getElementById('pedido-actions-float') };
}

function geom(w){
  const bar = w.bar;
  const rect = bar.getBoundingClientRect();
  return {
    left: rect.left,
    width: rect.width,
    right: rect.right,
    visible: bar.classList.contains('is-visible'),
    buttons: bar.visibleChildren(),
    rowLeft: ROW_LEFT,
    rowRight: w.rowRight,
    leftOverflow: +(ROW_LEFT - rect.left).toFixed(6),
    rightOverflow: +(rect.right - w.rowRight).toFixed(6),
  };
}

const hover = (w, row) => w.wrap.dispatch('mouseover', { target: row });
function select(w, row, additive){
  // Real order: the selection authority mutates on click, then the bar's own
  // click listener defers a sync through setTimeout(0).
  additive ? w.api.__add(row) : w.api.__only(row);
  w.wrap.dispatch('click', { target: row });
  w.document.dispatch('click', { target: row });
  w.flush();
}
function clearSelection(w){
  w.api.__clear();
  w.document.dispatch('click', { target: w.document.body });
  w.flush();
}
const fireWindow = (w, type) => (w.window.__l[type] || []).forEach(f => f({}));

// --------------------------------------------------------------- scenarios ---
const ROWS = [
  { id: 101, status: 'Pendente', emailPending: true },   // pending + e-mail pending
  { id: 102, status: 'Deferida', emailPending: false },  // processed, no e-mail
  { id: 103, status: 'Pendente', emailPending: true },
];

const SCENARIOS = {
  /* The reported defect: first visible state on hover of a pending row. */
  hover_pending_first_paint(){
    const w = buildWorld(ROWS);
    TRACE.length = 0;
    hover(w, w.rows[0]);
    const first = geom(w);
    const positions = TRACE.filter(t => t.kind === 'position');
    // A second, independent sync must not move anything.
    select(w, w.rows[0]);
    const afterSecondSync = geom(w);
    return { first, afterSecondSync, positions, finalWidth: w.bar.offsetWidth };
  },
  hover_non_pending_first_paint(){
    const w = buildWorld(ROWS);
    TRACE.length = 0;
    hover(w, w.rows[1]);
    return { first: geom(w), positions: TRACE.filter(t => t.kind === 'position') };
  },
  select_first_paint(){
    const w = buildWorld(ROWS);
    select(w, w.rows[0]);
    const first = geom(w);
    fireWindow(w, 'resize');
    return { first, afterResize: geom(w) };
  },
  switch_selection_first_paint(){
    const w = buildWorld(ROWS);
    select(w, w.rows[1]);
    const onRow2 = geom(w);
    select(w, w.rows[0]);
    const onRow1 = geom(w);
    fireWindow(w, 'scroll');
    return { onRow2, onRow1, afterScroll: geom(w) };
  },
  clear_then_hover_then_select(){
    const w = buildWorld(ROWS);
    select(w, w.rows[0]);
    clearSelection(w);
    const cleared = geom(w);
    hover(w, w.rows[0]);
    const hovered = geom(w);
    select(w, w.rows[0]);
    return { cleared, hovered, selected: geom(w) };
  },
  selection_owns_bar_against_hover(){
    const w = buildWorld(ROWS);
    select(w, w.rows[0]);
    const before = geom(w);
    hover(w, w.rows[1]);
    return { before, afterHoveringOther: geom(w), selectedId: w.rows[0].getAttribute('data-req-id') };
  },
  batch_mode(){
    const w = buildWorld(ROWS);
    select(w, w.rows[0]);
    select(w, w.rows[2], true);
    const countEl = w.bar.querySelector('[data-role="selection-count"]');
    return {
      geometry: geom(w),
      countHidden: countEl.hidden,
      countText: countEl.textContent,
      emailHidden: w.bar.querySelector('button[data-action="email"]').hidden,
    };
  },
  batch_mode_mixed_email_eligibility(){
    const w = buildWorld(ROWS);
    select(w, w.rows[0]);            // e-mail pending
    select(w, w.rows[1], true);      // NOT e-mail pending
    const countEl = w.bar.querySelector('[data-role="selection-count"]');
    return {
      geometry: geom(w),
      countHidden: countEl.hidden,
      countText: countEl.textContent,
      emailHidden: w.bar.querySelector('button[data-action="email"]').hidden,
    };
  },
  /* Fractional row boundary. A CSS grid row rarely ends on a whole pixel, and
     `Math.round(boundRight - barW)` rounded UP whenever frac(boundRight) >= 0.5,
     putting the bar's right edge past the row's. Swept across the whole
     fractional range, on the FIRST visible positioning. */
  fractional_row_boundary(){
    const out = [];
    for (const frac of [0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 0.99]){
      const rowRight = 1300 + frac;
      for (const mode of ['hover', 'select']){
        const w = buildWorld(ROWS, { rowRight });
        if (mode === 'hover') hover(w, w.rows[0]); else select(w, w.rows[0]);
        out.push({ frac, mode, ...geom(w) });
      }
    }
    return out;
  },
  /* Fractional BAR width. offsetWidth is rounded to an integer, so reading it
     instead of getBoundingClientRect().width positions a 160.4px bar as if it
     were 160px and overflows by the difference -- independently of the row
     edge. */
  fractional_bar_width(){
    const out = [];
    for (const delta of [0, 0.25, 0.4, 0.5, 0.75]){
      for (const frac of [0, 0.3, 0.7]){
        const w = buildWorld(ROWS, { rowRight: 1300 + frac, barWidthDelta: delta });
        hover(w, w.rows[0]);
        out.push({ delta, frac, offsetWidth: w.bar.offsetWidth, ...geom(w) });
      }
    }
    return out;
  },
  /* Containment must survive the horizontal-scroll clamp too: there the bound is
     the wrap's right edge, also fractional. */
  fractional_wrap_clamp(){
    const out = [];
    for (const frac of [0.25, 0.5, 0.75]){
      const w = buildWorld(ROWS, { rowRight: 2000 });   // row scrolled past the wrap
      w.wrap.__rect = { ...w.wrap.__rect, right: 1400 + frac };
      hover(w, w.rows[0]);
      const g = geom(w);
      out.push({ frac, wrapRight: 1400 + frac, left: g.left, right: g.right, width: g.width });
    }
    return out;
  },
  empty_count_bubble_after_batch_collapses(){
    const w = buildWorld(ROWS);
    select(w, w.rows[0]);
    select(w, w.rows[2], true);
    select(w, w.rows[0]);            // back to a single selection
    const countEl = w.bar.querySelector('[data-role="selection-count"]');
    return { countHidden: countEl.hidden, countText: countEl.textContent, geometry: geom(w) };
  },
};

const out = { css: CSS, scenarios: {} };
for (const [name, fn] of Object.entries(SCENARIOS)) out.scenarios[name] = fn();
process.stdout.write(JSON.stringify(out, null, 2));
