# coding: utf-8
"""Deployment source export and leak audit -- operator tool, never imported by ``app/``.

WHY THIS EXISTS
    The working tree beside the code holds the real database, its
    pre-migration copies, uploaded documents and logs (all untracked).  A
    platform CLI that uploads "the directory" would publish them.  Two controls:

    ``export``  builds the upload directory from ``git archive`` of one
                commit -- committed content only, byte for byte (every file's
                git blob id is re-computed and compared with the commit's
                tree, whatever the operator's ``core.autocrlf`` is) -- and
                keeps only the runtime allowlist (the application, its
                templates and static files, its requirements and the
                deployment descriptors).  Tests, docs, tools and this file are
                not part of what runs.
    ``audit``   scans a directory that is about to be uploaded and refuses it
                when it holds a forbidden path, a database or dump signature, a
                secret-shaped value, or a sentinel the operator planted.  Every
                file is read to the end (up to ``MAX_FILE_BYTES``); a larger
                file is itself a finding.

    The audit is the control; ``.vercelignore`` is defence in depth.

OUTPUT
    Value-free: counts, fixed codes and digests of paths.  A path may be a
    student's file name, so paths are shown only with ``--show-paths``, on the
    operator's terminal.  Contents are never printed.

Exit codes: 0 clean / exported, 1 findings or refused, 2 usage.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]

# What a deployment contains: exactly this and nothing else (first path segment or file).
RUNTIME_ALLOWLIST = (
    "app", "services", "utils", "templates", "static", "public",
    "main.py", "presets_api.py", "presets_data.json", "requirements.txt",
    "vercel.json", "pyproject.toml", ".python-version", ".vercelignore",
)

FORBIDDEN_DIRECTORIES = frozenset({
    "uploads", "documentos_alunos", "logs", "backups", "_normativos_inbox", ".git", ".claude",
    "__pycache__", ".venv", "venv", "tests", "docs", "tools", ".pytest_cache", "node_modules",
})
FORBIDDEN_NAMES = (
    ".env", ".env.*", "*.env", "*.db", "*.db-wal", "*.db-shm", "*.db-journal", "*.sqlite", "*.sqlite3",
    "*.dump", "*.sql", "*.bak", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", ".pgpass", "pgpass.conf",
    "ledger.jsonl", "MANIFEST.json", "*.manifest.json", "database.*", "*.log", "*.zip", "*.7z", "*.tar",
    "*.tar.gz", "*.tgz", "*.csv", "*.xls", "*.xlsx",
)
# ".env.example" is a documented template, not a secret.
ALLOWED_NAMES = frozenset({".env.example"})

SQLITE_MAGIC = b"SQLite format 3\x00"
PG_DUMP_MAGIC = b"PGDMP"
SECRET_PATTERNS = {
    "SECRET_DATABASE_URL_WITH_PASSWORD": re.compile(rb"postgres(?:ql)?(?:\+[a-z0-9]+)?://[^:/\s@]+:[^@\s]{3,}@"),
    "SECRET_PRIVATE_KEY_BLOCK": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "SECRET_SUPABASE_KEY": re.compile(rb"sb_secret_[A-Za-z0-9_\-]{20,}"),
    "SECRET_JWT": re.compile(rb"eyJ[A-Za-z0-9_\-]{15,}\.eyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}"),
    "SECRET_GOOGLE_CLIENT": re.compile(rb"GOCSPX-[A-Za-z0-9_\-]{20,}"),
    "POSTGRESQL_DUMP_TEXT": re.compile(rb"-- PostgreSQL database dump|COPY \S+ \([^)]*\) FROM stdin"),
}
CHUNK_BYTES = 1024 * 1024
OVERLAP_BYTES = 4096
MAX_FILE_BYTES = 16 * 1024 * 1024


class Refused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _inside(path: Path, root: Path) -> bool:
    resolved, base = path.resolve(), root.resolve()
    return resolved == base or base in resolved.parents


def _digest(relative: str) -> str:
    return hashlib.sha256(relative.encode("utf-8", "surrogatepass")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _allowed(member_path: str) -> bool:
    if "\\" in member_path or ":" in member_path:
        return False  # a Windows separator or an NTFS alternate data stream is never a runtime file
    parts = PurePosixPath(member_path).parts
    if not parts or ".." in parts or member_path.startswith("/"):
        return False
    return parts[0] in RUNTIME_ALLOWLIST


def _git(repo: Path, *arguments, text=True, timeout=300):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.safecrlf=false",
         *arguments],
        capture_output=True, text=text, timeout=timeout,
    )


def _blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def export(commit: str, out: Path, *, repo: Path = REPO_ROOT) -> dict:
    """Write the allowlisted tree of ``commit`` into the new directory ``out``, byte for byte."""
    out = Path(out)
    if _inside(out, repo):
        raise Refused("OUTPUT_INSIDE_REPOSITORY", "the upload directory lives outside the repository")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused("OUTPUT_NOT_EMPTY")
    try:
        resolved = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        raise Refused("COMMIT_NOT_FOUND") from None
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise Refused("COMMIT_NOT_FOUND")
    tree = _git(repo, "ls-tree", "-r", "-z", "--full-tree", resolved, text=False)
    if tree.returncode != 0:
        raise Refused("ARCHIVE_FAILED")
    blobs = {}
    for entry in tree.stdout.split(b"\x00"):
        if not entry:
            continue
        meta, _, name = entry.partition(b"\t")
        mode, kind, blob = meta.decode("ascii").split()
        if kind == "blob" and mode in {"100644", "100755"}:  # regular files; a link is not exported
            blobs[name.decode("utf-8", "surrogateescape")] = blob
    archive = _git(repo, "archive", "--format=tar", resolved, text=False)
    if archive.returncode != 0:
        raise Refused("ARCHIVE_FAILED")
    created = not out.exists()
    out.mkdir(parents=True, exist_ok=True)
    try:
        return _write_export(out, resolved, blobs, archive.stdout)
    except Refused:
        # A refused export leaves nothing that could be uploaded by mistake.
        if created:
            shutil.rmtree(out, ignore_errors=True)
        else:
            for child in out.iterdir():
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
        raise


def _write_export(out: Path, commit: str, blobs: dict, archive: bytes) -> dict:
    root = out.resolve()
    files = total = 0
    expected = {name for name in blobs if _allowed(name)}
    exported: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        for member in tar:
            if not member.isfile() or not _allowed(member.name):
                continue
            data = tar.extractfile(member).read()
            if blobs.get(member.name) != _blob_id(data):
                raise Refused("EXPORT_NOT_THE_COMMIT", "an exported file is not the committed blob")
            target = (out / PurePosixPath(member.name)).resolve()
            if root not in target.parents:
                raise Refused("ARCHIVE_MEMBER_UNSAFE")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files += 1
            total += len(data)
            exported.add(member.name)
    if files == 0:
        raise Refused("NOTHING_EXPORTED")
    if exported != expected:
        # An export-ignore attribute (or a sparse archive) would otherwise drop files and still succeed.
        raise Refused("EXPORT_INCOMPLETE", "the archive lacks files the commit has on the runtime allowlist")
    return {"commit": commit, "files": files, "bytes": total}


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def _name_findings(relative: PurePosixPath) -> list[str]:
    findings = []
    for part in relative.parts[:-1]:
        if part.lower() in FORBIDDEN_DIRECTORIES:  # NTFS is case-insensitive
            findings.append("FORBIDDEN_DIRECTORY")
    name = relative.name
    if name.lower() not in ALLOWED_NAMES:
        for pattern in FORBIDDEN_NAMES:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                findings.append("FORBIDDEN_NAME")
                break
    if ":" in relative.as_posix():
        findings.append("ALTERNATE_DATA_STREAM")
    return findings


SENTINEL_ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")


def _decode_sentinel_file(raw: bytes) -> str:
    """The text of a sentinel file as the Windows shells write it: UTF-8 (with or without a BOM) or UTF-16."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def load_sentinels(path: str | None) -> list[bytes]:
    """Each token searched as UTF-8 and as UTF-16 (both byte orders); a file with no usable token is refused."""
    if not path:
        return []
    try:
        text = _decode_sentinel_file(Path(path).read_bytes())
    except (OSError, ValueError):
        raise Refused("SENTINELS_UNREADABLE") from None
    tokens = [line.strip().lstrip("\ufeff") for line in text.splitlines()]
    if any("\x00" in token for token in tokens):
        raise Refused("SENTINELS_UNREADABLE")  # UTF-16 without a BOM, read as UTF-8
    usable = [token for token in tokens if len(token) >= 6]
    if not usable:
        raise Refused("SENTINELS_EMPTY", "a sentinel file needs at least one token of six characters")
    return [token.encode(encoding) for token in usable for encoding in SENTINEL_ENCODINGS]


