"""A plain copy written just after an early-return guard, moved above the guard.

`idx = f(); if (idx == -1) { ...; return 1; } start = idx;` (m2c puts a copy where its first reader is): written after
the guard, `start` is born in the block after the branch and lives in that block only, so local-alloc gives it a
register by its own block's order (a call argument it is subtracted into, `$a0`). Written before the test, the copy is a
value of the block that ends in the branch: it crosses into the next one, global.c allocates it among the function's
long-lived values, and delay-slot filling (reorg.c) puts the copy in the branch's slot, as targets have it (`beq $t2, $v0;
move $t3, $t2`). On a 179-instruction N64 billboard drawer (SN64 GCC 2.8.1, `-G0 -mips3 -O2`), with the call split into
its arms, it took the function from 250 to 10 and to 0 under its `-mfp32` profile; alone, 260 -> 250. The allocator
reading is a hypothesis the measurement agrees with; the judge decides each child.

The child (`guard_return_copy_hoist`, one per qualifying guard, bounded) moves `V = E;` to just before the `if` when:
- `E` is a local or a parameter, or a cast of one (no call, memory read, arithmetic or assignment);
- the `if` has no `else`, its arm ends with a `return` and has no `goto`, `break` or `continue`;
- neither the guard nor the arm names `V`, and the guard assigns none of `E`'s names.
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT, TYPES, _match

FAMILY = 'guard_return_copy_hoist'
FAMILIES = (FAMILY,)
LIMIT = 8
CAST = r'(?:\(\s*(?:unsigned\s+|signed\s+)?[A-Za-z_]\w*\s*\**\s*\)\s*)?'


def variants(source, name):
    return [(FAMILY, text) for text in copies(source, name)]


def copies(source, name, only=None):
    """The texts with one copy moved above its guard (`only`: just copies into that local)."""
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    known = set(re.findall(rf'\b{IDENT}\b', clean[start:opening])) | set(
        re.findall(rf'\b(?:{"|".join(TYPES)})\s+\**\s*({IDENT})\s*[;=,\[]', clean[opening:end]))
    result = []
    for hit in re.finditer(r'(?<![\w.])if\s*\(', clean[opening:end]):
        at = opening + hit.start()
        close = _match(clean, opening + hit.end() - 1)
        if close < 0 or not re.match(r'\s*\{', clean[close + 1:end]):
            continue
        brace = clean.find('{', close)
        arm_end = _match(clean, brace)
        if arm_end < 0:
            continue
        arm = clean[brace + 1:arm_end]
        if not re.search(r'\breturn\b[^;]*;\s*$', arm) or re.search(r'\b(?:goto|break|continue)\b', arm):
            continue
        copy = re.match(rf'\s*(?!else\b)({IDENT})\s*=(?!=)\s*({CAST}({IDENT}))\s*;', clean[arm_end + 1:end])
        if not copy:
            continue
        var, value, source_name = copy[1], copy[2].strip(), copy[3]
        if (only is not None and var != only) or var not in known or var in TYPES or source_name not in known or source_name == var:
            continue
        mention = re.compile(rf'(?<![\w.>]){re.escape(var)}\b')
        guard = clean[at:close + 1]
        if mention.search(guard) or mention.search(arm):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(source_name)}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\+\+|--', guard):
            continue
        copy_start, copy_end = arm_end + 1 + copy.start(1), arm_end + 1 + copy.end()
        statement = source[copy_start:copy_end]
        indent = re.search(r'[ \t]*$', source[:at])[0]
        rest = re.match(r'[ \t]*\n?', source[copy_end:]).end()
        text = (source[:at] + statement + '\n' + indent + source[at:copy_start].rstrip(' \t')
                + source[copy_end + rest:])
        if value and text != source and text not in result:
            result.append(text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
