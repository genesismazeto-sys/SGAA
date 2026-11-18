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
  const replace = document.getElementById('access-email-replace');
  const replaceText = document.getElementById('access-email-replace-text');
  const replaceAck = document.getElementById('access-email-replace-ack');
  const progress = document.getElementById('access-email-progress');
  const progressLabel = document.getElementById('access-email-progress-label');
  const progressPercent = document.getElementById('access-email-progress-percent');
  const progressTrack = document.getElementById('access-email-progress-track');
  const progressFill = progressTrack.querySelector('.progress-bar');
  const progressState = document.getElementById('access-email-progress-state');
  const progressLive = document.getElementById('access-email-progress-live');
  const checks = [...categories.querySelectorAll('input')];
  const labels = {
    sent: 'Envio confirmado', failed: 'Falha', unavailable: 'Envio indisponível',
    indeterminate: 'Resultado indeterminado — não reenviado', stale: 'Conta alterada — confirme novamente',
    excluded: 'Categoria não incluída', ineligible: 'Não elegível', not_started: 'Não iniciado'
  };
  // Categories that replace a link the person may still hold, or reach an
  // account that already has access. Never preselected; including one also
  // needs the acknowledgement checkbox.
  const REPLACING = ['resend', 'password_reset'];
  const TONES = ['status-neutral', 'status-info', 'status-positive', 'status-caution', 'status-negative'];
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
  const included = () => checks.filter(check => check.checked).map(check => check.value);
  const countOf = category => targets.filter(target => target.category === category).length;
  function replacingIncluded() {
    return included().filter(category => REPLACING.includes(category) && countOf(category) > 0);
  }
  function syncReplace() {
    const chosen = replacingIncluded();
    const parts = [];
    if (chosen.includes('resend')) {
      parts.push(`Reenvio para ${countOf('resend')} usuário(s): o link de primeiro acesso ainda válido deixará de funcionar ao emitir o novo, mesmo se o envio falhar.`);
    }
    if (chosen.includes('password_reset')) {
      parts.push(`Redefinição para ${countOf('password_reset')} conta(s) que já possuem acesso: cada uma receberá um link de redefinição e um link de redefinição anterior deixará de funcionar. A senha atual não muda.`);
    }
    replaceText.textContent = parts.join(' ');
    if (!chosen.length) replaceAck.checked = false;
    replace.hidden = !chosen.length;
  }
  function updateSubmit() {
    const needsAck = replacingIncluded().length > 0;
    submit.disabled = processing || !operation || !targets.some(
      target => checks.some(check => check.checked && check.value === target.category)
    ) || (needsAck && !replaceAck.checked);
  }
  function showResult(target, status, detail = '') {
    const category = { first_access: 'Primeiro acesso', resend: 'Reenvio', password_reset: 'Redefinição' }[target.category];
    const who = document.createElement('strong');
    who.textContent = `${target.nome || `ID ${target.id}`} (${target.email || 'sem e-mail'})`;
    rows.get(target.id).replaceChildren(
      who,
      `${category ? ` — ${target.access_status}: ${category}` : ''}: ${labels[status] || status}${detail ? ` — ${detail}` : ''}`
    );
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
  function setTone(element, tone) {
    element.classList.remove(...TONES);
    element.classList.add(`status-${tone}`);
  }
  function setTally(totals) {
    for (const [key, tone] of [['sent', 'positive'], ['failed', 'negative'], ['indeterminate', 'caution']]) {
      const pill = progress.querySelector(`[data-email-tally="${key}"]`);
      pill.querySelector('strong').textContent = String(totals[key]);
      setTone(pill, totals[key] ? tone : 'neutral');
    }
  }
  // `done` recipients have a result; `total` is the confirmed queue.
  function setProgress(done, total) {
    const percent = total ? Math.round((done / total) * 100) : 0;
    progressFill.style.width = `${percent}%`;
    progressPercent.textContent = `${percent}%`;
    progressTrack.setAttribute('aria-valuemax', String(total));
    progressTrack.setAttribute('aria-valuenow', String(done));
    progressTrack.setAttribute('aria-valuetext', `${done} de ${total} envio(s) processado(s)`);
  }
  // Every recipient for a short queue; otherwise each tenth of the way, so a
  // long batch does not flood a screen reader with one message per send. The
  // last send is not announced on its own: the final summary replaces it in
  // the same task anyway.
  function announce(done, total) {
    if (done >= total) return;
    const step = total <= 10 || Math.floor((done * 10) / total) !== Math.floor(((done - 1) * 10) / total);
    if (step) progressLive.textContent = `${done} de ${total} envio(s) processado(s).`;
  }
  function resetProgress() {
    progress.hidden = true;
    progress.dataset.state = 'running';
    progressLabel.textContent = '';
    progressLive.textContent = '';
    progressState.textContent = 'Em andamento';
    setTone(progressState, 'info');
    setTally({ sent: 0, failed: 0, indeterminate: 0 });
    setProgress(0, 0);
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
    resetProgress();
    categories.disabled = true;
    replaceAck.checked = false;
    replaceAck.disabled = false;
    replace.hidden = true;
    submit.hidden = false;
    submit.style.display = '';
    submit.disabled = true;
    cancel.textContent = 'Cancelar';
    document.getElementById('access-email-invalid').textContent = '';
    summary.textContent = `${ids.length} usuário(s) selecionado(s). Consultando contas…`;
    modal.hidden = false;
    window.lucide?.createIcons?.();
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
        const count = countOf(check.value);
        modal.querySelector(`[data-email-count="${check.value}"]`).textContent = count;
        // Only first access is ever preselected: accounts that already have
        // access, or a link that is still valid, are sent to only by choice.
        check.checked = check.value === 'first_access' && count > 0;
        check.disabled = count === 0;
      });
      targets.forEach(target => {
        const row = document.createElement('li');
        results.appendChild(row);
        rows.set(target.id, row);
        showResult(target, target.category === 'ineligible' ? 'ineligible' : 'not_started', target.reason);
      });
      const invalid = countOf('ineligible');
      document.getElementById('access-email-invalid').textContent = invalid
        ? `${invalid} destinatário(s) inválido(s) ou acesso(s) não elegível(is), detalhados abaixo.` : '';
      summary.textContent = `${targets.length} usuário(s) selecionado(s). Escolha as categorias e confirme o envio.`;
      categories.disabled = false;
      syncReplace();
      updateSubmit();
      cancel.focus();
    } catch (error) {
      if (version !== previewVersion) return;
      summary.textContent = `Não foi possível preparar os envios: ${error.message}`;
    }
  });
  categories.addEventListener('change', () => { syncReplace(); updateSubmit(); });
  replaceAck.addEventListener('change', updateSubmit);
  submit.addEventListener('click', async () => {
    if (processing || submit.disabled || !operation || finished) return;
    if (replacingIncluded().length && !replaceAck.checked) return;
    processing = true;
    categories.disabled = true;
    replaceAck.disabled = true;
    submit.disabled = true;
    cancel.disabled = true;
    close.disabled = true;
    const chosen = included();
    const queue = targets.filter(target => chosen.includes(target.category));
    const totals = { sent: 0, failed: 0, indeterminate: 0, excluded: 0, ineligible: 0 };
    targets.forEach(target => {
      if (target.category === 'ineligible') totals.ineligible++;
      else if (!chosen.includes(target.category)) { totals.excluded++; showResult(target, 'excluded'); }
    });
    let done = 0;
    setProgress(0, queue.length);
    progress.hidden = false;
    progress.closest('.modal-body').scrollTop = 0;
    summary.textContent = 'Envio em andamento. Mantenha esta janela aberta até o fim.';
    progressLive.textContent = `Envio iniciado: ${queue.length} destinatário(s).`;
    try {
      for (const target of queue) {
        progressLabel.textContent = `Enviando ${done + 1} de ${queue.length}`;
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
        done++;
        setProgress(done, queue.length);
        setTally(totals);
        announce(done, queue.length);
      }
      summary.textContent = `Concluído: ${totals.sent} confirmado(s), ${totals.failed} falha(s) ou não iniciado(s), ${totals.indeterminate} indeterminado(s), ${totals.excluded} não incluído(s), ${totals.ineligible} não elegível(is). Nenhum envio será repetido automaticamente.`;
    } finally {
      const clean = done === queue.length && !totals.failed && !totals.indeterminate;
      progress.dataset.state = clean ? 'done-ok' : 'done-attention';
      progressLabel.textContent = `Envio concluído: ${done} de ${queue.length} processado(s)`;
      progressState.textContent = clean ? 'Concluído' : 'Concluído com pendências';
      setTone(progressState, clean ? 'positive' : 'caution');
      progressLive.textContent = summary.textContent;
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
