"""A small `extern` scalar widened to a two-word array, so the compiler no longer files it as small data.

GCC's MIPS back end keeps a global at most `-G N` bytes in the small-data area and reaches it through `$gp` or, when the
profile keeps `$gp` out of it (an N64 build: `-G0`, or `-G4`/`-G8` with no `$gp` setup), as one address piece the
assembler expands with `$at` (`lw $r, G` is `lui $at; lw $r, lo($at)`). A symbol that is *not* small data is split by the
compiler itself into an explicit `lui $r, %hi(G)` and an access through `%lo(G)($r)`, which the optimiser can hoist,
share and allocate a register of its own. Which of the two a symbol gets is decided by its declared size against the
threshold, not by anything the function does with it.

The target of a small N64 function (SN GCC 2.8.1, `-G0 -mips2 -O2 -fno-schedule-insns`) read one float and one integer
global. At `-G0` both globals were split, but the target kept the float's address in `$at` (a scalar the compiler did not
split); at `-G4` the 4-byte float stayed unsplit and so matched, and the integer global, which the target still loaded
through `lui $v0; lw $v1, %lo(D)($v0)`, had to be split too. Declaring the integer as a two-word array,
`extern s32 G[2];`, read as `G[0]`, made its size 8 bytes (above `-G4`), so it was split again while the float was not
(the pair scored 110 with the scalar and 0 with the array). Statement order, qualifiers and float-literal spellings never
reached it.

A proposal takes a global that the function only reads, that the source (not the header) declares as `extern T G;` with
a scalar `T` of at most the profile's `-G` size in bytes (the profile must name one: IDO and others split their own way; `-G0` splits
everything, so there is nothing to widen), that no other function in the file names, and that the target's assembly
splits itself: a `lui` of `%hi(G)` into a register other than `$at`, never read through `$gp`. Children:
- each such global as `extern T G[n];` with its reads written `G[0]`, where `n` makes the array larger than the
  threshold (two elements, or more for a narrow type);
- all of them together (the source's profile may need several to cross at once).
At most MAX_GLOBALS globals and MAX_CHILDREN children. The caller pairs these with the small-data flag (`-G`) it is
judging; this module reads text only and never compiles or judges."""
import re

from .csource import _blank
from .float_literal_global import _reads
from .int_global_array_read import _code_lines
from .integer_repair_support import IDENT, edit, view

FAMILY = 'extern_size_widen'
FAMILIES = (FAMILY,)

MAX_GLOBALS = 4
MAX_CHILDREN = 6
_SIZES = (
    (re.compile(r'(?:[su]8|(?:unsigned|signed)\s+char|char)$'), 1),
    (re.compile(r'(?:[su]16|(?:unsigned|signed)\s+short|short)$'), 2),
    (re.compile(r'(?:[su]32|f32|float|(?:unsigned|signed)\s+(?:int|long)|unsigned|signed|int|long)$'), 4),
)
_TYPE = r'(?:[su](?:8|16|32)|f32|float|(?:unsigned|signed)\s+(?:char|short|int|long)|unsigned|signed|char|short|int|long)'
_DECLARATION = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)extern[ \t]+(?P<type>{_TYPE}|{IDENT}[ \t]*\*)[ \t]*(?P<name>{IDENT})[ \t]*;')


def threshold(flags):
    """The small-data size the flags set: `-G N` or `-GN`, the last one named; None when they name none."""
    if isinstance(flags, str):
        flags = flags.split()
    found = None
    flags = list(flags or ())
    for index, flag in enumerate(flags):
        if flag == '-G' and index + 1 < len(flags) and flags[index + 1].isdigit():
            found = int(flags[index + 1])
        elif re.fullmatch(r'-G\d+', flag):
            found = int(flag[2:])
    return found


def size_of(kind):
    """The byte size of an `extern` scalar type the function may be widened for, or None."""
    kind = re.sub(r'\s+', ' ', kind.strip())
    if kind.endswith('*'):
        return 4
    return next((size for pattern, size in _SIZES if pattern.match(kind)), None)


def split_by_target(symbol, asm):
    """True when the assembly builds `symbol`'s high half in a register other than `$at` (the compiler split it itself)
    and never reaches it through `$gp`."""
    split = False
    mention = re.compile(r'%(?:hi|lo|gp_rel)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)')
    for code in _code_lines(asm):
        if not mention.search(code):
            continue
        if re.search(r'%gp_rel\(|\$gp\s*\)', code):
            return False
        high = re.match(r'lui\s+\$(\w+)\s*,\s*%hi\(', code)
        if high:
            if high[1] == 'at':
                return False
            split = True
    return split


def variants(source, name, header='', asm='', flags=()):
    """Proposals: each small global the target splits, declared as an array above the `-G` threshold and read `G[0]`,
    then all of them together."""
    limit = threshold(flags)
    if not asm or not limit:  # (no -G in the profile: the compiler's own default and its $gp use are not this shape)
        return []
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    used = set(re.findall(IDENT, source[part.opening:part.end]))
    found = []
    for hit in _DECLARATION.finditer(outside):
        symbol, kind = hit['name'], re.sub(r'\s*\*$', ' *', re.sub(r'\s+', ' ', hit['type']).strip())
        if len(found) >= MAX_GLOBALS:
            break
        size = size_of(kind)
        if hit.start() >= part.opening or symbol not in used or symbol == name or size is None or size > limit:
            continue
        if re.search(rf'\b{re.escape(symbol)}\b', header or '') or not split_by_target(symbol, asm):
            continue
        spans = _reads(part, symbol)
        if not spans:
            continue
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue  # another function names it
        found.append((symbol, kind, hit, spans, max(2, limit // size + 1)))
    if not found:
        return []

    def plan(entry):
        symbol, kind, hit, spans, count = entry
        return [(hit.start(), hit.end(), f'{hit["indent"]}extern {kind} {symbol}[{count}];')] + [
            (a, b, f'{symbol}[0]') for a, b in spans]

    out = [(FAMILY, edit(source, plan(entry))) for entry in found]
    if len(found) > 1:
        out.append((FAMILY, edit(source, [e for entry in found for e in plan(entry)])))
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'flags'),
          'order': 63, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
