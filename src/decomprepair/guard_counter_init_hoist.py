"""A loop counter zeroed as the guarded block's first statement, moved above the guard, and narrowed to `u16`.

m2c writes a guarded triangle loop as `if (flag < n) { i = 0; do { ... } while ((i & 0xFFFF) < n); }` when the target's
`move $s0, $zero` sits in the guard's delay slot. GCC 2.7.2's reorg fills that slot from above the branch (an insn
before the jump the jump does not depend on) before it looks at either thread; with the zero inside the block it
takes the join's `li $v0, -1` from the branch target instead, one instruction more than the target (a 996-instruction
collision sweep, KMC GCC 2.7.2).

Moved above the guard, an `s32` counter is the same constant as the guard's flag, and cse (make_regs_eqv: the register
that lives longest heads the class) compares the counter, which combine then folds (`beqz count`, the `sltu` gone and an
8-byte frame slot more). A `u16` counter is another machine mode (HImode), so it never joins the flag's class and the
guard keeps comparing the flag (170 -> 60 on that function; either edit alone left it at 225 or 170). The counter is
narrowed only when every read of it is masked to 16 bits already (`i & 0xFFFF`), so the program is unchanged.

Children: the init moved alone (`guard_counter_init_hoist`) and moved with the narrowed counter
(`guard_counter_init_hoist_u16`). Evidence: one function (docs/learnings in decompdecomp).
"""
import re

from .integer_repair_support import IDENT, _address_taken, view
from .pattern_repairs import close

FAMILY = 'guard_counter_init_hoist'
FAMILY_U16 = 'guard_counter_init_hoist_u16'
FAMILIES = (FAMILY, FAMILY_U16)
LIMIT = 12

_GUARD = re.compile(r'\bif\s*\(')
_WIDE = r'(?:s32|u32|int|unsigned\s+int|unsigned|signed\s+int|s16|unsigned\s+short|short)'


def _narrowable(body, counter):
    """Every read of the counter is `counter & 0xFFFF`: only writes, increments and masked reads remain."""
    name = re.escape(counter)
    rest = re.sub(rf'(?m)^\s*(?:register\s+)?{_WIDE}\s+{name}\s*;', ';', body)
    rest = re.sub(rf'(?<![\w.>]){name}\s*=\s*0\s*;', ';', rest)
    rest = re.sub(rf'(?<![\w.>]){name}\s*(?:\+=\s*1\s*;|\+\+)', ' ', rest)
    rest = re.sub(rf'(?:\(\s*\(\s*int\s*\)\s*{name}\s*\)|\(\s*int\s*\)\s*{name}|(?<![\w.>]){name})\s*&\s*0x[fF]{{4}}\b', ' 0 ', rest)
    return not re.search(rf'(?<![\w.>]){name}\b', rest)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    out = []
    for guard in _GUARD.finditer(clean, part.opening, part.end):
        stop = close(clean, guard.end() - 1, '(', ')')
        if not stop:
            continue
        brace = stop
        while brace < part.end and clean[brace].isspace():
            brace += 1
        if brace >= part.end or clean[brace] != '{':
            continue
        first = re.match(rf'\s*({IDENT})\s*=\s*0\s*;', clean[brace + 1:part.end])
        if not first:
            continue
        counter = first[1]
        declared = re.search(rf'(?m)^(\s*)(?:register\s+)?({_WIDE})\s+{re.escape(counter)}\s*;', body)
        if (not declared or re.search(rf'(?<![\w.>]){re.escape(counter)}\b', clean[guard.end():stop])
                or _address_taken(body, counter)):
            continue
        line = clean.rfind('\n', 0, guard.start()) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        zero_start, zero_end = brace + 1 + first.start(1), brace + 1 + first.end()
        hoisted = (source[:guard.start()] + f'{counter} = 0;\n{indent}' + source[guard.start():zero_start]
                   + source[zero_end:])
        if hoisted != source and (FAMILY, hoisted) not in out:
            out.append((FAMILY, hoisted))
        at = part.opening + declared.start(2)
        if declared[2] != 'u16' and at < guard.start() and _narrowable(body, counter):
            narrowed = hoisted[:at] + 'u16' + hoisted[at + len(declared[2]):]
            out.append((FAMILY_U16, narrowed))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 400}  # the registry: no caller wiring (registry.py)
