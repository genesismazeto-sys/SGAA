import argparse
import socket
import subprocess
import sys
from pathlib import Path


RELEASE_TEST_FILES = [
    "tests/test_release_backend_core.py",
    "tests/test_release_admin_crud.py",
    "tests/test_release_admin_actions.py",
    "tests/test_release_admin_actions_csrf.py",
    "tests/test_release_requisicoes_flow.py",
    "tests/test_release_clean_database.py",
    "tests/test_release_backup_restore_local.py",
]

SMOKE_COMMANDS = [
    ["tools/smoke_test.py"],
    ["tools/smoke_test_admin.py"],
    ["tools/smoke_test_rbac_permissions.py"],
]

RUNTIME_PORT = 5000


def _runtime_port_active(port: int = RUNTIME_PORT, timeout: float = 0.5) -> bool:
    """True when something is listening on SGAA's single application port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_step(label: str, args: list[str], cwd: Path) -> int:
    print(f"\n=== {label} ===")
    print("Command:", " ".join(args))
    completed = subprocess.run(args, cwd=str(cwd))
    print(f"Exit code: {completed.returncode}")
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run release 1.0 checks in sequence (release tests + smokes + optional"
            " full pytest). The full-suite state requires the canonical SGAA runtime"
            " stopped (it writes logs/app.log and database.db); the automatic backup"
            " scheduler may stay enabled. pytest runs on its own isolated database."
        )
    )
    parser.add_argument(
        "--with-full-pytest",
        action="store_true",
        help="Also run the complete pytest suite (-m pytest -q) after release checks and smokes.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    py = sys.executable
    failures: list[str] = []

    release_cmd = [py, "-m", "pytest", "-q", *RELEASE_TEST_FILES]
    if _run_step("Release tests (Stages 1-5)", release_cmd, repo_root) != 0:
        failures.append("release_tests")

    for idx, smoke in enumerate(SMOKE_COMMANDS, start=1):
        smoke_cmd = [py, *smoke]
        if _run_step(f"Smoke {idx}", smoke_cmd, repo_root) != 0:
            failures.append(f"smoke_{idx}")

    if args.with_full_pytest:
        if _runtime_port_active():
            print("\n=== Full pytest suite REFUSED (custody entry contract) ===")
            print(
                f"Port {RUNTIME_PORT} is listening: the canonical SGAA runtime appears"
                " active. Stop it (run.bat / run_acceptance.bat) before the full suite."
            )
            print(
                "Why: the runtime writes logs/app.log and database.db while pytest runs;"
                " the full-suite custody gate reports those as external-writer failures."
            )
            print(
                "The automatic backup scheduler may stay enabled: only its run-log"
                " family is exempt and its database access is read-only."
            )
            failures.append("full_pytest_entry_contract")
        else:
            full_cmd = [py, "-m", "pytest", "-q"]
            if _run_step("Full pytest suite", full_cmd, repo_root) != 0:
                failures.append("full_pytest")

    print("\n=== Summary ===")
    if failures:
        print("Failed steps:", ", ".join(failures))
        return 1
    print("All requested checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
