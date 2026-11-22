"""A default value assigned before a guarded lookup, written as the `else` arm the guard's skip jumps into.

    head = -1;                              if (id == -1) goto no_head;
    if (id != -1) {                         lookup ...;
        lookup ...;                  ->     if (found) { head = found->head; }
        if (found) head = found->head;      else { no_head: head = -1; }
    }

Both ways of getting no head (the guard's skip and a lookup that found nothing) then share one block, as in a
KMC GCC 2.7.2 voice-list function: the skip is a `beql` whose delay slot holds the block's first instruction, the
not-found arm branches to the same block, and the lookup's found-block lands out of line. With the default assigned
up front the lookup's blocks and the final move were laid out differently (1330 -> 905, part of a 0 match). Offered when
the guarded block ends in one conditional assignment of the same variable and nothing else mentions it; the judge
decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'default_arm_goto'
FAMILIES = (FAMILY,)
_DEFAULT = re.compile(rf'(?P<var>{IDENT})\s*=(?!=)\s*(?P<k>[-\w.]+)\s*;')
_TEST = re.compile(r'\s*if\s*\(\s*(?P<a>[\w.\->]+)\s*(?P<op>!=|==)\s*(?P<b>[\w\-]+)\s*\)\s*\{')
_LAST = re.compile(rf'(?P<head>if\s*\((?P<t>[^;{{}}]+)\)\s*)(?:\{{\s*(?P<var>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+);\s*\}}|(?P<var2>{IDENT})\s*=(?!=)\s*(?P<e2>[^;{{}}]+);)\s*$')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean, result = part.clean, []
    for hit in _DEFAULT.finditer(clean, part.opening + 1, part.end):
        if clean[:hit.start()].rstrip()[-1:] not in ';{}' or hit['var'] in {'return', 'else'}:
            continue
        guard = _TEST.match(clean, hit.end())
        if not guard:
            continue
        opening = guard.end() - 1
        stop = close(clean, opening, '{', '}')
        if not stop:
            continue
        inner = clean[opening + 1:stop - 1]
        last = None
        for m in reversed(list(re.finditer(r'(?:^|(?<=[;}]))\s*(if\s*\()', inner))):
            tail = _LAST.match(inner, m.start(1))
            if tail:
                last = (m.start(1), tail)
                break
        if not last:
            continue
        at, tail = last
        variable = tail['var'] or tail['var2']
        value = (tail['e'] or tail['e2']).strip()
        if variable != hit['var'] or re.search(rf'\b{re.escape(variable)}\b', inner[:at]):
            continue
        label = f'__repair_default_{variable}'
        if label in source:
            continue
        skipped = '==' if guard['op'] == '!=' else '!='
        indent = re.search(r'[ \t]*$', clean[:hit.start()])[0]
        base = opening + 1
        body = source[base:base + at]
        replacement = (f'if ({guard["a"]} {skipped} {guard["b"]}) {{\n{indent}    goto {label};\n{indent}}}\n{indent}{{{body.rstrip()}\n{indent}}}\n'
                       f'{indent}if ({tail["t"].strip()}) {{\n{indent}    {variable} = {value};\n{indent}}} else {{\n{label}:\n{indent}    {variable} = {hit["k"]};\n{indent}}}')
        result.append((FAMILY, edit(source, [(hit.start(), stop, replacement)])))
    return list(dict.fromkeys(result))[:6]
