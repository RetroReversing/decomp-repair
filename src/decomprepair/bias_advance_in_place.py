"""A word local read as `v + K` from some point on, advanced in place there.

m2c names the sum once per use (`temp_a1 = ...; x = temp_a1 + 0x3C;`) and a typed rewrite writes it out at each use,
`v + 60` in every macro argument. When the game stepped the value itself, the compiler adds into the register `v` lives
in (`addiu $a1, $a1, 0x3c`) and the later reads use that register; written as `v + K` it adds into a scratch register
and adds the constant again for a sum the compiler does not recognise (`rest + v + 60`). The child writes `v += K;`
after the last read of `v` that wants the old value and reads `v` where `v + K` stood.

`bias_advance_past_use` is the combined child for a source that computes from the old value one statement too early:
`rest = 50 - v;` moves below the next statement (a rectangle's command written with `v + 60`), and the advance follows
it. The compiler's constants take their order from the statements' order, so neither edit alone need score.

Measured on an N64 HUD bar drawer (SN GCC, `sn-n64-281 -G0 -mips3 -O2`, 166 instructions): the advance 110 -> 0, the
combined child 335 -> 0. Only a 32-bit integer local assigned once is touched, so the new value is the old sum's, and
every read of it after the step is one that read the sum. Proposals only; the byte judge decides."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'bias_advance_in_place'
PAST_USE = 'bias_advance_past_use'
FAMILIES = (FAMILY, PAST_USE)
LIMIT = 8

_WORD = re.compile(r'\b(?:u32|s32|int|unsigned(?:\s+int)?|long|unsigned\s+long)\s+(?P<name>[A-Za-z_]\w*)\s*;')
# what may stand before `v + K` so that it is a term of its own, and after it
_BEFORE = re.compile(r'(?:[(,={]|(?<!\+)\+|\breturn)\s*$')
_AFTER = re.compile(r'\s*[),;+\-]')
_KEYWORD = re.compile(r'\s*(?:if|else|for|while|do|switch|case|default|return|goto|break|continue)\b')


def _block(clean, opening, end, at):
    """(start, end) of the inside of the innermost braces around `at`, within the function's body."""
    stack = []
    for brace in re.finditer(r'[{}]', clean[opening:end]):
        pos = opening + brace.start()
        if brace.group() == '{':
            stack.append(pos)
            continue
        if not stack:
            return None
        start = stack.pop()
        if start < at < pos:
            return start + 1, pos
    return None


def _statement(clean, low, at):
    """(start, end) of the plain statement holding `at`: no brace, label or keyword of its own."""
    before = max(clean.rfind(mark, low, at) for mark in ';{}')
    start = max(before + 1, low)
    stop = clean.find(';', at)
    if stop < 0:
        return None
    text = clean[start:stop]
    start += len(text) - len(text.lstrip())
    text = clean[start:stop]
    if '{' in text or '}' in text or _KEYWORD.match(text) or text.count('(') != text.count(')'):
        return None
    return start, stop + 1


def _own_line(source, start, stop):
    """(line start, line end, indent) when the statement is alone on its line."""
    line = source.rfind('\n', 0, start) + 1
    newline = source.find('\n', stop)
    if newline < 0 or source[line:start].strip() or source[stop:newline].strip():
        return None
    return line, newline + 1, source[line:start]


def _top_level(clean, block_start, at):
    """Whether `at` stands in the block itself, not in braces nested inside it."""
    text = clean[block_start:at]
    return text.count('{') == text.count('}')