def _scan_file(full: Path, sentinels: list[bytes]) -> tuple[bytes, set[str], bool]:
    """Head bytes, the pattern codes found and whether a sentinel was found; reads the whole file."""
    codes: set[str] = set()
    sentinel_found = False
    head = b""
    carry = b""
    with open(full, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            if not head:
                head = chunk[:16]
            window = carry + chunk
            for code, pattern in SECRET_PATTERNS.items():
                if code not in codes and pattern.search(window):
                    codes.add(code)
            if not sentinel_found and any(sentinel in window for sentinel in sentinels):
                sentinel_found = True
            carry = window[-OVERLAP_BYTES:]
    return head, codes, sentinel_found


def audit(directory: Path, *, sentinels: list[bytes] | None = None) -> dict:
    directory = Path(directory)
    if not directory.is_dir():
        raise Refused("DIRECTORY_MISSING")
    sentinels = sentinels or []
    findings: list[dict] = []
    files = total = 0
    for current, dirs, names in os.walk(directory):
        # Links could point anywhere (a document root, a database): never followed, always a finding.
        for name in list(dirs):
            full = Path(current) / name
            if full.is_symlink() or _is_reparse_point(full):
                findings.append({"code": "LINK_IN_UPLOAD", "path": _relative(full, directory)})
                dirs.remove(name)
            elif name.lower() in FORBIDDEN_DIRECTORIES:
                findings.append({"code": "FORBIDDEN_DIRECTORY", "path": _relative(full, directory)})
        for name in names:
            full = Path(current) / name
            relative = _relative(full, directory)
            if full.is_symlink() or _is_reparse_point(full):
                findings.append({"code": "LINK_IN_UPLOAD", "path": relative})
                continue
            files += 1
            size = full.stat().st_size
            total += size
            for code in _name_findings(PurePosixPath(relative)):
                findings.append({"code": code, "path": relative})
            if size > MAX_FILE_BYTES:
                findings.append({"code": "FILE_TOO_LARGE", "path": relative})
                continue
            head, codes, sentinel_found = _scan_file(full, sentinels)
            if head.startswith(SQLITE_MAGIC):
                findings.append({"code": "SQLITE_SIGNATURE", "path": relative})
            if head.startswith(PG_DUMP_MAGIC):
                findings.append({"code": "POSTGRESQL_DUMP_SIGNATURE", "path": relative})
            for code in sorted(codes):
                findings.append({"code": code, "path": relative})
            if sentinel_found:
                findings.append({"code": "SENTINEL_FOUND", "path": relative})
    return {"files": files, "bytes": total, "findings": findings, "sentinels_applied": len(sentinels) // len(SENTINEL_ENCODINGS)}


def _relative(path: Path, root: Path) -> str:
    return PurePosixPath(*path.relative_to(root).parts).as_posix()


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = os.lstat(path).st_file_attributes  # Windows junctions and symlinks
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _report(result: dict, *, show_paths: bool) -> dict:
    by_code: dict[str, int] = {}
    for finding in result["findings"]:
        by_code[finding["code"]] = by_code.get(finding["code"], 0) + 1
    report = {
        "result": "CLEAN" if not result["findings"] else "FINDINGS",
        "files": result["files"], "bytes": result["bytes"], "findings": by_code,
        "sentinels_applied": result.get("sentinels_applied", 0),
        "path_digests": sorted({_digest(f["path"]) for f in result["findings"]})[:20],
    }
    if show_paths:
        report["paths"] = sorted({f["path"] for f in result["findings"]})[:20]
    return report


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def main(argv=None, *, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="deploy_audit", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    export_parser = commands.add_parser("export", allow_abbrev=False)
    export_parser.add_argument("--commit", required=True)
    export_parser.add_argument("--out", required=True, help="a new, empty directory outside the repository")
    audit_parser = commands.add_parser("audit", allow_abbrev=False)
    audit_parser.add_argument("--dir", required=True)
    audit_parser.add_argument("--sentinels", default=None, help="a file with one sentinel token per line")
    audit_parser.add_argument("--show-paths", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        if args.command == "export":
            result = export(args.commit, Path(args.out))
            audited = audit(Path(args.out))
            result["audit"] = _report(audited, show_paths=False)
            json.dump(result, out, sort_keys=True)
            out.write("\n")
            return 0 if not audited["findings"] else 1
        audited = audit(Path(args.dir), sentinels=load_sentinels(args.sentinels))
        report = _report(audited, show_paths=args.show_paths)
        json.dump(report, out, sort_keys=True)
        out.write("\n")
        return 0 if report["result"] == "CLEAN" else 1
    except Refused as refusal:
        err.write(f"deploy-audit: refused: {refusal.code}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
