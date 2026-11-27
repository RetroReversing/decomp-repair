"""A pointer loaded, tested and otherwise rebuilt: the load in a local of its own, copied in the `else` arm.

`v = obj->head; if (v == NULL) { v = obj; while (v->prev != NULL) v = v->prev; }` loads straight into `v`'s register.
Where the target loads into a scratch register, branches on it and copies it into the saved one in the delay slot
(`lw $v0; bnez $v0; move $s0,$v0`), the source tested a local of the load's own and assigned `v` from it in the `else`:
`h = obj->head; if (h == NULL) { v = obj; ... } else { v = h; }`. cse keeps `h` and `v` apart because `v` is set in
both arms. On a 207-instruction homing projectile (SN GCC 2.8.1) this took the last rows, 210 -> 0.

A proposal takes `V = LOAD;` (a member read or dereference, no call) directly above `if (V == NULL) {...}` (or `!V`)
with no `else`, whose block assigns `V` before it reads it: the load goes to a new local of `V`'s pointer type and the
`if` gains `else { V = new; }`. One child per such site, at most 4."""
import re

from .integer_repair_support import edit, view

FAMILY = 'tested_load_else_copy'
FAMILIES = (FAMILY,)
LIMIT = 4

_ID = r'[A-Za-z_]\w*'
_SITE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<v>{_ID})[ \t]*=[ \t]*(?P<load>[^;\n(){{}}=]*(?:->|\*)[^;\n(){{}}=]*);[ \t]*\n'
    rf'[ \t]*if[ \t]*\([ \t]*(?:(?P=v)[ \t]*==[ \t]*(?:NULL|0)|!(?P=v))[ \t]*\)[ \t]*{{')


def _close(clean, at):
    depth = 0
    for position in range(at, len(clean)):
        depth += clean[position] == '{'
        depth -= clean[position] == '}'
        if depth == 0:
            return position
    return None


_python_close = _close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(clean, at):
        found = _scan.close_every(clean, at, '{', '}', False, None)
        return _python_close(clean, at) if found is NotImplemented else found


def variants(source, name):
    """One proposal for each tested load whose `NULL` arm rebuilds the variable."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _SITE.finditer(clean, part.opening + 1, part.end):
        v = hit['v']
        closing = _close(clean, hit.end() - 1)
        if closing is None or re.compile(r'\s*else\b').match(clean, closing + 1):
            continue
        inner = re.compile(rf'(?<![\w.>]){re.escape(v)}\b').search(clean, hit.end(), closing)
        assigned = inner and re.compile(rf'{re.escape(v)}\s*=(?!=)([^;]*);').match(clean, inner.start())
        if not assigned or re.search(rf'(?<![\w.>]){re.escape(v)}\b', assigned.group(1)):
            continue
        declared = re.compile(rf'(?m)^[ \t]*(?P<type>{_ID}(?:[ \t]+{_ID})*)[ \t]*\*[ \t]*{re.escape(v)}[ \t]*;[ \t]*$')
        declaration = declared.search(clean, part.opening + 1, part.end)
        if not declaration or declaration['type'].split()[0] in ('return', 'goto'):
            continue
        fresh, number = f'{v}_loaded', 0
        while re.search(rf'\b{fresh}\b', clean):
            number += 1
            fresh = f'{v}_loaded{number}'
        indent = hit['indent']
        load = source[hit.start('load'):hit.end('load')].strip()
        head = source[hit.start():hit.end()]
        head = f'{indent}{fresh} = {load};\n' + head[head.index('\n') + 1:]
        head = re.sub(rf'(?<![\w.>]){re.escape(v)}\b(?=\s*(?:==|\)))', fresh, head)
        out.append(edit(source, [
            (hit.start(), hit.end(), head),
            (closing + 1, closing + 1, f' else {{\n{indent}    {v} = {fresh};\n{indent}}}'),
            (declaration.end(), declaration.end(), f"\n    {declaration['type']} *{fresh};"),
        ]))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 99}  # the registry: no caller wiring (registry.py)
