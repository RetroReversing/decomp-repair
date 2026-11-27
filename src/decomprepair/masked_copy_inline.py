"""Word locals that only hold a narrow variable masked to its own width, written as the variable.

m2c shows every re-extension of a `u16` (or `u8`) variable as a local of its own:

    u16 var_a1;                                          u16 var_a1;
    s32 var_v0;                                          ...
    s32 var_v1;                                          loop:
    var_v0 = var_a1 & 0xFFFF;                    ->          if (t[var_a1].m1 == 2) ...
    loop:                                                    var_a1 = t[var_a1].m10;
        var_v1 = var_a1 & 0xFFFF;                            if (var_a1 != 0xFFFF) {
        if (t[var_v0].m1 == 2) ...                               if (var_a1 >= limit) {
        var_a1 = t[var_v1].m10;                                      goto loop;
        temp = var_a1 & 0xFFFF;
        if (temp != 0xFFFF) {
            var_v0 = var_a1 & 0xFFFF;
            if (temp >= limit) { goto loop; }

The compiler extends the variable itself where it is used as an index or compared, so the copies add registers the
game's code never had. A KMC GCC 2.7.2 `-O1` list walk of 142 instructions (`-G0 -mips3 -mgp32 -mfp32`) went
1860 -> 1420 with the copies written as the variable, and the goto loop then written as a `do`/`while` was exact.

A local is a copy when it is declared as a word, every assignment to it is `V = X & MASK;` for one `u8`/`u16` local or
parameter `X` of that width, neither is address-taken, and no read of `V` follows (in the text) an assignment to `X`
that no new copy came after. All the copies of one variable are written back together, as one child; a second child
writes back the copies of every variable. `masked_copy_inline`."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'masked_copy_inline'
FAMILIES = (FAMILY,)
MASKS = {'u8': r'(?:0[xX][fF]{2}|255)[uU]?', 'u16': r'(?:0[xX][fF]{4}|65535)[uU]?'}
WORD = r'(?:s32|u32|int|unsigned int|unsigned long|long)'


def _whole_lines(clean, start, end):
    """The whole line holding clean[start:end] when nothing else is on it."""
    a = clean.rfind('\n', 0, start) + 1
    b = clean.find('\n', end)
    b = len(clean) if b < 0 else b + 1
    return (a, b) if not (clean[a:start] + clean[end:b]).strip() else (start, end)


def _copy(source, clean, part, variable, kind, local):
    """The edits that write `local` as `variable`, or None when it is not a plain masked copy of it."""
    body = clean[part.opening:part.end]
    base = part.opening
    declared = re.search(rf'(?m)^[ \t]*{WORD}[ \t]+{local}[ \t]*;', body)
    # a unary `&`: one that no operand comes before
    if not declared or re.search(rf'(?:[(,=!{{}};?:<>|^~+\-*/]|&&|\breturn)\s*&\s*(?:{local}|{variable})\b', body):
        return None
    assigned = list(re.finditer(rf'(?<![\w.>]){local}\s*=\s*{variable}\s*&\s*{MASKS[kind]}\s*;', body))
    writes = re.findall(rf'(?<![\w.>]){local}\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{local}\b', body)
    if not assigned or len(writes) != len(assigned):
        return None
    events = [(m.start(), m.end(), 'copy') for m in assigned]
    events += [(m.start(), m.end(), 'changed') for m in re.finditer(
        rf'(?<![\w.>]){variable}\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{variable}\b', body)]
    inside = [(m.start(), m.end()) for m in assigned] + [(declared.start(), declared.end())]
    reads = [m for m in re.finditer(rf'(?<![\w.>]){local}\b', body)
             if not any(a <= m.start() < b for a, b in inside)]
    if not reads:
        return None
    for read in reads:
        before = [e for e in events if e[0] < read.start()]
        if not before:
            return None
        last = max(before)
        # `X = f(V);` reads the copy as part of the assignment that changes the variable
        if last[2] == 'changed' and ';' in body[last[1]:read.start()]:
            return None
    edits = [(base + a, base + b, '') for a, b in (_whole_lines(body, *span) for span in inside)]
    return edits + [(base + m.start(), base + m.end(), variable) for m in reads]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    start = clean.rfind('\n}', 0, part.opening) + 1
    scope = clean[start:part.end]
    narrow = {}
    for m in re.finditer(rf'(?<![\w.>])(u8|u16)[ \t]+({IDENT})[ \t]*(?=[;,)=])', scope):
        narrow[m[2]] = m[1]
    out, every = [], []
    for variable, kind in narrow.items():
        copies = re.findall(rf'(?<![\w.>])({IDENT})\s*=\s*{variable}\s*&\s*{MASKS[kind]}\s*;', clean[part.opening:part.end])
        edits = []
        for local in dict.fromkeys(copies):
            if local != variable:
                edits += _copy(source, clean, part, variable, kind, local) or []
        if edits:
            out.append((FAMILY, edit(source, edits)))
            every += edits
    if len(out) > 1:
        out.append((FAMILY, edit(source, every)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
