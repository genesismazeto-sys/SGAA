'use strict';
/* Behavioural harness for the Admin > Acesso floating action bar.
 *
 * Runs the REAL script extracted from templates/admin_acesso.html against a
 * minimal auto-stubbing DOM, and reproduces the exact interleaving the user
 * hit in production:
 *
 *   hover a row  -> showBar() stores the row descriptor in `currentData`
 *   click "Enviar acesso" -> the handler awaits the confirmation modal
 *   pointer leaves the list -> scheduleHide() -> hideBar() sets currentData = null
 *   confirm      -> the await resolves and the handler resumes
 *
 * Before the repair the resumed handler read `currentData.emailUrl`, which is
 * the reported `TypeError: Cannot read properties of null (reading 'emailUrl')`
 * at acesso:3786:47. This harness fails loudly if that read comes back.
 *
 * Why a hand-built DOM: the repo has no browser automation and no
 * node_modules. Nothing about the action bar is reimplemented here -- the
 * template's own IIFE is what executes.
 *
 * Usage:  node acesso_action_bar_harness.js <repo-root>
 * Output: one JSON document on stdout.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = process.argv[2] || path.resolve(__dirname, '..', '..');
const TPL = path.join(REPO, 'templates', 'admin_acesso.html');

// --------------------------------------------------------------- extraction --
/* The action-bar IIFE is the last `(function(){ ... })();` in the template's
 * final <script> block. Jinja expressions inside it are substituted with the
 * values this harness wants to exercise, exactly as the server would render. */
