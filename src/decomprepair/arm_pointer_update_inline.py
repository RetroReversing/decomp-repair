"""A pointer set only to be updated through, written as the update on the place itself.

m2c names the address a read-modify-write goes through, and often the new value too, in every arm that does it:

    p = (i * 4) + table;
    v = *p + 0x1F40;        // or `*p = *p + 0x1F40;`, or `*p += 0x1F40;`
    *p = v;

The source was `table[i] += 0x1F40;`. The named pointer is one variable with every arm's references, so the compiler
colours it apart from the index it was built from; written on the place (`*(T *)(address) += k;`) each arm's address
takes the register the index was loaded into (SN GCC 2.8.1, three arms of an N64 score routine: 240 to 0; read from
the diff, the allocation not dumped). Every site of every such pointer is rewritten at once, since one site left
keeps the variable. Only pointers (and value locals) with no other use are touched, so the program is the same.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'arm_pointer_update_inline'
FAMILIES = (FAMILY,)

_NUMBER = r'(?:-?(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+f?)?)[uUlL]*)'
_K = rf'(?:{_NUMBER}|[A-Za-z_]\w*)'
_SET = re.compile(r'(?<=[;{}:])(?P<lead>\s*)(?P<p>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<e>[^;{}=]+);')
_IMPURE = re.compile(r'\+\+|--|\?')


def _uses(text, word):
    return [hit.start() for hit in re.finditer(rf'(?<![\w.])(?<!->){word}\b', text)]


def _update(clean, at, p):
    """(end, operator, operand, value local or None) for the update through `p` that starts at `at`."""
    place = rf'\*\s*{p}'
    patterns = (
        rf'\s*{place}\s*(?P<op>[-+|&^])=\s*(?P<k>{_K})\s*;',
        rf'\s*{place}\s*=\s*{place}\s*(?P<op>[-+|&^])\s*(?P<k>{_K})\s*;',
        rf'\s*(?P<v>[A-Za-z_]\w*)\s*=\s*{place}\s*(?P<op>[-+|&^])\s*(?P<k>{_K})\s*;\s*{place}\s*=\s*(?P=v)\s*;',
    )
    for pattern in patterns:
        hit = re.compile(pattern).match(clean, at)
        if hit and hit['k'] != p:
            value = hit.groupdict().get('v')
            if value is None or value not in (p, hit['k']):
                return hit.end(), hit['op'], hit['k'], value
    return None


def _local(body, value, kind):
    """`value`'s declaration line when it is a plain local of type `kind`, else None."""
    found = re.findall(rf'(?m)^[ \t]*({re.escape(kind)}\s+{value}\s*;)[ \t]*\n', body)
    return found[0] if len(found) == 1 else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    sites = {}
    for hit in _SET.finditer(clean, opening + 1, end):
        expression = source[hit.start('e'):hit.end('e')].strip()
        if _IMPURE.search(expression) or re.search(rf'\b{hit["p"]}\b', expression):
            continue
        found = _update(clean, hit.end(), hit['p'])
        if found:
            sites.setdefault(hit['p'], []).append((hit.start('p'), *found, expression))
    edits, dropped = [], []
    for p, rows in sites.items():
        declared = re.findall(rf'(?m)^[ \t]*((?:(?:const|volatile|signed|unsigned|struct|union)\s+)*[A-Za-z_]\w*)'
                              rf'\s*\*\s*{p}\s*;[ \t]*\n', body)
        if len(declared) != 1:
            continue
        inside = [(start, stop) for start, stop, *_ in rows]
        outside = [at for at in _uses(body, p) if not any(a <= at + opening < b for a, b in inside)]
        locals_ = {value: _local(body, value, declared[0]) for *_, value, _expression in rows if value}
        # a value local must be of the pointee's type (a narrower one would truncate) and have no other use
        if (len(outside) != 1  # the declaration only
                or any(declaration is None for declaration in locals_.values())
                or any(len([at for at in _uses(body, value) if not any(a <= at + opening < b for a, b in inside)]) != 1
                       or any(_uses(expression, value) for *_, expression in rows) for value in locals_)):
            continue
        for start, stop, op, k, value, expression in rows:
            if not (expression.startswith('(') and close(expression, 0) == len(expression)):
                expression = f'({expression})'
            edits.append((start, stop, f'*({declared[0]} *){expression} {op}= {k};'))
        dropped.append(rf'(?m)^[ \t]*{re.escape(declared[0])}\s*\*\s*{p}\s*;[ \t]*\n')
        dropped += [rf'(?m)^[ \t]*{re.escape(declaration)}[ \t]*\n' for declaration in locals_.values()]
    if not edits:
        return []
    text = source[opening:end]
    for start, stop, new in sorted(edits, reverse=True):
        text = text[:start - opening] + new + text[stop - opening:]
    for pattern in dropped:
        text = re.sub(pattern, '', text, count=1)
    return [(FAMILY, source[:opening] + text + source[end:])]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 500}
