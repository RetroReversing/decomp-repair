"""A function that returns from every leaf of its `if` tree, given one result local and one `return`.

`return 0; ... return 1;` in each arm lets jump.c and reorg send a branch straight to the epilogue with the value the
compare left in `$v0` (`beq $v1,$v0,END`); where the target keeps `bne $v1,$v0,NEXT; nop; j END; li $v0,1` for every
leaf and extends the value once at the end, the source assigned a local of the function's type and returned it once.
KMC GCC 2.7.2 -O1, a 119-instruction two-key lookup returning `u8`: 460 -> 0.

returns_to_result_local
    Every `return V;` (three or more, each the last thing its path does) written `__repair_result = V;`, with
    `return __repair_result;` after the tree. One child.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'returns_to_result_local'
FAMILIES = (FAMILY,)
LEAST = 3
_TYPE = re.compile(r'\b((?:(?:unsigned|signed)\s+)?[A-Za-z_]\w*(?:\s*\*)*)\s*$')


def _skip(clean, at, hi):
    while at < hi and clean[at].isspace():
        at += 1
    return at


def _statement(clean, at, hi, returns):
    """(end, always returns) of the statement at `at`, adding the spans of its tail returns to `returns`; None for a
    statement this does not read."""
    at = _skip(clean, at, hi)
    if clean.startswith('{', at):
        tail = close(clean, at)
        if tail < 0:
            return None
        at, done = _skip(clean, at + 1, tail), False
        while at < tail:
            if done:
                return None
            found = []
            read = _statement(clean, at, tail, found)
            if read is None:
                return None
            end, done = read
            if found and not done:
                return None
            returns.extend(found)
            at = _skip(clean, end, tail)
        return tail + 1, done
    if re.compile(r'if\b').match(clean, at):
        opening = clean.find('(', at, hi)
        condition = close(clean, opening, '(', ')') if opening >= 0 else -1
        if condition < 0:
            return None
        read = _statement(clean, condition + 1, hi, returns)
        if read is None:
            return None
        end, first = read
        other = re.compile(r'\s*else\b').match(clean, end, hi)
        if not other:
            return end, False
        read = _statement(clean, other.end(), hi, returns)
        if read is None:
            return None
        end, second = read
        return (end, first and second) if first == second else None
    if re.compile(r'(?:for|while|do|switch|case|default|goto|break|continue)\b').match(clean, at):
        return None
    depth = 0
    for end in range(at, hi):
        char = clean[end]
        depth += (char in '([{') - (char in ')]}')
        if char == ';' and depth == 0:
            if re.compile(r'return\b').match(clean, at):
                returns.append((at, end + 1))
                return end + 1, True
            return (end + 1, False) if not re.compile(r'[A-Za-z_]\w*\s*:').match(clean, at) else None
    return None


def variants(source, name):
    span = find(source, name)
    if not span or '__repair_result' in source:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    head = re.compile(rf'\b{re.escape(name)}\s*\(').search(clean, span[0], opening)
    kind = head and _TYPE.search(clean[span[0]:head.start()])
    if opening < 0 or not kind or kind[1] in ('void', 'float', 'double', 'f32', 'f64'):
        return []
    returns = []
    read = _statement(clean, opening, span[1], returns)
    if (not read or not read[1] or len(returns) < LEAST
            or len(returns) != len(re.findall(r'\breturn\b', clean[opening:read[0]]))):
        return []
    values = [source[a + len('return'):b - 1].strip() for a, b in returns]
    if not all(values):
        return []
    edited = source[:read[0] - 1].rstrip() + '\n    return __repair_result;\n' + source[read[0] - 1:]
    for (a, b), value in reversed(list(zip(returns, values))):
        edited = edited[:a] + f'__repair_result = {value};' + edited[b:]
    edited = edited[:opening + 1] + f'\n    {kind[1]} __repair_result;' + edited[opening + 1:]
    return [(FAMILY, edited)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
