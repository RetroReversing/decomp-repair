"""A pointer member that only a `switch` arm uses, read before the dispatch as the game did.

m2c writes each load where its value is first used, so `temp->unk50->unk4 = 0;` sits inside its case. The game had
`p = temp->unk50;` among the locals above the `switch`: the target loads it with the other set-up (`lw $t0, 0x50($a1)`
before the case value) and the arm stores through that register. gcc 2.7.2 at -O1 never moves a load out of a case,
so the local has to be in the source (240 -> 35 on a 145-instruction state switch, and 0 with `low_field_step`).
Offered for a pointer-typed read used inside a `switch` body whose base the function never assigns inside that body,
placed just before the `switch` and before the statement above it (the dispatch value's own load).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'case_pointer_prefetch'
FAMILIES = (FAMILY,)
LOCAL = '__repair_prefetch'
LIMIT = 8

I = r'[A-Za-z_]\w*'
TYPE = r'(?P<type>(?:struct\s+)?\w+\s*\*)\s*\*'
OFF = r'(?:0x[0-9a-fA-F]+|\d+)'
SHAPES = (
    # (*(void **)((char *)(base) + 0x50))   and   *((void **) (((char *) base) + 0x50))
    re.compile(r'\*\s*\(\s*\(\s*' + TYPE + r'\s*\)\s*\(\s*\(\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*\(?\s*(?P<base>' + I
               + r')\s*\)?\s*\)\s*\+\s*' + OFF + r'\s*\)\s*\)'),
    re.compile(r'\*\s*\(\s*' + TYPE + r'\s*\)\s*\(\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*\(?\s*(?P<base>' + I
               + r')\s*\)?\s*\+\s*' + OFF + r'\s*\)'),
    re.compile(r'M2C_FIELD\(\s*(?P<base>' + I + r')\s*,\s*' + TYPE + r'\s*,\s*' + OFF + r'\s*\)'),
)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or LOCAL in clean:
        return []
    result = []
    for switch in re.finditer(r'(?m)^[ \t]*switch\s*\(', clean[opening:end]):
        start = opening + switch.start()
        head_end = close(clean, opening + switch.end() - 1)
        body = clean.find('{', head_end) if head_end else -1
        if body < 0:
            continue
        body_end = close(clean, body, '{', '}')
        if not body_end:
            continue
        seen = set()
        for shape in SHAPES:
            for hit in shape.finditer(clean, body, body_end):
                expr = source[hit.start():hit.end()]
                base = hit['base']
                if expr in seen or re.search(r'(?<![\w.>])' + base + r'\s*(?:=(?!=)|\+\+|--|[-+]=)', clean[body:body_end]):
                    continue
                # a store through this expression itself would change the value
                if re.match(r'\s*=(?!=)', clean[hit.end():]):
                    continue
                seen.add(expr)
                result += _placed(source, clean, opening, start, hit, hit['type'].strip(), expr, body_end)
    return [(FAMILY, text) for text in result[:LIMIT]]


def _placed(source, clean, opening, switch_start, hit, pointee, expr, body_end):
    """The local set right before the `switch`, and one statement earlier."""
    places = [switch_start]
    above = clean.rfind('\n', opening, switch_start - 1) + 1
    line = clean[above:switch_start].strip()
    if line.endswith(';') and re.match(I + r'\s*=(?!=)', line):
        places.append(above)
    out = []
    for place in places:
        if not re.search(r'\b' + hit['base'] + r'\s*=(?!=)', clean[opening:place]) and not _is_parameter(clean, opening, hit['base']):
            continue
        ind = re.match(r'[ \t]*', source[switch_start:])[0]
        text = (source[:place] + f'{ind}{LOCAL} = {expr};\n' + source[place:hit.start()] + LOCAL
                + source[hit.end():])
        text = text[:opening + 1] + f'\n    {pointee} {LOCAL};' + text[opening + 1:]
        out.append(text)
    return out


def _is_parameter(clean, opening, base):
    head = clean[:opening]
    return bool(re.search(r'\b' + base + r'\s*(?=[,)])', head[head.rfind('('):]))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
