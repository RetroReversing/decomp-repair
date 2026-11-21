"""Recover byte addressing when a generated word pointer scales a relocation twice."""

import re
from collections import Counter

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, split_args, view
from .pattern_repairs import close

_SHIFT = re.compile(rf'sll (?P<reg>\$\w+), (?P=reg), (?P<shift>{NUMBER})')
_BYTE_SHIFT = (
    rf'lui (?P<reg>\$\w+), %hi\((?P<symbol>{IDENT})\)\n'
    rf'lbu (?P=reg), %lo\((?P=symbol)\)\((?P=reg)\)\n'
    rf'sll (?P=reg), (?P=reg), (?P<shift>{NUMBER})'
)


def _scale_sites(rows, changed):
    sites = Counter()
    for i in changed:
        shifts = [_SHIFT.fullmatch(text) for text in rows[i][1:]]
        if not all(shifts):
            return Counter()
        wanted, actual = shifts
        if wanted['reg'] != actual['reg'] or integer(actual['shift']) != integer(wanted['shift']) + 2:
            return Counter()
        # A literal value may be prepared between the shift and the address.
        # Require a consecutive relocated high, address add, and access.
        tail = '\n'.join(row[1] for row in rows[i + 1:i + 8])
        index = re.escape(wanted['reg'])
        address = re.search(
            rf'(?m)^lui (?P<base>\$\w+), %hi\((?P<symbol>{IDENT})\)\naddu (?P=base), (?P=base), {index}\n'
            rf'(?:j [^\n]+\n)?(?P<kind>lw|sw) \$\w+, %lo\((?P=symbol)\)\((?P=base)\)$', tail)
        if not address or address['base'] == wanted['reg']:
            return Counter()
        prefix = tail[:address.start()].splitlines()
        if (len(prefix) > 2 or any(not re.fullmatch(
                rf'(?:lui \$\w+, %hi\({IDENT}\)|addiu \$\w+, \$\w+, %lo\({IDENT}\))', line)
                or re.match(rf'\w+ {index},', line) for line in prefix)):
            return Counter()
        sites[address['symbol'], address['kind']] += 1
    return sites


def _word_array_offsets(part, header, rows, changed):
    if not 2 <= len(changed) <= 8 or not (sites := _scale_sites(rows, changed)):
        return None
    source = part.source
    context = _blank(header)
    hits = Counter()
    changes = []
    pointer = re.compile(rf'\*\(&(?P<symbol>{IDENT})\s*\+\s*')
    for hit in pointer.finditer(part.clean, part.opening + 1, part.end):
        symbol = hit['symbol']
        if (symbol, 'lw') not in sites and (symbol, 'sw') not in sites:
            continue
        end = close(part.clean, hit.start() + 1)
        if not end or end > part.end:
            return None
        index = part.clean[hit.end():end - 1]
        if (not index.strip() or not re.fullmatch(r'[\w\s&+*(),]+', index) or len(split_args(index)) != 1
                or re.search(rf'\b{symbol}\b', context)
                or not re.search(rf'(?m)^[ \t]*extern M2C_UNK {symbol};', part.clean[:part.opening])):
            return None
        assignment = re.match(rf'\s*=(?!=)\s*(?P<pointer>&{IDENT})?', part.clean[end:part.end])
        hits[symbol, 'sw' if assignment else 'lw'] += 1
        changes.append((*hit.span(), f'*(u32 *)((u8 *)&{symbol} + '))
        if assignment and assignment['pointer']:
            at = end + assignment.start('pointer')
            changes.append((at, at, '(u32)'))
    return edit(source, changes) if hits == sites else None


def _two_byte_sums(part, header, rows, changed):
    if len(changed) != 6 or changed != list(range(changed[0], changed[0] + 6)):
        return None
    first = changed[0]
    shifts = []
    for i in (first, first + 3):
        pair = [re.fullmatch(_BYTE_SHIFT, '\n'.join(row[side] for row in rows[i:i + 3]))
                for side in (1, 2)]
        if not all(pair) or pair[0]['reg'] != pair[1]['reg']:
            return None
        shifts.append(pair)
    (left, wrong_left), (right, wrong_right) = shifts
    if (left['symbol'] != wrong_right['symbol'] or right['symbol'] != wrong_left['symbol']
            or left['symbol'] == right['symbol'] or left['reg'] == right['reg']
            or integer(wrong_left['shift']) != integer(right['shift']) + 2
            or integer(wrong_right['shift']) != integer(left['shift']) + 2):
        return None
    a, b = map(re.escape, (left['reg'], right['reg']))
    setup = re.fullmatch(
        rf'lui (?P<reg>\$\w+), %hi\((?P<base>{IDENT})\)\n'
        rf'addiu (?P=reg), (?P=reg), %lo\((?P=base)\)\n'
        rf'addu {b}, {b}, (?P=reg)\naddu {a}, {a}, {b}\nsw {a}, (?P<offset>{NUMBER})\(\$\w+\)',
        '\n'.join(row[1] for row in rows[first + 6:first + 11]))
    if not setup:
        return None
    base, outer, inner = setup['base'], left['symbol'], right['symbol']
    if (base in (outer, inner) or re.search(rf'\b{base}\b', _blank(header))
            or not all(re.search(rf'(?m)^[ \t]*extern {ctype} {symbol};', part.clean[:part.opening])
                       for ctype, symbol in (('M2C_UNK', base), ('u8', outer), ('u8', inner)))):
        return None
    pattern = re.compile(
        rf'M2C_FIELD\({IDENT}, void \*\*, (?P<offset>{NUMBER})\) = \(void \*\) '
        rf'\((?P<expr>\((?P<left>{outer} << (?P<left_shift>{NUMBER}))\) \+ '
        rf'\(\((?P<right>{inner} << (?P<right_shift>{NUMBER}))\) \+ &{base}\))\);')
    matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return None
    match = matches[0]
    if (integer(match['left_shift']) != integer(left['shift']) or integer(match['right_shift']) != integer(right['shift'])
            or integer(match['offset']) != integer(setup['offset'])):
        return None
    return edit(part.source, [(*match.span('expr'), f"({match['right']}) + (({match['left']}) + (u8 *)&{base})")])


def variants(source, name, header, rows, changed):
    if not 2 <= len(changed) <= 8 or 'extern M2C_UNK ' not in source or not (part := view(source, name)):
        return []
    if candidate := _word_array_offsets(part, header, rows, changed):
        return [('relocated_word_array_offsets', candidate)]
    if candidate := _two_byte_sums(part, header, rows, changed):
        return [('relocated_two_byte_sum', candidate)]
    return []
