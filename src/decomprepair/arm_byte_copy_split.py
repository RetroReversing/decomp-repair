"""A byte held in a wide local and read in both arms of an `if`/`else`, with the first arm reading a narrow copy of it.

m2c names a byte it loaded (`temp_a0 = *(u8 *) (rec + 4);`) once and reads that one name in both arms of the branch
that follows (`if (kind != 9) { x = table[temp_a0 + 8]; } else { x = table[temp_a0 + 0x8C]; }`). In KMC GCC 2.7.2
(`-G0 -mips3 -mgp32 -mfp32 -O2`) the two arms then start with the same address sum `temp_a0 + base`, the first
scheduler finds it in both arms, and reorg fills the branch's delay slot with it once. The target of a 59-instruction
voice-loop body had it in each arm (`move $v1, $a0; addu $v0, $v1, $s2` in the first arm, `addu $v0, $a0, $s2` in the
second) and a register more for the table base to hold on to: the first arm read a copy of the byte kept in a local of
the byte's own type, which cse leaves alone (a different machine mode: `narrow_copy_web`) and combine turns into a
plain `move`.

For a local `W` that is read in both arms of one `if`/`else`, never written in either, and whose every assignment in the
function is a read of a `u8`/`s8`/`u16`/`s16` (a cast dereference such as `*((u8 *) (p + 4))`), the child declares a
local `W_byte` of that narrow type, copies `W_byte = W;` right before the `if`, and reads `W_byte` in the first arm
(one child) or the second arm (another). A `W` that was itself declared narrow is widened to `s32` in the same child:
with both of the narrow type, cse sees one quantity and folds the copy away (measured: 2525 -> 2310 on that voice loop
once the byte was `s32` and the copy `u8`; with both `u8` the score did not move). Every value `W` holds is a byte read,
so the widened local holds the same values and the program is the same program.

Only an `if` whose `else` is a braced block is read; a `W` assigned in an arm or incremented, address-taken, or a `goto`,
label, `return`, `break` or `switch` between its last assignment and the end of the `else`, or any `asm` or `#` line, leaves
that `if` alone (a `goto` elsewhere in the function does not). Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, _address_taken, edit
from .pattern_repairs import close

FAMILY = 'arm_byte_copy_split'
FAMILIES = (FAMILY,)
NARROW = {'u8': 'u8', 's8': 's8', 'u16': 'u16', 's16': 's16',
          'unsigned char': 'u8', 'signed char': 's8', 'unsigned short': 'u16', 'signed short': 's16'}
WIDE = r'(?:s32|u32|int|unsigned\s+int|signed\s+int|unsigned|long)'
DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{WIDE}|u8|s8|u16|s16)[ \t]+(?P<name>{IDENT})[ \t]*;[ \t]*\n')
BYTE_READ = re.compile(r'\*\s*\(\s*\(?\s*(?P<type>u8|s8|u16|s16|unsigned char|signed char|unsigned short|signed short)\s*\*\s*\)')
LIMIT = 8


def _arms(clean, opening, end):
    """[(if start, first arm span, second arm span)] of every `if (...) { ... } else { ... }` in the function."""
    found = []
    for hit in re.finditer(r'(?<![\w.>])if\s*\(', clean[opening:end]):
        start = opening + hit.start()
        cond_end = close(clean, opening + hit.end() - 1)
        if not cond_end:
            continue
        brace = re.match(r'\s*\{', clean[cond_end:end])
        if not brace:
            continue
        first_open = cond_end + brace.end() - 1
        first_end = close(clean, first_open, '{', '}')
        if not first_end:
            continue
        other = re.match(r'\s*else\s*\{', clean[first_end:end])
        if not other:
            continue
        second_open = first_end + other.end() - 1
        second_end = close(clean, second_open, '{', '}')
        if second_end:
            found.append((start, (first_open + 1, first_end - 1), (second_open + 1, second_end - 1)))
    return found


def _assignments(clean, name, lo, hi):
    """The right-hand sides of every plain `name = ...;` in clean[lo:hi], and whether anything else writes it."""
    plain = re.compile(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*([^;{{}}]*);')
    other = re.compile(rf'(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)|(?:\+\+|--)\s*{re.escape(name)}\b')
    return [m[1] for m in plain.finditer(clean, lo, hi)], bool(other.search(clean, lo, hi))


def _balanced(text):
    depth = 0
    for char in text:
        depth += (char == '{') - (char == '}')
        if depth < 0:
            return False
    return depth == 0


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    body = clean[opening:end]
    if re.search(r'\b(?:asm|__asm__)\b|^\s*#', body, re.M):
        return []
    decls = {}
    for decl in DECL.finditer(clean, opening, end):
        if decl['name'] not in decls and len(re.findall(rf'\b(?:{WIDE}|u8|s8|u16|s16|void|float|double)\s*\**\s*{re.escape(decl["name"])}\s*(?=[;=,\[])', body)) == 1:
            decls[decl['name']] = decl
    result = []
    for if_start, first, second in _arms(clean, opening, end):
        for wide, decl in decls.items():
            if _address_taken(body, wide):
                continue
            reads = [bool(re.search(rf'(?<![\w.>]){re.escape(wide)}\b', clean[a:b])) for a, b in (first, second)]
            writes = [_assignments(clean, wide, a, b) for a, b in (first, second)]
            if not all(reads) or any(w[0] or w[1] for w in writes):
                continue
            values, other_writes = _assignments(clean, wide, opening, end)
            kinds = {BYTE_READ.match(v.strip())['type'] if BYTE_READ.match(v.strip()) else None for v in values}
            if other_writes or not values or None in kinds or len({NARROW[k] for k in kinds}) != 1:
                continue
            narrow = NARROW[kinds.pop()]
            before = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(wide)}\s*=(?!=)\s*[^;{{}}]*;', clean[opening:if_start])]
            if not before:
                continue
            gap = clean[opening + before[-1].end():if_start]
            region = clean[opening + before[-1].end():second[1]]
            if (re.search(rf'(?<![\w.>]){re.escape(wide)}\b', gap) or not _balanced(gap)
                    or re.search(r'\b(?:return|break|continue|switch|case|default|goto)\b|(?m:^[ \t]*[A-Za-z_]\w*[ \t]*:(?!:))', region)):
                continue
            fresh = f'{wide}_byte'
            if re.search(rf'\b{re.escape(fresh)}\b', source):
                continue
            line = source.rfind('\n', 0, if_start) + 1
            lead = source[line:if_start]
            for arm in (first, second):
                if not lead.strip():
                    edits = [(line, line, f'{lead}{fresh} = {wide};\n')]
                else:
                    edits = [(if_start, if_start, f'{fresh} = {wide}; ')]
                edits += [(arm[0] + m.start(), arm[0] + m.end(), fresh)
                          for m in re.finditer(rf'(?<![\w.>]){re.escape(wide)}\b', clean[arm[0]:arm[1]])]
                declared = decl['type'].strip()
                edits.append((decl.end(), decl.end(), f'{decl["indent"]}{narrow} {fresh};\n'))
                if declared in NARROW:
                    edits.append((decl.start('type'), decl.end('type'), 's32'))
                result.append((FAMILY, edit(source, edits)))
    unique = []
    for item in result:
        if item[1] != source and item not in unique:
            unique.append(item)
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
