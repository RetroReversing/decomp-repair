"""A byte value that GCC 2.7.2's cse folds away, kept in a register of its own and given the loop weight to win a saved one.

Found by matching a KMC N64 list-walk function (`gcc-2.7.2-kmc -O2 -G0`, 160 -> 0) that the permuter stalled on: after

    idx = (s8) p[0xF];  ...  p[0xF] = (u8) (((u8) idx) + table[idx * 8 + K]);  ...  (*q)[0xF] = idx;

the target keeps the index in two registers (`move $v1,$a1` for the sum, `move $s3,$s0` for the late store) where
the compiler wrote one. Why (cc1 `-dr -dj`: the `(u8) idx` QI copy is the one the late store reuses, and combine
substitutes it into the sum): the sum reads a byte copy of `idx`, so the store's copy shares its pseudo, and the saved
register goes to the table pointer, whose priority (refs * log2 refs / live length) is just above the copy's.
Three source edits, each no better alone, fix it together:

1. the sum re-reads the byte it was loaded from (`p[0xF]`, which cse turns into the load's own register) instead of
   casting `idx`, so the sum no longer owns the copy;
2. the late store's value is a `u8` local copied from `idx` just before the sum (`idx_bc = idx;`), the copy that now
   lives to the store and takes the saved register;
3. the store goes through a fresh pointer local inside two `do { } while (0)` wrappers: each wrapper adds one to the
   weighted references (flow.c counts a reference by loop depth) of the pointer, and of the value stored, so the copy's
   priority passes the table pointer's (0.387 against 0.333), while the wrapped statement names no other variable that
   would climb with it (wrapping `(*(arg0+0x68))[0xF] = idx` itself lifted `arg0` above the value kept in `$s0`).

Alone: step 3 160 -> 130, steps 1+2 without 3 worse; together 160 -> 33 (a frame size and an operand order left).
A fourth rewrite, `base[(i * 8) + K]` as `(base + (i<<3))[K]`, puts the base register second in the `addu`
(the target's), 15 -> 10 -> 0 with a fresh pointer local declared last. Hypothesis (the pass was read in the dumps, not
in a compiler source line): cse's copy propagation and combine's single-use substitution.

The rewrites are text edits on the function's source; the judge decides.
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'byte_copy_split_weight'
REREAD = 'byte_sum_reread_copy'
WEIGHT = 'store_pointer_weight'
SHIFT = 'shifted_index_base'
FAMILIES = (FAMILY, REREAD, WEIGHT, SHIFT)
LIMIT = 12
COPY = '_bc'
POINTER = 'pp_bw'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
DECLARATION = re.compile(r'[ \t]*(?:(?:register|volatile|const|unsigned|signed|struct|union)\s+)*[A-Za-z_]\w*[\s*]+'
                         r'\**\s*[A-Za-z_]\w*(?:\s*\[\s*\w+\s*\])*(?:\s*=[^;{}]+)?;[ \t]*(?:\n|$)')
# `p[K] = (u8) (((u8) v) + rest);` as m2c writes a byte that grows by a table byte
SUM = re.compile(rf'(?P<ptr>{IDENT})\s*\[\s*(?P<k>{NUMBER})\s*\]\s*=\s*\(u8\)\s*\(\s*\(\s*\(u8\)\s*(?P<v>{IDENT})\s*\)'
                 rf'(?P<rest>\s*\+[^;]*)\)\s*;')
SHIFTED = re.compile(rf'(?<![\w\]\)])(?P<base>{IDENT})\s*\[\s*\(\s*(?P<idx>{IDENT})\s*\*\s*(?P<mul>[248]|16)\s*\)'
                     rf'\s*\+\s*(?P<k>{NUMBER})\s*\]')
BITS = {'2': 1, '4': 2, '8': 3, '16': 4}


def _declared_end(clean, part):
    """The offset just past the function's last leading local declaration (where a new local goes)."""
    at = clean.find('\n', part.opening) + 1
    last = None
    while at and at < part.end:
        hit = DECLARATION.match(clean, at)
        if not hit:
            if clean[at:at + 1] in ('\n', ' ', '\t') and not clean[at:clean.find('\n', at)].strip():
                at = clean.find('\n', at) + 1
                continue
            break
        last = hit.end() if clean[hit.end() - 1:hit.end()] == '\n' else hit.end() + 1
        at = hit.end()
    return last


