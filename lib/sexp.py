"""Minimal KiCad s-expression reader/writer and symbol-library helpers.

eeschema has no Python API, so the schematic is emitted as text.  Symbols
are copied from the stock .kicad_sym libraries; `extends` children are
flattened (the embedded lib_symbols block of a schematic must be flat).
"""
import math
import re

_TOK = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+)')


class Sym(str):
    """Bare (unquoted) atom."""


def parse(text):
    pos, stack, cur = 0, [], []
    n = len(text)
    while pos < n:
        m = _TOK.match(text, pos)
        if not m:
            break
        tok = m.group(1)
        pos = m.end()
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif tok.startswith('"'):
            cur.append(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            cur.append(Sym(tok))
    return cur[0] if len(cur) == 1 else cur


def dump(node, indent=0):
    tab = "\t" * indent
    if not isinstance(node, list):
        return _atom(node)
    simple = all(not isinstance(c, list) for c in node)
    if simple:
        return tab + "(" + " ".join(_atom(c) for c in node) + ")"
    head = []
    rest = []
    for c in node:
        if isinstance(c, list) or rest:
            rest.append(c)
        else:
            head.append(c)
    out = tab + "(" + " ".join(_atom(c) for c in head)
    for c in rest:
        if isinstance(c, list):
            out += "\n" + dump(c, indent + 1)
        else:
            out += "\n" + tab + "\t" + _atom(c)
    return out + "\n" + tab + ")"


def _atom(a):
    if isinstance(a, Sym):
        return str(a)
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, (int, float)):
        return fmt(a)
    s = str(a).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def fmt(v):
    v = round(float(v), 4)
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip("0").rstrip(".")


def find(node, key):
    for c in node:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def find_all(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


# ------------------------------------------------------------------ libs
_LIB_CACHE = {}


def load_lib(path):
    if path not in _LIB_CACHE:
        _LIB_CACHE[path] = parse(open(path).read())
    return _LIB_CACHE[path]


def lib_symbol(path, name):
    """Return a flattened deep copy of symbol `name` from library `path`."""
    import copy
    lib = load_lib(path)
    syms = {s[1]: s for s in find_all(lib, "symbol")}
    s = copy.deepcopy(syms[name])
    ext = find(s, "extends")
    if ext is None:
        return s
    parent = lib_symbol(path, ext[1])
    pname = parent[1]
    out = [Sym("symbol"), name]
    child_props = {p[1]: p for p in find_all(s, "property")}
    for c in parent[2:]:
        if isinstance(c, list) and c[0] == "property" and c[1] in child_props:
            out.append(child_props.pop(c[1]))
        elif isinstance(c, list) and c[0] == "symbol":
            c = copy.deepcopy(c)
            c[1] = name + c[1][len(pname):]
            out.append(c)
        else:
            out.append(c)
    # child-only properties go before the unit sub-symbols
    idx = max(i for i, c in enumerate(out)
              if isinstance(c, list) and c[0] == "property") + 1
    for p in child_props.values():
        out.insert(idx, p)
        idx += 1
    return out


def symbol_pins(sym):
    """[(unit, number, name, etype, x, y, angle)] in symbol coordinates
    (y up).  Unit 0 pins belong to every unit."""
    pins = []
    for sub in find_all(sym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", sub[1])
        unit, style = int(m.group(1)), int(m.group(2))
        if style not in (0, 1):
            continue
        for p in find_all(sub, "pin"):
            at = find(p, "at")
            nm = find(p, "name")[1]
            num = find(p, "number")[1]
            pins.append((unit, num, nm, str(p[1]), float(at[1]),
                         float(at[2]), float(at[3]) if len(at) > 3 else 0))
    return pins


def sch_xy(at, rot, px, py):
    """Pin connection point in schematic coordinates (y down) for a symbol
    placed at `at` with rotation `rot` (no mirror)."""
    a = math.radians(rot)
    rx = px * math.cos(a) - py * math.sin(a)
    ry = px * math.sin(a) + py * math.cos(a)
    return round(at[0] + rx, 4), round(at[1] - ry, 4)
