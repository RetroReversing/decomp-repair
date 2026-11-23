"""Two integer locals that are never live together, written as one variable.

A decompiler names one local for each value; the game's C reused a few names (a counter's temporary in one loop is the
index of a later one), and the compiler gives a variable that is set in two places, with its uses in both, the
register priority of both: more references, a longer life. The allocator then ranks it above neighbours the split
version ranked below, and GCC 2.7.2's cse picks the longer-lived of two equal registers as the one it rewrites uses to
(240 -> 145 in one 242-instruction heightmap filter, where the first loop's selection temporary and the second
loop's clamped index are one variable). `pointer_local_merge` does this for pointers; this is the integer form.

A proposal takes two integer locals of the same declared type where every reference of the first comes before the
second's first reference, and that first reference is a plain assignment (`B = ...;`) that no loop shares with a
reference of the first (a value carried round a loop would be clobbered): the second is renamed to the first, and its
declaration dropped. No `goto`, label or `switch` in the function. At most 10 proposals, nearest pairs first; the
judge decides."""
import re

from .integer_repair_support import INTEGER, edit, view

FAMILY = 'disjoint_scalar_merge'
FAMILIES = (FAMILY,)
LIMIT = 10

_ID = r'[A-Za-z_]\w*'
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{INTEGER})\s+(?P<names>{_ID}(?:\s*,\s*{_ID})*)\s*;[ \t]*$')
_LOOP = re.compile(r'\b(?P<kind>for|while|do)\b')


def _match(text, at):
    """The index of the bracket closing the one at `at`."""
    pairs = {'(': ')', '{': '}'}
    depth = 0
    for position in range(at, len(text)):
        depth += text[position] in pairs
        depth -= text[position] in pairs.values()
        if depth == 0:
            return position
    return None


def _loops(clean, opening, end):
    """The span of every loop of the function (`for`, `while` and `do ... while`), or None when one has no braces."""
    spans = []
    for hit in _LOOP.finditer(clean, opening + 1, end):
        at = hit.end()
        if hit['kind'] == 'do':
            body = re.compile(r'\s*\{').match(clean, at)
            if not body:
                return None
            close = _match(clean, body.end() - 1)
            tail = re.compile(r'\s*while\s*\(').match(clean, close + 1) if close else None
            stop = _match(clean, tail.end() - 1) if tail else None
            spans.append((hit.start(), stop + 1 if stop else None))
            continue
        head = re.compile(r'\s*\(').match(clean, at)
        if not head:
            return None
        close = _match(clean, head.end() - 1)
        if close is None:
            return None
        after = re.compile(r'\s*(\{|;)').match(clean, close + 1)
        if not after or after.group(1) == ';':
            if after and re.compile(r'\s*while\s*\(').match(clean, hit.start()) and clean[:hit.start()].rstrip().endswith('}'):
                continue  # the `while (...)` that ends a `do` loop
            return None
        stop = _match(clean, after.end(1) - 1)
        spans.append((hit.start(), stop + 1 if stop else None))
    return None if any(stop is None for _, stop in spans) else spans


def variants(source, name):
    """Proposals: an integer local renamed to an earlier one that is dead before its first assignment."""
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|switch|asm|volatile)\b|\b\w+\s*:(?!:)\s*[;\n]', part.clean[part.opening:part.end]):
        return []
    declared = {}
    for hit in _DECL.finditer(part.clean, part.opening + 1, part.end):
        for local in re.findall(_ID, hit['names']):
            declared[local] = (hit['type'], hit)
    if len(declared) < 2:
        return []
    spans = _loops(part.clean, part.opening, part.end)
    if spans is None:
        return []
    declarations = [(hit.start(), hit.end()) for _, hit in declared.values()]
    refs = {}
    for local in declared:
        refs[local] = [m.start() for m in re.finditer(rf'(?<![\w.]){re.escape(local)}\b', part.clean[part.opening + 1:part.end])]
        refs[local] = [at + part.opening + 1 for at in refs[local]
                       if not any(start <= at + part.opening + 1 < stop for start, stop in declarations)]
    out = []
    names = sorted(declared, key=lambda local: min(refs[local], default=10**9))
    for index, keep in enumerate(names):
        if not refs[keep]:
            continue
        for drop in names[index + 1:]:
            if declared[keep][0] != declared[drop][0] or not refs[drop] or max(refs[keep]) >= refs[drop][0]:
                continue
            first = refs[drop][0]
            line = part.clean[part.clean.rfind('\n', 0, first) + 1:first]
            if line.strip() or not re.compile(rf'{re.escape(drop)}\s*=(?!=)').match(part.clean, first):
                continue
            if any(start <= first < stop and any(start <= at < stop for at in refs[keep]) for start, stop in spans):
                continue
            edits = [(at, at + len(drop), keep) for at in refs[drop]]
            hit = declared[drop][1]
            listed = [local for local in re.findall(_ID, hit['names']) if local != drop]
            replacement = f"{hit['indent']}{hit['type']} {', '.join(listed)};" if listed else ''
            edits.append((hit.start(), hit.end() + (1 if not listed else 0), replacement))
            out.append((first - max(refs[keep]), (FAMILY, edit(source, edits))))
    return list(dict.fromkeys(child for _, child in sorted(out, key=lambda item: item[0])))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 97}  # the registry: no caller wiring (registry.py)
