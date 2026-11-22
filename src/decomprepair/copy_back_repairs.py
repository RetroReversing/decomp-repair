"""A second set of a local: fold its two-step computation into one, and copy it back from a copy of it.

gcc 2.7.2 schedules and allocates a pseudo that is set once differently from one set twice: the scheduler's
register-pressure tie-break treats the single set as the birth of the pseudo, and the result of the last instruction
of its computation goes straight into the pseudo's register. A race function's table entry,
`p = base + (s8) *q * 0xE8`, had to come first among two such entries and end `sll $v0; addu $s1, $v0, $a1`. Written
as one expression, the other entry was scheduled first (500); written as two sets (`p = x * 0xE8; p = p + base;`) the
order was right but the shift landed in `$s1` (10). Folding the two sets and adding a no-op set of `p` after the
switch arm's copy `q = p;` (`p = q;`, which costs no instruction) gave both: exact.

Children: the copy-back alone after a copy `A = B;` of two plain locals (`B = A;`), the fold of two adjacent sets
`X = E; X = R(X);` into `X = R((E));`, and each fold with the copy-back of the first copy that reads the folded local.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'copy_back_set'
FAMILIES = (FAMILY,)
LIMIT = 24

_COPY = re.compile(rf'(?<=[;{{}}:])(?P<pad>\s*)(?P<dest>{IDENT})\s*=(?!=)\s*(?P<src>{IDENT})\s*;')
_SET = re.compile(rf'(?<=[;{{}}])\s*(?P<dest>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}]+);')
_KEYWORDS = {'return', 'goto', 'case', 'default', 'break', 'continue', 'sizeof'}


def _pure(value):
    """No call, assignment or increment: a value that may be moved into another expression."""
    calls = [m[1] for m in re.finditer(rf'\b({IDENT})\s*\(', value) if m[1] != 'sizeof']
    return not calls \
        and not re.search(r'\+\+|--|(?<![=!<>])=(?!=)', value)


def _locals(part):
    body = part.clean[part.opening + 1:part.end]
    return set(re.findall(rf'(?m)^\s*(?:register\s+)?[A-Za-z_][\w ]*?[\s*]({IDENT})\s*;', body)) - _KEYWORDS


def _copies(part, names):
    for hit in _COPY.finditer(part.clean, part.opening + 1, part.end):
        if hit['dest'] in names and hit['src'] in names and hit['dest'] != hit['src']:
            yield hit


def _back(hit):
    return (hit.end(), hit.end(), f'{hit["pad"] or chr(10)}{hit["src"]} = {hit["dest"]};')


def _folds(part, names):
    """(start, end, replacement, local) for each `X = E; X = R(X);` pair that reads X once in R."""
    sets = [hit for hit in _SET.finditer(part.clean, part.opening + 1, part.end) if hit['dest'] in names]
    for first, second in zip(sets, sets[1:]):
        local = first['dest']
        word = rf'(?<![\w.>]){local}\b'
        if second['dest'] != local or part.clean[first.end():second.start()].strip():
            continue
        if re.search(word, first['value']) or len(re.findall(word, second['value'])) != 1 or not _pure(first['value']):
            continue
        at = second.start('value')
        use = re.search(word, part.clean[at:second.end('value')])
        value = part.source[first.start('value'):first.end('value')].strip()
        replacement = part.source[at:at + use.start()] + f'({value})' + part.source[at + use.end():second.end('value')]
        start = first.start('dest')
        yield start, second.end(), f'{local} = {replacement};', local


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    names = _locals(part)
    copies = list(_copies(part, names))
    result = []

    def add(edits):
        text = edit(source, edits)
        if text != source and (FAMILY, text) not in result and len(result) < LIMIT:
            result.append((FAMILY, text))

    for start, end, replacement, local in _folds(part, names):
        fold = (start, end, replacement)
        later = [hit for hit in copies if hit['src'] == local and hit.start() > end]
        if later:
            add([fold, _back(later[0])])
        add([fold])
    seen = set()
    for hit in copies:
        if (hit['dest'], hit['src']) not in seen:
            seen.add((hit['dest'], hit['src']))
            add([_back(hit)])
    return result
