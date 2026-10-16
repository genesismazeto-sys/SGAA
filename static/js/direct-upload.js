/*
 * direct-upload.js -- STORAGE S3-A request documents (comprovantes).
 *
 * Files never travel through the application.  For every deliberately
 * selected file the browser:
 *   1. creates an opaque upload slot (128-bit random hex, kept with the file);
 *   2. computes its SHA-256 with WebCrypto;
 *   3. asks the application for an upload capability
 *      (POST /storage/upload-intents -- the SERVER chooses bucket and key);
 *   4. uploads straight to Supabase Storage with signed resumable (TUS)
 *      uploads (session created at the capability's signed-TUS endpoint):
 *      the capability token is sent as x-signature together with
 *      the capability's browser-safe publishable apikey, 6 MiB chunks;
 *   5. asks the application to verify the stored object
 *      (POST /storage/upload-intents/<id>/finalize);
 *   6. keeps the verified intent id in a hidden comprovantes_intent_ids field.
 * The form can only be submitted once every selected file is verified or
 * removed.  No key of any kind lives here: the only credentials are the
 * short-lived signed upload token and the public publishable apikey the
 * server returns per file.  No Authorization header is ever sent.
 *
 * STORAGE S3-B: the same client serves admin ARQUIVOS.  A form opts in with
 *   data-direct-upload-purpose="admin_arquivo"   (default: comprovante)
 *   data-direct-upload-single                    (one file; a new pick replaces)
 *   data-direct-upload-submission-field="..."    (default: comprovantes_submission_id)
 *   data-direct-upload-intent-field="..."        (default: comprovantes_intent_ids)
 *   data-admin-arquivo-id="<id>"                 (replacement target, sent as admin_arquivo_id)
 * A form without these attributes behaves exactly as the S3-A comprovantes form.
 */
