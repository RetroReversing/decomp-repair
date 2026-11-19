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
