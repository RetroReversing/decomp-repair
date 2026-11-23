"""A float global the function only reads, written as the float literal its word holds.

m2c names every word a function loads by its address, so a float constant the compiler put in its literal pool comes
out as a global: `extern f32 D_8000930C;` and `if (temp_fs0 < D_8000930C)`. The word there is the constant
(0x43FA0000, 500.0f). The game's compiler loaded it the way GCC loads a literal from its pool, `lui $at, %hi(...)` and
`lwc1 ... ($at)` (the assembler's `l.s` macro, which builds the address in `$at`), while a global read is a `lui` into
an ordinary register first: the saved best keeps a register row no spelling of the global fixes. Writing the literal
(`temp_fs0 < 500.0f`) is the fix. Three N64 functions built by GCC (SN GCC 2.8.1, one also under KMC GCC 2.7.2) went
10 -> 0 that way, each from its m2c draft: a compare with 500.0f, and two sums with 100.0f.

The word is game data the C cannot show, so the caller supplies it: `words` maps a symbol to the 32-bit word at its
address in the game, decoded in the game's byte order (decompdecomp reads it from the ROM, only for a symbol one function
refers to). A proposal replaces every read of one such symbol in the function by the literal, one child per symbol and
one with all of them, only when everything says it is a constant read where it is used:
- the symbol is declared `f32`/`float` (an `extern` in the source or the header), never a double, pointer or array;
- the function only reads it: never assigned, incremented, called, indexed, a member read or its address taken, and
  no other function in the source names it;
- the target's assembly loads it with `lwc1` through `$at` (`%lo`) or `$gp` (`%gp_rel`), and does nothing else with it
  (no store, no integer load, no address built from it); without the assembly there is no proposal;
- the word is a plausible literal: a normal finite float, not zero, with an exponent between 2**-32 and 2**32 (a
  pointer like 0x80123456 is a tiny float, small integers are denormals, both rejected), and printed with the fewest
  digits that give the same 32 bits back (`500.0f`, never a lossy decimal), a negative one in parentheses.
Doubles are left alone: one word cannot prove the other. Every proposal is judged; a word that is a real global's
initial value only costs a compile. The explanation of the `$at` load (the literal pool goes through `l.s`) is read off
the targets, not from the compiler's source, and is a hypothesis."""
import math
import re
import struct

from .csource import _blank
from .integer_repair_support import edit, view

FAMILY = 'float_literal_global'
FAMILIES = (FAMILY,)

LIMIT = 8  # symbols per function (each a child; the combination is one more)
MIN_EXPONENT, MAX_EXPONENT = -32, 32
_IDENT = r'[A-Za-z_]\w*'


def literal(word):
    """The C literal whose f32 has exactly the bits `word`, or None when `word` is not a plausible literal."""
    if not isinstance(word, int) or not 0 <= word <= 0xFFFFFFFF:
        return None
    exponent = (word >> 23) & 0xFF
    if exponent in (0, 0xFF) or not MIN_EXPONENT <= exponent - 127 < MAX_EXPONENT:
        return None  # zero, a denormal (small integers), inf or NaN, or a magnitude nobody writes (pointers)
    value = struct.unpack('>f', struct.pack('>I', word))[0]
    if not math.isfinite(value):
        return None
    for digits in range(1, 10):
        text = f'{value:.{digits}g}'
        if struct.unpack('>I', struct.pack('>f', float(text)))[0] == word:
            break
    else:
        return None
    text = repr(float(text))  # the same digits written out: 500.0, not 5e+02
    if 'e' not in text and '.' not in text:
        text += '.0'
    text += 'f'
    return f'({text})' if text.startswith('-') else text


def _declared_float(symbol, texts):
    """True when the last file-scope declaration of `symbol` (in `texts`, in order) is a plain f32/float."""
    found = None
    pattern = re.compile(r'(?m)^[ \t]*((?:(?:extern|static|const|volatile)[ \t]+)*)(' + _IDENT + r')[ \t]*(\**)[ \t]*'
                         + re.escape(symbol) + r'[ \t]*(\[[^\]]*\])?[ \t]*(?:=[^;]*)?;')
    for text in texts:
        for match in pattern.finditer(_blank(text or '')):
            found = (match[2] in ('f32', 'float') and not match[3] and not match[4]
                     and 'volatile' not in match[1].split())
    return bool(found)


def _float_loads(symbol, asm):
    """True when the target's assembly only loads `symbol` as a float through `$at` or `$gp` (`lui $at` for its high
    half), at least once."""
    loads = 0
    pattern = re.compile(r'%(?:hi|lo|gp_rel)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)')
    for line in (asm or '').splitlines():
        if not pattern.search(line):
            continue
        code = re.sub(r'/\*.*?\*/', ' ', line).strip()
        if re.match(r'lui\s+\$at\s*,\s*%hi\(', code):
            continue
        if re.match(r'lwc1\s+\$\w+\s*,\s*%lo\(\s*' + re.escape(symbol) + r'\s*\)\s*\(\s*\$at\s*\)', code) or \
                re.match(r'lwc1\s+\$\w+\s*,\s*%gp_rel\(\s*' + re.escape(symbol) + r'\s*\)\s*\(\s*\$gp\s*\)', code):
            loads += 1
            continue
        return False  # a store, an integer load, an offset into it or its address: not a literal read
    return loads > 0


def _reads(part, symbol):
    """The spans of `symbol` in the function's body when every one is a plain read, else None."""
    spans = []
    body = part.clean
    for match in re.finditer(r'(?<![\w.])' + re.escape(symbol) + r'\b', body[part.opening:part.end]):
        start, end = part.opening + match.start(), part.opening + match.end()
        before = body[:start].rstrip()
        after = body[end:].lstrip()
        if before.endswith('&') and not before.endswith('&&'):
            return None  # its address
        if before.endswith(('->', '.', '++', '--')):
            return None
        if re.match(r'(?:\+\+|--|\[|\(|\.|->|(?:[-+*/%&|^]|<<|>>)?=(?!=))', after):
            return None  # written, incremented, indexed, called or a member read
        spans.append((start, end))
    return spans or None


def variants(source, name, header='', asm='', words=None):
    """Proposals: each float global the function only reads, whose word the caller supplied, as its literal; then all
    of them together."""
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
        if text is None or not _float_loads(symbol, asm) or not _declared_float(symbol, (header, source)):
            continue
        spans = _reads(part, symbol)
        if not spans:
            continue
        # another function in this source naming it (a declaration is not a use)
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