(function () {
  'use strict';

  var ISSUE_URL = '/storage/upload-intents';
  var CHUNK_SIZE = 6 * 1024 * 1024;
  var RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000];
  var INTENT_FIELD = 'comprovantes_intent_ids';
  var SUBMISSION_FIELD = 'comprovantes_submission_id';
  var MIME_BY_EXTENSION = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };
  var MAX_FILE_BYTES = 16 * 1024 * 1024;

  function newSlot() {
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  function hex(buffer) {
    return Array.prototype.map.call(new Uint8Array(buffer), function (b) {
      return ('0' + b.toString(16)).slice(-2);
    }).join('');
  }

  function sha256(file) {
    return file.arrayBuffer().then(function (data) {
      return window.crypto.subtle.digest('SHA-256', data);
    }).then(hex);
  }

  function declaredMime(name) {
    var dot = name.lastIndexOf('.');
    return dot < 0 ? '' : (MIME_BY_EXTENSION[name.slice(dot + 1).toLowerCase()] || '');
  }

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        return { status: response.status, body: payload || {} };
      });
    });
  }

  function formAttr(form, name, fallback) {
    var value = form.getAttribute(name);
    return value === null || value === '' ? fallback : value;
  }

  // Lucide v0.544 geometry, inlined: the row must not depend on lucide.min.js
  // having run (or re-running) to show its controls.
  var ICON_PATHS = {
    'file-text': ['M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z', 'M14 2v4a2 2 0 0 0 2 2h4',
      'M10 9H8', 'M16 13H8', 'M16 17H8'],
    'rotate-cw': ['M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8', 'M21 3v5h-5'],
    'x': ['M18 6 6 18', 'm6 6 12 12']
  };

  function icon(name) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'lucide lucide-' + name);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    ICON_PATHS[name].forEach(function (d) {
      var path = document.createElementNS(ns, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    return svg;
  }

  // A compact row control: the icon is the visible label, the accessible name
  // carries the file, and the DS tooltip (static/js/ui-tooltips.js) shows the
  // action on hover and on keyboard focus.
  function rowButton(className, iconName, action, fileName) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.setAttribute('aria-label', action + ' ' + fileName);
    button.setAttribute('data-ui-tooltip', action);
    button.appendChild(icon(iconName));
    return button;
  }

  function DirectUploadForm(form) {
    this.form = form;
    this.purpose = formAttr(form, 'data-direct-upload-purpose', 'comprovante');
    this.single = form.hasAttribute('data-direct-upload-single');
    this.submissionField = formAttr(form, 'data-direct-upload-submission-field', SUBMISSION_FIELD);
    this.intentField = formAttr(form, 'data-direct-upload-intent-field', INTENT_FIELD);
    this.input = form.querySelector('input[type="file"][data-direct-upload-input]');
    this.list = form.querySelector('[data-direct-upload-list]');
    this.status = form.querySelector('[data-direct-upload-status]');
    this.entries = [];
    if (!this.input) return;
    this.input.disabled = false;
    this.input.addEventListener('change', this.onSelect.bind(this));
    form.addEventListener('submit', this.onSubmit.bind(this));
    form.addEventListener('reset', this.onReset.bind(this));
    this.refresh();
  }

  DirectUploadForm.prototype.submissionId = function () {
    var field = this.form.querySelector('input[name="' + this.submissionField + '"]');
    return field ? field.value : '';
  };

  DirectUploadForm.prototype.target = function () {
    if (this.purpose === 'admin_arquivo') return this.form.getAttribute('data-admin-arquivo-id') || '';
    var explicit = this.form.getAttribute('data-requisicao-id');
    if (explicit) return explicit;
    var editTarget = this.form.querySelector('input[name="edit_target_id"]');
    var action = this.form.getAttribute('action') || '';
    if (editTarget && editTarget.value && action.indexOf('/editar') >= 0) return editTarget.value;
    return '';
  };

  DirectUploadForm.prototype.onSelect = function () {
    var files = Array.prototype.slice.call(this.input.files || []);
    if (this.single) {
      // One document per ARQUIVOS operation: a new pick replaces the previous one.
      // The picker keeps its selection for the page's own file card; it has no
      // name attribute, so a submit never carries its bytes.
      if (!files.length) return;
      this.entries = [];
      files = files.slice(0, 1);
    }
    for (var i = 0; i < files.length; i += 1) {
      // Every deliberate selection is a new slot; retries keep the same slot.
      var entry = { slot: newSlot(), file: files[i], state: 'pending', intentId: null, attempts: 0 };
      this.entries.push(entry);
      this.start(entry);
    }
    if (!this.single) this.input.value = '';
    this.refresh();
  };

  DirectUploadForm.prototype.onReset = function () {
    this.entries = [];
    this.refresh();
  };

  DirectUploadForm.prototype.start = function (entry) {
    var self = this;
    var mime = declaredMime(entry.file.name);
    if (!mime) return this.fail(entry, 'Envie somente arquivos PDF, PNG ou JPEG.');
    if (entry.file.size <= 0) return this.fail(entry, 'O arquivo está vazio.');
    if (entry.file.size > MAX_FILE_BYTES) return this.fail(entry, 'O arquivo excede o limite de 16 MiB.');
    entry.state = 'hashing';
    this.refresh();
    sha256(entry.file).then(function (digest) {
      var body = {
        purpose: self.purpose,
        submission_id: self.submissionId(),
        upload_slot_id: entry.slot,
        filename: entry.file.name,
        mime_type: mime,
        size_bytes: entry.file.size,
        sha256: digest
      };
      var target = self.target();
      if (target && self.purpose === 'admin_arquivo') body.admin_arquivo_id = parseInt(target, 10);
      else if (target) body.requisicao_id = parseInt(target, 10);
      return postJson(ISSUE_URL, body);
    }).then(function (result) {
      if (result.status === 409 && result.body.error === 'UPLOAD_ALREADY_RECEIVED' && result.body.intent_id) {
        entry.intentId = result.body.intent_id;
        return self.finalize(entry);
      }
      if (result.status !== 201 || !result.body.intent_id || !result.body.apikey) {
        return self.fail(entry, result.body.message || 'Não foi possível preparar o envio.');
      }
      entry.intentId = result.body.intent_id;
      return self.upload(entry, result.body, mime);
    }).catch(function () {
      self.fail(entry, 'Falha de rede ao preparar o envio.');
    });
  };

  DirectUploadForm.prototype.upload = function (entry, capability, mime) {
    var self = this;
    entry.state = 'uploading';
    entry.progress = 0;
    this.refresh();
    var upload = new window.tus.Upload(entry.file, {
      endpoint: capability.tus_endpoint,
      chunkSize: capability.chunk_size || CHUNK_SIZE,
      retryDelays: RETRY_DELAYS,
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      headers: { apikey: capability.apikey, 'x-signature': capability.upload_token },
      metadata: {
        bucketName: capability.bucket,
        objectName: capability.object_name,
        contentType: mime,
        cacheControl: '3600'
      },
      onProgress: function (sent, total) {
        entry.progress = total ? Math.floor((sent / total) * 100) : 0;
        self.refresh();
      },
      onError: function () {
        self.fail(entry, 'O envio foi interrompido. Tente novamente.');
      },
      onSuccess: function () {
        self.finalize(entry);
      }
    });
    upload.start();
  };

  DirectUploadForm.prototype.finalize = function (entry) {
    var self = this;
    entry.state = 'verifying';
    this.refresh();
    return postJson(ISSUE_URL + '/' + encodeURIComponent(entry.intentId) + '/finalize').then(function (result) {
      if (result.status === 200 && result.body.state === 'verified') {
        entry.state = 'verified';
        self.refresh();
        return;
      }
      if ((result.status === 409 && result.body.state === 'issued') || result.status === 503) {
        entry.attempts += 1;
        if (entry.attempts <= 3) {
          window.setTimeout(function () { self.finalize(entry); }, 1500 * entry.attempts);
          return;
        }
      }
      self.fail(entry, result.body.message || 'O arquivo não pôde ser verificado.');
    }).catch(function () {
      self.fail(entry, 'Falha de rede ao verificar o arquivo.');
    });
  };

  DirectUploadForm.prototype.fail = function (entry, message) {
    entry.state = 'error';
    entry.message = message;
    this.refresh();
  };

  function viaKeyboard(element) {
    try { return element.matches(':focus-visible'); } catch (e) { return true; }
  }

  DirectUploadForm.prototype.remove = function (entry) {
    var position = this.entries.indexOf(entry);
    var hadFocus = document.activeElement === entry.removeButton;
    var keyboard = hadFocus && viaKeyboard(entry.removeButton);
    this.entries = this.entries.filter(function (item) { return item !== entry; });
    this.refresh();
    if (!hadFocus) return;
    // The focused button just left the page: keep focus in the list, on the
    // row that took its place (as comprovantes-picker.js does); a keyboard
    // user whose list is now empty goes back to the upload control (a mouse
    // user is not handed the card's focus ring).
    var next = this.entries[Math.min(position, this.entries.length - 1)];
    if (next && next.removeButton) next.removeButton.focus();
    else if (keyboard && this.input) this.input.focus();
  };

  DirectUploadForm.prototype.retry = function (entry) {
    entry.attempts = 0;
    entry.message = '';
    if (entry.intentId) {
      // Same file, same slot: the server replays the same intent and key.
      entry.intentId = null;
    }
    var hadFocus = document.activeElement === entry.retryButton;
    this.start(entry);
    // Retry hides itself until the next error; focus stays on the same row.
    if (hadFocus && entry.state !== 'error' && entry.removeButton) entry.removeButton.focus();
  };

  DirectUploadForm.prototype.unresolved = function () {
    return this.entries.some(function (entry) { return entry.state !== 'verified'; });
  };

  DirectUploadForm.prototype.syncHiddenFields = function () {
    var form = this.form;
    var intentField = this.intentField;
    Array.prototype.forEach.call(form.querySelectorAll('input[name="' + intentField + '"]'), function (node) {
      node.parentNode.removeChild(node);
    });
    this.entries.forEach(function (entry) {
      if (entry.state !== 'verified' || !entry.intentId) return;
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = intentField;
      hidden.value = entry.intentId;
      form.appendChild(hidden);
    });
  };

  DirectUploadForm.prototype.refresh = function () {
    var self = this;
    this.syncHiddenFields();
    var blocked = this.unresolved();
    var submitters = Array.prototype.slice.call(this.form.querySelectorAll('button[type="submit"], input[type="submit"]'));
    if (this.form.id) {
      // Submit buttons associated through form="<id>" (e.g. a modal footer).
      submitters = submitters.concat(Array.prototype.slice.call(
        document.querySelectorAll('button[type="submit"][form="' + this.form.id + '"]')));
    }
    submitters.forEach(function (button) {
      if (blocked) {
        button.setAttribute('data-direct-upload-blocked', '1');
        button.disabled = true;
      } else if (button.getAttribute('data-direct-upload-blocked')) {
        button.removeAttribute('data-direct-upload-blocked');
        button.disabled = false;
      }
    });
    if (this.status) {
      this.status.textContent = !blocked ? ''
        : (this.purpose === 'admin_arquivo' ? 'Aguarde a conclusão do envio do arquivo.'
          : 'Aguarde a conclusão do envio dos comprovantes.');
    }
    if (!this.list) return;
    // Each entry owns ONE stable list item, updated in place: re-rendering on
    // every progress event would destroy a focused button (keyboard users).
    var live = this.entries;
    Array.prototype.forEach.call(this.list.querySelectorAll('li[data-direct-upload-item]'), function (node) {
      if (!live.some(function (entry) { return entry.node === node; })) node.parentNode.removeChild(node);
    });
    this.entries.forEach(function (entry) {
      if (!entry.node) {
        // Same anatomy as a comprovantes-picker.js row (icon | name | controls),
        // so it lands on the .file-list-item grid's three tracks.
        entry.node = document.createElement('li');
        entry.node.className = 'file-list-item';
        entry.node.setAttribute('data-direct-upload-item', '');
        entry.node.appendChild(icon('file-text'));
        entry.label = document.createElement('span');
        entry.label.className = 'file-list-name';
        entry.node.appendChild(entry.label);
        var actions = document.createElement('span');
        actions.className = 'file-list-actions';
        entry.retryButton = rowButton('file-list-action', 'rotate-cw', 'Tentar novamente', entry.file.name);
        entry.retryButton.addEventListener('click', function () { self.retry(entry); });
        actions.appendChild(entry.retryButton);
        entry.removeButton = rowButton('file-list-remove', 'x',
          self.purpose === 'admin_arquivo' ? 'Remover arquivo' : 'Remover comprovante', entry.file.name);
        entry.removeButton.addEventListener('click', function () { self.remove(entry); });
        actions.appendChild(entry.removeButton);
        entry.node.appendChild(actions);
        self.list.appendChild(entry.node);
      }
      var text = entry.file.name;
      if (entry.state === 'uploading') text += ' — ' + (entry.progress || 0) + '%';
      else if (entry.state === 'hashing' || entry.state === 'pending') text += ' — preparando';
      else if (entry.state === 'verifying') text += ' — verificando';
      else if (entry.state === 'verified') text += ' — pronto';
      else if (entry.state === 'error') text += ' — ' + (entry.message || 'erro');
      entry.label.textContent = text;
      entry.node.setAttribute('data-state', entry.state);
      entry.retryButton.hidden = entry.state !== 'error';
    });
  };

  DirectUploadForm.prototype.onSubmit = function (event) {
    if (this.unresolved()) {
      event.preventDefault();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      this.refresh();
    }
  };

  function init() {
    if (!window.tus || !window.crypto || !window.crypto.subtle) return;
    Array.prototype.forEach.call(document.querySelectorAll('form[data-direct-upload]'), function (form) {
      if (!form.__directUpload) form.__directUpload = new DirectUploadForm(form);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
