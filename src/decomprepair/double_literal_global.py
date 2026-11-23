"""A double global the function only reads, written as the double literal its eight bytes hold.

The double twin of `float_literal_global`. m2c names every constant a function loads by its address, and a double the game
keeps with its data (not in the literal pool) comes out as `extern f64 D_800D2EF0;` and `(f64) x + D_800D2EF0`. The eight
bytes there are the constant (0x3FE0000000000000, 0.5). The game's compiler loaded it the way GCC loads a literal from its
pool, `lui $at, %hi(...)` and `ldc1 ... %lo(...)($at)`, once for the function, with the load hoisted above the loops
that use it, while a global read keeps its own address register and its own live range: on a 315-instruction tile-rectangle
builder the global spelling left 5980 against 855 for the literal (0 with the rest of its steps).

The constant is game data the C cannot show, so the caller supplies it: `words` maps a symbol to the integer its bytes hold
in the game's byte order, as wide as the load (the caller reads eight bytes for an `ldc1`, four for an `lwc1`; this family
takes only a value above 32 bits or an `ldc1`-loaded one, `float_literal_global` the four-byte ones). A proposal replaces
every read of one such symbol in the function by the literal, one child per symbol and one with all of them, only when
everything says it is a constant read where it is used:
- the symbol is declared `f64`/`double` (an `extern` in the source or the header), never an array, pointer or float;
- the function only reads it: never assigned, incremented, called, indexed, a member read or its address taken, and no
  other function in the source names it;
- the target's assembly loads it with `ldc1` through `$at` (`%lo`) and does nothing else with it;
- the value is a normal finite double (not zero, a denormal, inf or NaN, nor a magnitude nobody writes: exponent within
  2**-64 and 2**64), written with the fewest digits that give the same 64 bits back (`0.5`, never a lossy decimal).
Every proposal is judged; a value that is a real global's initial value only costs a compile. The explanation of the
`$at` load is read off the targets, not from the compiler's source, and is a hypothesis."""
import math
import re
import struct

from .csource import _blank
from .float_literal_global import _reads
from .integer_repair_support import edit, view

FAMILY = 'double_literal_global'
FAMILIES = (FAMILY,)

LIMIT = 8
_IDENT = r'[A-Za-z_]\w*'


def literal(value):
    """The C literal whose f64 has exactly the bits `value`, or None when it is not a plausible literal."""
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        return None
    exponent = (value >> 52) & 0x7FF
    if exponent in (0, 0x7FF) or not 1023 - 64 <= exponent < 1023 + 64:
        return None
    number = struct.unpack('>d', struct.pack('>Q', value))[0]
    if not math.isfinite(number):
        return None
    text = repr(number)
    if struct.unpack('>Q', struct.pack('>d', float(text)))[0] != value:
        return None
    if 'e' in text or 'inf' in text or 'nan' in text:
        return None
    if '.' not in text:
        text += '.0'
    return f'({text})' if text.startswith('-') else text


def _declared_double(symbol, texts):
    found = None
    pattern = re.compile(r'(?m)^[ \t]*((?:(?:extern|static|const|volatile)[ \t]+)*)(' + _IDENT + r')[ \t]*(\**)[ \t]*'
                         + re.escape(symbol) + r'[ \t]*(\[[^\]]*\])?[ \t]*(?:=[^;]*)?;')
    for text in texts:
        for match in pattern.finditer(_blank(text or '')):
            found = (match[2] in ('f64', 'double') and not match[3] and not match[4]
                     and 'volatile' not in match[1].split())
    return bool(found)


def _double_loads(symbol, asm):
    """True when the target's assembly only loads `symbol` as a double through `$at`, at least once."""
    loads = 0
    pattern = re.compile(r'%(?:hi|lo|gp_rel)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)')
    for line in (asm or '').splitlines():
        if not pattern.search(line):
            continue
        code = re.sub(r'/\*.*?\*/', ' ', line).strip()
        if re.match(r'lui\s+\$at\s*,\s*%hi\(', code):
            continue
        if re.match(r'ldc1\s+\$\w+\s*,\s*%lo\(\s*' + re.escape(symbol) + r'\s*\)\s*\(\s*\$at\s*\)', code):
            loads += 1
            continue
        return False
    return loads > 0


def variants(source, name, header='', asm='', words=None):
    """Proposals: each double global the function only reads, whose eight bytes the caller supplied, as its literal; then
    all of them together."""
    if not words or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    edits = []
    for symbol in sorted(words)[:64]:
        if not re.fullmatch(_IDENT, str(symbol)) or symbol == name:
            continue
        text = literal(words[symbol])
        if text is None or not _double_loads(symbol, asm) or not _declared_double(symbol, (header, source)):
            continue
        spans = _reads(part, symbol)
        if not spans:
            continue
        uses = [m for m in re.finditer(r'(?<![\w.])' + re.escape(symbol) + r'\b', outside)]
        declarations = re.findall(r'(?m)^[ \t]*(?:(?:extern|static|const)[ \t]+)*' + _IDENT + r'[ \t]+'
                                  + re.escape(symbol) + r'[ \t]*;', outside)
        if len(uses) > len(declarations):
            continue
        edits.append([(start, end, text) for start, end in spans])
        if len(edits) >= LIMIT:
            break
    out = [(FAMILY, edit(source, one)) for one in edits]
    if len(edits) > 1:
        out.append((FAMILY, edit(source, [item for one in edits for item in one])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'words'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py); `words` from the caller's data
