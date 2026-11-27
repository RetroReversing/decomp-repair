"""A callee m2c declared as returning a word whose result this function never uses, declared `void`.

m2c writes `M2C_UNK f(...); /* extern */` for a callee it knows nothing about. A caller that drops the result compiles
the same call either way, but a value-returning call also sets `$v0` as far as the allocator and the scheduler are
concerned, so the registers and the order around it differ (a 46-instruction N64 matrix routine, SN GCC 2.8.1 `-O3`:
1180 -> 940 alone, and the last 570 -> 0 with its other repairs).

Only prototypes written in the candidate itself are changed, and only when every mention of the callee in the function
is a call whose result is discarded. Children (`discarded_result_void`): each such callee alone, then all of them.
"""
import re

from .csource import _blank, find

FAMILY = 'discarded_result_void'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
PROTOTYPE = re.compile(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<kind>M2C_UNK(?:32)?|s32|u32|int)[ \t]+(?P<name>{IDENT})'
                       r'[ \t]*\([^;{{]*\)[ \t]*;')
STATEMENT_START = re.compile(r'(?:[;{}]|\belse|\bdo)\s*$')
CONDITION = re.compile(r'\b(?:if|while|for|switch)\s*$')


def _closing(text, opening):
    depth = 0
    for at in range(opening, len(text)):
        if text[at] == '(':
            depth += 1
        elif text[at] == ')':
            depth -= 1
            if not depth:
                return at
    return None


def _after_condition(before):
    """Whether `before` ends in the parentheses of an `if`/`while`/`for`/`switch` (the call is its whole body)."""
    before = before.rstrip()
    if not before.endswith(')'):
        return False
    depth = 0
    for at in range(len(before) - 1, -1, -1):
        if before[at] == ')':
            depth += 1
        elif before[at] == '(':
            depth -= 1
            if not depth:
                return bool(CONDITION.search(before[:at]))
    return False


def _discarded(body, name):
    """Whether `body` mentions `name`, and only as calls that are statements of their own."""
    mentions = list(re.finditer(rf'(?<![\w.>])\b{name}\b', body))
    for mention in mentions:
        rest = body[mention.end():]
        if not rest.lstrip().startswith('('):
            return False
        end = _closing(body, mention.end() + rest.index('('))
        before = body[:mention.start()]
        if end is None or not body[end + 1:].lstrip().startswith(';') or not (
                STATEMENT_START.search(before) or _after_condition(before)):
            return False
    return bool(mentions)


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[clean.find('{', span[0], span[1]):span[1]]
    shared = _blank(header or '')
    found = {}
    for prototype in PROTOTYPE.finditer(clean[:span[0]]):
        callee = prototype['name']
        if callee != name and not re.search(rf'\b{callee}\b', shared) and _discarded(body, callee):
            found[callee] = prototype.span('kind')
    groups = [[callee] for callee in found]
    if len(found) > 1:
        groups.append(list(found))
    result = []
    for group in groups:
        text = source
        for start, end in sorted((found[callee] for callee in group), reverse=True):
            text = text[:start] + 'void' + text[end:]
        result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
