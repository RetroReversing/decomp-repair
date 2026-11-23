"""A parameter read through a local that the function reuses later, and the parameter next to it overwritten.

m2c names the value a function computes and keeps in one saved register `temp_s0` and writes the parameter itself in
the first statements (`arg1 & 0xFF`, `arg1 & 0xFFFF`), then assigns the local a new value (`temp_s0 = temp_s1 * 0x10;`).
In KMC GCC 2.7.2 the target had the local initialised from the parameter at the top of the body and read in those first
statements: the parameter's entry copy (`move $s5, $a1`) is followed by the local's own (`move $s0, $s5`), the local's
register is reused for the new value, and the parameter is still read once more, late (`ori $a0, $s5, 0x7000`). With
the plain parameter the local never gets a register of its own, the allocator ranks the saved registers differently
(`local-alloc.c`/`global.c`: priority from refs and live length) and every saved register after it moves. 220 -> 155 in a
94-instruction object-action function, before the other edit below.

`reused_local_entry_copy`: `L = P;` after the declarations, and `P` read as `L` in the statements before the first
assignment of `L` (straight-line statements only: no branch, loop, label or `goto` among them, and `L` is not read
there). The parameter stays as it is in the later statements.

`entry_parameter_pair` is that copy together with `entry_parameter_clobber` for another parameter (`Q = Q_in;
Q_in = 0;` right after it): the same function needed both, 155 -> 80 on the pair where neither alone moved the
second scheduler's order of the prologue (`move $s3, $a2` after `andi $a1, $s0, 0xff`, which the plain parameter's entry
copy never allows: the scheduler leaves the leading hardware-register copies in place and orders the rest by position).
The pair is offered as one child because a one-step search only sees the first edit.
"""
import re

from .entry_parameter_copy_repairs import LIMIT, TYPE, _after_declarations, _parameters
from .integer_repair_support import IDENT, _address_taken, edit, view

FAMILY = 'reused_local_entry_copy'
PAIR = 'entry_parameter_pair'
FAMILIES = (FAMILY, PAIR)
SCALARS = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'long', 'M2C_UNK', 'M2C_UNK32'}
BLOCKS = re.compile(r'\b(?:if|else|for|while|switch|case|default|return|goto|break|continue|asm)\b|[{}]|^\s*\w+\s*:(?!:)', re.M)
WRAPPER = re.compile(r'\bdo\s*{|}\s*while\s*\(\s*0\s*\)\s*;?')


def _declared_locals(clean, start, stop):
    """{name: type} of the plain scalar locals declared in the leading declarations."""
    found = {}
    for match in re.finditer(rf'({TYPE})\s+({IDENT})\s*;', clean[start:stop]):
        kind = re.sub(r'\s+', ' ', match[1]).strip()
        if kind in SCALARS:
            found[match[2]] = kind
    return found


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean, body = part.clean, part.body
    end = clean.rfind('}', 0, part.end)
    top = _after_declarations(clean, part.opening + 1, end)
    parameters = _parameters(part)
    locals_ = _declared_locals(clean, part.opening + 1, top)
    result = []
    for where, param, kind in parameters:
        if kind not in SCALARS or _address_taken(body, param) or re.search(rf'\b{param}_in\b', clean):
            continue
        for local, local_kind in locals_.items():
            if local_kind != kind or local == param:
                continue
            assignment = re.search(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', clean[top:end])
            if not assignment:
                continue
            stop = top + assignment.start()
            span = WRAPPER.sub(' ', clean[top:stop])
            if BLOCKS.search(span) or re.search(rf'(?<![\w.>]){re.escape(local)}\b', span):
                continue
            reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(param)}\b', clean[top:stop])]
            later = re.search(rf'(?<![\w.>]){re.escape(param)}\b', clean[stop:end])
            if not reads or not later:
                continue
            edits = [(top + m.start(), top + m.end(), local) for m in reads]
            edits.append((top, top, f'\n    {local} = {param};'))
            result.append((FAMILY, edit(source, edits)))
            for where_q, other, other_kind in parameters:
                if other == param or _address_taken(body, other) or re.search(rf'\b{other}_in\b', clean):
                    continue
                if len(re.findall(rf'(?<![\w.>]){re.escape(other)}\b', body)) < 2:
                    continue
                declaration = f'\n    {other_kind} {other};'
                copy = f'\n    {local} = {param};\n    {other} = {other}_in;\n    {other}_in = 0;'
                pair = [e for e in edits if e[0] != e[1]] + [(where_q, where_q + len(other), f'{other}_in')]
                if top == part.opening + 1:
                    pair.append((top, top, declaration + copy))
                else:
                    pair += [(part.opening + 1, part.opening + 1, declaration), (top, top, copy)]
                result.append((PAIR, edit(source, pair)))
    return result[:2 * LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
