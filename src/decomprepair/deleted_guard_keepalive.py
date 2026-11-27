"""A loaded element stored from the two identical arms of a guard that names the loop's pointers.

    *dst = **src;        t_gk = **src;
                         if (flags && src && *src) { *dst = t_gk; } else { *dst = t_gk; }

Found on an SN64 GCC 2.8.1 (`sn-n64-281 -G0 -mips3 -O2`) controller-polling leaf of a 4-iteration cursor loop (40 -> 0).
The target loads the source pointer into `$v0` and the halfword into `$v1` (`lw $v0,0($a1); lhu $v1,0($v0)`), so the
pointer is still live when the value is born; every direct spelling (casts, struct members, helpers, temporaries,
volatile, `do { } while (0)` scopes) loaded the value over the pointer (`lhu $v0,0($v0)`) and moved the loop's cursors
one register down. With the store written in both arms of a guard that reads the pointer, the branch is still there
during register allocation, so the pointer lives past the load; the arms are merged afterwards and the branch and its
compare disappear, leaving the straight-line code. The other cursors the guard names gain references, which raises their
allocation priority past the destination cursor's. Which pass does the merging in SN's compiler is a hypothesis (it has
no public source); the measured part is the object code.

The guard costs nothing only because the arms are identical. It is scaffolding no developer wrote, and polishing removes
it once the match is recorded. The match also needed the cursor step the two arms of the surrounding `if` both ended
with to be written once after it, which alone scores worse (40 -> 70), so each guard is offered both on the source as
it is and on `common_arm_tail_hoist`'s child.

Offered for `*d = *e;` and `*d = **e;` inside a loop, `d` a pointer local. The guard is, in order: every other pointer
the loop steps and the loaded pointer together; each single stepped pointer with it; the loaded pointer alone. A
candidate rewrite; the exact judge decides.
"""
import re

from . import common_arm_tail_hoist
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'deleted_guard_keepalive'
HOISTED = 'deleted_guard_keepalive_hoisted'
FAMILIES = (FAMILY, HOISTED)
LOCAL = 't_gk'
LIMIT = 24
_STORE = re.compile(rf'\*\s*(?P<d>{IDENT})\s*=\s*(?P<rhs>\*\s*(?P<e>\*?\s*{IDENT}))\s*;')
_POINTER = re.compile(rf'(?m)^[ \t]*(?P<type>(?:(?:unsigned|signed|struct|union)\s+)*{IDENT})[ \t]*(?P<stars>\*+)[ \t]*'
                      rf'(?P<name>{IDENT})\s*(?:;|=)')
_FLOAT = re.compile(r'\b(?:float|double|f32|f64|volatile|void)\b')


def _loops(clean, part):
    """(start, end) of each loop, from its keyword to past its body, so a `for` header's steps are inside."""
    spans = []
    for hit in re.finditer(r'\bdo\s*\{|\b(?:for|while)\s*\(', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        at = part.opening + hit.end() - 1
        if clean[at] == '(':
            stop = close(clean, at, '(', ')')
            body = re.compile(r'\s*\{').match(clean, stop) if stop else None
            if not body:
                continue
            at = body.end() - 1
        end = close(clean, at, '{', '}')
        if end:
            spans.append((start, end))
    return spans


def _stepped(text, name):
    n = re.escape(name)
    return re.search(rf'(?<![\w.>]){n}\s*(?:\+\+|--|[-+]=)|(?:\+\+|--)\s*{n}\b', text) is not None


def _guarded(source, name):
    """The children of one source: (guard rank, text)."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(rf'\b{LOCAL}\b', clean):
        return []
    pointers = {m['name']: (' '.join(m['type'].split()), len(m['stars']))
                for m in _POINTER.finditer(clean, part.opening + 1, part.end)}
    loops = _loops(clean, part)
    out = []
    for hit in _STORE.finditer(clean, part.opening + 1, part.end):
        dest = hit['d']
        if dest not in pointers or pointers[dest][1] != 1 or _FLOAT.search(pointers[dest][0]):
            continue
        if clean[:hit.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        around = [span for span in loops if span[0] < hit.start() < span[1]]
        if not around:
            continue
        loop = clean[slice(*min(around, key=lambda span: span[1] - span[0]))]
        loaded = re.sub(r'\s+', '', hit['e'])
        if loaded.lstrip('*') == dest:
            continue
        cursors = [n for n in pointers if n != dest and _stepped(loop, n)]
        guards = [cursors + [loaded]] if cursors else []
        guards += [[n, loaded] for n in cursors if len(cursors) > 1]
        guards.append([loaded])
        indent = source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]
        indent = indent if not indent.strip() else ''
        value = source[hit.start('rhs'):hit.end('rhs')]
        arm = f'*{dest} = {LOCAL};'
        declaration = (part.opening + 1, part.opening + 1, f'\n    {pointers[dest][0]} {LOCAL};')
        for rank, guard in enumerate(guards):
            terms = ' && '.join(dict.fromkeys(guard))
            text = f'{LOCAL} = {value};\n{indent}if ({terms}) {{ {arm} }} else {{ {arm} }}'
            out.append((rank, edit(source, [declaration, (hit.start(), hit.end(), text)])))
    return out


def variants(source, name):
    found = []
    for family, text in common_arm_tail_hoist.variants(source, name):
        if family == common_arm_tail_hoist.FAMILY:
            found += [(rank, 0, HOISTED, child) for rank, child in _guarded(text, name)]
    found += [(rank, 1, FAMILY, child) for rank, child in _guarded(source, name)]
    result, seen = [], set()
    for _, _, family, child in sorted(found, key=lambda item: item[:2]):
        if child not in seen:
            seen.add(child)
            result.append((family, child))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
