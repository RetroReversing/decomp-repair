"""An array index the function has just stored into a field, read back from the field instead of repeated.

An N64 function (SN GCC 2.8.1, `-G8 -mips3 -O2`) set a record's field to a constant and then read a table at that same
number three times:

    D_800B3960->x70 = 1;
    D_800B3960->xB4 = D_8014A928[1] / 2;
    D_800B3960->xB0 = D_8014A928[D_800B3960->x70] / 2;
    D_800B3960->xAC = D_8014A928[D_800B3960->x70] / 2;

m2c wrote every read with the constant (`*((1 * 4) + &D_8014A928)`), which is the number the game's code could only have
had through the field: the target reloads the field (`lw $v0, 0x70($s0)`, then `sll`, `addu`, `lw`) where the constant
index keeps a register of its own for the folded address. Written `D[P->f]` the three reads are loads from the stored
field (the stores to the record's other fields in between are not known to leave it alone), and the constant no longer
holds a register through the function: 440 rows off to exact on that one change. The same holds for a local that holds
the value that was stored (`t = e; P->f = t; ... D[t]`).

A proposal takes a store of an integer constant or of a local, `P->f = K;` or `M2C_FIELD(P, T *, off) = K;`, and a later
statement in the same block that subscripts a table with that same number (`X[K]`, or m2c's `(K * 4)` byte offset; `X[t]`
for a local) and calls nothing. Every statement between them must be a plain statement that only stores to a local other
than the value's own or to a different field of the same base `P` (offsets that do not overlap; two names for the field
of an arrow), reads nothing it could change, calls nothing and does not write `P`. Children, per store: the later
statements one at a time (the statement's subscripts all read the field), and all of them together; at most MAX_CHILDREN.
The index keeps its value, so the program is the same, and a statement that stores the field itself is left as it was.
This module reads text only and never compiles or judges."""
import re

from .hand_found_support import (
    IDENT,
    NUMBER,
    blocks,
    calls_in,
    fields,
    local_type,
    number,
    simple,
    store_target,
    stmts,
)
from .integer_repair_support import edit, view

FAMILY = 'stored_field_readback_index'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 8
WINDOW = 12  # statements after the store that may hold the later read
LARGEST = 0xFFFF
_ARROW = re.compile(rf'(?P<base>{IDENT})\s*->\s*(?P<name>{IDENT})')
_INTEGER = re.compile(r'(?:[su](?:8|16|32)|(?:unsigned|signed)\s+(?:char|short|int)|char|short|int|unsigned)$')


def _lvalue(clean, start, end):
    """(base, key) of a store target that is one field of a plain-name base: `P->f` is (P, 'f'), an `M2C_FIELD(P, T *, off)`
    is (P, (off, size)); None for anything else."""
    text = clean[start:end].strip()
    arrow = _ARROW.fullmatch(text)
    if arrow:
        return arrow['base'], arrow['name']
    found = fields(clean, start, end)
    if len(found) == 1 and clean[start:end].strip() == found[0].text(clean) and found[0].size:
        field = found[0]
        return field.base, (field.offset, field.size, field.kind)
    return None


def _apart(one, other):
    """True when the two keys of one base are known not to be the same memory."""
    if isinstance(one, str) and isinstance(other, str):
        return one != other
    if isinstance(one, tuple) and isinstance(other, tuple):
        return one[0] + one[1] <= other[0] or other[0] + other[1] <= one[0]
    return False


def _store(clean, span):
    """(start, end, value text) of the target of the one-line store at `span` (the whole statement for a plain
    expression: value None, target None)."""
    text = clean[span[0]:span[1]]
    hit = store_target(text) if simple(text) else None
    if not hit:
        return None
    at = span[0] + text.index(hit[0])
    return at, at + len(hit[0]), hit[1].strip()


def _harmless(part, span, base, key, value):
    """True when the statement at `span` calls nothing and writes only a local (not `value`, not the base) or a different
    field of the same base: the stored field and the value are as they were after it."""
    clean = part.clean
    text = clean[span[0]:span[1]]
    if not simple(text) or calls_in(text) or re.search(r'\+\+|--', text):
        return False
    hit = _store(clean, span)
    if hit is None:
        return not re.search(r'(?<![=!<>])=(?!=)', text)  # no assignment at all
    lvalue = clean[hit[0]:hit[1]].strip()
    if re.fullmatch(IDENT, lvalue):
        return lvalue not in {base, value}
    target = _lvalue(clean, hit[0], hit[1])
    return bool(target) and target[0] == base and _apart(target[1], key)


def _uses(clean, span, value, number_value):
    """[(start, end)] of the subscript indices in the statement that spell the stored number: `[K]` (or `[t]`), and the
    `(K * 4)` byte offset m2c writes."""
    text = clean[span[0]:span[1]]
    found = []
    if number_value is None:
        found += [(span[0] + m.start(1), span[0] + m.end(1)) for m in re.finditer(
            rf'\[\s*({re.escape(value)})\s*\]', text)]
    else:
        for m in re.finditer(rf'\[\s*({NUMBER})\s*\]', text):
            if number(m[1]) == number_value:
                found.append((span[0] + m.start(1), span[0] + m.end(1)))
        for m in re.finditer(rf'\(\s*({NUMBER})\s*\*\s*{NUMBER}\s*\)', text):
            if number(m[1]) == number_value:
                found.append((span[0] + m.start(1), span[0] + m.end(1)))
    return found


def variants(source, name):
    """Proposals: a table read at the number just stored into a field (or held by a local), written with the field."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        for k, span in enumerate(spans):
            hit = _store(clean, span)
            if not hit or calls_in(clean[span[0]:span[1]]):
                continue
            target = _lvalue(clean, hit[0], hit[1])
            value = hit[2]
            if not target or isinstance(target[1], tuple) and not _INTEGER.match(
                    re.sub(r'\s*\*$', '', target[1][2]).strip()):
                continue
            constant = number(value) if re.fullmatch(NUMBER, value) else None
            if constant is None and not (re.fullmatch(IDENT, value) and local_type(part, value)
                                         and _INTEGER.match(local_type(part, value))):
                continue
            if constant is not None and not 0 <= constant <= LARGEST:
                continue
            base, key = target
            lvalue_text = clean[hit[0]:hit[1]].strip()
            found = []
            for later in spans[k + 1:k + 1 + WINDOW]:
                uses = _uses(clean, later, value, constant)
                if uses and _harmless(part, later, base, key, value if constant is None else ''):
                    found.append((later, uses))
                if not _harmless(part, later, base, key, value if constant is None else ''):
                    break
            for later, uses in found[:MAX_CHILDREN]:
                out.append((FAMILY, edit(source, [(a, b, lvalue_text) for a, b in uses])))
            if len(found) > 1:
                out.append((FAMILY, edit(source, [(a, b, lvalue_text) for _, uses in found for a, b in uses])))
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
