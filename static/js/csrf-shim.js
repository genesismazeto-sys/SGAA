/*
 * csrf-shim.js
 * Cobre tres frentes para impedir o 400 "A pagina ficou desatualizada":
 *   1. Adiciona X-CSRFToken automaticamente em fetch()/XHR nao-seguros.
 *   2. Antes de submeter qualquer <form method="post"> de mesma origem, faz
 *      refresh do csrf_token a partir de /csrf-token e atualiza o hidden
 *      input do form e o <meta name="csrf-token"> da pagina.
 *   3. Heartbeat periodico que atualiza o meta com um token fresco da sessao.
 * Tudo melhor-esforco: se /csrf-token falhar (sem sessao, sem rede, etc.),
 * o submit segue com o token que ja estava no form (comportamento antigo).
 */
(function () {
  'use strict';

  var REFRESH_ENDPOINT = '/csrf-token';
  var HEARTBEAT_MS = 15 * 60 * 1000; // 15 minutos
  var REFRESH_TIMEOUT_MS = 4000;

  function getToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function setToken(newToken) {
    if (!newToken) return;
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
      meta.setAttribute('content', newToken);
    } else if (document.head) {
      meta = document.createElement('meta');
      meta.setAttribute('name', 'csrf-token');
      meta.setAttribute('content', newToken);
      document.head.appendChild(meta);
    }
  }

  function isSafeMethod(method) {
    var m = String(method || 'GET').toUpperCase();
    return m === 'GET' || m === 'HEAD' || m === 'OPTIONS' || m === 'TRACE';
  }

  function isSameOrigin(url) {
    try {
      var u = new URL(url, window.location.origin);
      return u.origin === window.location.origin;
    } catch (e) {
      return true;
    }
  }

  // ----- fetch (preservado) -----
  if (window.fetch) {
    var originalFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      try {
        init = init || {};
        var method = init.method || (typeof input !== 'string' && input && input.method) || 'GET';
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        if (!isSafeMethod(method) && isSameOrigin(url)) {
          var token = getToken();
          if (token) {
            var headers = new Headers(init.headers || (typeof input !== 'string' && input ? input.headers : undefined) || {});
            if (!headers.has('X-CSRFToken')) {
              headers.set('X-CSRFToken', token);
            }
            init.headers = headers;
          }
        }
      } catch (e) {
        // não bloqueia o request por causa do shim
      }
      return originalFetch(input, init);
    };
  }

  // ----- XMLHttpRequest (preservado) -----
  if (window.XMLHttpRequest) {
    var XHR = window.XMLHttpRequest.prototype;
    var origOpen = XHR.open;
    var origSend = XHR.send;
    XHR.open = function (method, url) {
      this.__csrf_method = method;
      this.__csrf_url = url;
      return origOpen.apply(this, arguments);
    };
    XHR.send = function (body) {
      try {
        if (!isSafeMethod(this.__csrf_method) && isSameOrigin(this.__csrf_url || '')) {
          var token = getToken();
          if (token) {
            try { this.setRequestHeader('X-CSRFToken', token); } catch (e) {}
          }
        }
      } catch (e) {}
      return origSend.apply(this, arguments);
    };
  }

  // ----- Refresh helper -----
  function fetchFreshToken() {
    // Usa o fetch ORIGINAL para evitar recursao com nosso wrapper.
    var fetcher = (typeof originalFetch === 'function') ? originalFetch : (window.fetch && window.fetch.bind(window));
    if (!fetcher) return Promise.resolve('');
    var controller;
    var timeoutId;
    try {
      controller = (typeof AbortController === 'function') ? new AbortController() : null;
      if (controller) {
        timeoutId = setTimeout(function () { try { controller.abort(); } catch (_) {} }, REFRESH_TIMEOUT_MS);
      }
    } catch (_) { controller = null; }
    var opts = {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      cache: 'no-store',
    };
    if (controller) opts.signal = controller.signal;
    return fetcher(REFRESH_ENDPOINT, opts)
      .then(function (resp) {
        if (timeoutId) clearTimeout(timeoutId);
        if (!resp || !resp.ok) return '';
        return resp.json().then(function (data) {
          return (data && data.csrf_token) ? String(data.csrf_token) : '';
        }, function () { return ''; });
      })
      .catch(function () {
        if (timeoutId) clearTimeout(timeoutId);
        return '';
      });
  }

  function ensureFormCsrfInput(form, token) {
    if (!form || !token) return;
    var input = form.querySelector('input[name="csrf_token"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'csrf_token';
      form.appendChild(input);
    }
    input.value = token;
  }

  // ----- Submit interceptor -----
  // Captura submit, prevent default, refresca token, e resubmete o form.
  // Bandeira por-form evita recursao quando reenviarmos via requestSubmit().
  document.addEventListener('submit', function (event) {
    try {
      if (event.defaultPrevented) return;
      var form = event.target;
      if (!form || form.tagName !== 'FORM') return;
      if (form.__csrfShimRefreshed) return;
      var method = (form.getAttribute('method') || form.method || 'GET').toUpperCase();
      if (isSafeMethod(method)) return;
      var action = form.getAttribute('action') || window.location.href;
      if (!isSameOrigin(action)) return;

      event.preventDefault();
      var submitter = event.submitter || null;

      fetchFreshToken().then(function (token) {
        if (token) {
          setToken(token);
          ensureFormCsrfInput(form, token);
        }
      }).catch(function () { /* best-effort */ }).then(function () {
        form.__csrfShimRefreshed = true;
        try {
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit(submitter || undefined);
          } else {
            form.submit();
          }
        } catch (_) {
          try { form.submit(); } catch (__) {}
        }
      });
    } catch (e) {
      // best-effort: nunca quebrar o submit nativo por causa do shim.
    }
  }, false);

  // ----- Heartbeat -----
  // A cada HEARTBEAT_MS, busca um token fresco e atualiza o meta. Mantem o
  // valor do meta valido mesmo que o usuario nao interaja por horas.
  function startHeartbeat() {
    if (window.__csrfShimHeartbeatStarted) return;
    window.__csrfShimHeartbeatStarted = true;
    setInterval(function () {
      // So bate quando a aba esta visivel para nao gastar quota em background.
      if (document.hidden) return;
      fetchFreshToken().then(function (token) {
        if (token) setToken(token);
      });
    }, HEARTBEAT_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startHeartbeat);
  } else {
    startHeartbeat();
  }
})();
