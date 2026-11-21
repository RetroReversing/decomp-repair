"""A string literal written as the symbol the target loads in its place.

m2c reads a format string from the game's data as a literal ("%s"), which the compiler places in its own
read-only section; the game's instructions load a symbol of the data section instead (`%lo(D_800D2AA0)`). Three N64
functions printing one string each went from 96.4% to 97.2% with the symbol. When the C has as many string literals
as the target has symbols the C never names, each literal becomes the symbol in its turn, declared `extern char
D[];`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_string_symbol'
FAMILIES = (FAMILY,)

STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    # (_blank blanks literals whole: find them in the source, at the same offsets, outside comments)
    literals = [m for m in STRING.finditer(source, opening, end) if not clean[m.start():m.end()].strip()]
    if not literals or len(literals) > 4:
        return []
    symbols = list(dict.fromkeys(m[1] for m in re.finditer(r'%(?:hi|lo)\(\s*([A-Za-z_]\w*)\s*\)', asm)))
    unknown = [s for s in symbols if not re.search(r'\b' + re.escape(s) + r'\b', source)]
    if len(unknown) != len(literals):
        return []
    text = source
    for m, symbol in sorted(zip(literals, unknown), key=lambda p: -p[0].start()):
        text = text[:m.start()] + symbol + text[m.end():]
    line = text.rfind('\n', 0, span[0]) + 1
    text = text[:line] + ''.join(f'extern char {s}[];\n' for s in unknown) + text[line:]
    return [(FAMILY, text)]


VERIFIED_FAMILY = 'verified_rom_string_symbol'
_HI = re.compile(r'lui\s+(\$\w+),\s*%hi\(([\w?]+)\)')
_LO = re.compile(r'addiu\s+(\$\w+),\s*(\$\w+),\s*%lo\(([\w?]+)\)')


def verified_variants(source, name, header, rows, read_data):
    """Bind standalone literal arguments to byte-identical ROM strings in aligned address loads."""
    from collections import Counter

    from .csource import _COMMENT_OR_STRING
    from .integer_repair_support import edit

    if not read_data or '"' not in source or not (span := find(source, name)):
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    literals = {}
    for hit in _COMMENT_OR_STRING.finditer(source, opening, span[1]):
        value = hit[0]
        if not re.fullmatch(r'"[ -!#-\[\]-~]{1,95}"', value):
            continue
        if (clean[opening:hit.start()].rstrip()[-1:] not in ('(', ',')
                or clean[hit.end():span[1]].lstrip()[:1] not in (')', ',')):
            continue
        literals.setdefault(value[1:-1].encode('ascii') + b'\0', []).append(hit.span())

    if not literals:
        return []
    references = Counter()
    for i, (mark, target, candidate) in enumerate(rows):
        if mark == ' ' or not (wanted := _HI.fullmatch(target)) or not (local := _HI.fullmatch(candidate)):
            continue
        symbol = wanted[2]
        if local[2] != '?local' or not re.fullmatch(r'[A-Za-z_]\w*', symbol) or symbol.startswith('jtbl_'):
            continue
        for _, next_target, next_candidate in rows[i+1:i+5]:
            if (not (low := _LO.fullmatch(next_target)) or not (low_local := _LO.fullmatch(next_candidate))
                    or low.groups() != (wanted[1], wanted[1], symbol)
                    or low_local.groups() != (local[1], local[1], '?local')):
                if next_target.startswith(('jal ', 'jr ', 'j ')) or next_candidate.startswith(('jal ', 'jr ', 'j ')):
                    break
                continue
            references[symbol] += 1
            break

    bindings = {}
    for symbol, count in references.items():
        if re.search(rf'\b{re.escape(symbol)}\b', clean+'\n'+header):
            continue
        for payload, spans in literals.items():
            if count == len(spans) and read_data(symbol, len(payload)) == payload:
                bindings.setdefault(payload, []).append(symbol)
    return [
        (VERIFIED_FAMILY, edit(source, [
            (span[0], span[0], f'extern const char {symbols[0]}[];\n'),
            *((start, stop, symbols[0]) for start, stop in literals[payload]),
        ]))
        for payload, symbols in bindings.items() if len(symbols) == 1
    ][:4]
