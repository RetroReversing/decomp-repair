"""An integer (or pointer) global whose address the target builds early, declared as an array and read through a cast.

GCC loads a scalar global with `lui $r, %hi(G)` and `lw $r, %lo(G)($r)` and schedules the `lui` next to its load. The
target of one small function (SN64 GCC 2.8.1-based `sn-n64-281`, -G8 -mips2 -O2: a field load plus an integer global
inside a `coss(...)` argument) instead had the `lui $v0, %hi(G)` before the prologue's `sw $ra` and two instructions
above the `lw`; every scalar spelling stayed at 60 (`*(s32 *)&G`, `&G`, a pointer local, `volatile`, swapped sum
operands) and a local holding the read swapped `$v0`/`$v1` (380-430). Declaring the symbol as a byte array,
`extern u8 G[];`, and reading it as `*(s32 *) G` made the address an ordinary address constant the compiler
materialises on its own (the scalar's `lui` rides with its load), and the `lui` moved to the target's place (60 -> 0).
It is the integer sibling of `float_global_array_read`, which does the same for float globals the target loads
through a register other than `$at`.
(Hypothesis: the explanation of the early `lui` is read off one target, not from the compiler's source.)

A proposal takes one integer or single-pointer global that the function only reads, that is declared in the source
(not the header) as `extern T G;` and that no other function in the file names, and whose address the target's
assembly builds in a register other than `$at` with at least one instruction between that `lui` and the first
`%lo(G)` use (a scalar read has them adjacent). Children, per global, from the plainest:
- `extern u8 G[];` with every read written `*(T *) G`;
- `extern T G[];` with every read written `G[0]` (the same as the first for a byte type, so offered once).
Then each form for all the globals together. At most 4 globals and 24 children.

Second shape (a 7-instruction function, 200 -> 0): a global read as `*(T *)((s8 *)G + K)` at two or more offsets, which
the compiler folds into the symbol (`lui/%lo(G+K)`), where the target builds the address once (`lui` + `addiu %lo(G)`,
no load through `%lo(G)`) and reads at `K($r)`. The child declares `extern u8 G[];`, adds `u8 *base_G = G;` and reads
`*(T *)(base_G + K)`; the array alone scored 600, the pointer local is what pins the address in a register.

Third shape (KMC GCC 2.7.2 `-O1`, N64; an 838-instruction menu renderer, 1995 -> 0): a byte the target mostly reads as
`lui; lbu %lo(G)` but in places builds the address of (`lui $s3; addiu $s3, %lo(G)`) and reads twice as `0($s3)`. The
scalar reads each carry their own `lui`; the array form gets the held address. The first two tests miss it, since the
first `lui` in the function is an ordinary scalar read's.

Family `reloaded_global_array`: a global the target loads again where a scalar's value would have been kept (SN64 GCC
2.8.1, `-G0 -mips3 -O2`; a 48-instruction N64 object update, 115 -> 0). The function copies two halfwords and a byte from
the record a pointer global names into the record its argument names, and the target loads the global three times through
one `%hi` register. With `extern void *G;` a store to a member of another record (a nonzero offset) leaves the global's
value in its register, so it is loaded twice; with `extern void *G[];` read `G[0]` the load is a member's too and every
such store makes the compiler load it again, while reads with no store between still share one load. `volatile` (the
`reloaded_global` family) reloads at every use, so it only fits a target with as many loads as mentions. The gate: the
source reads the global at least twice (through `->` and `[` too), and the target has at least two `%lo(G)` loads outside
`$at`. (The aliasing explanation is a controlled snippet's behaviour, not traced through the compiler's source.)"""
import re

from .csource import _blank
from .float_literal_global import _reads
from .integer_repair_support import IDENT, edit, view

FAMILY = 'int_global_array_read'
RELOAD_FAMILY = 'reloaded_global_array'
FAMILIES = (FAMILY, RELOAD_FAMILY)

MAX_GLOBALS = 4
MAX_CHILDREN = 24
_BASE = (r'(?:unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int|long)|unsigned|signed|[su](?:8|16|32)|'
         r'char|short|int|long)')
_BYTES = re.compile(r'(?:[su]8|(?:unsigned|signed)\s+char|char)$')
_DECLARATION = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)extern[ \t]+(?P<type>{_BASE}|{IDENT}[ \t]*\*)[ \t]*(?P<name>{IDENT})[ \t]*;')