def _advance(source, line_end, indent, name, constant, sums, moved=None):
    edits = [(match.start(), match.end(), name) for match in sums]
    step = f'{indent}{name} += {constant};\n'
    if moved:
        cut_start, cut_end, text = moved
        edits += [(cut_start, cut_end, ''), (line_end, line_end, text + step)]
    else:
        edits.append((line_end, line_end, step))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    if re.search(r'\b(?:goto|asm|__asm__|volatile)\b', part.body):
        return []
    out = []
    declared = {match['name']: match for match in _WORD.finditer(clean, opening, end)}
    for local, declaration in declared.items():
        word = re.escape(local)
        if re.search(rf'(?<!&)&\s*{word}\b', part.body):
            continue
        uses = [match for match in re.finditer(rf'(?<![\w.])(?<!->){word}\b', clean[:end])
                if match.start() > opening and not declaration.start() <= match.start() < declaration.end()]
        writes = [use for use in uses if re.match(r'\s*(?:[+\-*/%&|^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', clean[use.end():])
                  or re.search(r'(?:\+\+|--)\s*$', clean[:use.start()])]
        if len(writes) != 1 or not uses or uses[0] != writes[0]:
            continue
        block = _block(clean, opening, end, writes[0].start())
        if not block or uses[-1].end() > block[1] or not _top_level(clean, block[0], writes[0].start()):
            continue
        assigned = _statement(clean, block[0], writes[0].start())
        if not assigned or not re.match(rf'{word}\s*=(?!=)', clean[assigned[0]:]):
            continue
        reads = uses[1:]
        sums = {}
        for use in reads:
            match = re.compile(rf'{word}\s*\+\s*(?P<constant>{NUMBER})(?![\w.\[])').match(clean, use.start())
            if match and _BEFORE.search(clean, opening, use.start()) and _AFTER.match(clean, match.end()):
                sums[use.start()] = match
        for constant in dict.fromkeys(match['constant'] for match in sums.values()):
            # the reads that stay as they are: the run of this constant's sums after the last other read
            plain = [use for use in reads if use.start() not in sums or sums[use.start()]['constant'] != constant]
            last = plain[-1] if plain else writes[0]
            statement = _statement(clean, block[0], last.start())
            if not statement or not _top_level(clean, block[0], statement[0]):
                continue
            later = [sums[use.start()] for use in reads if use.start() >= statement[1]]
            line = _own_line(source, *statement)
            if not later or not line:
                continue
            if len(later) > 1:
                out.append((FAMILY, _advance(source, line[1], line[2], local, constant, later)))
            moved = _past_use(source, clean, block, statement, line, local, declared, part.body)
            if moved:
                stop, indent, text = moved
                after = [sums[use.start()] for use in reads if use.start() >= stop]
                if after:
                    out.append((PAST_USE, _advance(source, stop, indent, local, constant, after,
                                                   (line[0], line[1], text))))
    return list(dict.fromkeys(out))[:LIMIT]


def _past_use(source, clean, block, statement, line, local, declared, body):
    """(end of the next statement's line, indent, the moved line) for `d = f(v);` moved below the statement after it,
    which reads `v + K` and does not name `d` (a local no pointer reaches)."""
    match = re.match(rf'(?P<dest>{IDENT})\s*=(?!=)', clean[statement[0]:statement[1]])
    if not match or match['dest'] == local:
        return None
    dest = match['dest']
    value = clean[statement[0] + match.end():statement[1]]
    if dest not in declared and not re.search(rf'\b(?:u8|s8|u16|s16|u32|s32|int|short|char)\s+{dest}\b', body):
        return None
    # the moved value reads locals only: the statement it passes may store anywhere
    if re.search(r'->|\.\w|\[|\*\s*\(|\w\s*\(', value) or any(
            not re.search(rf'\b[A-Za-z_]\w*\s+{name}\s*[;=,]', body) for name in re.findall(rf'(?<!\w){IDENT}', value)):
        return None
    if re.search(rf'(?<!&)&\s*{dest}\b', body):
        return None
    following = re.compile(rf'\s*(?={IDENT})').match(clean, statement[1])
    if not following:
        return None
    nxt = _statement(clean, statement[1], following.end())
    if not nxt or nxt[1] > block[1]:
        return None
    text = clean[nxt[0]:nxt[1]]
    if re.search(rf'\b{dest}\b', text) or not re.search(rf'\b{local}\s*\+', text):
        return None
    next_line = _own_line(source, *nxt)
    if not next_line:
        return None
    return next_line[1], line[2], source[line[0]:line[1]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',), 'order': 80}
