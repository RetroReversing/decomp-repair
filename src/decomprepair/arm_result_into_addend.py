"""A two-arm sum m2c put in a result local of its own, added into the value both arms start from.

    off = span * roll() / 32767;            off = span * roll() / 32767;
    if (low < high) {                       if (low < high) {
        result = off + low;                     off += low;
    } else {                        ->      } else {
        result = off + high;                    off += high;
    }                                       }
    obj->x = result;                        obj->x = off;

The target keeps one value in one register and adds to it in each arm. m2c names the sum again (often narrower, because
the store after the join is narrow). On a 187-instruction N64 object spawner (`sn-n64-281 -O2 -mips3`) the clamp stayed
430 away with every other row fixed, and 0 with this written; no family offered it.

Offered only when the meaning is unchanged: the result local is mentioned four times (declaration, the two arm
assignments, one store `PLACE = result;` right after the `if`), the added value is a plain local both arms add to that
is not read again after that store (its next mention, if any, is a plain assignment), neither is `volatile` or has its
address taken, and the result's type is a word or the store narrows to it anyway.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'arm_result_into_addend'
FAMILIES = (FAMILY,)
LIMIT = 8
ARM = r'\{{\s*(?P<{r}>[A-Za-z_]\w*)\s*=\s*(?P<{a}>[A-Za-z_]\w*)\s*\+\s*(?P<{b}>[A-Za-z_]\w*)\s*;\s*\}}'
SHAPE = re.compile(r'(?<![\w])if\s*\((?:[^(){}]|\((?:[^(){}]|\([^(){}]*\))*\))*\)\s*' + ARM.format(r='r1', a='a1', b='b1')
                   + r'\s*else\s*' + ARM.format(r='r2', a='a2', b='b2')
                   + r'\s*(?P<place>[^;{}=]+?)\s*=\s*(?P<cast>\(\s*[su](?:8|16|32)\s*\)\s*)?(?P<used>[A-Za-z_]\w*)\s*;')
WORD = r'(?:s32|u32|int|unsigned(?:\s+int)?)'
INTEGER = r'(?:s8|u8|s16|u16|s32|u32|int|short|char|unsigned(?:\s+(?:int|short|char))?)'


def _local(body, var):
    """The declared type of a plain local (declared once, no initialiser), else None."""
    found = re.findall(rf'(?:^|[;{{}}])\s*({INTEGER})\s+{var}\s*;', body)
    if len(found) != 1 or re.search(rf'(?<!&)&\s*{var}\b', body) and re.search(rf'[(,=]\s*&\s*{var}\b', body):
        return None
    return found[0]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening + 1:end - 1]
    sites = []
    for m in SHAPE.finditer(clean, opening + 1, end):
        result = m['r1']
        if m['r2'] != result or m['used'] != result:
            continue
        shared = [v for v in (m['a1'], m['b1']) if v in (m['a2'], m['b2'])]
        if len(shared) != 1:
            continue
        held = shared[0]
        first = m['b1'] if m['a1'] == held else m['a1']
        second = m['b2'] if m['a2'] == held else m['a2']
        kind, carried = _local(body, result), _local(body, held)
        if not kind or not carried or held == result or not re.fullmatch(WORD, carried):
            continue
        if len(re.findall(rf'(?<![\w.>]){result}\b', body)) != 4:
            continue
        # a narrow result is safe only when the store converts to that width anyway
        cast = re.sub(r'[()\s]', '', m['cast'] or '')
        if not re.fullmatch(WORD, kind) and not (cast == kind or re.search(rf'\b{kind}\s*\*', m['place'])):
            continue
        later = re.search(rf'(?<![\w.>]){held}\b', clean[m.end():end])
        if later and not re.match(r'\s*=(?!=)', clean[m.end() + later.end():end]):
            continue
        edits = []
        for group, other in (('r1', first), ('r2', second)):
            start = m.start(group)
            stop = clean.index(';', start) + 1
            edits.append((start, stop, f'{held} += {other};'))
        edits.append((m.start('used'), m.end('used'), held))
        sites.append(edits)
    if not sites:
        return []

    def apply(edits):
        text = source
        for start, stop, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[stop:]
        return text

    groups = sites[:LIMIT - 1] + ([sum(sites, [])] if len(sites) > 1 else [])
    return [(FAMILY, apply(edits)) for edits in groups]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
