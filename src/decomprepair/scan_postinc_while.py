"""A sentinel scan whose pointer is stepped in the body, written as `while (*p++ != 0)`.

m2c writes a string walk such as a length count as a guard over a `do`, stepping the pointer first:

    if (*p != 0) { do { p += 1; n += 1; } while (*p != 0); }

An optimising gcc rebuilds that (and the plain `while (*p != 0) { p++; n++; }`) as an entry test copied in front of a
bottom-tested loop. Written as `while (*p++ != 0) { n++; }` the exit test steps the pointer itself, and the target is a
jump to that one test with the increment in the bottom branch's delay slot (`j test; move n,0; loop: addiu n,1; test:
lbu; bnez loop; addiu p,1`). Matched on an 8-instruction N64 string length (SN GCC 2.8.1, `-G0 -mips3 -O2`): the
autopilot draft stood at 310 through 16 attempts and this child is 0. Why the compiler keeps the test uncopied is a
hypothesis (the side effect in the condition), not read from its source.

scan_postinc_while
    `if (*p != 0) { do { p += 1; S } while (*p != 0); }` or `while (*p != 0) { p += 1; S }` becomes
    `while (*p++ != 0) { S }`. The new loop leaves `p` one element further, so it is offered only when `p` is a local or
    parameter that is not named after the loop, not named by S, never has its address taken, and the loop is not inside
    another loop. S has no `continue`; a function with `goto` or `volatile` is declined. A candidate for the exact judge.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'scan_postinc_while'
FAMILIES = (FAMILY,)
LIMIT = 4
_TEST = (rf'(?:\*\s*(?P<cast>\(\s*(?:unsigned\s+char|signed\s+char|char|u8|s8|u16|s16)\s*\*\s*\)\s*)?(?P<star>{IDENT})'
         rf'|(?P<index>{IDENT})\s*\[\s*0\s*\])(?:\s*!=\s*0)?')
_GUARD = re.compile(rf'\bif\s*\(\s*(?P<test>{_TEST})\s*\)\s*\{{\s*do\s*\{{')
_WHILE = re.compile(rf'\bwhile\s*\(\s*(?P<test>{_TEST})\s*\)\s*\{{')


def _inside_loop(clean, opening, at):
    """Whether the statement at `at` sits in a loop, or is the braceless body of another statement."""
    before = clean[opening + 1:at].rstrip()
    if before and before[-1] not in ';{}':
        return True
    braces = []
    for hit in re.finditer(r'[{}]', before):
        if hit.group() == '{':
            braces.append(hit.start())
        elif braces:
            braces.pop()
    return any(re.search(r'(?:\bdo|\b(?:for|while)\s*\([^{}]*\))$', before[:brace].rstrip()) for brace in braces)


def _squeeze(text):
    return re.sub(r'\s+', '', text)


def _sites(part, name):
    """(start, end, replacement) of every loop the rewrite applies to, in the source's own positions."""
    clean = part.clean
    signature = clean[:part.opening]
    signature = signature[signature.rfind(name):]
    body = clean[part.opening:part.end]
    for pattern in (_GUARD, _WHILE):
        for hit in pattern.finditer(clean, part.opening + 1, part.end):
            pointer = hit['star'] or hit['index']
            inner = hit.end() - 1
            after_inner = close(clean, inner, '{', '}')
            if after_inner is None:
                continue
            inner_end = after_inner - 1
            if pattern is _GUARD:
                bottom = re.compile(r'\s*while\s*\(\s*([^;{}]+?)\s*\)\s*;\s*\}').match(clean, after_inner)
                if not bottom or _squeeze(bottom[1]) != _squeeze(hit['test']):
                    continue
                end = bottom.end()
            else:
                end = after_inner
            if re.compile(r'\s*else\b').match(clean, end):
                continue
            p = re.escape(pointer)
            statements = clean[inner + 1:inner_end]
            step = re.compile(rf'(?<![\w.>]){p}\s*(?:\+=\s*1|\+\+|=\s*{p}\s*\+\s*1)\s*;|\+\+\s*{p}\s*;')
            steps = list(step.finditer(statements))
            if len(steps) != 1 or re.search(r'\bcontinue\b', statements):
                continue
            first = steps[0]
            ahead = statements[:first.start()].rstrip()
            if (ahead and ahead[-1] not in ';{}') or ahead.count('{') != ahead.count('}'):
                continue
            rest = statements[:first.start()] + statements[first.end():]
            if re.search(rf'(?<![\w.>]){p}\b', rest) or re.search(rf'(?<![\w.>]){p}\b', clean[end:part.end]):
                continue
            declared = re.compile(rf'(?:^|[;{{}}(,])\s*(?!return\b)(?:(?:struct|union|const|unsigned|signed)\s+)*'
                                  rf'{IDENT}\s*\*+\s*{p}\s*[;,=)]')
            if not (declared.search(signature) or declared.search(body)) or _address_taken(body, pointer):
                continue
            if _inside_loop(clean, part.opening, hit.start()):
                continue
            cast = part.source[hit.start('cast'):hit.end('cast')] if hit['cast'] else ''
            source_body = part.source[inner + 1:inner_end]
            kept = source_body[:first.start()].rstrip(' \t') + source_body[first.end():].lstrip(' \t')
            kept = re.sub(r'\n[ \t]*\n', '\n', kept)
            if pattern is _GUARD:
                kept = re.sub(r'\n    ', '\n', kept)
            if not kept.strip():
                line = part.source.rfind('\n', 0, hit.start()) + 1
                kept = '\n' + re.match(r'[ \t]*', part.source[line:])[0]
            yield hit.start(), end, f'while (*{cast}{pointer}++ != 0) {{{kept}}}'


def variants(source, name):
    """[(family, source)]: each scan loop rewritten, and all of them together when there are several."""
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|volatile|asm|__asm__)\b', part.body):
        return []
    sites = sorted(_sites(part, name))[:LIMIT]
    out = [(FAMILY, edit(source, [site])) for site in sites]
    if len(sites) > 1 and all(left[1] <= right[0] for left, right in zip(sites, sites[1:])):
        out.append((FAMILY, edit(source, sites)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
