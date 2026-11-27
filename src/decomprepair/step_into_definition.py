"""A later `v = v + K;` folded into the statement that set `v`, so the add is written where the load is.

m2c recovers a counter's next value in the order the target's instructions come out: `v = rec->count;`, a run of stores
through other pointers, then `v = v + 2;` just before the value is stored. The game wrote it in one statement,
`v = rec->count + 2;`, and the scheduler moved the add down to its use. Written in two statements the add is a second
set of the same local, which the compiler holds in a different place in the block: on an 82-instruction N64 function
(SN64 GCC 2.8.1 `-G0 -mips3 -O2`) the fold took the saved C from 1235 to 515, and it was one of the five edits that
matched it.

`variants` finds `v = E;` followed, later in the same block, by `v = v OP K;`, `v OP= K;`, `v++;` or `v--;` (OP one of
`+ - & | ^ <<`, K an integer literal) with no mention of `v` and no brace, label or control keyword in between, `v` a
local whose address is never taken. The first statement becomes `v = E OP K;` (E parenthesised unless it is a name, a
call, a member or a load) and the second goes. `v` is not read between them, so the program is the same; one child per
site and one with every site. A candidate for the exact judge, never a verdict."""
import re

from .c_scan import close
from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view

FAMILY = 'step_into_definition'
FAMILIES = (FAMILY,)

LIMIT = 8  # single-site children
_LOCAL = re.compile(rf'(?m)^[ \t]*(?:(?:unsigned|signed|struct)[ \t]+)?{IDENT}[ \t*]+(?P<name>{IDENT})[ \t]*;')
_STEP = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})[ \t]*(?:'
                   rf'=[ \t]*(?P=v)[ \t]*(?P<op>\+|-|&|\||\^|<<)[ \t]*(?P<k>{NUMBER})'
                   rf'|(?P<compound>\+|-|&|\||\^|<<)=[ \t]*(?P<ck>{NUMBER})'
                   rf'|(?P<inc>\+\+|--))[ \t]*;')
_CONTROL = re.compile(r'[{}?#]|\b(?:if|else|for|while|do|switch|case|default|goto|return|break|continue)\b|(?<!:):(?!:)')


def _simple(expression):
    """Whether `expression` needs no parentheses before a binary operator: a name, a member chain or one parenthesised
    group or call covering the whole of it."""
    text = expression.strip()
    if re.fullmatch(rf'{IDENT}(?:(?:\.|->){IDENT})*', text):
        return True
    hit = re.match(rf'(?:{IDENT})?\(', text)
    return bool(hit) and close(text, hit.end() - 1, '(', ')') == len(text) - 1


def _sites(part):
    """[((start, end, replacement) of the definition, (start, end, '') of the step)] in source order."""
    clean, lo, hi = part.clean, part.opening, part.end
    local = {hit['name'] for hit in _LOCAL.finditer(clean, lo, hi)}
    sites = []
    for step in _STEP.finditer(clean, lo, hi):
        name = step['v']
        before = clean[:step.start()].rstrip()
        if name not in local or before[-1:] not in (';', '}') or _address_taken(clean[lo:hi], name):
            continue
        mentions = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[lo:step.start()])]
        if not mentions:
            continue
        found = None
        # The last mention before the step must be the assignment itself, or sit in its right side.
        for mention in reversed(mentions):
            at = lo + mention.start()
            head = clean[:at].rstrip()
            assign = re.match(rf'{re.escape(name)}[ \t]*=(?!=)', clean[at:step.start()])
            if assign and head[-1:] in (';', '{', '}'):
                found = (at, at + assign.end())
                break
        if not found:
            continue
        semicolon = clean.find(';', found[1])
        if semicolon < 0 or semicolon >= step.start():
            continue
        right = (found[1], semicolon)
        if _CONTROL.search(clean[right[0]:right[1]]) or ',' in _top(clean[right[0]:right[1]]):
            continue
        between = clean[semicolon + 1:step.start()]
        if _CONTROL.search(between) or re.search(rf'(?<![\w.>]){re.escape(name)}\b', between):
            continue
        operator = step['op'] or step['compound'] or (step['inc'] or '')[:1]
        constant = step['k'] or step['ck'] or '1'
        expression = part.source[right[0]:right[1]].strip()
        if not _simple(clean[right[0]:right[1]]) and not re.fullmatch(r'\w*\([^;]*\)', expression):
            expression = f'({expression})'
        start = part.source.rfind('\n', 0, step.start()) + 1
        end = step.end()
        if not part.source[start:step.start()].strip() and part.source[end:end + 1] == '\n':
            end += 1
        else:
            start = step.start()
        sites.append(((right[0], right[1], f' {expression} {operator} {constant}'), (start, end, '')))
    return sites


def _top(text):
    """`text` without what sits inside parentheses or brackets."""
    depth, out = 0, []
    for char in text:
        depth += char in '(['
        depth -= char in ')]'
        if depth == 0:
            out.append(char)
    return ''.join(out)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    out = [edit(source, list(site)) for site in sites[:LIMIT]]
    if len(sites) > 1:
        out.append(edit(source, [one for site in sites for one in site]))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
