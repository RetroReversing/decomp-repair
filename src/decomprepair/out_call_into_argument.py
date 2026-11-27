"""Calls that fill an outer call's by-value arguments, written inside its argument list as comma expressions.

    sub(&u, &b, &a);
    sub(&v, &c, &a);
    n = cross(u, v);

becomes `n = cross((sub(&u, &b, &a), u), (sub(&v, &c, &a), v));`. The program is the same (the order of the calls is
kept), but GCC 2.7.2 works out where a structure result goes before it expands the arguments, so the address of `n` is
computed before the first of the helper calls, takes its place among the other addresses and the saved registers
follow. Measured on a 261-instruction N64 visibility test of four such groups (KMC GCC 2.7.2, `-G0 -mips3 -O1`): 340
with the separate statements, 0 with all four folded. That this order comes from `expand_call` handling the result's
address first is a hypothesis read from the target's instructions.

A site is a statement holding one call with at least one argument that is a bare variable `v`, preceded directly by
statements `helper(&v, ...);` for such variables, in the arguments' own order. Only calls whose first argument is that
address are folded, and only when no other argument of the outer call is named by them (the order of evaluation of the
arguments is not fixed by C, so nothing else may depend on it). One child folds every site, then one per site.
"""
import re

from .call_site_prototype_repairs import split_args
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FOLDED = 'out_call_into_argument'
FAMILIES = (FOLDED,)
LIMIT = 8
_MARK = re.compile(r'[{};()\[\]]')
_KEYWORDS = ('sizeof', 'if', 'for', 'while', 'switch', 'return', 'do', 'else', 'case', 'goto')


def _split(text, opening):
    """(start, end) of each argument of the call whose parenthesis opens at `opening`, and where it closes."""
    past = close(text, opening, '(', ')')
    if past is None:
        return None, None
    stop = past - 1
    spans, at = [], opening + 1
    for argument in split_args(text[opening + 1:stop]):
        begin = text.index(argument, at)
        spans.append((begin, begin + len(argument)))
        at = begin + len(argument)
    return spans, stop


def _statements(clean, begin, end):
    """(start, stop) of each simple statement of each block, grouped in runs of neighbours."""
    run, start, depth = [], begin, 0
    for hit in _MARK.finditer(clean, begin, end):
        char, at = hit[0], hit.start()
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0:
            if char == ';' and clean[start:at].strip():
                run.append((start, at))
            elif run:
                yield run
                run = []
            start = at + 1
    if run:
        yield run


def _out_call(clean, span):
    """The variable `v` of a statement that is only `helper(&v, ...)`, or None."""
    text = clean[span[0]:span[1]]
    hit = re.match(rf'\s*({IDENT})\s*\(', text)
    if not hit or hit[1] in _KEYWORDS:
        return None
    arguments, close = _split(clean, span[0] + hit.end() - 1)
    if not arguments or clean[close + 1:span[1]].strip():
        return None
    first = re.fullmatch(rf'\s*&\s*({IDENT})\s*', clean[arguments[0][0]:arguments[0][1]])
    return first[1] if first else None


def _outer(clean, span):
    """Argument spans of the one outer call of `x = f(a, b)` or `f(a, b)`."""
    text = clean[span[0]:span[1]]
    hit = re.match(rf'\s*(?:{IDENT}(?:\s*(?:\.|->)\s*{IDENT}|\s*\[[^\]]*\])*\s*=\s*)?({IDENT})\s*\(', text)
    if not hit or hit[1] in _KEYWORDS:
        return None
    arguments, close = _split(clean, span[0] + hit.end() - 1)
    if not arguments or clean[close + 1:span[1]].strip():
        return None
    return arguments


def _site(source, clean, run, at):
    """The edits that fold the calls before statement `run[at]` into its arguments, or None."""
    arguments = _outer(clean, run[at])
    if not arguments:
        return None
    names = []
    for start, end in arguments:
        bare = re.fullmatch(rf'\s*({IDENT})\s*', clean[start:end])
        names.append(bare[1] if bare else None)
    folded, back = [], at - 1
    for index in range(len(arguments) - 1, -1, -1):
        if back >= 0 and names[index] and names.count(names[index]) == 1 and _out_call(clean, run[back]) == names[index]:
            folded.append((index, back))
            back -= 1
    if not folded:
        return None
    helpers = ' '.join(clean[run[i][0]:run[i][1]] for _, i in folded)
    taken = {index for index, _ in folded}
    for index, (start, end) in enumerate(arguments):
        if index not in taken:
            if re.search(r'\b\w+\s*\(|\+\+|--|=', clean[start:end]):
                return None
            if any(re.search(rf'\b{word}\b', helpers) for word in re.findall(rf'\b{IDENT}\b', clean[start:end])):
                return None
    # a helper must not read another folded variable: its value would depend on the order of the arguments
    for index, i in folded:
        others = [names[j] for j, _ in folded if j != index]
        if any(re.search(rf'\b{other}\b', clean[run[i][0]:run[i][1]]) for other in others):
            return None
    edits = []
    for index, i in folded:
        start, end = run[i]
        call = source[start:end].strip()
        a, b = arguments[index]
        lead = source[a:b][:len(source[a:b]) - len(source[a:b].lstrip())]
        edits.append((a, b, f'{lead}({call}, {names[index]})'))
        cut = start
        while cut > 0 and source[cut - 1] in ' \t':
            cut -= 1
        if cut > 0 and source[cut - 1] == '\n':
            cut -= 1
        else:
            cut = start
        edits.append((cut, end + 1, ''))
    return edits


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    sites = []
    for run in _statements(part.clean, part.opening + 1, part.end - 1):
        for at in range(1, len(run)):
            found = _site(source, part.clean, run, at)
            if found:
                sites.append(found)
    sites = sites[:LIMIT]
    results = []
    if len(sites) > 1:
        results.append((FOLDED, edit(source, [item for site in sites for item in site])))
    results += [(FOLDED, edit(source, site)) for site in sites]
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
