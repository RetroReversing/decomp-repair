"""Stores an old field-load hoist turned into assignments to its own local, written back.

`field_load_hoist` once hoisted a field that was only ever *stored*: `__repair_hoisted = M2C_FIELD(p, void **, 0x48);`
before the test and `__repair_hoisted = v;` where the code had `M2C_FIELD(p, void **, 0x48) = v;`. The store is gone,
yet the saved best kept it because the instructions around it still fitted (a 131-instruction spawn-point routine, SN
GCC 2.8.1: 1003 until the store came back, 903 with it alone). The module no longer does that, but saved sources made
before the fix carry it. The tell is a hoisted local that is assigned and never read.

lost_store_restore
    For a `__repair_hoisted*` local that nothing reads, whose first assignment is an `M2C_FIELD(...)` read: every
    later `local = value;` becomes `M2C_FIELD(...) = value;`, and the dead read and the declaration go.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'lost_store_restore'
FAMILIES = (FAMILY,)

LOCAL = re.compile(r'\b__repair_hoisted\w*')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for local in sorted(set(LOCAL.findall(clean[opening:end]))):
        declaration = None
        assigns = []
        read = False
        for use in re.finditer(r'\b' + local + r'\b', clean[opening:end]):
            at = opening + use.start()
            line = clean.rfind('\n', 0, at) + 1
            before, after = clean[line:at], clean[at + len(local):end]
            if re.fullmatch(r'[ \t]*(?:[A-Za-z_]\w*[ \t]+)+[ \t*]*', before) and re.match(r'[ \t]*;', after):
                declaration = line
                continue
            assigned = re.match(r'[ \t]*=(?!=)[ \t]*', after)
            semi = after.find(';')
            if assigned and not before.strip() and semi >= 0:
                value = source[at + len(local) + assigned.end():at + len(local) + semi]
                assigns.append((line, at, at + len(local) + semi + 1, value))
                continue
            read = True
            break
        if read or declaration is None or len(assigns) < 2 or not re.match(r'M2C_FIELD\s*\(', assigns[0][3]):
            continue
        field = assigns[0][3].strip()
        text = source
        # From the end, so earlier offsets stay true.
        edits = [(at, at + len(local), field) for _, at, _, _ in assigns[1:]]
        for line, _, stop, _ in (assigns[0],):
            edits.append((line, stop + (source[stop:stop + 1] == '\n'), ''))
        newline = source.find('\n', declaration)
        edits.append((declaration, newline + 1, ''))
        for first, last, new in sorted(edits, reverse=True):
            text = text[:first] + new + text[last:]
        result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
