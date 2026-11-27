"""endian_word_load: m2c's C for a loader that byte swaps words from a table, written as the steps a macro leaves.

Matched on a Nintendo 64 function built by SN-N64 2.81 (`-G0 -mips3 -O2 -mgas -mcpu=VR4300`), a loader that reads a
little-endian directory from the cartridge, swaps an entry's size and offset words, rounds the size up to 16 and copies
the data by DMA. From m2c's draft (4298 refined, 4613 raw) the first four rewrites together reach 2453, and with the
buffer, order and early-return edits 0. Each is a pure rewrite of the source text; the exact judge decides every child,
and why the compiler wants these forms is a hypothesis from that one match.

byte_swap_spelled_out
    m2c writes `t = x >> 0x10;` and drops the mask of the last byte, `(((t & 0xFF) << 8) + (t >> 8))`; GCC then folds the
    two shifts into one `>> 24`. The swap macro's spelling, with the shift written at both uses and the mask kept
    (`(((x >> 0x10) & 0xFF00) >> 8)`), keeps `x >> 0x10` in a register of its own.

byte_swap_word_in_place
    `y = ((u32) (SWAP(x) + 0xF) >> 4) * 0x10;` becomes `x = SWAP(x); x = ((u32) (x + 0xF) >> 4) << 4;` with `y`'s later
    reads naming `x`, and `p = SWAP(a) + BASE;` becomes `a = SWAP(a); p = a + BASE;` (`BASE += a;` when BASE is the
    cursor below). Only when the word is not read again.

round_up_global_in_place
    `y = ((u32) (G + 0xF) >> 4) * 0x10;` for a global's value or address `G`: `y = G; y = ((u32) (y + 0xF) >> 4) * 0x10;`.
    (m2c folds an address's `+ 0xF` into the relocation, and on an unknown type's `&D` that scales it by 4.)

symbol_cursor_base
    A symbol's address passed to calls twice or more and then added to a swapped offset is a local set at the top of the
    function (`repair_base`), advanced by `repair_base += a;`.

endian_word_load
    The four above in one child: apart they move the score little or make it worse.

rounded_buffer_reuse
    Two locals that each take a rounded global in turn (`a = G; a = round(a);`, later `b = H; b = round(b);`) are one
    local when the first is not read after the second is set: the target reuses its register.

buffer_before_record_reads
    Those two statements, written after the reads of a record's words, go above them.

endian_word_load_early
    All of it in one child, with guard_tail_return_hoist's early return: the exact C of the match.
"""
import re

from .guard_tail_return_hoist import _hoist
from .integer_repair_support import IDENT, edit, view

SPELL = 'byte_swap_spelled_out'
INPLACE = 'byte_swap_word_in_place'
ROUND = 'round_up_global_in_place'
BASE = 'symbol_cursor_base'
BOTH = 'endian_word_load'
REUSE = 'rounded_buffer_reuse'
FIRST = 'buffer_before_record_reads'
WHOLE = 'endian_word_load_early'
FAMILIES = (SPELL, INPLACE, ROUND, BASE, BOTH, REUSE, FIRST, WHOLE)

CURSOR = 'repair_base'
_CAST = r'(?:\(u32\)\s*)?'
_LOW16 = rf'\(\(\((?P<x>{IDENT}) & 0xFF\) << 8\) \+ \({_CAST}\((?P=x) & 0xFF00\) >> 8\)\)'
_HIGH = rf'\({_LOW16} << (?:0x10|16)\) \+ '
# m2c's form (the high half in a temporary, its last mask dropped) and the spelled-out form this module writes
_SHORT = re.compile(_HIGH + rf'\(\(\((?P<t>{IDENT}) & 0xFF\) << 8\) \+ \((?P=t) >> 8\)\)')
_LONG = re.compile(_HIGH + r'\(\(\(\((?P=x) >> (?:0x10|16)\) & 0xFF\) << 8\) \+ '
                   r'\(\(\((?P=x) >> (?:0x10|16)\) & 0xFF00\) >> 8\)\)')
_GAP = r';[ \t]*\n(?P<blank>[ \t]*\n)(?=[ \t]*\S)'  # m2c's blank line between declarations and statements
_ROUNDED = r'\(\(u32\) \(%s \+ 0xF\) >> 4\) \* 0x10'


def _body(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:for|while|do|goto|switch|asm|__asm__|volatile)\b', part.body):
        return None  # the rewrites reason about textual order, which a loop or a jump breaks
    return part.opening + 1, part.end - 1


def _count(text, name):
    return len(re.findall(rf'(?<![\w.>]){re.escape(name)}\b', text))


def _declaration(body, name):
    """The one plain declaration line of local `name` in the body."""
    found = list(re.finditer(rf'(?m)^[ \t]*(?:[su](?:8|16|32)|int|char|short|void)[ \t]+\**[ \t]*{re.escape(name)};[ \t]*\n',
                             body))
    return found[0] if len(found) == 1 else None


