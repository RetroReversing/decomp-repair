"""A value's last use, doubled, written as the value doubled in place: `v = v * 2; ... (v & 0xFFE)`.

m2c spells a packed field read as `(w * 2) & 0xFFE` (or `(w << 1) & mask`) wherever the field is used. When that is the
last mention of `w` in its block, KMC GCC 2.7.2's local allocator ties the doubled value to the register `w` dies in
(a result takes the register of an input that dies in the insn), and the target's `sll $v1,$v1,1; andi $v0,$v1,0xffe`
has the doubling in `w`'s own register, then the mask in the next one. Spelled in place the shift's result is `w`'s
pseudo (a global one, set twice) and the mask result a fresh temporary; spelled inline the shift result is a temporary
of its own. On a 150-instruction packed-vector interpolation that turned 20 into 10 (after `call_arg_register_locals`;
alone it was 65 -> 65).

Rewrites `(V * 2)` / `(V << 1)`, where `V` is a local assigned earlier in the same block and not mentioned again in it,
into `V = V * 2;` before the statement and `V` in it. One child per site, at most four. It declines when `V` is a
parameter, volatile, or mentioned after the statement in the block (the loop's next pass reads a fresh `V` only when
the block sets it first, which is checked)."""
import re

from .integer_repair_support import edit, view

FAMILY = 'last_use_double_in_place'
FAMILIES = (FAMILY,)
LIMIT = 4

_DOUBLE = re.compile(r'\(\s*([A-Za-z_]\w*)\s*(?:\*\s*2|<<\s*1)\s*\)')
_STATEMENT = re.compile(r'(?m)^([ \t]*)([^;{}\n][^;{}]*;)')


def _python_block(clean, pos, lo, hi):
    depth, i = 0, pos
    while i > lo:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                break
            depth -= 1
    start, depth = i, 0
    for j in range(pos, hi):
        if clean[j] == '{':
            depth += 1
        elif clean[j] == '}':
            if depth == 0:
                return start, j
            depth -= 1
    return None


_block = _python_block
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block(clean, pos, lo, hi):
        found = _scan.enclosing_open(clean, pos, lo, -1)
        end = _scan.enclosing_end(clean, pos, hi, None)
        if found is NotImplemented or end is NotImplemented:
            return _python_block(clean, pos, lo, hi)
        start = pos if pos <= lo else (lo if found < 0 else found)
        return None if end is None else (start, end)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean):
        return []
    out = []
    for statement in _STATEMENT.finditer(clean, lo, hi):
        found = list(_DOUBLE.finditer(statement.group(2)))
        if len(found) != 1:
            continue
        var = found[0].group(1)
        if not re.search(rf'(?m)^[ \t]*(?:s32|u32|int|long|u16|s16|u8|s8)\s+{var}\s*;', clean[lo:hi]):
            continue
        block = _block(clean, statement.start(), lo, hi)
        if not block:
            continue
        before, after = clean[block[0]:statement.start()], clean[statement.end():block[1]]
        if re.search(rf'\b{var}\b', after) or not re.search(rf'(?m)^\s*{var}\s*=[^=]', before):
            continue
        if re.search(rf'\b{var}\b', statement.group(2).replace(found[0].group(0), '')):
            continue
        at = statement.start(2) + found[0].start()
        text = statement.group(1) + f'{var} = {var} * 2;\n'
        out.append((FAMILY, edit(source, [(statement.start(), statement.start(), text),
                                          (at, at + len(found[0].group(0)), f'({var})')])))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
