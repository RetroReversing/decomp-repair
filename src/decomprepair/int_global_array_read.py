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
Then each form for all the globals together. At most 4 globals and 24 children."""
import re

from .csource import _blank
from .float_literal_global import _reads
from .integer_repair_support import IDENT, edit, view

FAMILY = 'int_global_array_read'
FAMILIES = (FAMILY,)

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
        if re.search(rf'\b{re.escape(symbol)}\b', header or '') or not early_address(symbol, asm):
            continue
        spans = _reads(part, symbol)
        if not spans:
            continue
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue
        found.append((symbol, kind, hit, spans))
    if not found:
        return []

    def plan(entry, form):
        symbol, kind, hit, spans = entry
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
    for form in ('bytes', 'array'):
        for entry in found:
            if form == 'array' and _BYTES.match(entry[1]):
                continue
            out.append((FAMILY, edit(source, plan(entry, form))))
    if len(found) > 1:
        for form in ('bytes', 'array'):
            edits = [e for entry in found for e in one(entry, form)]
            out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'order': 62,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
