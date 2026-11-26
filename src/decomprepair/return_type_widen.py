"""A narrow return type (`u16`, `s16`, `u8`, `s8`) the target never narrows to: written as the word it returns.

    u16 f(s32 a) { ... return (u16) -(s32) *(u16 *)(tab + a); }   ->   s32 f(s32 a) { ... return -(s32) *(u16 *)(tab + a); }

m2c gives a function the narrow type of the loads it saw returned (a `lhu` into `$v0`), and puts a cast of that type
around a value it negated or computed. A narrow return type makes KMC GCC 2.7.2 (`-O2`) narrow every value it
returns: a `u16` return adds `andi $v0,$v0,0xffff` after a negation, an `s16` one `sll`/`sra`, a `u8` one `andi
0xff`. The target's `negu $v0,$v0` flows straight into the epilogue with no such row, because the original returned
an `int` (a 100-point difference of one row on a 4-way sine-table lookup, 28 instructions: `u16` -> `s32` and the
`(u16)` casts dropped from the returns made it 0). The loads themselves are unaffected: `lhu` already zero-extends.

Offered when the function returns a narrow integer type and the target's `$v0` is never narrowed (none of `andi
$v0,*,0xff`/`0xffff`, `sll $v0,*,16`/`24`, `andi` with those masks into `$v0` on the way out; the target's `asm` is
needed, without it nothing is offered). Children, the combination first because it is what scores (the type alone
leaves the narrowing cast in place):
  * `return_type_widen`: the return type is `s32` and every `return (T) expr;` whose cast covers the whole expression
    and names the return type loses the cast;
  * `return_type_widen_type`: only the return type is `s32` (when there was a cast to drop, so the two differ).
A prototype of the function earlier in the source changes with it; one in the project's header is not a source
rewrite and stops the repair (change it with `edit_context` first). Hypothesis, not confirmed in the compiler source:
the narrowing row comes from the front end's conversion of the return value to the declared type; the exact judge
decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'return_type_widen'
FAMILY_TYPE = 'return_type_widen_type'
FAMILIES = (FAMILY, FAMILY_TYPE)
NARROW = {'u8', 's8', 'u16', 's16', 'char', 'short', 'unsigned char', 'unsigned short', 'signed char', 'signed short'}
BASE = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64', 'char', 'short', 'int', 'long', 'unsigned', 'signed',
        'float', 'double', 'f32', 'f64'}
ROW = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s+(?P<args>[^\n]*)$', re.M)
MASK = re.compile(r'0[xX](?:[fF]{2}|[fF]{4})(?![0-9a-fA-F])|^(?:255|65535)$')


def narrowed(asm):
    """Whether the target writes `$v0` through a byte or halfword mask or a 16/24-bit shift pair's left half."""
    for row in ROW.finditer(asm or ''):
        args = [a.strip() for a in row['args'].split(',')]
        if len(args) != 3 or args[0] != '$v0':
            continue
        if row['op'] == 'andi' and MASK.search(args[2]):
            return True
        if row['op'] == 'sll' and args[2] in ('16', '24', '0x10', '0x18'):
            return True
    return False


def _narrow_type(text):
    return ' '.join(text.split())


def _cast_covers(clean, at, end):
    """Whether the unary cast that ends at `at` applies to everything up to `end` (the `;`): no binary operator,
    comma or conditional at the top level of the rest."""
    i, operand = at, True
    while i < end:
        c = clean[i]
        if c.isspace():
            i += 1
        elif c in '([':
            shut = ')' if c == '(' else ']'
            depth, j = 0, i
            while j < end:
                depth += (clean[j] == c) - (clean[j] == shut)
                j += 1
                if depth == 0:
                    break
            if depth:
                return False
            group = clean[i + 1:j - 1]
            if c == '(' and operand and re.fullmatch(rf'\s*(?:(?:const|unsigned|signed|struct)\s+)*(?:{"|".join(sorted(BASE))})(?:\s+\w+)?\s*\**\s*', group):
                i = j  # another cast: an operand is still to come
                continue
            operand = False
            i = j
        elif c.isalnum() or c == '_':
            if not operand:
                return False
            j = i
            while j < end and (clean[j].isalnum() or clean[j] in '_.'):
                j += 1
            operand = False
            i = j
        elif operand and c in '-+*&~!':
            i += 1
        elif not operand and clean.startswith('->', i):
            i += 2
            operand = True
            continue
        else:
            return False
    return not operand


def variants(source, name, asm='', header=''):
    if not asm or narrowed(asm):
        return []
    part = view(source, name)
    if not part:
        return []
    heads = list(re.finditer(rf'(?m)^[ \t]*(?:(?:static|inline|extern)[ \t]+)*(?P<type>(?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)'
                             rf'[ \t]+{re.escape(name)}\s*\(', part.clean[:part.opening + 1]))
    if not heads:
        return []
    kind = _narrow_type(heads[-1]['type'])
    if kind not in NARROW:
        return []
    if re.search(rf'(?m)^[ \t]*(?:extern[ \t]+)?{re.escape(kind)}[ \t]+{re.escape(name)}\s*\(', header or ''):
        return []  # a header prototype would conflict; changing it is the header's edit
    type_edits = [(m.start('type'), m.end('type'), 's32') for m in heads if _narrow_type(m['type']) == kind]
    body = part.clean[part.opening:part.end]
    cast_edits = []
    for m in re.finditer(r'\breturn\s*\(\s*(?P<t>[A-Za-z_][\w ]*?)\s*\)\s*', body):
        if _narrow_type(m['t']) != kind:
            continue
        stop = body.find(';', m.end())
        if stop < 0 or not _cast_covers(body, m.end(), stop):
            continue
        cast_edits.append((part.opening + m.start() + len('return'), part.opening + m.end(), ' '))
    out = []
    if cast_edits:
        out.append((FAMILY, edit(source, type_edits + cast_edits)))
    out.append((FAMILY_TYPE if cast_edits else FAMILY, edit(source, type_edits)))
    return [(f, t) for f, t in dict.fromkeys(out) if t != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
