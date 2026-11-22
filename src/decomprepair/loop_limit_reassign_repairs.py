"""A `do { } while (cursor < limit-expression)` whose limit GCC 2.7's loop pass hoists but the target recomputes.

loop.c moves a loop-invariant computation in front of the loop only when its result pseudo is set exactly once
(`n_times_set == 1`). A bound written inline in the loop test (`arg1 + n * 8`, or m2c's `(u32) cursor - (u32) base <
n * 8`) is a single set, so the compiler hoists it into a callee-saved register and the loop gets one register
more than the target, which keeps `sll; addu; sltu` at the loop's tail. A local that is assigned before the loop and
again in the test through a comma expression has two sets and stays in the loop, which is how the target's tail
reads. (A 180-instruction N64 function, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 2913 -> 901 for the
pointer-bound form plus the second set; the bound alone only moved to the other register.)

Two shapes are offered for a `do { } while` whose test compares against an invariant arithmetic limit, none of whose
names the loop assigns or takes the address of and which reads no memory and makes no call:

* `cursor < limit` (any relation, `u32`/`s32` casts of a plain name on the left): the limit goes into a local set
  to zero before the loop and in the test: `while (L = limit, cursor < L)`.
* m2c's offset form `(u32) cursor - (u32) base < limit`: rewritten to the pointer-bound form with the base added to
  the limit: `while (L = limit + (u32) base, (u32) cursor < L)`.

The local is a `u32` named `__repair_loop_limit`. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, edit, view
from .loop_address_hoist_repairs import _match

FAMILIES = ('loop_limit_reassign',)
LIMIT = 8
NAME = '__repair_loop_limit'
CASTS = {'u8', 's8', 'u16', 's16', 'u32', 's32', 'int', 'unsigned', 'char', 'short', 'long', 'signed'}
CAST = r'\(\s*(?:u32|s32|unsigned(?:\s+int)?|int)\s*\)'
OFFSET = re.compile(rf'^\(*\s*{CAST}\s*\(?\s*(?P<cursor>{IDENT})\s*\)?\s*\)*\s*-\s*\(*\s*{CAST}\s*\(?\s*(?P<base>{IDENT})\s*\)?\s*\)*$')
PLAIN = re.compile(rf'^\(*\s*(?:{CAST}\s*)?\(?\s*(?P<cursor>{IDENT})\s*\)?\s*\)*$')


def _relation(cond):
    """(left, operator, right) of the one top-level relational operator, or None."""
    depth, found, at = 0, [], 0
    while at < len(cond):
        char = cond[at]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0:
            pair = cond[at:at+2]
            if pair in ('<<', '>>', '->', '<=', '>=', '==', '!=', '&&', '||'):
                if pair in ('<=', '>='):
                    found.append((at, pair))
                at += 2
                continue
            if char in '<>':
                found.append((at, char))
            elif char in '?:,=':
                return None
        at += 1
    if len(found) != 1:
        return None
    at, op = found[0]
    return cond[:at].strip(), op, cond[at+len(op):].strip()


def _invariant(expr, loop):
    """A pure arithmetic expression over names the loop never writes."""
    if re.search(r'\[|->|\.|\+\+|--|\?|:|,|\bsizeof\b|(?:^|[(+\-*/<>=&|^])\s*[*&!~]', expr):
        return False
    for call in re.finditer(rf'({IDENT})\s*\(', expr):
        if call[1] not in CASTS:
            return False
    names = set(re.findall(IDENT, expr)) - CASTS
    if not names or not re.search(r'[-+*/]|<<|>>', expr):
        return False
    for ident in names:
        written = rf'(?<![\w.>]){re.escape(ident)}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)|\+\+\s*{re.escape(ident)}\b|\b{re.escape(ident)}\s*(?:\+\+|--)|--\s*{re.escape(ident)}\b|&\s*{re.escape(ident)}\b'
        if re.search(written, loop):
            return False
    return True


def _loops(clean, start, end):
    found = []
    for m in re.finditer(r'\bdo\s*\{', clean[start:end]):
        brace = start+m.end()-1
        close = _match(clean, brace, '{', '}')
        if close < 0:
            continue
        tail = re.compile(r'\s*while\s*\(').match(clean, close+1)
        if not tail:
            continue
        paren = tail.end()-1
        right = _match(clean, paren, '(', ')')
        if right < 0 or not re.compile(r'\s*;').match(clean, right+1):
            continue
        found.append((start+m.start(), brace, close, paren+1, right))
    return found


def _rewrite(clean, loop, index):
    do, brace, close, left, right = loop
    cond = clean[left:right]
    relation = _relation(cond)
    if not relation:
        return None
    side, op, limit = relation
    body = clean[do:close+1]
    if not _invariant(limit, body):
        return None
    name = NAME if index is None else f'{NAME}_{index}'
    offset = OFFSET.match(side)
    if offset:
        if op not in ('<', '<=') or offset['cursor'] == offset['base']:
            return None
        if re.search(rf'(?<![\w.>]){re.escape(offset["base"])}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)|&\s*{re.escape(offset["base"])}\b', body):
            return None
        new = f'{name} = {limit} + (u32) {offset["base"]}, (u32) {offset["cursor"]} {op} {name}'
    elif PLAIN.match(side):
        new = f'{name} = {limit}, {side} {op} {name}'
    else:
        return None
    return name, (left, right, new)


def variants(source, name, header=''):
    part = view(source, name)
    if not part or NAME in part.clean:
        return []
    found = []
    for loop in _loops(part.clean, part.opening, part.end):
        rewritten = _rewrite(part.clean, loop, None)
        if rewritten:
            found.append((loop, rewritten[1]))
    if not found:
        return []
    start = part.opening+1

    def build(chosen):
        edits = [(start, start, '\n  ' + ''.join(f'u32 {NAME}{"" if len(chosen) == 1 else "_" + str(i)}; ' for i in range(len(chosen))).rstrip())]
        for i, (loop, (left, right, new)) in enumerate(chosen):
            if len(chosen) > 1:
                new = new.replace(NAME, f'{NAME}_{i}')
            label = NAME if len(chosen) == 1 else f'{NAME}_{i}'
            line = source.rfind('\n', 0, loop[0])+1
            indent = re.match(r'[ \t]*', source[line:loop[0]])[0] if not source[line:loop[0]].strip() else '  '
            edits.append((loop[0], loop[0], f'{label} = 0;\n{indent}'))
            edits.append((left, right, new))
        return edit(source, edits)

    out = [build([one]) for one in found]
    if len(found) > 1:
        out.append(build(found))
    return [(FAMILIES[0], c) for c in out[:LIMIT] if c != source]
