"""Deterministic UUIDs and item order for generated .kicad_pcb files.

pcbnew gives every item a fresh random UUID on each run and writes top-level
items in uuid order, so a regenerated board differs on every line even when
nothing changed.  canonicalize() rewrites each uuid as a hash of (its top-level
item's content, its own block's content, its index within the item), all with
uuids stripped, then sorts each run of same-kind top-level items by that uuid.
Identical geometry therefore yields an identical file and `git diff` shows only
real changes.  Board files do not cross-reference item uuids (footprint
`(path ...)` entries point at schematic symbols and are untouched), so this is
safe.  Not for schematics: their instance paths embed symbol uuids.
"""
import hashlib
import re

_UUID = re.compile(r'\(uuid "[0-9a-f-]{36}"\)')
_SORTED_KINDS = {"footprint", "segment", "via", "arc", "zone", "gr_line",
                 "gr_arc", "gr_circle", "gr_rect", "gr_poly", "gr_text"}


def _uuid(*parts):
    h = hashlib.sha1("\x00".join(parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def _enclosing(s, pos):
    """Span of the innermost "( ... )" containing position pos."""
    depth, i = 0, pos - 1
    while i >= 0:
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            if depth == 0:
                break
            depth -= 1
        i -= 1
    depth, j = 0, i
    while j < len(s):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return i, j + 1


def _rewrite_item(item):
    base = _UUID.sub("", item)
    out, pos = [], 0
    for k, m in enumerate(_UUID.finditer(item)):
        a, b = _enclosing(item, m.start())
        inner = _UUID.sub("", item[a:b])
        out.append(item[pos:m.start()])
        out.append(f'(uuid "{_uuid(base, inner, str(k))}")')
        pos = m.end()
    out.append(item[pos:])
    return "".join(out)


def canonicalize(path):
    s = open(path, encoding="utf-8").read()
    new = canonical_text(s)
    if new != s:
        open(path, "w", encoding="utf-8").write(new)


def canonical_text(s):
    """canonicalize() on the text of a .kicad_pcb."""
    head_end = s.index("\n", s.index("(kicad_pcb")) + 1
    close = s.rindex(")")
    body, tail = s[head_end:close], s[close:]
    items, depth, start = [], 0, None
    for j, c in enumerate(body):
        if c == "(":
            if depth == 0:
                start = j
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                items.append(_rewrite_item(body[start:j + 1]))
    # pcbnew writes tracks (segments, arcs, vias) as one list in random-uuid
    # order, and likewise the board graphics: a run of one class is sorted
    # as a whole (by kind, then the new uuid), so how the kinds happened to
    # interleave on this run does not matter (FoveaCam: segment / via runs
    # differed between runs before)
    _CLASS = {"segment": "track", "arc": "track", "via": "track"}
    kind = lambda b: _CLASS.get(b[1:].split(None, 1)[0],  # noqa: E731
                                "gr" if b[1:].startswith("gr_") else b[1:].split(None, 1)[0])
    key = lambda b: (_UUID.search(b) or [""])[0] if _UUID.search(b) else ""  # noqa: E731
    out, k = [], 0
    while k < len(items):
        g = [items[k]]
        while k + len(g) < len(items) and kind(items[k + len(g)]) == kind(g[0]):
            g.append(items[k + len(g)])
        if kind(g[0]) in _SORTED_KINDS | {"track", "gr"}:
            g.sort(key=lambda b: (b[1:].split(None, 1)[0],
                                  _UUID.search(b).group(0) if _UUID.search(b) else ""))
        out.extend(g)
        k += len(g)
    return s[:head_end] + "".join("\t" + b + "\n" for b in out) + tail


def strip_render_cache(s):
    """The text without its (render_cache ...) blocks: the TrueType glyph outlines
    KiCad stores with the text, drawn by the machine's FreeType, so they differ by
    platform (lib/fonts/README.md)."""
    return strip_blocks(s, "render_cache")


def strip_blocks(s, head):
    """The text without its (<head> ...) blocks, each with its own line when it has
    one.  Quoted strings may hold parentheses."""
    out, pos = [], 0
    while (i := s.find("(" + head, pos)) >= 0:
        line = s.rfind("\n", 0, i) + 1
        depth, j, quoted = 0, i, False
        while j < len(s):
            c = s[j]
            if quoted:
                if c == "\\":
                    j += 1
                elif c == '"':
                    quoted = False
            elif c == '"':
                quoted = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        end = j + 1
        if s[end:end + 1] == "\n" and not s[line:i].strip():
            end += 1
        else:
            line = i
        out.append(s[pos:line])
        pos = end
    out.append(s[pos:])
    return "".join(out)