def _code_lines(asm):
    """The assembly's instruction lines with their comments, labels and directives gone."""
    out = []
    for line in (asm or '').splitlines():
        code = re.sub(r'/\*.*?\*/', ' ', line).strip()
        if not code or code.startswith(('.', 'glabel', 'endlabel', 'nonmatching')) or re.match(rf'{IDENT}:', code):
            continue
        out.append(code)
    return out


def early_address(symbol, asm):
    """True when the assembly builds `symbol`'s high half in a register other than `$at`, never reads it through `$at`
    or `$gp`, and the first `lui` is not directly followed by the first `%lo` use (the scheduler hoisted it)."""
    lines = _code_lines(asm)
    mention = re.compile(r'%(?:hi|lo|gp_rel)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)')
    first_lui = first_lo = None
    for index, code in enumerate(lines):
        if not mention.search(code):
            continue
        high = re.match(r'lui\s+\$(\w+)\s*,\s*%hi\(', code)
        if high:
            if high[1] == 'at':
                return False
            if first_lui is None:
                first_lui = index
            continue
        if re.search(r'\$(?:at|gp)\s*\)', code):
            return False
        if first_lo is None and re.search(r'%lo\(', code):
            first_lo = index
    return first_lui is not None and first_lo is not None and first_lo - first_lui >= 2


def address_taken(symbol, asm):
    """True when the assembly materialises `symbol`'s address (`lui` then `addiu ...%lo(G)`, not through `$at`) and
    never loads or stores through its `%lo`: every use is the address plus a constant offset."""
    taken = False
    for code in _code_lines(asm):
        if not re.search(r'%(?:hi|lo|gp_rel)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)', code):
            continue
        high = re.match(r'lui\s+\$(\w+)\s*,\s*%hi\(', code)
        if high:
            if high[1] == 'at':
                return False
        elif re.match(r'addiu\s+\$\w+\s*,\s*\$\w+\s*,\s*%lo\(', code):
            taken = True
        else:
            return False
    return taken


def held_address(symbol, asm):
    """True when somewhere the assembly builds `symbol`'s whole address in a register other than `$at` and then loads at
    offset 0 through that register, whatever its other reads do."""
    built = None
    for code in _code_lines(asm):
        whole = re.match(rf'addiu\s+\$(\w+)\s*,\s*\$\w+\s*,\s*%lo\(\s*{re.escape(symbol)}\s*\)', code)
        if whole and whole[1] != 'at':
            built = whole[1]
        elif built:
            if re.match(rf'l[bhw]u?\s+\$\w+\s*,\s*(?:0x0|0)?\(\s*\${built}\s*\)', code):
                return True
            if re.match(rf'(?!s[bhw]\b|b|j)\w+\s+\${built}\b', code):
                built = None
    return False


def reloaded(symbol, asm):
    """True when the assembly loads through `symbol`'s `%lo` two or more times, none through `$at` or `$gp`."""
    load = re.compile(r'l[bhwd]u?\s+\$\w+\s*,\s*%lo\(\s*' + re.escape(symbol) + r'\s*\)\(\$(?!at\b|gp\b)\w+\)')
    return sum(1 for code in _code_lines(asm) if load.match(code)) >= 2


def _any_reads(part, symbol):
    """Every read of `symbol` in the function, member and element reads too: [(start, end)], or None when the function
    writes it, takes its address, calls it or names a member of the same spelling."""
    out = []
    for hit in re.finditer(r'(?<![\w.])' + re.escape(symbol) + r'\b', part.clean[part.opening:part.end]):
        start, end = part.opening + hit.start(), part.opening + hit.end()
        before, after = part.clean[:start].rstrip(), part.clean[end:].lstrip()
        if before.endswith(('->', '.', '++', '--')) or (before.endswith('&') and not before.endswith('&&')):
            return None
        if after.startswith(('.', '(')) or re.match(r'(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))', after):
            return None
        out.append((start, end))
    return out


