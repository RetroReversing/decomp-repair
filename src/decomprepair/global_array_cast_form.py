"""A small-data global the target splits, declared as a byte array and read through a cast (its members too).

Under `-G N` GCC keeps a global of at most N bytes in small data and loads it with one assembler macro (`lw $r, G` is
`lui $r; lw $r, %lo(G)($r)`, or through `$at` for a float), so its `lui` can never be scheduled apart from the load.
A global the compiler cannot place in small data (an array of unknown size) is split: `lui %hi(G)` into a register of its
own, which the scheduler places anywhere, and `%lo(G)` loads (or stores) through it, which may be shared by several
accesses. Several small N64 functions (SN GCC 2.8.1, `-G8 -mips2/-mips3 -O2`) had that split on a global the draft
declared as a plain scalar or pointer: `extern Obj *G;` read `G->f`, `extern void *G;` read as `M2C_FIELD(G, f32 *, 0xC)`,
`extern s32 G;`. Declaring it `extern u8 G[];` and reading it `(*(Obj **) G)->f` (a pointer) or `(*(s32 *) G)` gave the
target's explicit `lui`. The byte array is better than a plain `extern Obj *G[];` read `G[0]->f` because the cast read
goes through the byte array's type, which the compiler cannot prove distinct from the record the pointer points at: the
stores to the record's fields go by without forcing the pointer to be loaded again, and the loads of the fields can
move above those stores, which the plain array did not allow (five pointer-reading functions decided this way, and
three integer ones decided with `extern s32 G[];` read `G[0]`).
`int_global_array_read` has the same retype for a global read as a plain value and cannot rewrite `G->f` or `G[i]` (its
reads stop at a member), nor reads the `-G` size. This family adds those: a pointer global read through `->` or `[`.
(Hypothesis: the explanation is read off the targets, not from the compiler's source.)

A proposal takes a global that the source (not the header) declares `extern T G;` with a scalar or pointer `T` of at most
the profile's `-G` size in bytes (the flags must name one), that the function only reads (`G`, and for a pointer `G->f`,
`G[i]`: never written, never its address, never `.f`) and that no other function in the file names, and whose
target assembly splits its high half: a `lui %hi(G)` into a register other than `$at` that a `%lo(G)` access uses with a
different register as its destination (or at least two instructions before its first use). Children, per global:
- `extern u8 G[];` with every read `(*(T *) G)` (for a pointer `T`: `(*(Obj **) G)`), the cast form;
- `extern T G[];` with every read `G[0]` (`G[0]->f`), the plain array form.
Then each form for all the globals together (a function whose several globals the target splits). Children come cast form
first for a pointer global and array form first for an integer one. At most MAX_GLOBALS globals and MAX_CHILDREN
children. This module reads text only and never compiles or judges; the caller pairs it with the profile being judged."""
import re

from .csource import _blank
from .extern_size_widen import size_of, threshold
from .int_global_array_read import _code_lines, address_taken, early_address
from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_array_cast_form'
FAMILIES = (FAMILY,)

MAX_GLOBALS = 4
MAX_CHILDREN = 8
_TYPE = r'(?:[su](?:8|16|32)|(?:unsigned|signed)\s+(?:char|short|int|long)|unsigned|signed|char|short|int|long)'
_DECLARATION = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)extern[ \t]+(?P<type>{_TYPE}|(?:struct[ \t]+)?{IDENT}[ \t]*\*)[ \t]*(?P<name>{IDENT})[ \t]*;')
_STORE = re.compile(r'(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))')
_LOAD = re.compile(r'(?:lw|lh|lhu|lb|lbu|lwc1|lwl|lwr|ld|ldc1|l\.s|l\.d)\b')


