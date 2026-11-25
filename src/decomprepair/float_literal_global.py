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
- the symbol is declared `f32`/`float`, or as a plain 32-bit integer word (`s32`, `u32`, `M2C_UNK`: m2c types a pool
  word by its uses, so `temp_f = D_x;` into a float local leaves it an `s32`; the target's `lwc1` says it is a float),
  an `extern` in the source or the header, never a double, pointer or array;
- the function only reads it: never assigned, incremented, called, indexed, a member read or its address taken, and
  no other function in the source names it;
- the target's assembly loads it with `lwc1` through `$at` (`%lo`) or `$gp` (`%gp_rel`), and does nothing else with it
  (no store, no integer load, no address built from it); without the assembly there is no proposal;
- the word is a plausible literal: a normal finite float, not zero, with an exponent between 2**-32 and 2**32 (a
  pointer like 0x80123456 is a tiny float, small integers are denormals, both rejected), and printed with the fewest
  digits that give the same 32 bits back (`500.0f`, never a lossy decimal), a negative one in parentheses.
The same word read through its address, `*(f32 *)0x80009BD0` (agents wrote that when a target lost the symbol's
annotation and the extern could not be linked; an N64 game's boundary-adjusted functions, SN GCC 2.8.1, -mfp32), is the
same literal: an automatic name `D_80009BD0` in `words` also replaces every `*(f32 *)` / `*(float *)` read of its
address, under the same load and plausibility tests (the cast needs no declaration). Three such functions went to exact
or to their last scheduling rows with the literal (2205 -> 0, 4565 -> 0 after one unrelated edit, 1240 -> 640).
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


WORD_TYPES = ('s32', 'u32', 'int', 'unsigned', 'M2C_UNK', 'M2C_UNK32')  # m2c's type for a word it read as an integer


def _declared_float(symbol, texts):
    """True when the last file-scope declaration of `symbol` (in `texts`, in order) is a plain f32/float, or a plain
    32-bit integer word (`s32`, `u32`, `M2C_UNK`): m2c types a literal-pool word by how the code around it uses it, and
    `temp_f = D_x;` into a float local leaves the word an `s32`. The target's own load is `lwc1` (`_float_loads`), so
    the word is a float whatever the declaration says."""
    found = None
    pattern = re.compile(r'(?m)^[ \t]*((?:(?:extern|static|const|volatile)[ \t]+)*)(' + _IDENT + r')[ \t]*(\**)[ \t]*'
                         + re.escape(symbol) + r'[ \t]*(\[[^\]]*\])?[ \t]*(?:=[^;]*)?;')
    for text in texts:
        for match in pattern.finditer(_blank(text or '')):
            found = (match[2] in ('f32', 'float') + WORD_TYPES and not match[3] and not match[4]
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


_AUTO = re.compile(r'D_([0-9A-Fa-f]{8})')


def _address_reads(part, symbol):
    """The spans of `*(f32 *)0xADDR` reads of an automatic name's address in the function's body, when there are any
    and none is written (an assignment, an increment) or has its address taken."""
    auto = _AUTO.fullmatch(symbol)
    if not auto:
        return None
    spans = []
    body = part.clean
    pattern = re.compile(r'\*\s*\(\s*(?:const\s+)?(?:f32|float)\s*\*\s*\)\s*\(?\s*0[xX]0*' + auto[1].lstrip('0')
                         + r'\b[uU]?\s*\)?', re.IGNORECASE)
    for match in pattern.finditer(body, part.opening, part.end):
        text = match[0]
        start, end = match.start(), match.end()
        if text.count('(') != text.count(')'):  # an unbalanced `( 0x..` took a bracket that is not its own
            if text.endswith(')'):
                end -= 1
                text = text[:-1]
            if text.count('(') != text.count(')'):
                continue
        before = body[:start].rstrip()
        after = body[end:].lstrip()
        if before.endswith('&') and not before.endswith('&&'):
            return None
        if re.match(r'(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))', after) or before.endswith(('++', '--')):
            return None
        spans.append((start, end))
    return spans or None


def _holder(part, spans, text):
    """Edits that write `text` at every read of a local whose one assignment is `k = <one of spans>;` and drop the
    assignment and the local's own declaration line, or None. A saved best that kept the word in a local (`k =
    *(f32 *)0x80008274;` then `o->x100 > k` five times) needs both: SN 2.8.1 emits each literal use as its own `li.s`
    (one pool word per use) and schedules it as a macro insn, which a local's one load does not reproduce (a debug
    printer, 2205 -> 500 with the local, 0 with the literal at each compare)."""
    body = part.clean
    for start, end in spans:
        before = body[:start]
        assign = re.search(r'(?:^|[;{}])\s*(' + _IDENT + r')\s*=\s*$', before)
        stop = re.match(r'\s*;', body[end:])
        if not assign or not stop:
            continue
        local = assign[1]
        statement = (start - len(before) + assign.start(1), end + stop.end())
        declaration = re.search(r'(?m)^[ \t]*(?:f32|float)[ \t]+' + re.escape(local) + r'[ \t]*;[ \t]*\n', body[part.opening:part.end])
        if not declaration:
            continue
        uses = [m for m in re.finditer(r'(?<![\w.>])' + re.escape(local) + r'\b', body[part.opening:part.end])]
        reads = []
        for m in uses:
            at = part.opening + m.start()
            if at == statement[0]:
                continue
            if part.opening + declaration.start() <= at < part.opening + declaration.end():
                continue
            after = body[at + len(local):].lstrip()
            prior = body[:at].rstrip()
            if re.match(r'(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))', after) or prior.endswith(('&', '++', '--')):
                return None  # assigned again, incremented or its address taken: a variable, not a holder
            reads.append((at, at + len(local), text))
        if not reads:
            continue
        line = part.source.rfind('\n', 0, statement[0]) + 1
        tail = part.source.find('\n', statement[1])
        cut = (line, tail + 1) if part.source[line:statement[0]].strip() == '' and part.source[statement[1]:tail].strip() == '' \
            else (statement[0], statement[1])
        return [*reads, (cut[0], cut[1], ''),
                (part.opening + declaration.start(), part.opening + declaration.end(), '')]
    return None


def variants(source, name, header='', asm='', words=None):
    """Proposals: each float global the function only reads, whose word the caller supplied, as its literal; then all
    of them together."""
    if not words or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    edits, holders = [], []
    for symbol in sorted(words)[:64]:
        if not re.fullmatch(_IDENT, str(symbol)) or symbol == name:
            continue
        text = literal(words[symbol])
        if text is None or not _float_loads(symbol, asm):
            continue
        cast = _address_reads(part, symbol)
        spans = _reads(part, symbol) if _declared_float(symbol, (header, source)) else None
        if not spans:
            if cast:
                edits.append([(start, end, text) for start, end in cast])
                held = _holder(part, cast, text)
                if held:
                    holders.append(held)
            continue
        spans += cast or []
        held = _holder(part, spans, text)
        if held:
            holders.append(held)
        # another function in this source naming it (a declaration is not a use)
        uses = [m for m in re.finditer(r'(?<![\w.])' + re.escape(symbol) + r'\b', outside)]
        declarations = re.findall(r'(?m)^[ \t]*(?:(?:extern|static|const)[ \t]+)*' + _IDENT + r'[ \t]+'
                                  + re.escape(symbol) + r'[ \t]*;', outside)
        if len(uses) > len(declarations):
            continue
        edits.append([(start, end, text) for start, end in spans])
        if len(edits) >= LIMIT:
            break
    out = [(FAMILY, edit(source, one)) for one in edits] + [(FAMILY, edit(source, one)) for one in holders]
    if len(edits) > 1:
        out.append((FAMILY, edit(source, [item for one in edits for item in one])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'words'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py); `words` from the caller's data
