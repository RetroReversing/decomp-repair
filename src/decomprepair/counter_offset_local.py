"""A byte offset stepped beside a loop counter, written as a local of the loop body computed from the counter
(GCC 2.7.2, KMC, N64).

`s32 offset; for (i = 0, offset = 0; i < n; offset += 0x24, i++) { ... *(f32 *)((u8 *) &table + offset) ... }` keeps
the offset as a second basic induction variable, initialised before the loop's guard and stepped beside the counter.
`counter_derived_offset` writes the offset as an expression of the counter at every read (`i << 2`, `i * 36`); with a
symbol added to it the loop pass then reduces the whole address (`lui $s1,%hi(sym)` and a pointer stepped by 0x24)
where the game's code kept `lui $at,%hi(sym); addu $at,$at,$s1` with only the product in a register (910 against 120
on the function it came from). Read through a local of the body, `s32 offset = i * 0x24;`, the product is a giv of its
own (loop.c's `replaceable` giv), initialised after the pointer the loop also steps and in the register order the
target has: 340 -> 120 on a 529-instruction function, the other loop of it was the only difference left.

Offered when the offset is read only inside the loop's body, never assigned there, and both start at 0 in the `for`'s
head. A candidate rewrite; the exact judge decides.

m2c also writes the offset's zero as the statement just before the `for` (`off = 0; for (i = 0; i < n; i++, off += K)`)
and reuses the offset's name in other arms of a switch. Both are read the same way: the zero before the loop goes, and a
name that other code still uses becomes an assignment at the top of the body (`off = i * K;`), offered only when the next
mention of the name after the loop assigns it (no read sees the old stepped value). On a 1315-instruction sound-sequence
interpreter's voice scan (KMC GCC 2.7.2 `-O2`, N64) that put the zero after the guard and the symbol at each use, as the
target has: 4645 -> 4000.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'counter_offset_local'
FAMILIES = (FAMILY,)
_FOR = re.compile(r'\bfor\s*\(')
_ONE = re.compile(rf'(?:(?P<a>{IDENT})\s*\+\+|\+\+\s*(?P<b>{IDENT})|(?P<c>{IDENT})\s*\+=\s*1)')


def _python_split(text):
    parts, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char in '([{') - (char in ')]}')
        if char == ',' and depth == 0:
            parts.append(text[start:at].strip())
            start = at + 1
    parts.append(text[start:].strip())
    return parts


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text):
        return [piece.strip() for piece in _scan.top_pieces(text, ',', 3)]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _FOR.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if not shut:
            continue
        head = clean[hit.end():shut - 1]
        pieces = head.split(';')
        if len(pieces) != 3:
            continue
        inits, cond, steps = (_split(p) for p in pieces)
        before = None  # an `offset = 0;` written as the statement just before the `for`
        if len(inits) == 1 and len(steps) == 2:
            line = clean.rfind('\n', part.opening, hit.start())
            prev = clean.rfind('\n', part.opening, line)
            if line < 0 or prev < 0 or clean[line:hit.start()].strip():
                continue
            found_zero = re.fullmatch(rf'[ \t]*(?P<v>{IDENT})\s*=\s*0\s*;[ \t]*', clean[prev + 1:line])
            if not found_zero:
                continue
            before = (prev + 1, line + 1, found_zero['v'])
            inits = inits + [f'{found_zero["v"]} = 0']
        if len(inits) != 2 or len(steps) != 2:
            continue
        zero = [re.fullmatch(rf'(?P<v>{IDENT})\s*=\s*0', i) for i in inits]
        if not all(zero):
            continue
        names = [z['v'] for z in zero]
        plus = [re.fullmatch(rf'(?P<v>{IDENT})\s*\+=\s*(?P<k>{NUMBER})', s) for s in steps]
        one = [_ONE.fullmatch(s) for s in steps]
        pairs = [(plus[0], one[1]), (plus[1], one[0])]
        found = [(p, o) for p, o in pairs if p and o and not (p['k'].rstrip('uUlL') == '1' and o)]
        if len(found) != 1:
            continue
        step, counter_step = found[0]
        offset = step['v']
        counter = counter_step['a'] or counter_step['b'] or counter_step['c']
        if offset not in names or counter not in names or offset == counter or not 0 < int(step['k'].rstrip('uUlL'), 0) <= 0x10000:
            continue
        body_open = re.match(r'\s*\{', clean[shut:])
        if not body_open:
            continue
        open_at = shut + body_open.end() - 1
        end = close(clean, open_at, '{', '}')
        if not end:
            continue
        body = clean[open_at + 1:end - 1]
        mention = re.compile(rf'(?<![\w.>]){re.escape(offset)}\b')
        write = re.compile(rf'(?<![\w.>]){re.escape(offset)}\s*(?:=(?!=)|[-+*/|&^%]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{re.escape(offset)}\b|&\s*{re.escape(offset)}\b')
        counter_write = re.compile(rf'(?<![\w.>]){re.escape(counter)}\s*(?:=(?!=)|[-+*/|&^%]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{re.escape(counter)}\b')
        if not mention.search(body) or write.search(body) or counter_write.search(body) or re.search(r'\b(?:goto|case|default)\b', body):
            continue
        if before and before[2] != offset:
            continue  # the zero before the loop is the counter's, not the offset's
        declaration = re.search(rf'(?m)^(?P<lead>[ \t]*)(?P<type>s32|int|u32|unsigned int|long)[ \t]+{re.escape(offset)}[ \t]*;[ \t]*\n', clean[part.opening + 1:hit.start()])
        if not declaration:
            continue
        gone = part.opening + 1 + declaration.start(), part.opening + 1 + declaration.end()
        start_cut = before[0] if before else hit.start()
        rest = clean[part.opening + 1:gone[0]] + clean[gone[1]:start_cut] + clean[end:part.end]
        k = step['k']
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, open_at) + 1:])[0]
        init = counter + ' = 0' if before else f'{counter} = 0'
        header = f'for ({init}; {source[hit.end() + len(pieces[0]) + 1:shut - 1 - len(pieces[2]) - 1].strip()}; {counter}++)'
        edits = [(hit.start(), shut, header)]
        if before:
            edits.append((before[0], before[1], ''))
        if mention.search(rest):
            after = mention.search(clean, end, part.end)
            if after and not re.match(rf'{re.escape(offset)}\s*=(?!=)', clean[after.start():]):
                continue  # code after the loop may read the stepped value
            edits.append((open_at + 1, open_at + 1, f'\n{indent}  {offset} = {counter} * {k};'))
        else:
            edits += [(gone[0], gone[1], ''), (open_at + 1, open_at + 1, f'\n{indent}  {declaration["type"]} {offset} = {counter} * {k};')]
        text = edit(source, edits)
        out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
