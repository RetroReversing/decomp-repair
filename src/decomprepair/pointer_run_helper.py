"""The statements that work on one freshly built pointer, written as a `static inline` helper that takes it.

An N64 sound player's note routine (KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`, 347 instructions) builds a pointer to
the note's envelope record and then copies its seven bytes into the channel, with three float divisions. Written in
place (`env = &song->envelopes[i];` and the reads through `env`) the candidate was 395: the first read used the pointer's
own register. The target forms the address in `$v0`, reads the first byte through it and copies it to `$a1` in the
branch's delay slot, which the later reads use. The same lines as a `static inline` function that takes the pointer and
copies its parameter into a local were 15, and exact with one more step another family has
(`cfg_integer_lifetimes`); with the parameter used directly they stayed at 310. A copy in a block of the function itself
reached 35. Why the helper's own copy survives (integrate.c gives the parameter a pseudo of its own and cse keeps
reading the first value through the older one) is a hypothesis, not confirmed in the compiler source.

`pointer_run_helper`
    For `p = E;` (p a local pointer, E without a call), the statements after it in its block up to the last that names
    `p` or a value those statements left in a local, when nothing else reads `p`. They become a helper that takes the
    pointer: `helper(.., E);`. Two children per pointer, the copying form (`T *p = p_in;` first in the helper) and the
    parameter used directly. Locals only the run needs move into the helper, as in `repeated_run_helper`, whose rules
    for what moves are used; a run that would need a value passed by address is left alone. A run with `goto`, a label, `return`, `break` or `continue` is
    left alone. The exact judge decides.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, view
from .repeated_run_helper import _blocks, _declared, _parameters, _variants

FAMILY = 'pointer_run_helper'
FAMILIES = (FAMILY,)
POINTERS = 3        # how many pointers are offered
STATEMENTS = 3      # a shorter run is not worth a function


def _mentions(text, word):
    return re.search(r'(?<![\w.>])' + re.escape(word) + r'\b', text)


def _made_first(run, word):
    first = _mentions(run, word)
    return bool(first and re.compile(r'\s*=(?!=)').match(run, first.end()))


def _last(clean, rows, first, pointer, locals_):
    """The index of the last statement of the run that starts at `first`, or None when the pointer is not read."""
    reads = [n for n in range(first, len(rows)) if _mentions(clean[rows[n][0]:rows[n][1]], pointer)]
    if not reads or re.match(re.escape(pointer) + r'\s*=(?!=)', clean[rows[reads[-1]][0]:rows[reads[-1]][1]]):
        return None
    last = reads[-1]
    n = last + 1
    while n < len(rows):
        text = clean[rows[n][0]:rows[n][1]]
        run = clean[rows[first][0]:rows[last][1]]
        # the temporaries the run makes: locals its first mention of them assigns
        carried = [w for w in locals_ if w != pointer and _made_first(run, w)]
        used = [w for w in carried if _mentions(text, w)]
        if used and not all(re.match(w + r'\s*=(?!=)(?![^;]*\b' + w + r'\b)', text) for w in used):
            last = n
        elif used:
            break
        n += 1
    return last


def variants(source, name):
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    clean = part.clean
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:part.opening])
    if not head:
        return []
    parameters = _parameters(clean, span[0], part.opening, name)
    locals_ = _declared(clean[part.opening:part.end])
    results, offered = [], 0
    for rows in _blocks(clean, part.opening, part.end):
        for n, (start, stop) in enumerate(rows):
            made = re.fullmatch(r'(?P<p>' + IDENT + r')\s*=(?!=)\s*(?P<e>[^;{}]+?)\s*;', clean[start:stop])
            if not made:
                continue
            pointer = made['p']
            entries = locals_.get(pointer)
            if not entries or len(entries) != 1 or not entries[0][0].rstrip().endswith('*'):
                continue
            value = source[start + made.start('e'):start + made.end('e')]
            # a call (a name before a parenthesis that is not `sizeof`) must not move, nor an assignment inside
            if (re.search(r'(?<![\w])(?!sizeof\b)' + IDENT + r'\s*\(', made['e']) or _mentions(made['e'], pointer)
                    or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', made['e'])):
                continue
            last = _last(clean, rows, n + 1, pointer, locals_)
            if last is None or last - n < STATEMENTS:
                continue
            low, high = rows[n + 1][0], rows[last][1]
            rest = clean[part.opening:start] + clean[stop:low] + clean[high:part.end]
            rest = re.sub(r'(?<![\w.>])' + pointer + r'\s*;', '', rest, count=1)
            if _mentions(rest, pointer):
                continue
            children = _children(source, name, clean, span, part, (start, stop), (low, high), pointer,
                                 entries[0][0].strip(), value, parameters, locals_)
            results.extend((FAMILY, child) for child in children)
            offered += bool(children)
            if offered == POINTERS:
                return results
    return results


def _children(source, name, clean, span, part, assignment, run, pointer, kind, value, parameters, locals_):
    made = _variants(source, name, clean, span, part, [run], parameters, locals_, 'void')
    if not made:
        return []
    child = made[0]
    helper = next((m[1] for m in re.finditer(r'static inline void (' + IDENT + r')\(', child)
                   if not re.search(r'\b' + m[1] + r'\b', source)), None)
    if not helper:
        return []
    call = None
    for hit in re.finditer(r'(?<!void )\b' + helper + r'\(([^()]*)\);', child):
        call = hit
    if not call:
        return []
    arguments = [a.strip() for a in call[1].split(',')]
    # a value the run changes for its caller (passed by address) is not this shape
    if pointer not in arguments or any(a.startswith('&') for a in arguments):
        return []
    arguments[arguments.index(pointer)] = value
    child = child[:call.start()] + f'{helper}({", ".join(arguments)});' + child[call.end():]
    # the assignment and the pointer's declaration go
    original = source[assignment[0]:assignment[1]]
    body = child.index(f'{helper}({", ".join(arguments)});')
    at = child.rfind(original, 0, body)
    if at < 0:
        return []
    line = child.rfind('\n', 0, at) + 1
    finish = at + len(original)
    if not child[line:at].strip() and child[finish:finish + 1] == '\n':
        at, finish = line, finish + 1
    child = child[:at] + child[finish:]
    opening = view(child, name)
    if not opening:
        return []
    declaration = re.compile(r'^[ \t]*' + re.escape(kind.rstrip('* ')) + r'\s*\*+\s*' + pointer + r'\s*;[ \t]*\n', re.M)
    found = declaration.search(child, opening.opening)
    if found and len(re.findall(r'(?<![\w.>])' + pointer + r'\b', child[opening.opening:opening.end])) == 1:
        child = child[:found.start()] + child[found.end():]
    definition = re.search(r'static inline void ' + helper + r'\((?P<signature>[^()]*)\)\n\{\n', child)
    if not definition:
        return []
    inner = f'{pointer}_in'
    signature = re.sub(r'\b' + pointer + r'\b', inner, definition['signature'])
    copy = f'  {kind}{"" if kind.endswith("*") else " "}{pointer} = {inner};\n'
    copied = (child[:definition.start('signature')] + signature + child[definition.end('signature'):definition.end()]
              + copy + child[definition.end():])
    return [copied, child]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # the registry: no caller wiring (registry.py)
