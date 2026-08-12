"""SGAA Design System — static CSS cascade analyser.

Purpose
-------
Give the Design System migration a *browser-free* proof of visual equivalence
for refactors that only move, merge or delete CSS declarations.

The analyser answers three questions for every page template:

1.  Which stylesheets and ``<style>`` blocks does this page load, in which
    order?  (``page_sources``)
2.  What is the flattened, ordered stream of CSS declarations that results?
    (``page_stream``)
3.  For every ``(at-rule context, selector, property)`` triple, which
    declaration finally wins?  (``resolve_winners``)

Two invariants can then be enforced by the test-suite:

*   **ORDER**   — the new declaration stream is a *subsequence* of the old one.
    Nothing was reordered; declarations were only removed or relocated in a
    way that preserves relative order.
*   **RESOLUTION** — every surviving ``(context, selector, property)`` triple
    resolves to the same value as before.

ORDER + RESOLUTION together prove that a *deletion/relocation* refactor cannot
change the rendered result, without ever opening a browser.

Scope and honest limits
-----------------------
Winners are resolved **per exact selector text**, not per DOM element.  That is
precisely the granularity needed to prove file reorganisation safe (identical
selector text ⇒ identical specificity ⇒ document order decides).  It does *not*
model cross-selector competition (``.btn`` vs ``.toolbar .btn``), because that
needs a DOM.  Phases that deliberately change selector text or specificity are
therefore **out of scope for this gate** and require a browser-based check.

The module has no third-party dependencies and is importable from tests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

# At-rules that wrap other rules and therefore form a nesting context.
CONDITIONAL_AT_RULES = ("media", "supports", "layer", "container", "document", "scope")


# --------------------------------------------------------------------------
# CSS text utilities
# --------------------------------------------------------------------------

def strip_comments(css: str) -> str:
    """Remove ``/* ... */`` comments without touching string literals."""
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        ch = css[i]
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                if css[i] == "\\" and i + 1 < n:
                    out.append(css[i : i + 2])
                    i += 2
                    continue
                out.append(css[i])
                if css[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < n and css[i + 1] == "*":
            end = css.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize_selector(selector: str) -> str:
    """Whitespace/combinator normalisation. Never changes what a selector matches."""
    s = re.sub(r"\s+", " ", selector).strip()
    s = re.sub(r"\s*([>+~])\s*", r" \1 ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.strip()


def normalize_at_prelude(prelude: str) -> str:
    """Normalise an at-rule prelude so equivalent conditions compare equal.

    ``@media (max-width: 640px)`` and ``@media (max-width:640px)`` select the
    same context; without this they would be treated as two independent
    cascade contexts and a genuine conflict between them could be missed.
    """
    s = normalize_selector(prelude)
    s = re.sub(r"\s*:\s*", ":", s)
    s = re.sub(r"\(\s*", "(", s)
    s = re.sub(r"\s*\)", ")", s)
    return s.strip()


def normalize_value(value: str) -> str:
    """Whitespace normalisation for declaration values.

    Collapses runs of whitespace and removes whitespace around commas.  Both
    are semantically inert in CSS, so two values that normalise equal render
    identically.  This is what lets us prove that ``--font-sans`` declared as
    ``'Inter',-apple-system`` and ``'Inter', -apple-system`` are the same token.
    """
    v = re.sub(r"\s+", " ", value).strip()
    v = re.sub(r"\s*,\s*", ",", v)
    return v.strip().rstrip(";").strip()


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split on ``separator`` only at paren/bracket depth 0 and outside strings."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i : i + 2])
                    i += 2
                    continue
                buf.append(text[i])
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == separator and depth <= 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


# --------------------------------------------------------------------------
# Declaration model
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Declaration:
    """One CSS declaration, with everything needed to reason about the cascade."""

    context: str        # at-rule chain, e.g. "@media (max-width:640px)"; "" at top level
    selector: str       # single normalized selector (selector lists are exploded)
    prop: str           # property name, e.g. "color" or "--brand"
    value: str          # normalized value
    important: bool
    source: str         # human-readable origin, e.g. "static/css/modern-style.css"

    def key(self) -> tuple[str, str, str]:
        return (self.context, self.selector, self.prop)

    def as_tuple(self) -> tuple:
        return (self.context, self.selector, self.prop, self.value, self.important)


def parse_declarations(css: str, source: str) -> list[Declaration]:
    """Flatten a stylesheet into an ordered list of :class:`Declaration`."""
    css = strip_comments(css)
    result: list[Declaration] = []
    _parse_block_list(css, "", source, result)
    return result


def _parse_block_list(css: str, context: str, source: str, out: list[Declaration]) -> None:
    i, n = 0, len(css)
    prelude: list[str] = []
    while i < n:
        ch = css[i]
        if ch in "\"'":
            quote = ch
            prelude.append(ch)
            i += 1
            while i < n:
                if css[i] == "\\" and i + 1 < n:
                    prelude.append(css[i : i + 2])
                    i += 2
                    continue
                prelude.append(css[i])
                if css[i] == quote:
                    i += 1
                    break
                i += 1
            continue

        if ch == ";" and not "".join(prelude).strip().startswith("@"):
            prelude = []
            i += 1
            continue

        if ch == ";":
            # statement at-rule such as @import / @charset — record verbatim so
            # that adding or removing one is detected by the gate.
            text = normalize_selector("".join(prelude))
            if text:
                out.append(
                    Declaration(context, text, "@statement", "", False, source)
                )
            prelude = []
            i += 1
            continue

        if ch == "{":
            body, end = _read_block(css, i)
            head = "".join(prelude).strip()
            prelude = []
            i = end
            _handle_block(head, body, context, source, out)
            continue

        prelude.append(ch)
        i += 1


def _read_block(css: str, open_index: int) -> tuple[str, int]:
    """Return (body, index_after_closing_brace) for the block starting at ``{``."""
    depth = 0
    i, n = open_index, len(css)
    start = open_index + 1
    while i < n:
        ch = css[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n:
                if css[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if css[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return css[start:i], i + 1
        i += 1
    return css[start:], n


def _handle_block(head: str, body: str, context: str, source: str, out: list[Declaration]) -> None:
    if not head:
        return

    if head.startswith("@"):
        name = re.match(r"@([a-zA-Z-]+)", head)
        at_name = name.group(1).lower() if name else ""
        if at_name in CONDITIONAL_AT_RULES:
            nested = normalize_at_prelude(head)
            new_context = f"{context} {nested}".strip() if context else nested
            _parse_block_list(body, new_context, source, out)
            return
        # Opaque at-rule (@keyframes, @font-face, @page...). Record its whole
        # body as one declaration so any edit is still caught by the gate.
        out.append(
            Declaration(
                context,
                normalize_selector(head),
                "@block",
                normalize_value(re.sub(r"\s+", " ", body)),
                False,
                source,
            )
        )
        return

    selectors = [normalize_selector(s) for s in _split_top_level(head, ",")]
    decls = _parse_declaration_body(body)
    for selector in selectors:
        if not selector:
            continue
        for prop, value, important in decls:
            out.append(Declaration(context, selector, prop, value, important, source))


def _parse_declaration_body(body: str) -> list[tuple[str, str, bool]]:
    decls: list[tuple[str, str, bool]] = []
    for chunk in _split_top_level(body, ";"):
        chunk = chunk.strip()
        if not chunk or "{" in chunk:
            continue
        pieces = _split_top_level(chunk, ":")
        if len(pieces) < 2:
            continue
        prop = pieces[0].strip()
        value = ":".join(pieces[1:]).strip()
        if not prop:
            continue
        important = bool(re.search(r"!\s*important\s*$", value, re.I))
        if important:
            value = re.sub(r"!\s*important\s*$", "", value, flags=re.I)
        decls.append((prop, normalize_value(value), important))
    return decls


# --------------------------------------------------------------------------
# Template head resolution (Jinja inheritance, statically resolved)
# --------------------------------------------------------------------------

@dataclass
class CssSource:
    kind: str            # "link" | "inline"
    ident: str           # stylesheet path, or "<style> #n in <template>"
    css: str = ""
    missing: bool = False


_EXTENDS_RE = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]\s*-?%}")
_EXTENDS_ANY_RE = re.compile(r"{%-?\s*extends\s+(.+?)\s*-?%}", re.S)
# `{% extends base_template|default("base_aluno.html") %}` — a runtime-swappable
# parent. The default literal is the parent used in normal rendering.
_EXTENDS_DEFAULT_RE = re.compile(r"\|\s*default\(\s*['\"]([^'\"]+)['\"]")


def parent_template_name(text: str) -> str | None:
    """Resolve the parent of a template, including the ``|default(...)`` form.

    Returns ``None`` when the template does not extend anything. Raises
    :class:`UnresolvableExtends` when it extends something this analyser cannot
    resolve — silence there would drop the whole page from every gate.
    """
    literal = _EXTENDS_RE.search(text)
    if literal:
        return literal.group(1)
    any_extends = _EXTENDS_ANY_RE.search(text)
    if not any_extends:
        return None
    fallback = _EXTENDS_DEFAULT_RE.search(any_extends.group(1))
    if fallback:
        return fallback.group(1)
    raise UnresolvableExtends(any_extends.group(1).strip())


class UnresolvableExtends(Exception):
    """A template extends an expression the analyser cannot statically resolve."""


def templates_with_unresolvable_extends() -> list[tuple[str, str]]:
    """(template, expression) for every template whose parent cannot be resolved."""
    offenders = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            parent_template_name(text)
        except UnresolvableExtends as exc:
            offenders.append((rel_path(path), str(exc)))
    return offenders
_URL_FOR_STATIC_RE = re.compile(
    r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]"
)


def _extract_block(text: str, block_name: str) -> str | None:
    """Return the inner body of ``{% block <name> %}...{% endblock %}``."""
    open_re = re.compile(r"{%-?\s*block\s+" + re.escape(block_name) + r"\s*-?%}")
    match = open_re.search(text)
    if not match:
        return None
    idx = match.end()
    depth = 1
    token_re = re.compile(r"{%-?\s*(block|endblock)\b[^%]*-?%}")
    while depth:
        token = token_re.search(text, idx)
        if not token:
            return text[match.end():]
        if token.group(1) == "block":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return text[match.end(): token.start()]
        idx = token.end()
    return None


_FROM_IMPORT_RE = re.compile(
    r"{%-?\s*from\s+['\"]([^'\"]+)['\"]\s+import\s+([A-Za-z_][A-Za-z0-9_,\s]*)-?%}"
)
_CSS_LITERAL_RE = re.compile(r"['\"](css/[^'\"]+\.css)['\"]")


def _macro_stylesheets(macro_file: str) -> list[str]:
    """Stylesheet paths declared, in order, by a load-order macro file."""
    path = TEMPLATES_DIR / macro_file
    if not path.exists():
        return []
    return _CSS_LITERAL_RE.findall(path.read_text(encoding="utf-8", errors="replace"))


def _collect_macro_imports(template: Path, seen: frozenset[str] = frozenset()) -> dict[str, str]:
    """Map macro name -> defining template, across the whole inheritance chain."""
    text = template.read_text(encoding="utf-8", errors="replace")
    imports: dict[str, str] = {}
    parent_name = parent_template_name(text)
    if parent_name and parent_name not in seen:
        parent = TEMPLATES_DIR / parent_name
        if parent.exists():
            imports.update(_collect_macro_imports(parent, seen | {parent_name}))
    for macro_file, names in _FROM_IMPORT_RE.findall(text):
        for name in names.split(","):
            name = name.strip()
            if name:
                imports[name] = macro_file
    return imports


def _expand_macro_calls(head: str, imports: dict[str, str]) -> str:
    """Replace ``{{ some_macro(...) }}`` with the <link> tags it emits.

    Only macros whose defining file declares ``css/...`` literals are expanded.
    This is what lets the analyser see through
    ``templates/components/design_system_css.html``, which by contract is the
    single owner of design-system stylesheet load order.
    """
    for name, macro_file in imports.items():
        sheets = _macro_stylesheets(macro_file)
        if not sheets:
            continue
        links = "\n".join(
            f'<link rel="stylesheet" href="/static/{sheet}">' for sheet in sheets
        )
        head = re.sub(
            r"{{-?\s*" + re.escape(name) + r"\s*\([^}]*\)\s*-?}}",
            lambda _m: links,
            head,
        )
    return head


def _head_text(template: Path, seen: frozenset[str] = frozenset()) -> str | None:
    """Resolve a template's rendered ``<head>`` text through Jinja inheritance."""
    text = template.read_text(encoding="utf-8", errors="replace")
    parent_name = parent_template_name(text)

    if parent_name is None:
        head = re.search(r"<head\b[^>]*>(.*?)</head>", text, re.S | re.I)
        return head.group(1) if head else None

    if parent_name in seen:
        return None
    parent = TEMPLATES_DIR / parent_name
    if not parent.exists():
        return None
    parent_head = _head_text(parent, seen | {parent_name})
    if parent_head is None:
        return None

    child_extra = _extract_block(text, "extra_head")
    replacement = child_extra if child_extra is not None else ""
    # Splice the child's extra_head into the parent's placeholder, preserving
    # the parent's document order (base.html emits its own <style> *after*
    # extra_head; base_aluno.html emits its own *before*).
    placeholder = re.compile(
        r"{%-?\s*block\s+extra_head\s*-?%}.*?{%-?\s*endblock\s*(?:extra_head\s*)?-?%}",
        re.S,
    )
    return placeholder.sub(lambda _m: replacement, parent_head, count=1)


def rel_path(path: Path) -> str:
    """Repo-relative POSIX path, tolerant of relative inputs."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (PROJECT_ROOT / resolved).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _resolve_href(href: str) -> str | None:
    """Map an href expression to a repo-relative static path."""
    match = _URL_FOR_STATIC_RE.search(href)
    if match:
        return f"static/{match.group(1)}"
    plain = href.strip().strip("\"'")
    if plain.startswith("/static/"):
        return plain.lstrip("/")
    return None


def page_sources(template: Path) -> list[CssSource]:
    """Ordered CSS sources for a page template, or ``[]`` if it has no head."""
    head = _head_text(template)
    if head is None:
        return []
    head = _expand_macro_calls(head, _collect_macro_imports(template))

    sources: list[CssSource] = []
    inline_index = 0
    token_re = re.compile(r"<link\b[^>]*>|<style\b[^>]*>(.*?)</style>", re.S | re.I)

    for token in token_re.finditer(head):
        raw = token.group(0)
        if raw.lower().startswith("<style"):
            inline_index += 1
            sources.append(
                CssSource(
                    kind="inline",
                    ident=f"{rel_path(template)}#style{inline_index}",
                    css=token.group(1) or "",
                )
            )
            continue

        if "stylesheet" not in raw.lower():
            continue
        href_match = re.search(r'href\s*=\s*"([^"]*)"|href\s*=\s*\'([^\']*)\'', raw)
        if not href_match:
            continue
        href = href_match.group(1) or href_match.group(2) or ""
        rel = _resolve_href(href)
        if rel is None:
            continue  # external stylesheet (fonts) — not part of the design system
        path = PROJECT_ROOT / rel
        if not path.exists():
            sources.append(CssSource(kind="link", ident=rel, css="", missing=True))
            continue
        sources.append(
            CssSource(kind="link", ident=rel, css=path.read_text(encoding="utf-8", errors="replace"))
        )

    return sources


def page_templates() -> list[Path]:
    """Every template that renders a full document (i.e. resolves to a <head>)."""
    pages = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        if page_sources(path):
            pages.append(path)
    return pages


# --------------------------------------------------------------------------
# Cascade resolution
# --------------------------------------------------------------------------

def page_stream(template: Path) -> list[Declaration]:
    """Flattened, ordered declaration stream for one page."""
    stream: list[Declaration] = []
    for source in page_sources(template):
        if source.missing:
            continue
        stream.extend(parse_declarations(source.css, source.ident))
    return stream


def resolve_winners(stream: list[Declaration]) -> dict[tuple[str, str, str], tuple[str, bool]]:
    """Winning declaration per ``(context, selector, property)``.

    Within one selector text specificity is constant, so the cascade reduces to:
    last ``!important`` wins, otherwise last normal declaration wins.
    """
    normal: dict[tuple[str, str, str], str] = {}
    important: dict[tuple[str, str, str], str] = {}
    for decl in stream:
        (important if decl.important else normal)[decl.key()] = decl.value
    winners: dict[tuple[str, str, str], tuple[str, bool]] = {}
    for key, value in normal.items():
        winners[key] = (value, False)
    for key, value in important.items():
        winners[key] = (value, True)
    return winners


_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*(.*?))?\)\s*$", re.S)


def resolve_tokens(stream: list[Declaration], scope: str = ":root") -> dict[str, str]:
    """Resolve every ``--token`` declared on ``scope`` down to a literal value.

    ``var()`` chains are followed so that ``--btn-primary: var(--brand)``
    resolves to ``#003366``.  This is what proves a token consolidation left
    every computed value untouched.
    """
    raw: dict[str, str] = {}
    for decl in stream:
        if decl.context or decl.selector != scope or not decl.prop.startswith("--"):
            continue
        raw[decl.prop] = decl.value

    def expand(name: str, seen: frozenset[str]) -> str:
        if name in seen or name not in raw:
            return raw.get(name, "")
        value = raw[name]
        for _ in range(10):
            match = _VAR_RE.search(value)
            if not match:
                break
            ref, fallback = match.group(1), (match.group(2) or "").strip()
            resolved = expand(ref, seen | {name}) or fallback
            value = (value[: match.start()] + resolved).strip()
        return normalize_value(value)

    return {name: expand(name, frozenset()) for name in sorted(raw)}


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------

@dataclass
class PageFingerprint:
    template: str
    sources: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)
    stream: list[list] = field(default_factory=list)
    winners: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)


def fingerprint_page(template: Path) -> PageFingerprint:
    sources = page_sources(template)
    stream = page_stream(template)
    winners = resolve_winners(stream)
    return PageFingerprint(
        template=rel_path(template),
        sources=[s.ident for s in sources if not s.missing],
        missing_sources=[s.ident for s in sources if s.missing],
        stream=[list(d.as_tuple()) for d in stream],
        winners={
            "|".join(key): [value, important]
            for key, (value, important) in sorted(winners.items())
        },
        tokens=resolve_tokens(stream),
    )


def fingerprint_all() -> dict:
    return {
        "pages": [
            {
                "template": fp.template,
                "sources": fp.sources,
                "missing_sources": fp.missing_sources,
                "stream": fp.stream,
                "winners": fp.winners,
                "tokens": fp.tokens,
            }
            for fp in (fingerprint_page(p) for p in page_templates())
        ]
    }


def is_subsequence(smaller: list, larger: list) -> bool:
    """True if ``smaller`` appears inside ``larger`` in order (gaps allowed)."""
    it = iter(larger)
    return all(item in it for item in smaller)


def compare(before: dict, after: dict) -> tuple[bool, list[str]]:
    """Prove a deletion/relocation refactor changed nothing that renders.

    Checks the two invariants described in the module docstring:

    * ORDER      — the new declaration stream is a subsequence of the old one.
    * RESOLUTION — every ``(context, selector, property)`` still resolves to the
                   same value, and none disappeared.

    Returns ``(ok, findings)``.
    """
    findings: list[str] = []
    before_pages = {p["template"]: p for p in before["pages"]}
    after_pages = {p["template"]: p for p in after["pages"]}

    gone = sorted(set(before_pages) - set(after_pages))
    new = sorted(set(after_pages) - set(before_pages))
    for template in gone:
        findings.append(f"PAGE REMOVED: {template}")
    for template in new:
        findings.append(f"PAGE ADDED: {template}")

    for template in sorted(set(before_pages) & set(after_pages)):
        old, cur = before_pages[template], after_pages[template]

        old_stream = [tuple(d) for d in old["stream"]]
        new_stream = [tuple(d) for d in cur["stream"]]
        if not is_subsequence(new_stream, old_stream):
            findings.append(
                f"ORDER VIOLATED: {template} — new declaration stream is not a "
                f"subsequence of the old one (declarations were reordered or added)"
            )

        for key, old_value in old["winners"].items():
            new_value = cur["winners"].get(key)
            if new_value is None:
                findings.append(f"RESOLUTION LOST: {template} — {key} no longer resolves")
            elif new_value != old_value:
                findings.append(
                    f"RESOLUTION CHANGED: {template} — {key}: "
                    f"{old_value!r} -> {new_value!r}"
                )
        for key in cur["winners"]:
            if key not in old["winners"]:
                findings.append(f"RESOLUTION ADDED: {template} — {key}")

        for token, old_value in old["tokens"].items():
            new_value = cur["tokens"].get(token)
            if new_value != old_value:
                findings.append(
                    f"TOKEN CHANGED: {template} — {token}: {old_value!r} -> {new_value!r}"
                )

    return (not findings), findings


def main() -> None:  # pragma: no cover - developer utility
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the fingerprint JSON here")
    parser.add_argument("--summary", action="store_true", help="print a human summary")
    parser.add_argument(
        "--compare",
        type=Path,
        metavar="BEFORE.json",
        help="prove the working tree is cascade-equivalent to a saved fingerprint",
    )
    args = parser.parse_args()

    data = fingerprint_all()

    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        ok, findings = compare(before, data)
        if ok:
            print(f"EQUIVALENT — {len(data['pages'])} pages, ORDER + RESOLUTION invariants hold.")
        else:
            print(f"NOT EQUIVALENT — {len(findings)} finding(s):")
            for line in findings[:200]:
                print(f"  {line}")
            if len(findings) > 200:
                print(f"  ... and {len(findings) - 200} more")
        raise SystemExit(0 if ok else 1)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote {args.out} ({len(data['pages'])} pages)")

    if args.summary or not args.out:
        for page in data["pages"]:
            missing = f"  MISSING={page['missing_sources']}" if page["missing_sources"] else ""
            print(
                f"{page['template']:<58} sources={len(page['sources'])} "
                f"decls={len(page['stream']):>5} winners={len(page['winners']):>5}"
                f"{missing}"
            )


if __name__ == "__main__":  # pragma: no cover
    main()
