"""A call's result temporary reused for a later load whose masked value goes to another local.

`t = f(...); a = t & 0xFF; b = t & 0xFF00; ... x = p->flags & 4;` becomes `... t = p->flags; x = t & 4;`.

GCC 2.7.2's first scheduler (sched.c `birthing_insn_p`) launches an insn whose destination pseudo is set exactly once
as soon as it is ready; scheduling runs backwards, so the call result's zero-extend into a single-set `t` lands after
the next call's argument loads (`lw $a0; lw $a1; andi $v0, $v0, 0xffff` where the target has the `andi` first). With
the later byte load written into the same temporary, `t` has two sets and is not boosted, and the byte and its mask
keep their own registers (`lbu $v0; andi $v1, $v0, 4`), which a shared mask variable does not (60 -> 0 on a
996-instruction collision sweep, KMC GCC 2.7.2; the mask written into `t` itself gave 15: `t` became a global pseudo
and took `$v1`). The program is unchanged: `t` is dead after its last mask and holds the loaded value only.

A proposal needs `t` declared as a 32-bit integer local, assigned a call result, read afterwards only by the statements
between the call and the masked load, and the load statement `x = <expr without calls> & K;` with `x` another local.
Evidence: one function (docs/learnings in decompdecomp).
"""
import re

from .integer_repair_support import IDENT, _address_taken, view

FAMILY = 'call_temp_load_reuse'
FAMILIES = (FAMILY,)
LIMIT = 12
WINDOW = 12  # statements between the call and the load

_WIDE = r'(?:s32|u32|int|unsigned\s+int|unsigned|signed\s+int)'
_CALL = re.compile(rf'(?<![\w.>])(?P<t>{IDENT})\s*=\s*(?:\(\s*\w+\s*\)\s*)?{IDENT}\s*\([^;]*\)\s*;')
_MASKED = re.compile(rf'(?<![\w.>])(?P<x>{IDENT})\s*=\s*(?P<e>[^;=]+?)\s*&\s*(?P<k>0x[0-9A-Fa-f]+|[0-9]+)\s*;')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    out = []
    for call in _CALL.finditer(clean, part.opening, part.end):
        temp = call['t']
        if (not re.search(rf'(?m)^\s*(?:register\s+)?{_WIDE}\s+{re.escape(temp)}\s*;', body)
                or _address_taken(body, temp)):
            continue
        after = call.end()
        for count, masked in enumerate(_MASKED.finditer(clean, after, part.end)):
            if count >= WINDOW or '{' in clean[after:masked.start()] or '}' in clean[after:masked.start()]:
                break
            if (masked['x'] == temp or re.search(r'\w\s*\(', masked['e'])
                    or re.search(rf'(?<![\w.>]){re.escape(temp)}\b', masked['e'])
                    or re.search(rf'(?<![\w.>]){re.escape(temp)}\b', clean[masked.end():part.end])
                    or not re.search(rf'(?m)^\s*(?:register\s+)?[\w ]+\s+{re.escape(masked["x"])}\s*;', body)):
                continue
            line = clean.rfind('\n', 0, masked.start()) + 1
            indent = re.match(r'[ \t]*', source[line:])[0]
            text = source[masked.start('e'):masked.end('e')].strip()
            new = f'{temp} = {text};\n{indent}{masked["x"]} = {temp} & {masked["k"]};'
            child = source[:masked.start()] + new + source[masked.end():]
            if child != source and (FAMILY, child) not in out:
                out.append((FAMILY, child))
            break
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 400}  # the registry: no caller wiring (registry.py)
