"""A float literal written as the named pool word the target loads, the other direction of `float_literal_global`.

`float_literal_global` turns `extern f32 D_8000930C;` into `500.0f` where the target loads the constant through `$at`
(the assembler's `l.s`). The opposite also decided matches on SN GCC 2.8.1 (`-G8`) code: a literal in the draft shows
up as `?.rdata` and a different register order, where the game's source named the word (`extern f32 D_8000930C;`, a
literal that shows `?.rdata` under `-G8` in two compare functions, and `extern const f32 D_...;` as the word a local
constant was held in for another), and a draft whose literals were all rewritten at once (every rodata word of one
value as a literal) changed the allocation of one routine, so the word has to be named at some uses and not others.

The word is game data the caller supplies (`words`, {symbol: the 32-bit word at its address}, as for
`float_literal_global`), and the target's assembly must load the symbol as a float through `$at` or `$gp`
(`float_literal_global._float_loads`), at least once. For each symbol whose word is a plausible float literal
(`float_literal_global.literal`) and whose text the function writes as a float literal (`500.0f`, `-150.0f`, `1e3f`
spellings are read by value), the children are, in this order:
- every use of that literal in the function replaced by the symbol, `extern f32 NAME;` declared before the function when
  neither the header nor the source declares it;
- the same with `extern const f32 NAME;` (a new declaration only);
- the first use only, when the literal appears more than once (the other uses stay literals).
At most `LIMIT` children. A symbol the source already declares as a double, pointer or array is skipped. A function with
`volatile` or `asm` is left alone. Proposals only; the compiler and the byte judge decide."""
import math
import re
import struct

from .csource import _blank, find
from .float_literal_global import _declared_float, _float_loads, literal
from .integer_repair_support import IDENT, edit, view

FAMILY = 'pool_word_literal_swap'
FAMILIES = (FAMILY,)
LIMIT = 8
_NUMBER = re.compile(r'(?<![\w.])-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[fF](?![\w.])')


def _bits(text):
    try:
        value = float(text.rstrip('fF'))
        return struct.unpack('>I', struct.pack('>f', value))[0] if math.isfinite(value) else None
    except (ValueError, OverflowError):
        return None


def _declared_anywhere(symbol, header, source):
    return bool(re.search(rf'(?m)^[ \t]*(?:(?:extern|static|const)\s+)*{IDENT}[ \t*]+{re.escape(symbol)}\b[^;(]*;', _blank(header + '\n' + source)))


def variants(source, name, header='', asm='', words=None):
    if not words or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b', body):
        return []
    uses = {}
    for hit in _NUMBER.finditer(part.clean, part.opening, part.end):
        start, text = hit.start(), hit.group()
        if text.startswith('-') and re.search(r'[\w)\]]\s*$', part.clean[:start]):
            start, text = start + 1, text[1:]  # `x -1.5f` is a subtraction: the literal is the 1.5f
        bits = _bits(text)
        if bits is not None:
            uses.setdefault(bits, []).append((start, start + len(text)))
    out = []
    for symbol in sorted(words):
        word = words[symbol]
        if not isinstance(word, int) or not re.fullmatch(IDENT, str(symbol)) or word not in uses or literal(word) is None:
            continue
        if not _float_loads(symbol, asm):
            continue
        declared = _declared_anywhere(symbol, header, source)
        if declared and not _declared_float(symbol, (header, source)):
            continue
        # a negative literal is written `-150.0f` (the minus is part of the match) and stays a plain `-` use
        spans = uses[word]
        every = [(a, b, symbol) for a, b in spans]
        at = source.rfind('\n', 0, find(source, name)[0]) + 1
        forms = [('', every)]
        if not declared:
            forms.append(('const ', every))
        if len(spans) > 1:
            forms.append(('', every[:1]))
        for const, edits in forms:
            extra = [] if declared else [(at, at, f'extern {const}f32 {symbol};\n')]
            out.append((FAMILY, edit(source, edits + extra)))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'words'),
          'order': 61, 'archs': ('mips',)}