def _late_stores(clean, part, var, after):
    """`(*(X))[K] = var;` statements after `after`: (start, end, X text, K)."""
    found = []
    for hit in re.finditer(r'\(\s*\*\s*\(', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        if start < after:
            continue
        inner = start + hit.end() - hit.start() - 1
        stop = close(clean, inner, '(', ')')
        if not stop:
            continue
        tail = re.match(rf'\s*\)\s*\[\s*({NUMBER})\s*\]\s*=\s*{re.escape(var)}\s*;', clean[stop:])
        if tail:
            found.append((start, stop + tail.end(), (inner, stop), tail[1]))
    return found


def _loaded_from(clean, part, before, var, ptr, k):
    """Whether `var` was assigned from the byte `ptr[k]` (signed or not) before `before`."""
    text = clean[part.opening:before]
    return re.search(rf'\b{var}\s*=\s*(?:\(\s*[su](?:8|16|32)\s*\)\s*)?{re.escape(ptr)}\s*\[\s*{re.escape(k)}\s*\]\s*;', text) is not None


def _fresh(clean, name):
    return name not in clean


def _indent(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return re.match(r'[ \t]*', line)[0]


def _weight_edits(source, store, value, ladder):
    start, end, (inner, stop), k = store
    pointer = source[inner:stop]
    wrapped = 'do { ' * ladder + f'{POINTER}[{k}] = {value};' + ' } while (0);' * ladder
    text = f'{POINTER} = *{pointer}; {wrapped}'
    return [(start, end, text)]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    where = _declared_end(clean, part)
    if where is None or not _fresh(clean, POINTER) or not _fresh(clean, COPY):
        return []
    result = []

    def declare(edits, copy_type=None, copy_name=None, pointer=False):
        if copy_name:
            edits.append((where, where, f'  {copy_type} {copy_name};\n'))
        if pointer:
            edits.append((where, where, f'  u8 *{POINTER};\n'))
        return edits

    for hit in SUM.finditer(clean, part.opening, part.end):
        var, ptr, k = hit['v'], hit['ptr'], hit['k']
        if not _loaded_from(clean, part, hit.start(), var, ptr, k):
            continue
        copy = var + COPY
        if copy in clean:
            continue
        stores = _late_stores(clean, part, var, hit.end())
        if len(stores) != 1:
            continue
        indent = _indent(source, hit.start())
        reread = f'{ptr}[{k}] = (u8) ({ptr}[{k}]{hit["rest"]});'
        sum_edit = (hit.start(), hit.end(), f'{copy} = {var};\n{indent}{reread}')
        late = stores[0]
        # steps 1+2 alone: the late store reads the copy
        plain = [sum_edit, (late[0], late[1], f'{source[late[0]:late[2][1]]})[{late[3]}] = {copy};')]
        result.append((REREAD, edit(source, declare(plain, 'u8', copy))))
        for ladder in (2, 3):
            weighted = [sum_edit] + _weight_edits(source, late, copy, ladder)
            result.append((FAMILY, edit(source, declare(weighted, 'u8', copy, True))))
        if len(result) >= LIMIT:
            break
    result.extend(_weight_only(source, clean, part, where))
    result.extend(_shifted(source, clean, part))
    combined = []
    for family, text in list(result):
        if family == FAMILY:
            for revised in variants_shift(text, name):
                combined.append((FAMILY, revised))
    return (result + combined)[:LIMIT * 2]


def _weight_only(source, clean, part, where):
    """Step 3 alone: `(*(X))[K] = local;` through a fresh pointer inside two wrappers."""
    result = []
    for hit in re.finditer(r'\(\s*\*\s*\(', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        inner = start + hit.end() - hit.start() - 1
        stop = close(clean, inner, '(', ')')
        if not stop:
            continue
        tail = re.match(rf'\s*\)\s*\[\s*({NUMBER})\s*\]\s*=\s*({IDENT})\s*;', clean[stop:])
        if not tail or tail[2] in ('0', 'NULL'):
            continue
        if re.search(rf'{POINTER}', clean):
            return []
        store = (start, stop + tail.end(), (inner, stop), tail[1])
        edits = _weight_edits(source, store, tail[2], 2) + [(where, where, f'  u8 *{POINTER};\n')]
        result.append((WEIGHT, edit(source, edits)))
        if len(result) >= 4:
            break
    return result


def _shifted(source, clean, part):
    result = []
    for hit in SHIFTED.finditer(clean, part.opening, part.end):
        text = f'({hit["base"]} + ({hit["idx"]}<<{BITS[hit["mul"]]}))[{hit["k"]}]'
        result.append((SHIFT, edit(source, [(hit.start(), hit.end(), text)])))
        if len(result) >= 4:
            break
    return result


def variants_shift(source, name):
    """The shifted-base form on top of another child (the combination that closed the function)."""
    part = view(source, name)
    if not part:
        return []
    return [revised for _, revised in itertools.islice(_shifted(source, part.clean, part), 2)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