def split_high(symbol, asm):
    """True when the assembly builds `symbol`'s high half in a register other than `$at` and reaches the low half
    through it in a way one macro cannot (a load into another register, a store, a second access), or leaves at least
    one instruction between the `lui` and its first use (`int_global_array_read.early_address`)."""
    mention = re.compile(r'%(?:hi|lo)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)')
    highs, uses = set(), {}
    for code in _code_lines(asm):
        if not mention.search(code):
            continue
        high = re.match(r'lui\s+\$(\w+)\s*,\s*%hi\(', code)
        if high:
            if high[1] == 'at':
                return False
            highs.add(high[1])
            continue
        low = re.match(r'(\w+(?:\.\w)?)\s+\$(\w+)\s*,\s*%lo\([^)]*\)\(\$(\w+)\)', code)
        if not low or low[3] not in highs:
            return False  # through `$at` or `$gp`, or not a memory access
        uses[low[3]] = uses.get(low[3], 0) + 1
        if not _LOAD.match(low[1]) or low[2] != low[3] or uses[low[3]] > 1:
            return True
    return early_address(symbol, asm)


def _norm(kind):
    return re.sub(r'\s*\*$', ' *', re.sub(r'\s+', ' ', kind.strip()))


def _uses(part, symbol, pointer):
    """[(start, end, member)] of every read of `symbol` in the function, None when one writes it, takes its address,
    calls it or reads a member of it with `.`; `member` is true for `G->f` and `G[i]` (a pointer's)."""
    out = []
    for hit in re.finditer(r'(?<![\w.])' + re.escape(symbol) + r'\b', part.clean[part.opening:part.end]):
        start, end = part.opening + hit.start(), part.opening + hit.end()
        before, after = part.clean[:start].rstrip(), part.clean[end:].lstrip()
        if (before.endswith('&') and not before.endswith('&&')) or before.endswith(('->', '.', '++', '--')):
            return None
        if after.startswith(('->', '[')):
            if not pointer:
                return None
            out.append((start, end, True))
        elif after.startswith(('.', '(')) or _STORE.match(after):
            return None
        else:
            out.append((start, end, False))
    return out or None


def _found(source, part, name, header, asm, flags):
    limit = threshold(flags)
    if not asm or not limit:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    used = set(re.findall(IDENT, source[part.opening:part.end]))
    found = []
    for hit in _DECLARATION.finditer(outside):
        symbol, kind = hit['name'], _norm(hit['type'])
        if len(found) >= MAX_GLOBALS:
            break
        size = size_of(kind)
        if hit.start() >= part.opening or symbol not in used or symbol == name or size is None or size > limit:
            continue
        if re.search(rf'\b{re.escape(symbol)}\b', header or '') or not split_high(symbol, asm):
            continue
        spans = _uses(part, symbol, kind.endswith('*'))
        if not spans:
            continue
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue  # another function in the file reads it
        found.append((symbol, kind, hit, spans))
    return found


def _plan(entry, form):
    """The edits of one global in one form: 'cast' (a byte array read through the cast) or 'array' (its own type)."""
    symbol, kind, hit, spans = entry
    indent = hit['indent']
    if form == 'cast':
        pointer = kind if kind.endswith('*') else kind + ' '
        declaration, read = f'{indent}extern u8 {symbol}[];', f'(*({pointer}*) {symbol})'
        if re.fullmatch(r'(?:[su]8|(?:unsigned|signed)\s+char|char)', kind):
            read = f'{symbol}[0]'
    else:
        declaration = f'{indent}extern {kind}{"" if kind.endswith("*") else " "}{symbol}[];'
        read = f'{symbol}[0]'
    return [(hit.start(), hit.end(), declaration)] + [(a, b, read) for a, b, _ in spans]


def variants(source, name, header='', asm='', flags=()):
    """Proposals: each small global the target splits, as a byte array read through a cast and as an array of its own
    type, per global and for all of them together."""
    part = view(source, name)
    found = _found(source, part, name, header, asm, flags) if part else []
    # a plain read the sibling's gate already takes is `int_global_array_read`'s: keep a global with a member read, or
    # whose high half is split in a way the sibling's gate (one early `lui`) does not see
    if not any(any(member for _, _, member in entry[3]) or not (early_address(entry[0], asm) or address_taken(entry[0], asm))
               for entry in found):
        return []
    pointers = [entry for entry in found if entry[1].endswith('*')]
    order = ('cast', 'array') if pointers else ('array', 'cast')
    out = []
    for form in order:
        out += [edit(source, _plan(entry, form)) for entry in found]
        if len(found) > 1:
            out.append(edit(source, [e for entry in found for e in _plan(entry, form)]))
    return [(FAMILY, child) for child in dict.fromkeys(out)][:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'flags'),
          'order': 64, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
