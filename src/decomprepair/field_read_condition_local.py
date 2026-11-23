"""A field read in an `if` condition kept in a local that the body of that `if` reuses.

m2c draws the same object field wherever the game read it: `if (flag == 0 && ((Field_s16 *) (((char *) obj) + 0x7A))->v == 1)`
and, a few hundred instructions later and inside the `if`'s body, `if (level == ((Field_s16 *) (((char *) obj) + 0x7A))->v)`. GCC 2.7.2
re-reads a halfword after any call or store it cannot see through, so the draft has a second `lh`; the target had one
(`lh $s0, 0x7a($s2)` before the first compare, and the compare in the body against `$s0`). Written with a local
assigned inside the first condition and read in the body, a player-update routine of 1137 instructions went 4316 -> 4201
(KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`); one step of a chain that ended at 60 rows from a match. The reason
(a pseudo that lives across the body, allocated to a saved register) is the usual cost of a local, here a hypothesis.

field_read_condition_local
    For a field read `((Field_T *) (((char *) base) + off))->v` that occurs at least twice, where the first occurrence is
    an operand of a comparison in an `if (...)` condition and at least one other occurrence is inside that `if`'s braced
    body (reads after the `if` are left as reads), and no assignment to that field (same type, base and offset) appears anywhere in the function: one child declares a
    local `base_field_off` of the field's type, writes the first read as `(local = read)` and every read in the body as the
    local. At most 4 children, the earliest `if` first."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'field_read_condition_local'
FAMILIES = (FAMILY,)
LIMIT = 4
_FIELD = re.compile(r'\(\(Field_(?P<type>[A-Za-z_]\w*)\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<base>[A-Za-z_]\w*)\)\s*\+\s*'
                    r'(?P<offset>0[xX][0-9A-Fa-f]+|\d+)\)\)\s*->\s*v\b')
_IF = re.compile(r'\bif\s*\(')


def _key(hit):
    return hit['type'], hit['base'], int(hit['offset'], 0)


def _is_comparison_operand(clean, start, end, left, right):
    """True when the read at [start, end) is directly an operand of ==, !=, <, >, <= or >= inside the condition."""
    before = clean[left:start].rstrip()
    after = clean[end:right].lstrip()
    return bool(re.search(r'(?:==|!=|<=|>=|[<>])$', before) or re.match(r'(?:==|!=|<=|>=|[<>])(?!=)', after))


def _written(clean, begin, limit, key):
    for hit in _FIELD.finditer(clean, begin, limit):
        if _key(hit) == key and re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', clean[hit.end():hit.end() + 6]):
            return True
        if _key(hit) == key and re.search(r'(?:\+\+|--)\s*$', clean[max(begin, hit.start() - 4):hit.start()]):
            return True
    return False


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    reads = {}
    for hit in _FIELD.finditer(clean, opening, span[1]):
        reads.setdefault(_key(hit), []).append(hit)
    out = []
    for key, hits in reads.items():
        if len(hits) < 2 or _written(clean, opening, span[1], key):
            continue
        first = hits[0]
        found = None
        for branch in _IF.finditer(clean, opening, first.start()):
            stop = close(clean, branch.end() - 1, '(', ')')
            if stop and branch.end() <= first.start() < stop:
                found = (branch, stop)  # the innermost if whose condition holds the read
        if not found:
            continue
        branch, stop = found
        if not _is_comparison_operand(clean, first.start(), first.end(), branch.end(), stop - 1):
            continue
        body = re.match(r'\s*\{', clean[stop:span[1]])
        if not body:
            continue
        body_open = stop + body.end() - 1
        body_stop = close(clean, body_open, '{', '}')
        inside = [other for other in hits[1:] if body_open < other.start() and other.end() < body_stop]
        if not body_stop or not inside:
            continue
        local = f'{key[1]}_field_{key[2]:X}'
        if re.search(rf'\b{local}\b', clean):
            continue
        edits = [(first.start(), first.end(), f'({local} = {source[first.start():first.end()]})')]
        edits += [(other.start(), other.end(), local) for other in inside]
        text = source
        for start, end, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[end:]
        indent = re.match(r'[ \t]*', source[source.find('\n', opening) + 1:])[0] or '  '
        at = source.find('\n', opening) + 1
        out.append(text[:at] + f'{indent}{key[0]} {local};\n' + text[at:])
    return [(FAMILY, text) for text in out][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
