# Outbound mail: reuse contract for authentication e-mails

`app/services/mail_service.py` is deliberately generic: it accepts a recipient,
a subject and a plain-text body, and knows nothing about Requisições. Request
e-mails are simply its first consumer.

This document records the contracts for the two planned consumers. **Neither is
implemented in this front**, and no route, schema or UI for them exists yet.

## Why the transport is separate

`app/request_email_dispatch.py` owns request-specific concerns (decision events,
grouping, the `{requisicoes}` block). `mail_service` owns only delivery:

* resolving the connected delegated Microsoft identity;
* `POST /me/sendMail` without spoofing `From`;
* sanitizing provider errors so no token ever reaches persistence or logs;
* reporting `indeterminate` outcomes honestly instead of implying exactly-once.

Any future consumer reuses exactly that, by calling
`send_text_email(conn, MailMessage(...))`.

## First access

* The student receives a **single-use link**, never a generated or plaintext
  password.
* The link carries a cryptographically random token; the account is activated
  only when the student sets their own password.
* Store only a safe representation (hash) of the token, never the token itself.
* The token has an expiry and a used/revoked state.

## Password recovery

* Entry point: "Esqueci minha senha" on the login screen.
* The response must be **generic** and identical whether or not an account
  exists — no account enumeration via message text, status code or timing class.
* Token: cryptographically random, single-use, stored only as a hash.
* Token carries an expiry and an explicit used/revoked state.
* Completing a password change invalidates outstanding tokens for that account.

## What a future implementation must add

Only the auth-specific parts:

1. a token table (hash, purpose, expiry, used/revoked, user reference);
2. the two routes plus their RBAC/CSRF entries;
3. templates for the two messages.

The transport itself requires no change. If it ever does, the change belongs in
`mail_service`, not in a consumer.
