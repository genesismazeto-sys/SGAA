import argparse
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


def _run_step(label: str, args: list[str], cwd: Path) -> int:
    print(f"\n=== {label} ===")
    print("Command:", " ".join(args))
    completed = subprocess.run(args, cwd=str(cwd))
    print(f"Exit code: {completed.returncode}")
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run release 1.0 checks in sequence (release tests + smokes + optional full pytest)."
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
