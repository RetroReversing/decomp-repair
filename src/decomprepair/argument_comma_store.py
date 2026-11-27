"""A store written just before a call, moved into the call's argument list as a comma operand.

    p->state = 5;                                  angle = turn(p->x, (p->state = 5, p->y));
    angle = turn(p->x, p->y);

The store still happens before the call, but GCC now expands it between the loads of the arguments, so the scheduler no
longer sees it ahead of them and the target's order of loads and constant comes (hypothesis about the pass; the order
itself is measured). Measured on a 98-instruction N64 actor setup (SN GCC 2.8.1, `-G0 -mips3 -O2`): 60 with the
separate statement (`li` of the stored constant before the argument loads), 0 with the store as a comma operand of the
second argument. Locals for the arguments, loaded before the store, gave the same bytes.

The program must not change, so a site is offered only when the order cannot matter: the stored value is a literal, the
call's arguments are literals, locals or fields read off the same base as the stored field at bytes that do not overlap
it (`M2C_FIELD(base, T, off)` or `base->member`), and no argument calls anything or has a side effect.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

SUNK = 'argument_comma_store'
FAMILIES = (SUNK,)
LIMIT = 24
_FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>{IDENT})\s*\*\s*,\s*(?P<offset>-?{NUMBER})\s*\)')
_MEMBER = re.compile(rf'(?P<base>{IDENT})\s*->\s*(?P<member>{IDENT})')
_CONSTANT = re.compile(rf'-?(?:{NUMBER}|{NUMBER}?\.[0-9]*f?)')
_CALL = re.compile(rf'(?P<head>\s*(?:{IDENT}\s*=\s*)?)(?P<callee>{IDENT})\s*\(')
_WIDTHS = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4}
_NOT_CALLS = ('if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'M2C_FIELD')


def _place(text):
    """(base, byte range or None, member or None) of a field access, or None."""
    text = text.strip()
    field = _FIELD.fullmatch(text)
    if field:
        width = _WIDTHS.get(field['type'])
        if not width:
            return None
        offset = int(field['offset'].rstrip('uUlL'), 0)
        return field['base'], (offset, offset + width), None
    member = _MEMBER.fullmatch(text)
    return (member['base'], None, member['member']) if member else None


def _apart(stored, read):
    if stored[0] != read[0]:
        return False
    if stored[1] and read[1]:
        return stored[1][1] <= read[1][0] or read[1][1] <= stored[1][0]
    return bool(stored[2] and read[2] and stored[2] != read[2])


def _arguments(clean, opening, closing):
    """(start, end) of each argument between the parentheses."""
    spans, depth, start = [], 0, opening + 1
    for at in range(opening + 1, closing):
        depth += (clean[at] in '([') - (clean[at] in ')]')
        if depth == 0 and clean[at] == ',':
            spans.append((start, at))
            start = at + 1
    spans.append((start, closing))
    return spans


def _harmless(text, stored, body):
    text = re.sub(r'^(?:\(\s*(?:s|u)(?:8|16|32)\s*\)\s*)+', '', text.strip())
    if _CONSTANT.fullmatch(text):
        return True
    if re.fullmatch(IDENT, text):
        # a parameter or a local of this function: a global could be the very bytes stored
        return bool(re.search(rf'\b{IDENT}[\s*]+{text}\s*[;=,)\[]', body))
    place = _place(text)
    return bool(place and _apart(stored, place))


def _sites(part):
    clean = part.clean
    body = clean[:part.end]
    for call_at in range(part.opening + 1, part.end - 1):
        if clean[call_at] != ';':
            continue
        # the statement that ends here is the store, the one that follows holds the call
        start = max(clean.rfind(c, part.opening, call_at) for c in ';{}') + 1
        store = clean[start:call_at]
        left, equals, right = store.partition('=')
        if not equals or not _CONSTANT.fullmatch(right.strip()):
            continue
        stored = _place(left)
        if not stored:
            continue
        call = _CALL.match(clean, call_at + 1)
        if not call or call['callee'] in _NOT_CALLS:
            continue
        opening = call.end() - 1
        closing = close(clean, opening, '(', ')')
        if not closing:
            continue
        closing -= 1
        if not re.match(r'\s*;', clean[closing + 1:]):
            continue
        spans = _arguments(clean, opening, closing)
        if not all(_harmless(clean[a:b], stored, body) for a, b in spans):
            continue
        first = start + len(store) - len(store.lstrip())
        yield first, call_at + 1, spans


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    found = []
    for first, after, spans in _sites(part):
        statement = source[first:after - 1].strip()
        # the last argument first: the measured order
        for a, b in reversed(spans):
            argument = source[a:b]
            if not argument.strip():
                continue
            lead = argument[:len(argument) - len(argument.lstrip())]
            wrapped = f'{lead}({statement}, {argument.strip()})'
            rest = after
            while rest < len(source) and source[rest] in ' \t\r\n':
                rest += 1
            found.append((SUNK, edit(source, [(first, rest, ''), (a, b, wrapped)])))
            if len(found) >= LIMIT:
                return found
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}
