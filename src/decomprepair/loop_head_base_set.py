"""A local that only ever holds one global array's address, set as the first statement of the loop that reads it
(`p = D_x;` at the top of the body) instead of before the loop, at its end or inside its condition.

On a 74-instruction N64 list walk (KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O1`) the target built the array's address
for the loop's entry test and then copied it into the register the body reads (`lui; addiu; move $v1,$v0`). Written
`while ((p = D_x)[i] != END)`, or `p = D_x;` before the loop and again at its end, the address went straight into the
body's register. With the set at the top of the body and the condition reading the array itself, the loop pass moves
the set in front of the loop as a copy of the entry test's address: 115 -> 0.

loop_head_base_set
    A pointer local, not address-taken, whose every assignment is the same global address (`p = G`, `p = (T *) G`,
    `p = &G[0]`; as a statement, as `p = G,` or as `(p = G)` inside an expression) and whose every other use lies in
    one braced loop (its condition or body). The assignments go, the condition reads the address itself, and
    `p = G;` becomes the first statement of the body.

The program is the same: the local holds that address wherever the body reads it, and nothing reads it elsewhere.
Hypothesis from that match (loop.c moving an invariant set); the exact judge decides.
"""
import re

from .c_scan import _close as brace_close
from .integer_repair_support import IDENT, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'loop_head_base_set'
FAMILIES = (FAMILY,)
LIMIT = 6
_LOOP = re.compile(r'\b(?P<word>while|for|do)\b\s*')
_POINTER = re.compile(rf'(?m)^[ \t]*(?:(?:const|unsigned|signed|struct)\s+)*{IDENT}\s*\*+\s*(?P<name>{IDENT})\s*;')
_VALUE = rf'(?:\(\s*(?:(?:const|unsigned|signed|struct)\s+)*{IDENT}\s*\*+\s*\)\s*)?(?:&\s*)?{IDENT}(?:\s*\[\s*0\s*\])?'


def _loops(part):
    """(start, body `{`, end) of each braced loop; a `do` loop ends after its `while (..);`."""
    clean, out = part.clean, []
    for hit in _LOOP.finditer(clean, part.opening + 1, part.end):
        at = hit.end()
        if hit['word'] != 'do':
            if clean[at:at + 1] != '(':
                continue
            at = close(clean, at)
            if not at:
                continue
        brace = re.compile(r'\s*\{').match(clean, at)
        if not brace:
            continue
        shut = brace_close(clean, brace.end() - 1)
        if shut < 0:
            continue
        end = shut + 1
        if hit['word'] == 'do':
            tail = re.compile(r'\s*while\s*(?=\()').match(clean, end)
            after = tail and close(clean, tail.end())
            if not after:
                continue
            end = after
        out.append((hit.start(), brace.end() - 1, end))
    return out


def _global_address(part, value, locals_):
    """Whether `value` names an address that cannot change: `&G`, or an array declared outside the function."""
    name = re.findall(IDENT, re.sub(r'^\(.*?\)\s*', '', value))[-1]
    if name in locals_:
        return False
    if '&' in value:
        return True
    head = part.clean[:part.opening] + part.clean[part.end:]
    return bool(re.search(rf'\b{re.escape(name)}\s*\[[^\]\n]*\]\s*(?:\[[^\]\n]*\]\s*)*;', head)) or bool(
        re.match(r'D_[0-9A-Fa-f]{8}', name))


def _assignments(part, name):
    """(span to remove or replace, replacement, value span, value) of each `name = value`, or None if one is odd."""
    clean, found = part.clean, []
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b'
                           rf'|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', clean[:part.end]):
        if hit.start() <= part.opening:
            continue
        value = re.compile(rf'{re.escape(name)}\s*=\s*(?P<value>{_VALUE})\s*(?P<next>[;,)])').match(clean, hit.start())
        if not value:
            return None
        before = clean[:hit.start()].rstrip()
        text = value['value']
        if value['next'] == ';' and before[-1:] in ('{', '}', ';'):
            start = clean.rfind('\n', 0, hit.start()) + 1
            stop = value.end()
            if not clean[start:hit.start()].strip() and clean[stop:stop + 1] == '\n':
                stop += 1
            else:
                start = hit.start()
            found.append(((start, stop), '', value.span('value'), text))
        elif value['next'] == ',':
            stop = value.end() + len(re.match(r'\s*', clean[value.end():])[0])
            found.append(((hit.start(), stop), '', value.span('value'), text))
        elif value['next'] == ')' and before.endswith('('):
            open_at = len(before) - 1
            found.append(((open_at, value.end()), None, value.span('value'), text))
        else:
            return None
    return found


def _child(source, part, name, loop, assigned):
    start, brace, end = loop
    clean = part.clean
    value = source[slice(*assigned[0][2])]
    bare = re.fullmatch(IDENT, value) is not None
    reads = value if bare else f'({value})'
    edits = []
    for span, replacement, _, _ in assigned:
        edits.append((span[0], span[1], reads if replacement is None else replacement))
    shut = brace_close(clean, brace)
    taken = [span for span, _, _, _ in assigned]
    for use in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[:part.end]):
        at = use.start()
        outside_body = start <= at < brace or shut < at < end
        if outside_body and not any(a <= at < b for a, b in taken):
            edits.append((at, use.end(), reads))
    first = re.compile(r'\s*?\n(?P<indent>[ \t]*)').match(clean, brace + 1)
    indent = first['indent'] if first else '    '
    edits.append((brace + 1, brace + 1, f'\n{indent}{name} = {value};'))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pointers = [hit['name'] for hit in _POINTER.finditer(clean, part.opening + 1, part.end)]
    locals_ = set(pointers)
    loops = _loops(part)
    out = []
    for local in pointers:
        if _address_taken(part.body, local):
            continue
        assigned = _assignments(part, local)
        if not assigned or len({re.sub(r'\s+', '', item[3]) for item in assigned}) != 1:
            continue
        if not _global_address(part, assigned[0][3], locals_):
            continue
        declared = next(hit for hit in _POINTER.finditer(clean, part.opening + 1, part.end) if hit['name'] == local)
        taken = [span for span, _, _, _ in assigned] + [declared.span()]
        uses = [use.start() for use in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean)
                if part.opening < use.start() < part.end and not any(a <= use.start() < b for a, b in taken)]
        if not uses:
            continue
        # The innermost loop that holds every use, with at least one of them in its body.
        holding = [loop for loop in loops if all(loop[0] <= at < loop[2] for at in uses)
                   and any(loop[1] < at < brace_close(clean, loop[1]) for at in uses)]
        if not holding:
            continue
        loop = max(holding)
        child = _child(source, part, local, loop, assigned)
        if child != source:
            out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
