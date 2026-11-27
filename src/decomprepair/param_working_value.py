"""The narrow parameter is the working value, and a constant minus a value staged in two statements (KMC GCC 2.7.2 -O1).

An N64 game's signed number printer takes a halfword value. m2c, and a first hand version, give the digits loop a local
of its own: `w = a; if (a < 0) { w = -a; ... }` (or `w = (s16) a; if (w < 0) r = -w; else r = w;`), and every later
statement works on that local. The target instead keeps the raw argument word copied at entry and negates into it: the
parameter itself is what the loop works on, and the local only holds the value as it arrived (`s32 w = a;
if (a < 0) a = -w;`).

* `param_works`: swaps those roles. The negation is assigned to the parameter and reads the local, and every use of the
  working local after the `if` names the parameter. Offered only when the parameter is a narrow integer that the body
  mentions nowhere else, so nothing else can see the new value.
* `constant_minus_split`: `v = 5 - n;` written `v = 5; v -= n;`. GCC 2.7.2 -O1 then subtracts the byte parameter
  without extending it first (a hypothesis about combine; the exact judge showed the instruction).
* `param_works_split`: both, since each alone left a difference.

Candidate rewrites, not equivalence proofs: the compiler and the exact judge decide.
"""
import re

from .integer_repair_support import edit, view

FAMILY_PARAM = 'param_works'
FAMILY_SPLIT = 'constant_minus_split'
FAMILY_BOTH = 'param_works_split'
FAMILIES = (FAMILY_PARAM, FAMILY_SPLIT, FAMILY_BOTH)
_NARROW = r'(?:s16|u16|s8|u8|short|char|(?:un)?signed\s+(?:short|char))'
_CAST = r'(?:\(\s*s(?:16|8)\s*\)\s*)?'
_SPLIT = re.compile(r'(?m)^([ \t]*)(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*-\s*(\w+)\s*;')


def _narrow_parameters(clean, opening, name):
    found = list(re.finditer(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*$', clean[:opening]))
    if not found:
        return []
    return [m[1] for piece in found[-1][1].split(',')
            if (m := re.fullmatch(rf'\s*(?:const\s+)?{_NARROW}\s+(\w+)\s*', piece))]


def _renamed(text, old, new):
    """`old` as a plain identifier (not a member or a declaration) replaced by `new`."""
    return re.sub(rf'(?<![\w.>])\b{re.escape(old)}\b', new, text)


def _drop_declaration(head, local):
    return re.sub(rf'(?m)^[ \t]*(?:s32|u32|int|s16|u16)\s+{re.escape(local)}\s*;[ \t]*\n', '', head)


def _copy_form(body, param):
    """`w = p; if (p < 0) { w = -p; ...`: the (start, end, replacement) edits of the body."""
    p = re.escape(param)
    m = re.search(rf'\b(\w+)\s*=\s*{p}\s*;(\s*if\s*\(\s*{_CAST}{p}\s*<\s*0\s*\)\s*\{{\s*)\1\s*=\s*-\s*{_CAST}{p}\s*;', body)
    if not m or m[1] == param:
        return None
    work = m[1]
    rest = body[m.end():]
    if re.search(rf'\b{p}\b', body[:m.start()] + rest) or not re.search(rf'\b{re.escape(work)}\b', rest):
        return None
    head = f'{work} = {param};{m[2]}{param} = -{work};'
    return body[:m.start()] + head + _renamed(rest, work, param)


def _read_form(body, param):
    """`w = (s16) p; if (w < 0) { ..; r = -w; } else { ..; r = w; }`: the new body, `r` replaced by the parameter."""
    p = re.escape(param)
    m = re.search(rf'\b(\w+)\s*=\s*{_CAST}{p}\s*;(\s*if\s*\(\s*\1\s*<\s*0\s*\)\s*\{{[^{{}}]*?)\b(\w+)\s*=\s*-\s*\1\s*;'
                  rf'([^{{}}]*\}}\s*else\s*\{{[^{{}}]*?)\b\3\s*=\s*\1\s*;[ \t]*\n?', body)
    if not m or param in (m[1], m[3]):
        return None
    value, work = m[1], m[3]
    before, rest = body[:m.start()], body[m.end():]
    if re.search(rf'\b{p}\b', before + rest) or not re.search(rf'\b{re.escape(work)}\b', rest):
        return None
    head = f'{value} = {param};{m[2].replace(value + " < 0", "(s16) " + param + " < 0")}{param} = -{value};{m[4]}'
    return _drop_declaration(before, work) + head + _renamed(rest, work, param)


def param_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, base = part.clean, part.opening + 1
    body = clean[base:part.end - 1]
    result = []
    for param in _narrow_parameters(clean, part.opening, name):
        for form in (_copy_form, _read_form):
            new = form(body, param)
            if new:
                # comments are blanked in `clean`, so the offsets match the source; the body is replaced whole
                result.append((FAMILY_PARAM, edit(source, [(base, part.end - 1, new)])))
    return result


def split_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    base = part.opening + 1
    result = []
    for m in _SPLIT.finditer(part.clean[base:part.end - 1]):
        indent, target, constant, value = m.groups()
        if target == value:
            continue
        text = f'{indent}{target} = {constant};\n{indent}{target} -= {value};'
        result.append((FAMILY_SPLIT, edit(source, [(base + m.start(), base + m.end(), text)])))
    return result


def variants(source, name):
    swapped = param_variants(source, name)
    split = split_variants(source, name)
    both = [(FAMILY_BOTH, child) for _, once in swapped for _, child in split_variants(once, name)]
    return both + swapped + split


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
