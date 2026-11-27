"""m2c's rotated two-test scan loop written back as `while (A || B) i++;` over a record view of the table.

A table scan such as `i = 0; while (x < t[i].first || t[i].last < x) i++;` comes out of m2c as the entry test with the
index folded to zero, an inner `for (;;)` that steps the index and `continue`s while the first test holds, an outer
`do`/`while` on the second test, and the loop's "found" flag set twice:

    i = 0;
    if (A0 || ((found = 0U < N, B0) != 0)) {
        do {
            for (;;) { i += 1; p = i * S; p = (char *) p + (s32) &t; if (x <= p->first - 1) { continue; } break; }
        } while (B(p));
        found = i < N;
    }

gcc 2.7.2 (SN build) does not rebuild the target's loop from that: the registers and the branch-likely instructions differ.
Written as the one `while` with the table read as records, followed by `found = i < N;`, a 135-instruction N64 transfer
routine went 1060 -> 175; with the subtrahend staged afterwards (difference_block_stage) it was exact. The raw casts of
the same loop stayed at 455: the record index is what gives one pointer per step (a hypothesis from the output).

The child is offered only when the entry tests are the loop's own tests at index zero (`x <= v - 1` read as `x < v`,
as the entry test shows) and the stepped pointer is assigned again before any later use.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'scan_loop_while'
FAMILIES = (FAMILY,)
_SIZES = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4}
_TYPE = '|'.join(_SIZES)
_IF = re.compile(r'(?<![\w.>])(?P<index>' + IDENT + r')\s*=\s*0\s*;\s*(?P<head>if)\s*\(')
_STEP = re.compile(r'(?P<i>\w+)(?:\+=1|\+\+|=(?P=i)\+1);')


def _plain(text):
    """`text` without spaces, casts and parentheses; a dereference keeps its type as `*[type]`."""
    text = re.sub(r'\s+', '', text)
    text = re.sub(rf'\*\(*\(({_TYPE})\*\)', r'*[\1]', text)
    text = re.sub(rf'\((?:(?:{_TYPE}|char|void)\**)\)', '', text)
    return text.replace('(', '').replace(')', '')


def _test(plain, base):
    """(left side, field type, offset, field is on the left) of one `<` test against a field of `base`, else None."""
    field = rf'\*\[(?P<type>{_TYPE})\]{re.escape(base)}(?:\+(?P<offset>{NUMBER}))?'
    other = rf'(?P<other>{IDENT}|{NUMBER})'
    for pattern, first in ((rf'{other}<{field}', False), (rf'{field}<{other}', True)):
        hit = re.fullmatch(pattern, plain)
        if hit:
            return hit['other'], hit['type'], int(hit['offset'] or '0', 0), first
    return None


def _block(clean, at):
    """(opening, end) of the braces starting at or after `at`, only blanks before them."""
    opening = at + len(clean[at:]) - len(clean[at:].lstrip())
    end = close(clean, opening, '{', '}') if clean[opening:opening + 1] == '{' else None
    return (opening, end) if end else None


def _condition(plain):
    """(first test, second test, flag, bound) of `A||found=0U<N,B!=0` (casts and parentheses already gone)."""
    hit = re.fullmatch(rf'(?P<a>[^|]+)\|\|(?:(?P<flag>{IDENT})=0U?<(?P<n>{NUMBER})U?,(?P<b>[^|,]+?)!=0|(?P<c>[^|,=]+))', plain)
    if not hit:
        return None
    return hit['a'], hit['b'] or hit['c'], hit['flag'], hit['n']


def _loop(clean, begin, end):
    """The parts of `do { for (;;) { step; pointer; if (A) { continue; } break; } } while (B); [found = i < N;]`."""
    plain_head = re.match(r'\s*do\s*', clean[begin:end])
    outer = plain_head and _block(clean, begin + plain_head.end())
    if not outer:
        return None
    inner_head = re.match(r'\s*for\s*\(\s*;\s*;\s*\)', clean[outer[0] + 1:outer[1] - 1])
    inner = inner_head and _block(clean, outer[0] + 1 + inner_head.end())
    if not inner or clean[inner[1]:outer[1] - 1].strip():
        return None
    body = clean[inner[0] + 1:inner[1] - 1]
    skip = re.search(r'\bif\s*\(', body)
    if not skip:
        return None
    paren = skip.end() - 1
    paren_end = close(body, paren)
    if not paren_end or not re.fullmatch(r'\s*\{\s*continue\s*;\s*\}\s*break\s*;\s*', body[paren_end:]):
        return None
    tail = re.match(r'\s*while\s*\(', clean[outer[1]:end])
    if not tail:
        return None
    start = outer[1] + tail.end() - 1
    stop = close(clean, start)
    rest = re.match(r'\s*;', clean[stop:end]) if stop else None
    if not rest:
        return None
    return body[:skip.start()], body[paren + 1:paren_end - 1], clean[start + 1:stop - 1], clean[stop + rest.end():end]


def _record(name, fields, stride):
    members, at = [], 0
    for offset, kind in sorted(fields.items()):
        if offset < at or offset % _SIZES[kind]:
            return None
        if offset > at:
            members.append(f'u8 pad{at:X}[{offset - at}];')
        members.append(f'{kind} f{offset:X};')
        at = offset + _SIZES[kind]
    if at > stride:
        return None
    if stride > at:
        members.append(f'u8 pad{at:X}[{stride - at}];')
    return f'typedef struct {{ {" ".join(members)} }} {name};\n'


def _site(source, part, hit):
    clean = part.clean
    index = hit['index']
    paren = hit.end() - 1
    paren_end = close(clean, paren)
    block = paren_end and _block(clean, paren_end)
    if not block or re.match(r'\s*else\b', clean[block[1]:]):
        return None
    condition = _condition(_plain(clean[paren + 1:paren_end - 1]))
    loop = condition and _loop(clean, block[0] + 1, block[1] - 1)
    if not loop:
        return None
    first, second, flag, bound = condition
    steps, skip, repeat, after = loop
    steps = _plain(steps)
    step = _STEP.match(steps)
    if not step or step['i'] != index:
        return None
    pointer = re.fullmatch(rf'(?P<p>{IDENT})={index}\*(?P<s>{NUMBER});(?P=p)=(?P=p)\+&(?P<base>{IDENT});',
                           steps[step.end():]) \
        or re.fullmatch(rf'(?P<p>{IDENT})=&(?P<base>{IDENT})\+{index}\*(?P<s>{NUMBER});', steps[step.end():])
    if not pointer:
        return None
    name, base, stride = pointer['p'], pointer['base'], int(pointer['s'], 0)
    after = _plain(after)
    if flag:
        if int(bound.rstrip('uUlL'), 0) <= 0 or not re.fullmatch(rf'{flag}={index}<{re.escape(bound)}U?;', after):
            return None
    elif after:
        return None

    def at_zero(text):
        # `x <= v - 1` is how m2c wrote the `x < v` the entry test shows
        plain = re.sub(rf'(?<![\w.>]){name}(?!\w)', '&' + base, _plain(text))
        return re.sub(rf'<=(\*\[(?:{_TYPE})\]&{base}(?:\+{NUMBER})?)-1\Z', r'<\1', plain)

    tests = [_test(plain, '&' + base) for plain in (first, second)]
    if None in tests or [_test(at_zero(skip), '&' + base), _test(at_zero(repeat), '&' + base)] != tests:
        return None
    # the pointer's value after the loop is gone: its next mention must assign it
    later = re.search(rf'(?<![\w.>]){name}(?!\w)', clean[block[1]:part.end])
    if later and not re.match(r'\s*=(?!=)', clean[block[1] + later.end():]):
        return None
    fields = {}
    for _, kind, offset, _ in tests:
        if fields.setdefault(offset, kind) != kind:
            return None
    record, number = 'ScanEntry', 1
    while re.search(rf'\b{record}\b', source):
        number += 1
        record = f'ScanEntry{number}'
    typedef = _record(record, fields, stride)
    if not typedef:
        return None
    spelled = []
    for other, _, offset, field_first in tests:
        read = f'(({record} *) &{base})[{index}].f{offset:X}'
        spelled.append(f'{read} < {other}' if field_first else f'{other} < {read}')
    start = hit.start('head')
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
    text = f'while ({spelled[0]} || {spelled[1]})\n{indent}{{\n{indent}    {index}++;\n{indent}}}'
    if flag:
        text += f'\n{indent}{flag} = {index} < {bound};'
    return typedef, (start, block[1], text)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    head = re.search(rf'(?m)^[^\n;{{}}()]*(?<![\w.>]){re.escape(name)}\s*\(', part.clean[:part.opening])
    if not head:
        return []
    children = []
    for hit in _IF.finditer(part.clean, part.opening, part.end):
        site = _site(source, part, hit)
        if site:
            typedef, change = site
            children.append((FAMILY, edit(source, [(head.start(), head.start(), typedef), change])))
    return children[:3]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