def _reload_children(source, part, name, header, asm, outside):
    """`extern T G[];` read `G[0]` for each global the target loads again, one at a time and then all together."""
    used = set(re.findall(IDENT, source[part.opening:part.end]))
    plans = []
    for hit in _DECLARATION.finditer(outside):
        symbol = hit['name']
        kind = re.sub(r'\s*\*$', ' *', re.sub(r'\s+', ' ', hit['type']).strip())
        if len(plans) >= MAX_GLOBALS:
            break
        if hit.start() >= part.opening or symbol not in used or symbol == name \
                or re.search(rf'\b{re.escape(symbol)}\b', header or '') or not reloaded(symbol, asm):
            continue
        spans = _any_reads(part, symbol)
        if not spans or len(spans) < 2:
            continue
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue
        space = '' if kind.endswith('*') else ' '
        plans.append([(hit.start(), hit.end(), f'{hit["indent"]}extern {kind}{space}{symbol}[];')]
                     + [(a, b, f'{symbol}[0]') for a, b in spans])
    out = [edit(source, plan) for plan in plans]
    if len(plans) > 1:
        out.append(edit(source, [e for plan in plans for e in plan]))
    return [(RELOAD_FAMILY, child) for child in out]


_BYTE_CAST = re.compile(r'\(\s*(?:(?:unsigned|signed)\s+char|[su]8|char|void)\s*\*\s*\)\s*$')


def _offset_form(source, part, symbol, hit, spans):
    """The byte-array declaration and a `u8 *base_G = G;` local the offset reads go through (`(s8 *)G` becomes
    `base_G`); None when the local's name is taken."""
    local = f'base_{symbol}'
    if local in set(re.findall(IDENT, source)):
        return None
    edits = [(hit.start(), hit.end(), f'{hit["indent"]}extern u8 {symbol}[];'),
             (part.opening + 1, part.opening + 1, f'\n    u8 *{local} = {symbol};')]
    for a, b in spans:
        cast = _BYTE_CAST.search(part.clean[:a])
        edits.append((cast.start() if cast else a, b, local))
    return edit(source, edits)


def _read(kind, symbol):
    pointer = f'{kind}*' if kind.endswith('*') else f'{kind} *'
    return f'*({pointer}) {symbol}'


def variants(source, name, header='', asm=''):
    """Proposals: an integer global the target's `lui` hoists, as `extern u8 G[];` read `*(T *) G` and as
    `extern T G[];` read `G[0]`, per global and for all of them together."""
    if not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    body = source[part.opening:part.end]
    used = set(re.findall(IDENT, body))
    found = []
    for hit in _DECLARATION.finditer(outside):
        symbol, kind = hit['name'], re.sub(r'\s*\*$', ' *', re.sub(r'\s+', ' ', hit['type']).strip())
        if len(found) >= MAX_GLOBALS:
            break
        if hit.start() >= part.opening or symbol not in used or symbol == name:
            continue
        if re.search(rf'\b{re.escape(symbol)}\b', header or '') \
                or not (early_address(symbol, asm) or address_taken(symbol, asm) or held_address(symbol, asm)):
            continue
        spans = _reads(part, symbol)
        if not spans:
            continue
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue
        found.append((symbol, kind, hit, spans, address_taken(symbol, asm)))
    again = _reload_children(source, part, name, header, asm, outside)
    if not found:
        return again

    def plan(entry, form):
        symbol, kind, hit, spans, _ = entry
        indent = hit['indent']
        if form == 'bytes':
            declaration = f'{indent}extern u8 {symbol}[];'
            reads = [(a, b, _read(kind, symbol)) for a, b in spans]
        else:
            declaration = f'{indent}extern {kind} {symbol}[];'
            reads = [(a, b, f'{symbol}[0]') for a, b in spans]
        return [(hit.start(), hit.end(), declaration)] + reads

    def one(entry, form):
        return plan(entry, 'bytes' if _BYTES.match(entry[1]) else form)

    out = []
    for entry in found:
        if entry[4] and len(entry[3]) >= 2:
            child = _offset_form(source, part, entry[0], entry[2], entry[3])
            if child:
                out.append((FAMILY, child))
    found = [entry for entry in found if not entry[4]]
    for form in ('bytes', 'array'):
        for entry in found:
            if form == 'array' and _BYTES.match(entry[1]):
                continue
            out.append((FAMILY, edit(source, plan(entry, form))))
    if len(found) > 1:
        for form in ('bytes', 'array'):
            edits = [e for entry in found for e in one(entry, form)]
            out.append((FAMILY, edit(source, edits)))
    texts = {child for _, child in out}
    out = list(dict.fromkeys(out))[:MAX_CHILDREN]
    return out + [pair for pair in again if pair[1] not in texts]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'order': 62,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
