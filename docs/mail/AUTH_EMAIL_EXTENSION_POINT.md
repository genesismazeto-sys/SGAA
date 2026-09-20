# Outbound mail: reuse contract for authentication e-mails

`app/services/mail_service.py` is deliberately generic: it accepts a recipient,
a subject and a plain-text body, and knows nothing about Requisições. Request
e-mails are simply its first consumer.

This document records the contracts for the two authentication consumers,
implemented by the password-foundation Phase 2 surface.

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
* The first-access token expires after 72 hours and has a used/revoked state.

## Password recovery

* Entry point: "Esqueci minha senha" on the login screen.
* The response must be **generic** and identical whether or not an account
  exists — no account enumeration via message text, status code or timing class.
* Token: cryptographically random, single-use, stored only as a hash.
* The password-reset token expires after 60 minutes and has an explicit
  used/revoked state.
* Completing a password change invalidates outstanding tokens for that account.

## Implemented ownership

The auth-specific parts are owned by:

1. `senha_tokens` for token hash, purpose, expiry, consumed/revoked state and
   user reference;
2. `/esqueci-minha-senha`, `/redefinir-senha` and `/primeiro-acesso`, all with
   their explicit CSRF/RBAC inventory entries;
3. `app/password_email.py` and `app/password_tokens.py` for message and token
   lifecycle policy.

The transport itself requires no change. If it ever does, the change belongs in
`mail_service`, not in a consumer.