def _drop_declaration(text, name):
    found = _declaration(text, name)
    if found and _count(text, name) == 1:
        return text[:found.start()] + text[found.end():]
    return text


def _rename(text, old, new):
    text = re.sub(rf'\((?:s32|u32)\)\s*{re.escape(old)}\b', new, text) if new == CURSOR else text
    return re.sub(rf'(?<![\w.>]){re.escape(old)}\b', new, text)


def _apply(source, name, rewrite):
    span = _body(source, name)
    if not span:
        return None
    low, high = span
    body = source[low:high]
    new = rewrite(body, source)
    return edit(source, [(low, high, new)]) if new is not None and new != body else None


def _unsigned(body, *names):
    """Each declared `u32`: only then is `t >> 8` the same as the masked byte of `x >> 16`."""
    return all((found := _declaration(body, name)) and found[0].split()[0] == 'u32' for name in names)


def _spell_one(body):
    for hit in _SHORT.finditer(body):
        x, t = hit['x'], hit['t']
        setter = re.search(rf'(?m)^[ \t]*{t} = (?:\(u32\) )?{x} >> (?:0x10|16);[ \t]*\n', body)
        if not setter or setter.end() > hit.start() or _count(body, t) != 4 or not _unsigned(body, t, x):
            continue  # its declaration, its assignment and two reads
        high = f'({x} >> 0x10)'
        old = f'((({t} & 0xFF) << 8) + ({t} >> 8))'
        text = hit[0].replace(old, f'((({high} & 0xFF) << 8) + (({high} & 0xFF00) >> 8))')
        body = body[:hit.start()] + text + body[hit.end():]
        body = body[:setter.start()] + body[setter.end():]
        return _drop_declaration(body, t)
    return None


def _repeat(step, body):
    for _ in range(16):  # each pass rewrites one site and searches again: offsets move with every edit
        new = step(body)
        if new is None:
            break
        body = new
    return body


def _spell(body, _source):
    return _repeat(_spell_one, body)


def _swaps(body):
    return sorted([*_SHORT.finditer(body), *_LONG.finditer(body)], key=lambda m: m.start())


def _line(body, at):
    start = body.rfind('\n', 0, at) + 1
    end = body.find('\n', at)
    end = len(body) if end < 0 else end
    return start, end, body[start:end]


def _in_place_one(body):
    for hit in _swaps(body):
        x = hit['x']
        start, end, line = _line(body, hit.start())
        indent = line[:len(line) - len(line.lstrip())]
        before, after = body[start:hit.start()], body[hit.end():end]
        later = body[end:]
        if _count(later, x) or not _declaration(body, x):
            continue
        rounded = re.fullmatch(rf'[ \t]*({IDENT}) = \(\(u32\) \(', before)
        summed = re.fullmatch(rf'[ \t]*({IDENT}) = (?:\({CURSOR} \+ )?', before)
        if rounded and re.fullmatch(r' \+ 0xF\) >> 4\) \* 0x10;', after):
            y = rounded[1]
            if y == x or _count(body[:start], y) != 1 or not _declaration(body, y):
                continue
            text = (f'{indent}{x} = {hit[0]};\n'
                    f'{indent}{x} = ((u32) ({x} + 0xF) >> 4) << 4;')
            new = body[:start] + text + _rename(later, y, x)
            return _drop_declaration(new, y)
        added = re.fullmatch(r' \+ (&?[A-Za-z_]\w*);', after)
        if summed and added:
            p, base = summed[1], added[1]
            if p in (x, base) or _count(body[:start], p) != 1 or not _declaration(body, p):
                continue
            if base == CURSOR:
                if _count(later, CURSOR):
                    continue
                new = body[:start] + f'{indent}{x} = {hit[0]};\n{indent}{CURSOR} += {x};' + _rename(later, p, CURSOR)
                return _drop_declaration(new, p)
            return body[:start] + f'{indent}{x} = {hit[0]};\n{indent}{p} = {x} + {base};' + later
    return None


def _in_place(body, _source):
    return _repeat(_in_place_one, body)


def _is_array(source, symbol):
    return bool(re.search(rf'\bextern\b[^;()]*\b{re.escape(symbol)}\s*\[', source))


def _round(body, source):
    pattern = re.compile(rf'(?m)^([ \t]*)({IDENT}) = {_ROUNDED % "(&?D_[0-9A-Fa-f]{8})"};')

    def split(hit):
        indent, y, value = hit.groups()
        symbol = value.lstrip('&')
        if not _declaration(body, y):
            return hit[0]
        if value.startswith('&') or _is_array(source, symbol):
            value = f'(s32) {value}'
        return f'{indent}{y} = {value};\n{indent}{y} = ((u32) ({y} + 0xF) >> 4) * 0x10;'

    return pattern.sub(split, body)


