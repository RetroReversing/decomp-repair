"""m2c's nest of negated guards, written back as the flat chain of early returns it came from.

A function that tests one value against 1, 2, 3, ... in turn, each arm returning, can come out of m2c with the later
arms nested under negated tests and their bodies in reverse order after the nest:

    if (G == 1) { A; return; }
    if (G == 2) { B; return; }
    if (G != 3) {
        if (G != 4) { ...; return; }
        D; return;
    }
    C;

gcc lays blocks out in source order, so that spelling puts C after D and the arms' branches differ, while

    if (G == 1) { A; return; }
    if (G == 2) { B; return; }
    if (G == 3) { C; return; }
    if (G == 4) { D; return; }
    ...

is the same program (an N64 page-stepping routine, SN GCC: 1150 -> 0). Each guard whose block holds another test and
ends in `return` is exchanged with the statements after it; one child per depth reached, the deepest first.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'negated_guard_unnest'
FAMILIES = (FAMILY,)
DECLARATION = re.compile(r'^\s*(?!return\b|goto\b|else\b)(?:[A-Za-z_]\w*[\s*]+)+[A-Za-z_]\w*\s*(?:=|;|\[|,)')


def _depth(clean, at):
    return clean[:at].count('{') - clean[:at].count('}')


def _ends_in_return(block):
    match = re.search(r'\breturn\b[^;{}]*;\s*\Z', block)
    return bool(match) and _depth(block, match.start()) == 0 and not re.search(r'(?:\)|\belse)\s*\Z', block[:match.start()])


def _shift(text, indent):
    """The lines of `text` moved so that the least indented one starts at `indent`."""
    lines = text.strip('\n').rstrip().split('\n')
    width = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return '\n'.join(indent + line[width:] if line.strip() else '' for line in lines) + '\n'


def _flip(body, void, limit):
    """(new body, guards exchanged) for a block that falls off the function's end, at most `limit` exchanges."""
    clean = _blank(body)
    for guard in re.finditer(r'(?m)^([ \t]*)if\s*\(', clean):
        if _depth(clean, guard.start()) != 0:
            continue
        cond_close = close(clean, guard.end() - 1)
        opening = re.compile(r'\s*\{').match(clean, cond_close or len(clean))
        if not cond_close or not opening:
            continue
        end = close(clean, opening.end() - 1, '{', '}')
        if not end or re.match(r'\s*else\b', clean[end:]):
            continue
        block, tail = body[opening.end():end - 1], body[end:]
        clean_block, clean_tail = clean[opening.end():end - 1], clean[end:]
        if (not re.search(r'\bif\s*\(', clean_block) or not _ends_in_return(clean_block) or not clean_tail.strip()
                or DECLARATION.match(clean_block)
                or re.search(r'(?m)^\s*(?:case\b[^:]*|default|[A-Za-z_]\w*)\s*:(?!:)', clean_block + '\n' + clean_tail)
                or re.search(r'(?m)^\s*#', clean_block + '\n' + clean_tail)):
            continue
        if not _ends_in_return(clean_tail):
            if not void:
                continue
            tail = tail.rstrip() + '\n' + guard[1] + 'return;\n'
        condition = body[guard.end():cond_close - 1].strip()
        inverse = negate(condition) if re.search(r'==|!=', condition) else None
        rest, count = block, 0
        if limit > 1:
            rest, count = _flip(block, void, limit - 1)
        return (body[:guard.start()] + f'{guard[1]}if ({inverse or f"!({condition})"}) {{\n'
                + _shift(tail, guard[1] + '    ') + guard[1] + '}\n' + _shift(rest, guard[1]), count + 1)
    return body, 0


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    void = bool(re.search(r'\bvoid\s+(?:[\w~<>]+::)*' + re.escape(name.split('::')[-1]) + r'\s*\(', clean[span[0]:opening]))
    body = source[opening + 1:end - 1]
    result = []
    for limit in range(8, 0, -1):
        changed, count = _flip(body, void, limit)
        child = source[:opening + 1] + changed.rstrip() + '\n' + source[end - 1:]
        if count and (FAMILY, child) not in result:
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
