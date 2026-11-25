"""A pointer local that takes a fresh load several times in one block, split into one local per load, all at once.

m2c names the register a pointer was in and reuses that name for every reload of a volatile (or otherwise re-read)
global: `p = G; p[7] = 0; p = G; p[0x2F] = 0; q = G; ...`. The compiler sees one pseudo with the long life and the
many references of all of them. Written the way the game's code reads, each load a pointer of its own, every pseudo
is short and the allocator rotates the registers the way the target does (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32
-O2`, a 136-instruction menu reset: 165 -> 60, every register row of its twelve loads).

`reused_temp_split` (scalars only, one web per child) cannot reach this: its locals are integers, and one web split
alone changes nothing here (the webs only pay off together), so a greedy chain stops. This family writes every web of
a pointer local as a local of its own in one child, for every such local at once, and each local alone as well.

The shape: a pointer local (never a parameter, address never taken) assigned by plain `L = EXPR;` statements (EXPR
not reading `L`) directly in one brace block, two or more of them, or one when the name is already read before it.
The block must not sit in a loop or switch, and the function has no label beside a goto before the block ends; no
label, goto, case or loop lies inside the block and the name is not mentioned after it. Each set's span, up to the next
set of that name or the end of the block, is renamed `L_b<k>` with a declaration beside the original's. The first
set keeps the name when nothing read it before. The exact judge decides every child.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'pointer_reload_web_split'
LOCAL_FAMILY = 'pointer_reload_web_split_local'
FAMILIES = (FAMILY, LOCAL_FAMILY)
LIMIT = 8

IDENT = r'[A-Za-z_]\w*'
POINTER_DECL = re.compile(rf'(?m)^([ \t]*)((?:struct\s+|union\s+|unsigned\s+|signed\s+)?{IDENT})([ \t]*\*+[ \t]*)({IDENT})[ \t]*;[ \t]*\n')
UNORDERED = re.compile(r'\b(?:goto|switch|case|default|for|while|do|asm|__asm__|setjmp|longjmp)\b|(?m:^[ \t]*\w+\s*:(?!:))')


def _params(clean, part):
    signature = clean[:part.opening]
    start = signature.rfind('(')
    return set(re.findall(rf'({IDENT})\s*(?:,|\))', signature[start + 1:] + ')'))


def _blocks(clean, part):
    """Every `{ }` block inside the body as (open, close, depth-first enclosing chain of open positions)."""
    found, stack = [], []
    for index in range(part.opening, part.end):
        char = clean[index]
        if char == '{':
            stack.append(index)
        elif char == '}' and stack:
            opening = stack.pop()
            found.append((opening, index, tuple(stack)))
    return found


def _in_loop(clean, enclosing):
    """True when a statement around this block is a loop or switch, braced or not (a value could come round again)."""
    for opening in enclosing:
        position = opening
        while True:
            head = clean[:position].rstrip()
            if re.search(r'\bdo$', head):
                return True
            if re.search(r'\belse$', head):
                position = len(head) - 4
                continue
            if not head.endswith(')'):
                break
            depth = 0
            for index in range(len(head) - 1, -1, -1):
                depth += (head[index] == ')') - (head[index] == '(')
                if depth == 0:
                    break
            keyword = re.search(r'(\w+)\s*$', head[:index])
            if keyword and keyword[1] in ('while', 'for', 'switch'):
                return True
            if keyword and keyword[1] == 'if':
                position = keyword.start(1)
                continue
            break
    return False


def _python_depth_text(clean, start, end):
    """The text of start:end with nested blocks blanked, so only the block's own statements show."""
    out, depth = [], 0
    for index in range(start, end):
        char = clean[index]
        if char == '{':
            depth += 1
            out.append(' ')
        elif char == '}':
            depth -= 1
            out.append(' ')
        else:
            out.append(char if depth == 0 else ' ')
    return ''.join(out)


_depth_text = _python_depth_text
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _depth_text(clean, start, end):
        found = _scan.depth_text(clean, start, end)
        return _python_depth_text(clean, start, end) if found is NotImplemented else found


def _plans(source, part):
    clean = part.clean
    params = _params(clean, part)
    declarations = {}
    for hit in POINTER_DECL.finditer(clean, part.opening + 1, part.end):
        local = hit[4]
        if local in params or local in declarations:
            continue
        if re.search(rf'&\s*{re.escape(local)}\b', clean[part.opening:part.end]):
            continue
        declarations[local] = (hit[1], hit[2], hit[3], hit.end())
    if not declarations:
        return []
    blocks = _blocks(clean, part)
    plans = []
    for opening, closing, enclosing in blocks:
        if _in_loop(clean, enclosing + (opening,)):
            continue
        own = _depth_text(clean, opening + 1, closing)
        for local, (indent, kind, stars, declared_end) in declarations.items():
            pattern = re.compile(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)([^;{{}}]*);')
            sets = [m for m in pattern.finditer(own) if not re.search(rf'(?<![\w.>]){re.escape(local)}\b', m[1])]
            if not sets:
                continue
            sets = [(opening + 1 + m.start(), opening + 1 + m.end()) for m in sets]
            span_all = clean[sets[0][0]:closing]
            if UNORDERED.search(span_all):
                continue
            later = re.search(rf'(?<![\w.>]){re.escape(local)}\b', clean[closing:part.end])
            if later:
                continue
            before = re.search(rf'(?<![\w.>]){re.escape(local)}\b', clean[declared_end:sets[0][0]])
            # a nested block holding a set of this name has no single reaching value: leave it alone
            if any(pattern.search(clean[o + 1:c]) for o, c, enc in blocks if opening in enc or (o > opening and c < closing and enc and enc[-1] == opening)):
                continue
            if len(sets) < 2 and not before:
                continue
            first_renamed = bool(before)
            bounds = [s[0] for s in sets] + [closing]
            pieces = []
            for k, (start, _) in enumerate(sets):
                if k == 0 and not first_renamed:
                    continue
                pieces.append((start, bounds[k + 1]))
            plans.append((local, (indent, kind, stars, declared_end), pieces))
    # a label and a goto outside the block can still make the block a loop body: decline when the function has both
    if re.search(r'\bgoto\b', clean[part.opening:part.end]):
        labels = [m.start() for m in re.finditer(r'(?m)(?:^|[;{}])\s*([A-Za-z_]\w*)\s*:(?!:)', clean[part.opening:part.end])
                  if m[1] not in ('default',)]
        if labels:
            first_label = part.opening + min(labels)
            plans = [p for p in plans if all(piece[1] <= first_label for piece in p[2])]
    return plans


def _apply(source, part, plans):
    clean = part.clean
    edits = []
    taken = set()
    for local, (indent, kind, stars, declared_end), pieces in plans:
        names = []
        for number, (start, stop) in enumerate(pieces, 1):
            fresh = f'{local}_b{number}'
            while re.search(rf'\b{fresh}\b', clean) or fresh in taken:
                fresh += '_'
            taken.add(fresh)
            names.append(fresh)
            for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[start:stop]):
                edits.append((start + m.start(), start + m.end(), fresh))
        decl = ''.join(f'{indent}{kind}{stars}{fresh};\n' for fresh in names)
        edits.append((declared_end, declared_end, decl))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    plans = [plan for plan in _plans(source, part) if plan[2]]
    if not plans:
        return []
    out = []
    if len(plans) > 1:
        out.append((FAMILY, _apply(source, part, plans)))
    for plan in plans[:LIMIT]:
        out.append((LOCAL_FAMILY if len(plans) > 1 else FAMILY, _apply(source, part, [plan])))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 50}  # the registry: no caller wiring (registry.py)
