# Service follow-ups

No open items in this file.

The historical `cloud_accounts.token_json` encryption TODO is **complete**:
`app.services.token_encryption` encrypts tokens for storage, and the cloud
connection owner uses it for writes and reads. A read-only production check on
2026-10-15 confirmed that all 3 `cloud_accounts` rows (2 Google, 1 OneDrive)
use the `fernet:` encrypted-storage format; none held non-empty plaintext.
No token value was accessed or exposed in the check.
