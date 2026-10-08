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

  function DirectUploadForm(form) {
    this.form = form;
    this.input = form.querySelector('input[type="file"][data-direct-upload-input]');
    this.list = form.querySelector('[data-direct-upload-list]');
    this.status = form.querySelector('[data-direct-upload-status]');
    this.entries = [];
    if (!this.input) return;
    this.input.disabled = false;
    this.input.addEventListener('change', this.onSelect.bind(this));
    form.addEventListener('submit', this.onSubmit.bind(this));
    this.refresh();
  }

  DirectUploadForm.prototype.submissionId = function () {
    var field = this.form.querySelector('input[name="' + SUBMISSION_FIELD + '"]');
    return field ? field.value : '';
  };

  DirectUploadForm.prototype.target = function () {
    var explicit = this.form.getAttribute('data-requisicao-id');
    if (explicit) return explicit;
    var editTarget = this.form.querySelector('input[name="edit_target_id"]');
    var action = this.form.getAttribute('action') || '';
    if (editTarget && editTarget.value && action.indexOf('/editar') >= 0) return editTarget.value;
    return '';
  };

  DirectUploadForm.prototype.onSelect = function () {
    var files = Array.prototype.slice.call(this.input.files || []);
    for (var i = 0; i < files.length; i += 1) {
      // Every deliberate selection is a new slot; retries keep the same slot.
      var entry = { slot: newSlot(), file: files[i], state: 'pending', intentId: null, attempts: 0 };
      this.entries.push(entry);
      this.start(entry);
    }
    this.input.value = '';
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
        purpose: 'comprovante',
        submission_id: self.submissionId(),
        upload_slot_id: entry.slot,
        filename: entry.file.name,
        mime_type: mime,
        size_bytes: entry.file.size,
        sha256: digest
      };
      var target = self.target();
      if (target) body.requisicao_id = parseInt(target, 10);
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

  DirectUploadForm.prototype.remove = function (entry) {
    this.entries = this.entries.filter(function (item) { return item !== entry; });
    this.refresh();
  };

  DirectUploadForm.prototype.retry = function (entry) {
    entry.attempts = 0;
    entry.message = '';
    if (entry.intentId) {
      // Same file, same slot: the server replays the same intent and key.
      entry.intentId = null;
    }
    this.start(entry);
  };

  DirectUploadForm.prototype.unresolved = function () {
    return this.entries.some(function (entry) { return entry.state !== 'verified'; });
  };

  DirectUploadForm.prototype.syncHiddenFields = function () {
    var form = this.form;
    Array.prototype.forEach.call(form.querySelectorAll('input[name="' + INTENT_FIELD + '"]'), function (node) {
      node.parentNode.removeChild(node);
    });
    this.entries.forEach(function (entry) {
      if (entry.state !== 'verified' || !entry.intentId) return;
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = INTENT_FIELD;
      hidden.value = entry.intentId;
      form.appendChild(hidden);
    });
  };

  DirectUploadForm.prototype.refresh = function () {
    var self = this;
    this.syncHiddenFields();
    var blocked = this.unresolved();
    Array.prototype.forEach.call(this.form.querySelectorAll('button[type="submit"], input[type="submit"]'), function (button) {
      if (blocked) {
        button.setAttribute('data-direct-upload-blocked', '1');
        button.disabled = true;
      } else if (button.getAttribute('data-direct-upload-blocked')) {
        button.removeAttribute('data-direct-upload-blocked');
        button.disabled = false;
      }
    });
    if (this.status) {
      this.status.textContent = blocked ? 'Aguarde a conclusão do envio dos comprovantes.' : '';
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
        entry.node = document.createElement('li');
        entry.node.className = 'file-list-item';
        entry.node.setAttribute('data-direct-upload-item', '');
        entry.label = document.createElement('span');
        entry.label.className = 'file-list-name';
        entry.node.appendChild(entry.label);
        entry.retryButton = document.createElement('button');
        entry.retryButton.type = 'button';
        entry.retryButton.className = 'btn btn-secondary btn-sm';
        entry.retryButton.textContent = 'Tentar novamente';
        entry.retryButton.setAttribute('aria-label', 'Tentar novamente ' + entry.file.name);
        entry.retryButton.addEventListener('click', function () { self.retry(entry); });
        entry.node.appendChild(entry.retryButton);
        var drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'file-list-remove';
        drop.textContent = 'Remover';
        drop.setAttribute('aria-label', 'Remover comprovante ' + entry.file.name);
        drop.addEventListener('click', function () { self.remove(entry); });
        entry.node.appendChild(drop);
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
      // display, not the hidden attribute: .btn sets display and would override [hidden].
      entry.retryButton.style.display = entry.state === 'error' ? '' : 'none';
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