function extractScript(flags){
  // The template ships CRLF on Windows checkouts; normalise so the markers
  // below are line-ending agnostic.
  const source = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');
  const marker = "  (function(){\n    const accessDefaults =";
  const start = source.indexOf(marker);
  if (start < 0) throw new Error('action-bar IIFE not found in admin_acesso.html');
  const end = source.indexOf('</script>', start);
  if (end < 0) throw new Error('unterminated script block');
  let body = source.slice(start, end);

  // Render the one Jinja hole the handler branches on.
  body = body.replace('{{ mail_status.ready|tojson }}', JSON.stringify(flags.mailAvailable));

  // Remaining Jinja holes are URLs the action bar never reaches in these
  // scenarios; render them as plain paths so the script still parses.
  body = body.replace(/\{\{\s*url_for\(\s*["']([a-z_]+)["']\s*\)\s*\}\}/g, (_m, endpoint) => `/__${endpoint}`);
  // Render the action-bar markup with full Acesso permission -- that is the
  // branch in which the e-mail and delete buttons exist at all.
  body = body.replace(/\{%\s*if auth_can\('acesso', 'full'\)\s*%\}/g, '');
  body = body.replace(/\{%\s*endif\s*%\}/g, '');
  body = body.replace(/\{\{\s*user_message\(\s*(["'])(.*?)\1\s*\)\s*\}\}/g, (_m, _q, text) => text);

  const leftover = body.match(/\{\{.*?\}\}|\{%.*?%\}/);
  if (leftover) throw new Error('unrendered Jinja left in extracted script: ' + leftover[0]);

  /* Self-check mode: put the pre-repair read back. A harness that cannot
   * reproduce the original crash proves nothing about the repair, so the
   * suite runs this mutation and requires it to fail. */
  if (flags.reintroduceBug) {
    const before = body;
    body = body.replace('if (confirmed) submitPost(target.emailUrl);',
                        'if (confirmed) submitPost(currentData.emailUrl);');
    if (body === before) throw new Error('could not reintroduce the pre-repair read');
  }
  return body;
}

// --------------------------------------------------------------- DOM stubs --
function makeClassList(){
  const set = new Set();
  return {
    add: (...c) => c.forEach((x) => set.add(x)),
    remove: (...c) => c.forEach((x) => set.delete(x)),
    toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
    contains: (c) => set.has(c),
  };
}

function makeElement(id, doc){
  const listeners = Object.create(null);
  const attrs = Object.create(null);
  const el = {
    id: id || '',
    tagName: 'DIV',
    textContent: '',
    innerHTML: '',
    value: '',
    hidden: true,
    disabled: false,
    checked: false,
    className: '',
    style: {},
    dataset: {},
    offsetWidth: 120,
    offsetHeight: 32,
    classList: makeClassList(),
    children: [],
    _listeners: listeners,
    addEventListener(type, fn){ (listeners[type] ||= []).push(fn); },
    removeEventListener(){},
    dispatch(type, event){
      return Promise.all((listeners[type] || []).map((fn) => fn(event)));
    },
    setAttribute(name, value){ attrs[name] = String(value); },
    getAttribute(name){ return name in attrs ? attrs[name] : null; },
    removeAttribute(name){ delete attrs[name]; },
    hasAttribute(name){ return name in attrs; },
    appendChild(child){ el.children.push(child); return child; },
    removeChild(){},
    remove(){},
    focus(){},
    click(){ el.dispatch('click', { target: el, preventDefault(){}, stopPropagation(){} }); },
    submit(){ doc._submissions.push({ method: el.method, action: el.action }); },
    closest(){ return null; },
    querySelector(sel){ return doc._scoped(el, sel); },
    querySelectorAll(){ return []; },
    getBoundingClientRect(){ return { top: 0, left: 0, right: 900, bottom: 32, width: 900, height: 32 }; },
    insertAdjacentHTML(){},
  };
  return el;
}

function makeDocument(){
  const byId = new Map();
  const doc = {
    _submissions: [],
    _created: [],
    _listeners: Object.create(null),
    /* Every id the page ships resolves to a stub. The floating bar is the one
     * element the script is supposed to CREATE, so it must start absent --
     * otherwise the creation branch never runs and there is nothing to drive. */
    _absent: new Set(['pedido-actions-float']),
    getElementById(id){
      if (doc._absent.has(id)) return null;
      if (!byId.has(id)) byId.set(id, makeElement(id, doc));
      return byId.get(id);
    },
    createElement(tag){
      const el = makeElement('', doc);
      el.tagName = String(tag).toUpperCase();
      doc._created.push(el);
      return el;
    },
    querySelector(){ return null; },
    querySelectorAll(){ return []; },
    addEventListener(type, fn){ (doc._listeners[type] ||= []).push(fn); },
    removeEventListener(){},
    /* The action bar asks for its own buttons by [data-action="..."]. Hand back
     * a stable stub per selector so the script can disable/label them. */
    _scoped(owner, sel){
      owner._scopedCache ||= new Map();
      if (!owner._scopedCache.has(sel)) {
        const el = makeElement('', doc);
        const action = /data-action="([^"]+)"/.exec(sel);
        if (action) el.setAttribute('data-action', action[1]);
        owner._scopedCache.set(sel, el);
      }
      return owner._scopedCache.get(sel);
    },
  };
  doc.body = makeElement('body', doc);
  doc.documentElement = makeElement('html', doc);
  return doc;
}

// ------------------------------------------------------------------- driver --
async function run(scenario){
  const doc = makeDocument();

  // Seed the JSON data islands the IIFE parses at startup.
  doc.getElementById('access-defaults-data').textContent = JSON.stringify({ administrativo: 'admin123' });
  doc.getElementById('access-profile-defaults-data').textContent = JSON.stringify({ administrativo: {} });
  doc.getElementById('access-users-data').textContent = JSON.stringify({
    '7': {
      id: 7,
      emailActionLabel: 'Enviar acesso',
      emailActionUrl: '/admin/acesso/7/senha-por-email',
      accessOverrides: {},
      // UI-B09: "Aplicar senha padrão" is authorised per row by the backend
      // and travels in this descriptor. These scenarios drive the eligible
      // row; the ineligible ones are covered in Python, where the real view
      // decides. Without this field the action bar refuses by contract.
      canApplyDefaultPassword: true,
      applyDefaultPasswordReason: '',
    },
  });
  doc.getElementById('access-message-templates').textContent = JSON.stringify({
    sendEmailConfirm: 'Enviar {value_1} para {value_2}?',
    applyDefaultLabel: 'Aplicar senha padrao',
    applyDefaultConfirm: 'Aplicar a senha padrao ao acesso de {value_1}?',
    defaultCurrentWithValue: 'Senha padrao atual: {value_1}',
    defaultCurrentMissing: 'Senha padrao atual nao configurada.',
    passwordHelpCreate: 'create help',
    passwordHelpEdit: 'edit help',
    actionsHintIdle: '',
    actionsHintCount: '',
    selectAll: '',
    clearSelection: '',
    passwordModalSingle: '',
    passwordModalMultiple: '',
  });

  const scrollWrap = doc.getElementById('acesso-scroll-container');

  const errors = [];
  const sandbox = {
    console,
    JSON,
    Math,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Promise,
    Set,
    Map,
    Headers: class { constructor(){ } has(){ return false; } set(){} },
    setTimeout,
    clearTimeout,
    document: doc,
    fetch: async () => ({ ok: true, json: async () => ({}) }),
  };
  sandbox.window = {
    // The toolbar helpers are a separate, already-tested subsystem: hand back
    // a no-op for whatever the page asks of them.
    createToolbarQueryHelpers: () =>
      new Proxy({}, { get: () => () => {}, has: () => true }),
    appFormatMessage: (tpl, values) =>
      String(tpl || '').replace(/\{(value_\d+)\}/g, (_m, k) => String(values?.[k] ?? '')),
    ensureFormCsrfToken: () => {},
    lucide: { createIcons(){} },
    addEventListener(){},
    getComputedStyle: () => ({ paddingRight: '0' }),
    location: { reload(){}, href: '' },
    alert(){},
    confirm: () => true,
    setTimeout,
    clearTimeout,
  };
  sandbox.globalThis = sandbox;

  const context = vm.createContext(sandbox);
  try {
    vm.runInContext(extractScript(scenario.flags), context, { filename: 'admin_acesso.inline.js' });
  } catch (error) {
    return { scenario: scenario.name, phase: 'init', error: String(error && error.message || error) };
  }

  // The bar is the <div> the script created and appended to body.
  const bar = doc._created.find((el) => el.id === 'pedido-actions-float');
  if (!bar) return { scenario: scenario.name, phase: 'init', error: 'action bar was never created' };

  // 1. Hover a row: the script reads the descriptor off the card's data-*.
  const card = makeElement('', doc);
  card.getAttribute = (name) => ({
    'data-user-id': '7',
    'data-user-nome': 'Subject',
    'data-user-email': 'subject@example.test',
    'data-user-level': 'administrativo',
    'data-user-matricula': '',
    'data-user-turma-id': '',
    'data-user-status': 'Ativo',
    'data-user-is-self': '0',
    'data-reset-url': '/admin/acesso/7/resetar-senha',
    'data-email-url': '/admin/acesso/7/senha-por-email',
    'data-delete-url': '/admin/acesso/7/deletar',
  })[name] ?? null;
  await scrollWrap.dispatch('mouseover', { target: { closest: (sel) => (sel === '.impresso-card' ? card : null) } });

  // 2. Click the e-mail action. The handler now awaits the confirm modal.
  const button = makeElement('', doc);
  button.setAttribute('data-action', scenario.action);
  const clickDone = bar.dispatch('click', {
    target: { closest: (sel) => (sel === 'button.act-btn' ? button : null) },
  });

  // 3. The pointer leaves the list while the modal is open. This is the step
  //    that nulls `currentData` underneath the pending await.
  if (scenario.hideWhileAwaiting) {
    await scrollWrap.dispatch('mouseleave', {});
    await new Promise((resolve) => setTimeout(resolve, 260));
  }

  // 4. Confirm. The handler resumes here.
  const confirmSubmit = doc.getElementById('access-confirm-submit');
  await confirmSubmit.dispatch('click', { target: confirmSubmit });

  let crashed = null;
  try {
    await clickDone;
  } catch (error) {
    crashed = String((error && error.message) || error);
  }

  return {
    scenario: scenario.name,
    action: scenario.action,
    hideWhileAwaiting: !!scenario.hideWhileAwaiting,
    crashed,
    submissions: doc._submissions,
    errors,
  };
}

(async () => {
  const flags = { mailAvailable: true };
  const results = [];
  for (const scenario of [
    { name: 'email-hidden-mid-confirm', action: 'email', hideWhileAwaiting: true, flags },
    { name: 'email-bar-still-visible', action: 'email', hideWhileAwaiting: false, flags },
    { name: 'reset-hidden-mid-confirm', action: 'reset', hideWhileAwaiting: true, flags },
    {
      name: 'selfcheck-pre-repair-read-crashes',
      action: 'email',
      hideWhileAwaiting: true,
      flags: { ...flags, reintroduceBug: true },
    },
  ]) {
    results.push(await run(scenario));
  }
  process.stdout.write(JSON.stringify(results, null, 2));
})();
