/* One explicit confirmation, then one HTTP request per recipient. Never retry a send. */
window.initAccessEmailBatch = function ({ getSelectedRows, buildPostHeaders, onBusyChange }) {
  const modal = document.getElementById('access-email-modal');
  if (!modal) return null;
  const action = document.getElementById('access-action-email');
  const submit = document.getElementById('access-email-submit');
  const cancel = document.getElementById('access-email-cancel');
  const close = document.getElementById('access-email-close');
  const summary = document.getElementById('access-email-summary');
  const categories = document.getElementById('access-email-categories');
  const results = document.getElementById('access-email-results');
  const progress = document.getElementById('access-email-progress');
  const checks = [...categories.querySelectorAll('input')];
  const labels = {
    sent: 'Envio confirmado', failed: 'Falha', unavailable: 'Envio indisponível',
    indeterminate: 'Resultado indeterminado — não reenviado', stale: 'Conta alterada — confirme novamente',
    excluded: 'Categoria não incluída', ineligible: 'Não elegível', not_started: 'Não iniciado'
  };
  let busy = false;
  let processing = false;
  let finished = false;
  let operation = null;
  let targets = [];
  let trigger = null;
  let previewVersion = 0;
  const rows = new Map();
  function setBusy(value) { busy = value; onBusyChange(); }
  async function post(body) {
    const response = await fetch(modal.dataset.endpoint, {
      method: 'POST', credentials: 'same-origin', redirect: 'error',
      headers: buildPostHeaders({ 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }),
      body: JSON.stringify(body), signal: AbortSignal.timeout(55000)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.detail || 'Solicitação recusada.');
    return data;
  }
  function updateSubmit() {
    submit.disabled = processing || !operation || !targets.some(
      target => checks.some(check => check.checked && check.value === target.category)
    );
  }
  function showResult(target, status, detail = '') {
    const category = { first_access: 'Primeiro acesso', resend: 'Reenvio', password_reset: 'Redefinição' }[target.category];
    rows.get(target.id).textContent = `${target.nome || `ID ${target.id}`} (${target.email || 'sem e-mail'})${category ? ` — ${target.access_status}: ${category}` : ''}: ${labels[status] || status}${detail ? ` — ${detail}` : ''}`;
  }
  function updateStatus(result) {
    if (!result.access_status) return;
    const card = document.querySelector(`#acesso-list [data-user-id="${result.id}"]`);
    const pill = card?.querySelector('.status-pill');
    if (!pill) return;
    const tone = result.access_tone;
    pill.textContent = result.access_status;
    for (const name of [...pill.classList]) {
      if (/^status-(neutral|caution|info|positive|negative)$/.test(name)) pill.classList.remove(name);
    }
    if (tone) pill.classList.add(`status-${tone}`);
  }
  async function dismiss() {
    if (processing) return;
    const canceledOperation = !finished ? operation : null;
    previewVersion++;
    modal.hidden = true;
    operation = null;
    setBusy(false);
    trigger?.focus();
    if (canceledOperation) {
      try { await post({ action: 'cancel', operation: canceledOperation }); } catch (_) { /* no send was requested */ }
    }
  }
  action?.addEventListener('click', async () => {
    if (busy) return;
    const ids = getSelectedRows().map(row => Number(row.getAttribute('data-user-id')));
    if (!ids.length) return;
    trigger = action;
    const version = ++previewVersion;
    setBusy(true);
    operation = null;
    finished = false;
    targets = [];
    rows.clear();
    results.replaceChildren();
    progress.hidden = true;
    categories.disabled = true;
    submit.hidden = false;
    submit.style.display = '';
    submit.disabled = true;
    cancel.textContent = 'Cancelar';
    document.getElementById('access-email-invalid').textContent = '';
    summary.textContent = `${ids.length} usuário(s) selecionado(s). Consultando contas…`;
    modal.hidden = false;
    modal.querySelector('[role="dialog"]').focus();
    document.getElementById('access-actions-menu').hidden = true;
    document.getElementById('btn-acesso-actions').setAttribute('aria-expanded', 'false');
    try {
      const preview = await post({ action: 'preview', ids });
      if (modal.hidden || version !== previewVersion) {
        await post({ action: 'cancel', operation: preview.operation });
        return;
      }
      operation = preview.operation;
      targets = preview.targets;
      checks.forEach(check => {
        const count = targets.filter(target => target.category === check.value).length;
        modal.querySelector(`[data-email-count="${check.value}"]`).textContent = count;
        check.checked = check.value === 'first_access' && count > 0;
        check.disabled = count === 0;
      });
      targets.forEach(target => {
        const row = document.createElement('li');
        results.appendChild(row);
        rows.set(target.id, row);
        showResult(target, target.category === 'ineligible' ? 'ineligible' : 'not_started', target.reason);
      });
      const invalid = targets.filter(target => target.category === 'ineligible').length;
      document.getElementById('access-email-invalid').textContent = `${invalid} destinatário(s) inválido(s) ou acesso(s) não elegível(is), detalhados abaixo.`;
      summary.textContent = `${targets.length} usuário(s) selecionado(s). Escolha as categorias e confirme o envio.`;
      categories.disabled = false;
      updateSubmit();
      cancel.focus();
    } catch (error) {
      if (version !== previewVersion) return;
      summary.textContent = `Não foi possível preparar os envios: ${error.message}`;
    }
  });
  categories.addEventListener('change', updateSubmit);
  submit.addEventListener('click', async () => {
    if (processing || submit.disabled || !operation || finished) return;
    processing = true;
    categories.disabled = true;
    submit.disabled = true;
    cancel.disabled = true;
    close.disabled = true;
    const included = checks.filter(check => check.checked).map(check => check.value);
    const queue = targets.filter(target => included.includes(target.category));
    const totals = { sent: 0, failed: 0, indeterminate: 0, excluded: 0, ineligible: 0 };
    targets.forEach(target => {
      if (target.category === 'ineligible') totals.ineligible++;
      else if (!included.includes(target.category)) { totals.excluded++; showResult(target, 'excluded'); }
    });
    progress.value = 0;
    progress.max = queue.length;
    progress.hidden = false;
    try {
      for (const target of queue) {
        summary.textContent = `Processando ${progress.value + 1} de ${queue.length} envio(s)…`;
        let result;
        try {
          result = await post({ action: 'send', operation, id: target.id, category: target.category });
        } catch (_) {
          // Read-only reconciliation after a lost response. It cannot issue mail.
          try { result = await post({ action: 'status', operation, id: target.id }); }
          catch (_) { result = { status: 'indeterminate', detail: 'Sem confirmação do servidor. Verifique antes de solicitar outro envio.' }; }
        }
        const status = result.status;
        totals[status === 'sent' ? 'sent' : status === 'indeterminate' ? 'indeterminate' : 'failed']++;
        showResult(target, status, result.detail);
        updateStatus(result);
        progress.value++;
      }
      summary.textContent = `Concluído: ${totals.sent} confirmado(s), ${totals.failed} falha(s) ou não iniciado(s), ${totals.indeterminate} indeterminado(s), ${totals.excluded} não incluído(s), ${totals.ineligible} não elegível(is). Nenhum envio será repetido automaticamente.`;
    } finally {
      processing = false;
      finished = true;
      submit.hidden = true;
      submit.style.display = 'none';
      cancel.disabled = false;
      close.disabled = false;
      cancel.textContent = 'Fechar';
      cancel.focus();
    }
  });
  cancel.addEventListener('click', dismiss);
  close.addEventListener('click', dismiss);
  modal.addEventListener('click', event => {
    event.stopPropagation(); // Keep the table selection while using its confirmation.
    if (event.target === modal) dismiss();
  });
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
    if (event.key !== 'Tab') return;
    const focusable = [...modal.querySelectorAll('button, input, [tabindex="0"]')].filter(el => !el.matches(':disabled') && !el.hidden && el.getClientRects().length);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  window.addEventListener('beforeunload', event => { if (processing) { event.preventDefault(); event.returnValue = ''; } });
  return { get busy() { return busy; } };
};
