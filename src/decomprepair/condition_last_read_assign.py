"""A field read again into a local at the top of an `if` body, assigned inside the condition's last test instead.

    if (ready && (item->kind != 7 || item->count < 2)) {         if (ready && ((kind = item->kind) != 7 || item->count < 2)) {
        kind = item->kind;                              ->
        ...                                                          ...

Written as a statement, the body's first instruction copies the value the test loaded into a throwaway register; the
target loads the field straight into the local's register and tests that register (`lw $a0, 0x5c($s0); bne $a0, $t1`).
SN64 GCC 2.8.1 `-O2`, a 435-instruction hit search: 165 -> 0.

The read moves only where it is certain to run whenever the body does: it is the first thing evaluated in the last
`&&` operand of a condition with no top-level `||`. The local is then also set when the condition fails, so it must not
be read after the `if`, and the condition must not read it after the new assignment.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'condition_last_read_assign'
FAMILIES = (FAMILY,)
LIMIT = 6

_IF = re.compile(r'\bif\s*\(')
_FIRST = re.compile(rf'\s*(?P<local>{IDENT})\s*=\s*(?P<read>{IDENT}(?:\s*(?:->|\.)\s*{IDENT})+)\s*;[ \t]*\n?')


def _last_operand(condition):
    """Where the last top-level `&&` operand starts, or None when the condition has a top-level `||`, `?` or `,`."""
    depth, start, at = 0, 0, 0
    while at < len(condition):
        char = condition[at]
        depth += (char in '([') - (char in ')]')
        if depth == 0 and (condition.startswith('||', at) or char in '?,'):
            return None
        if depth == 0 and condition.startswith('&&', at):
            start = at + 2
            at += 1
        at += 1
    return start


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for m in _IF.finditer(clean, part.opening, part.end):
        stop = close(clean, m.end() - 1)
        if not stop:
            continue
        opening = stop + len(clean[stop:part.end]) - len(clean[stop:part.end].lstrip())
        if not clean.startswith('{', opening):
            continue
        end = close(clean, opening, '{', '}')
        first = _FIRST.match(clean, opening + 1)
        if not end or not first:
            continue
        local, read = first.group('local'), first.group('read')
        condition = clean[m.end():stop - 1]
        start = _last_operand(condition)
        if start is None:
            continue
        lead = re.compile(r'[\s(]*').match(condition, start).end()
        if not condition.startswith(read, lead) or re.match(r'\s*(?:->|\.|\[|\w)', condition[lead + len(read):]):
            continue
        if re.search(rf'(?<![\w.>]){local}\b', condition[lead:]):
            continue
        declared = re.search(rf'(?:^|(?<=[;{{}}]))\s*(?:{IDENT}\s+|\*\s*)+\*?\s*{local}\s*(?:,[^;()]*)?;|'
                             rf'\b{IDENT}\s+(?:{IDENT}\s*,\s*)+{local}\b[^;()]*;', clean[part.opening:part.end])
        if not declared or re.search(rf'&\s*{local}\b', clean[part.opening:part.end]):
            continue
        if re.search(rf'(?<![\w.>]){local}\b', clean[end:part.end]):
            continue
        at = m.end() + lead
        text = (source[:at] + f'({local} = {source[at:at + len(read)]})' + source[at + len(read):opening + 1] + '\n'
                + source[first.end():])
        found.append((FAMILY, text))
        if len(found) >= LIMIT:
            break
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
