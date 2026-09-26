"""Synthetic, test-only root administrator configuration.

The real root address and break-glass hash of an installation are
configuration (``APP_BOOTSTRAP_ADMIN_EMAIL`` / ``APP_ROOT_MASTER_KEY_HASH``,
kept in the machine-local, git-ignored ``.env``), never source.  The suite
therefore configures its own values: ``tests/conftest.py`` exports these into
the environment before ``main`` is imported, so a developer's ``.env`` can never
leak into a test run.  Neither value is, or resembles, an operational one.
"""

TEST_ROOT_ADMIN_EMAIL = "root-admin@sgaa-tests.invalid"
TEST_ROOT_MASTER_KEY = "synthetic-test-master-key-not-operational"
