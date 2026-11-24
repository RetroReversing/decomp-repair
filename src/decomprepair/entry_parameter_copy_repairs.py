"""A scalar parameter copied into a local at the top of the function, to change where the entry block is scheduled.

gcc 2.7.2 copies each parameter register into a pseudo at the function's entry, and the second scheduler places
those copies together with the prologue's register saves. A parameter that is also modified, or that the game copied
into a local (`idx = arg1;`), has a second pseudo beside it, and that moves the copy past the first statements. A
twenty-statement N64 camera function was exact once `arg1` became a local assigned from the parameter right after its
first load; before that, the register saves of its prologue came out in another order (`sw $s5` ahead of `sw $ra`)
and nothing else differed (40 to 0). m2c never writes such a copy for a parameter it only reads, so nothing else
proposes one (`parameter_copy_drop` is the opposite rewrite).

`entry_parameter_clobber` is the same copy followed by `NAME_in = 0;`. A plain copy is optimised away: cse replaces the
local by the parameter and the parameter's own entry copy (`move $s2, $a3`) stays above the first statement, so the copy
never moves. Overwriting the parameter after the copy leaves cse no later use to propagate into, the local keeps its own
`move` after the function's first statement, and the second scheduler (which places the prologue's saves and the copy by
original order) puts it after the first call's `li $a0` (hypothesis from `cc1 -dS -dR` dumps, not confirmed in the
compiler source). A 150-instruction N64 effect spawner (KMC GCC 2.7.2) whose target had `move $s6,$a0; li $a0,0x50;
sw $s2; move $s2,$a3` ahead of its first call was 60 with the plain copy (no change) and exact (0) with the clobber; the
dead store is deleted, so nothing else in the code moves. Offered where the copy is (top of the body, the wrapper, and
after each plain statement).

Offered for each scalar or pointer parameter that is read at least twice and never has its address taken (the fifth and
later parameters, which o32 passes on the stack and a target often loads after other stores, as much as the first four;
reads of the parameter ahead of the copy keep the parameter's own name): the
signature takes `NAME_in`, a local called NAME is declared, and `NAME = NAME_in;` goes at the top of the entry block
or after each of its first three plain statements (the entry block is the function body, or the body of a
`do { ... } while (0)` that wraps it). The judge decides.
"""
import re
from itertools import zip_longest

from .integer_repair_support import IDENT, edit, view

FAMILY = 'entry_parameter_copy'
CLOBBER = 'entry_parameter_clobber'
FAMILIES = (FAMILY, CLOBBER)
LIMIT = 8
PER_FAMILY = 24
TYPE = r'(?:(?:unsigned|signed|const)\s+)*[A-Za-z_]\w*(?:\s*\*)*'
CONTROL = re.compile(r'\b(?:if|else|for|while|do|switch|case|default|return|goto|break|continue)\b')


def _parameters(part):
    """(offset of the name, name, type) of each parameter, or nothing for a list this does not read."""
    signature = re.search(r'\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not signature or signature[1].strip() in ('', 'void'):
        return []
    found, position = [], signature.start(1)
    for piece in signature[1].split(','):
        match = re.fullmatch(rf'\s*({TYPE})\s*({IDENT})\s*', piece)
        if not match:
            return []
        found.append((position + match.start(2), match[2], match[1].strip()))
        position += len(piece) + 1
    return found


def _matching(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return None


def _after_declarations(clean, cursor, end):
    """The offset past the leading declarations, which stay first (a function-pointer local, `T (*f)(void *);`, is one:
    m2c writes the callee it calls through that way, and a copy placed above it did not compile)."""
    while True:
        match = re.match(rf'\s*(?:typedef\b[^;]*?{{[^{{}}]*}}\s*{IDENT}\s*;|{TYPE}\s+\**\s*{IDENT}\b[^;(){{}}=]*(?:=[^;(){{}}]*)?;'
                         rf'|{TYPE}\s*\(\s*\*\s*{IDENT}\s*\)\s*\([^;(){{}}]*\)\s*;)',
                         clean[cursor:end])
        if not match or CONTROL.match(match.group().strip()):
            return cursor
        cursor += match.end()


def _after_statements(clean, cursor, end):
    """The offsets after each of the first three plain statements, with no call or control flow among them."""
    places = []
    for _ in range(3):
        match = re.match(r'\s*([^;{}]*);', clean[cursor:end])
        if not match or CONTROL.search(match[1]) or re.search(r'\w\s*\(', match[1]):
            break
        cursor += match.end()
        places.append(cursor)
    return places


def _insertions(part):
    """Where a copy may go: at the top of the body, and in the `do { } while (0)` wrapper m2c-style sources carry."""
    clean = part.clean
    end = clean.rfind('}', 0, part.end)
    top = _after_declarations(clean, part.opening + 1, end)
    places = [top]
    wrapper = re.match(r'\s*do\s*{', clean[top:end])
    if wrapper:
        inner = top + wrapper.end()
        closing = _matching(clean, inner - 1)
        if closing is not None and re.fullmatch(r'\s*while\s*\(\s*0\s*\)\s*;?\s*', clean[closing + 1:end]):
            first = _after_declarations(clean, inner, closing)
            places += [first] + _after_statements(clean, first, closing)
            return places
    return places + _after_statements(clean, top, end)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    plain, clobbers = [], []
    places = _insertions(part)
    body = part.body
    for where, param, kind in _parameters(part):
        if (len(re.findall(rf'(?<![\w.>]){param}\b', body)) < 2 or re.search(rf'&\s*{param}\b', body)
                or re.search(rf'\b{param}_in\b', part.clean)):
            continue
        own, own_clobbers = [], []
        for place in places:
            # A read ahead of the copy sees the parameter, not the local the copy has not filled yet.
            earlier = [(part.opening + 1 + hit.start(), part.opening + 1 + hit.end(), f'{param}_in')
                       for hit in re.finditer(rf'(?<![\w.>]){param}\b', part.clean[part.opening + 1:place])]
            edits = [(where, where + len(param), f'{param}_in'),
                     (part.opening + 1, part.opening + 1, f'\n  {kind} {param};'),
                     (place, place, f'\n  {param} = {param}_in;')] + earlier
            own.append((FAMILY, edit(source, edits)))
            edits[2] = (place, place, f'\n  {param} = {param}_in;\n  {param}_in = 0;')
            own_clobbers.append((CLOBBER, edit(source, edits)))
        plain.append(own)
        clobbers.append(own_clobbers)
    return _interleaved(plain)[:PER_FAMILY] + _interleaved(clobbers)[:PER_FAMILY]


def _interleaved(per_parameter):
    """The children place by place across the parameters, so a cap keeps every parameter's first places: a parameter-by-
    parameter order ran out at the second parameter, and the stack-passed fifth one (read by the target after three
    stores to another argument, 60 -> 0) was never offered."""
    return [kid for row in zip_longest(*per_parameter) for kid in row if kid]