def _base(body, source):
    if CURSOR in source:
        return None
    for symbol in sorted(set(re.findall(r'\bD_[0-9A-Fa-f]{8}\b', body))):
        word = rf'(?:\(s32\) )?&?{symbol}\b'
        passed = list(re.finditer(rf'(?<=[(,] )\(s32\) &?{symbol}\b(?=[,)])|(?<=\()\(s32\) &?{symbol}\b(?=[,)])', body))
        added = [m for m in re.finditer(rf'\+ (&?{symbol});', body)]
        if len(passed) < 2 or len(added) != 1 or len(re.findall(word, body)) != len(passed) + 1:
            continue
        # a sum written with the word on the left of the address, assigned to a local: `p = SWAP + &D;`
        start, end, line = _line(body, added[0].start())
        sum_ = re.fullmatch(rf'([ \t]*)({IDENT}) = (.+) \+ &?{symbol};', line)
        if not sum_ or _count(body[end:], symbol) or passed[-1].start() > start or not _swaps(line):
            continue
        indent, p, offset = sum_.groups()
        if _count(body[:start], p) != 1 or not _declaration(body, p):
            continue
        first = re.search(_GAP, body)
        if not first or first.end() > passed[0].start():
            continue
        address = f'(s32) {added[0][1]}'
        swap = _swaps(offset)
        word_name = swap[0]['x'] if len(swap) == 1 and swap[0][0] == offset else None
        if word_name and _declaration(body, word_name) and not _count(body[end:], word_name):
            total = f'{indent}{word_name} = {offset};\n{indent}{CURSOR} += {word_name};'
        else:
            total = f'{indent}{CURSOR} += {offset};'
        later = _rename(body[end:], p, CURSOR)
        head = body[:start]
        for hit in passed[::-1]:
            head = head[:hit.start()] + CURSOR + head[hit.end():]
        new = head + total + later
        new = _drop_declaration(new, p)
        gap = re.search(_GAP, new)
        pad = re.match(r'[ \t]*', new[gap.end():])[0]
        return (new[:gap.start('blank')] + f'{pad}s32 {CURSOR};\n' + new[gap.start('blank'):gap.end()]
                + f'{pad}{CURSOR} = {address};\n' + new[gap.end():])
    return None


_PAIR = (r'(?m)^[ \t]*(?P<{0}>' + IDENT + r') = D_[0-9A-Fa-f]{{8}};\n'
         r'[ \t]*(?P={0}) = \(\(u32\) \((?P={0}) \+ 0xF\) >> 4\) \* 0x10;\n')


def _buffer(body, _source):
    """Two locals that each hold a rounded global in turn, the first never read after the second is set: one local."""
    pairs = list(re.finditer(_PAIR.format('y'), body))
    if len(pairs) != 2:
        return None
    first, second = pairs[0]['y'], pairs[1]['y']
    one, other = _declaration(body, first), _declaration(body, second)
    if first == second or not one or not other or one[0].split()[0] != other[0].split()[0]:
        return None
    at = pairs[1].start()
    if _count(body[at:], first) or _count(body[:at], second) != 1:
        return None
    return _drop_declaration(body[:at] + _rename(body[at:], second, first), second)


def _buffer_first(body, _source):
    """The words read from a record just before a buffer is set: the buffer's two statements go above the reads."""
    pattern = re.compile(r'(?m)(?P<reads>(?:^[ \t]*' + IDENT + r' = M2C_FIELD\(' + IDENT + r', u32 \*, \w+\);\n)+)'
                         r'(?P<pair>' + _PAIR.format('b')[4:] + ')')
    hit = pattern.search(body)
    if not hit or _count(hit['reads'], hit['b']):
        return None
    return body[:hit.start()] + hit['pair'] + hit['reads'] + body[hit.end():]


def variants(source, name, header=''):
    if len(source) > 128000 or '0xFF00' not in source:
        return []
    steps = ((SPELL, _spell), (BASE, _base), (INPLACE, _in_place), (ROUND, _round))
    out, seen = [], {source}

    def offer(family, text):
        if text is not None and text not in seen:
            seen.add(text)
            out.append((family, text))

    combined, used = source, 0
    for _family, step in steps:
        new = _apply(combined, name, step)
        if new is not None:
            combined, used = new, used + 1
    if used > 1:
        whole = combined
        for step in (_buffer, _buffer_first):
            whole = _apply(whole, name, step) or whole
        hoisted = _hoist(whole, name)
        offer(WHOLE, hoisted or whole)
        offer(BOTH, combined)
    for family, step in (*steps, (REUSE, _buffer), (FIRST, _buffer_first)):
        offer(family, _apply(source, name, step))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
