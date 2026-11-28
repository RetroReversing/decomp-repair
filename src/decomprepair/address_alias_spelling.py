"""Some uses of a global's address spelled as another global's address plus an offset, so the compiler cannot share them.

GCC 2.x's cse puts `&sFmtEntryName` (a `symbol_ref`) in one value class wherever it is written and reuses the first
`lui/addiu` for every later use in the same extended block, and jump2's cross-jumping merges two branch ends whose
arguments are the same constant (the equal `REG_EQUAL` notes let it replace `move $a1,$s0` by the constant, jump.c
`find_cross_jump`). `&D_800D2858 + 0xC` is a different rtx (`(const (plus (symbol_ref D_800D2858) 12))`) at the same
address: it is its own class, it is not the plain symbol's note, and the linker puts both in the same place. The game's
code reached one address in two ways (a struct's first field by the struct's name, a buffer inside it by the buffer's own
name) and the compiler kept the two apart; a decompiler that names the address once cannot tell.

A KMC GCC 2.7.2 N64 menu function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 335 instructions, three calls that format a text entry
into one buffer, two of them before a four-way `switch` whose arms called it again): the target loaded the buffer's
address once into `$s0` and passed it in two calls and in the `switch`'s first two arms, and loaded it again, with
a fresh `lui/addiu` into `$a1`, in the `switch`'s last two arms (which cross-jumping then merged into one tail), and in
an earlier branch. With every use plain the arms all merged and the registers never matched (1930); with the four uses
that share the register spelled `&D_800D2858 + 0xC` the score fell to 920 and, with the arm-shared locals written inline
(`arm_shared_arg_inline`), to 0. Hypotheses read from the dumps of a `cc1` built with prints (`cse`, `jump2`, reorg) and
from cse.c and jump.c, not statements of the compiler's documentation.

`variants` reads the symbols whose address the function takes (`&sym`). A symbol named `D_xxxxxxxx` (as splat and the
draft name them) says its own address; for one the game's names replaced, the target's assembly (`asm`) still has the
original name, so the names that only the assembly uses stand in for it. For each such symbol and each other
`D_xxxxxxxx` the function names, within 0x100 bytes, it offers every contiguous run of that symbol's address uses spelled as
`((T *) ((u8 *) &base + offset))` (the whole run being the same class again, never the whole set), longest runs first.

`second_names` (family `address_second_name`) is the same idea where no neighbouring symbol reaches the address: the
address gets a second automatic name, `data_xxxxxxxx` beside `D_xxxxxxxx` (the judge resolves both to xxxxxxxx; two
linker symbols can share an address, as the end of one blob is the start of the next). An SN GCC 2.8.1 N64 frame
function (`-G0 -mips3 -O2 -mfp32`, 386 instructions) computed a microcode's size as `end - start` and later, in one arm
of an `if`, stored the next microcode's start, which is the same address as `end`. With one name cse kept the address
in its register for the later store, so the subtraction could not overwrite it (630). With the later uses named
`data_800549D0` the target's `subu` into the end's register and the fresh `lui/addiu` came back (40; an adjacent
statement swap then gave 0). It applies to uses that take the address: an `extern T D_x[];` array named without a
subscript, or `&D_x`. Offered are each use alone, all uses but one, then the longer contiguous runs; never every use.
When `asm` is given, only symbols whose address the target builds (`addiu ... %lo(D_x)`) at least twice are tried."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'address_alias_spelling'
SECOND = 'address_second_name'
FAMILIES = (FAMILY, SECOND)
LIMIT = 40
REACH = 0x100
_DNAME = re.compile(r'\bD_([0-9A-Fa-f]{8})\b')
_EXTERN = re.compile(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>(?:(?:const|volatile|unsigned|signed|struct|union)[ \t]+)*{IDENT})'
                     rf'[ \t]*(?P<stars>\**)[ \t]*(?P<name>{IDENT})[ \t]*(?P<array>\[[^\]\n]*\])?[ \t]*;')


def _declared(text):
    """name -> element type text of each simple `extern T name;` or `T name[];` in the text."""
    found = {}
    for hit in _EXTERN.finditer(text):
        if hit['stars'] or hit['type'] in {'return', 'goto', 'typedef'}:
            continue
        found.setdefault(hit['name'], hit['type'].strip())
    return found


def _address_uses(clean, part, symbol):
    """(start, end) of each `&symbol` in the function that takes the address (not `a & symbol`)."""
    uses = []
    for hit in re.finditer(rf'&[ \t]*{re.escape(symbol)}\b(?![ \t]*[\[.(]|[ \t]*->)', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        before = clean[part.opening:start].rstrip()
        if before.endswith('&') or (before and re.search(r'[\w)\]]$', before) and not re.search(r'\breturn$', before)):
            continue
        uses.append((start, part.opening + hit.end()))
    return uses


def _call_argument(clean, start, end):
    """Whether `clean[start:end]` is a whole argument of a call: `f(a, &x, b)`, not a cast operand or a sum."""
    after = clean[end:].lstrip()[:1]
    before = clean[:start].rstrip()
    if after not in (',', ')') or not before or before[-1] not in '(,':
        return False
    depth, at = 0, len(before)
    while at > 0:
        at -= 1
        depth += (before[at] == ')') - (before[at] == '(')
        if depth < 0:
            return bool(re.search(rf'{IDENT}[ \t]*$', before[:at])) and not re.search(r'\b(?:if|while|for|switch|return|sizeof)[ \t]*$', before[:at])
    return False


def _runs(count):
    """Index ranges (i, j) over `count` uses, longest first, never the whole set."""
    ranges = [(i, j) for i in range(count) for j in range(i, count) if not (i == 0 and j == count - 1)]
    return sorted(ranges, key=lambda r: (-(r[1] - r[0]), r[0]))


def _spelling(kind, base, offset):
    sign = '+' if offset > 0 else '-'
    return f'(({kind} *) ((u8 *) &{base} {sign} 0x{abs(offset):X}))'


def _offset_variants(source, name, header='', asm=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    types = _declared(clean[:part.opening]) | _declared(re.sub(r'/\*.*?\*/|//[^\n]*', '', header or '', flags=re.S))
    bases = {m[0]: int(m[1], 16) for m in _DNAME.finditer(body) if m[0] in types and _address_uses(clean, part, m[0])}
    asm_only = {m[0]: int(m[1], 16) for m in _DNAME.finditer(asm or '')
                if m[0] not in body and m[0] not in clean and m[0] not in (header or '')}
    taken = {}
    for symbol in dict.fromkeys(re.findall(rf'&[ \t]*({IDENT})\b', body)):
        uses = [use for use in _address_uses(clean, part, symbol) if _call_argument(clean, *use)]
        if len(uses) >= 2 and symbol in types:
            taken[symbol] = uses
    result = []
    for symbol, uses in taken.items():
        own = _DNAME.fullmatch(symbol)
        addresses = [int(own[1], 16)] if own else sorted(set(asm_only.values()))
        for address in addresses:
            for base, where in bases.items():
                offset = address - where
                if base == symbol or not offset or abs(offset) > REACH:
                    continue
                kind = types[symbol] if re.fullmatch(rf'(?:(?:unsigned|signed)[ \t]+)?{IDENT}', types[symbol]) \
                    and not types[symbol].startswith(('struct', 'union')) else 'void'
                for first, last in _runs(len(uses)):
                    text = _spelling(kind, base, offset)
                    result.append((FAMILY, edit(source, [(a, b, text) for a, b in uses[first:last + 1]])))
    return result[:LIMIT]


_ARRAY_EXTERN = re.compile(rf'(?m)^[ \t]*extern[ \t]+(?P<type>(?:(?:const|volatile|unsigned|signed|struct|union)[ \t]+)*{IDENT}'
                           rf'[ \t]*\**)[ \t]*(?P<name>D_[0-9A-Fa-f]{{8}})[ \t]*(?P<array>\[[^\]\n]*\])?[ \t]*;')


def _plain_uses(clean, part, symbol):
    """(start, end) of each bare `symbol` of an array in the function: its address, not an element or a member."""
    uses = []
    for hit in re.finditer(rf'\b{symbol}\b(?![ \t]*\[)', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        before = clean[part.opening:start].rstrip()
        if before.endswith(('.', '->')) or re.search(r'\bsizeof[ \t]*\(?$', before):
            continue
        uses.append((start, part.opening + hit.end()))
    return uses


def _choices(count):
    """Which of `count` uses to rename: one, all but one, then longer contiguous runs; never all of them."""
    picks = [(i,) for i in range(count)]
    picks += [tuple(i for i in range(count) if i != skip) for skip in range(count)]
    picks += [tuple(range(i, j + 1)) for i, j in _runs(count)]
    return [pick for pick in dict.fromkeys(picks) if 0 < len(pick) < count]


def second_names(source, name, asm=''):
    """Children that give some uses of one address a second automatic name (`data_xxxxxxxx`)."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    per_symbol = []
    for hit in _ARRAY_EXTERN.finditer(clean[:part.opening]):
        symbol, array = hit['name'], hit['array']
        alias = 'data_' + symbol[2:]
        if re.search(rf'\b{alias}\b', clean):
            continue
        if asm and len(re.findall(rf'\baddiu\b[^\n]*%lo\({symbol}\)', asm)) < 2:
            continue
        uses = _plain_uses(clean, part, symbol) if array else _address_uses(clean, part, symbol)
        if len(uses) < 2:
            continue
        declared = f"extern {hit['type'].strip()} {alias}{'[]' if array else ''};\n"
        line = clean.rfind('\n', 0, hit.start('name')) + 1
        children = []
        for pick in _choices(len(uses)):
            edits = [(line, line, declared)]
            edits += [(uses[i][0], uses[i][1], alias if array else f'&{alias}') for i in pick]
            children.append((SECOND, edit(source, edits)))
        per_symbol.append(children)
    # A child of each symbol in turn, so one much-used global cannot take the whole limit.
    result = []
    for k in range(max(map(len, per_symbol), default=0)):
        result += [children[k] for children in per_symbol if k < len(children)]
    return result[:LIMIT]


def variants(source, name, header='', asm=''):
    return _offset_variants(source, name, header, asm) + second_names(source, name, asm)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm')}
