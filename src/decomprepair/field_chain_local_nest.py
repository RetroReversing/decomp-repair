"""A flag word read into a local, then re-read in an `&&` chain of bit tests: the chain on the local, as nested `if`s,
and the body's update of the word through the local too.

    t = *((s32 *) (((char *) v) + 0x24));
    *((s32 *) (((char *) v) + 0xA4)) += step;
    if ((*(..0x24) & 4) && !(t & 0x40000000) && (*(..0x24) & 8)) { *(..0x24) = *(..0x24) & ~4; .. }

as

    if (t & 4) { if (!(t & 0x40000000)) { if (t & 8) { *(..0x24) = t & ~4; .. } } }

KMC GCC 2.7.2 (`-O2`, N64): the store to another field between the read and the tests is a store at a varying
address, so cse reloads the word for every re-read (`lw $v1, 0x24($s1)`), where the target tests one register three
times and updates the word from it (`andi $v0, $a0, 4; ..; and $v0, $a0, $v0`). Written on the local in one `&&`
chain, fold's `fold_truthop` merges the three tests into `(t & 0x4000000c) == 0xc` (one `and`, one `bne`); as nested
`if`s it cannot, and the three branches stay. On a 1315-instruction sound-sequence interpreter's tick tail, 3455 -> 3350
(the nesting alone, without the update through the local, was 3825).

Rewrites the first `if` without `else` after `T = F;` (`F` a field read `*((T *) (((char *) B) + K))`, `T` a local
assigned nowhere between) whose condition is an `&&` chain of two or three terms reading `F` or `T`, when no statement
between writes `F` (stores to other offsets of `B` are other memory) or calls. The body's statements that update `F`
from `F` read `T` while nothing in the body before them wrote `F`.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'field_chain_local_nest'
FAMILIES = (FAMILY,)
LIMIT = 4
_FIELD = r'\*\s*\(\s*\(\s*(?:s32|u32|int)\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{base}\s*\)\s*\+\s*{off}\s*\)\s*\)'


def _python_terms(cond):
    depth, cuts = 0, []
    for at in range(len(cond) - 1):
        depth += (cond[at] in '([') - (cond[at] in ')]')
        if depth == 0 and cond[at:at + 2] == '&&':
            cuts.append(at)
    if not cuts:
        return None
    pieces, start = [], 0
    for cut in cuts:
        pieces.append(cond[start:cut].strip())
        start = cut + 2
    pieces.append(cond[start:].strip())
    return pieces


_terms = _python_terms
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _terms(cond):
        cuts = _scan.and_cuts(cond)
        if not cuts:
            return None
        pieces, start = [], 0
        for cut in cuts:
            pieces.append(cond[start:cut].strip())
            start = cut + 2
        pieces.append(cond[start:].strip())
        return pieces


def _flat(cond):
    terms = _terms(_strip(cond))
    if not terms:
        return None
    out = []
    for term in terms:
        out += _flat(term) or [term]
    return out


def _strip(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    out = []
    reads = re.compile(rf'(?m)^[ \t]*(?P<t>{IDENT})\s*=\s*(?P<f>\*\s*\(\s*\(\s*(?:s32|u32|int)\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*'
                       rf'(?P<base>{IDENT})\s*\)\s*\+\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\))\s*;')
    for found in reads.finditer(clean, lo, hi):
        local, base, off = found['t'], found['base'], found['off']
        field = re.compile(_FIELD.format(base=re.escape(base), off=re.escape(off)))
        guard = re.compile(r'\bif\s*\(').search(clean, found.end(), hi)
        if not guard:
            continue
        between = clean[found.end():guard.start()]
        if re.search(rf'\b{local}\s*=(?!=)|\b[A-Za-z_]\w*\s*\(\s*[^)]*\)\s*;', between) or re.search(field.pattern + r'\s*=(?!=)', between):
            continue
        cond_end = close(clean, guard.end() - 1)
        terms = _flat(source[guard.end():cond_end - 1]) if cond_end else None
        if not terms or len(terms) > 3:
            continue
        arm = re.compile(r'\s*\{').match(clean, cond_end)
        if not arm:
            continue
        a = arm.end() - 1
        b = close(clean, a, '{', '}')
        if not b or re.compile(r'\s*else\b').match(clean, b):
            continue
        new_terms = [field.sub(local, _strip(term)) for term in terms]
        if not all(re.search(rf'\b{local}\b', term) for term in new_terms):
            continue
        body = source[a + 1:b - 1]
        statements = body.split(';')
        written = False
        fixed = []
        for statement in statements:
            target = re.match(r'\s*(' + field.pattern + r')\s*=(?!=)(.*)$', statement, re.S)
            if target and not written:
                statement = statement[:target.end(1)] + ' =' + field.sub(local, target.group(2))
                statement = re.sub(r'=\s*\(s32\)\s*\(\s*\(' + re.escape(local) + r'\)', '= (' + local, statement)
                written = True
            elif re.search(field.pattern + r'\s*=(?!=)', statement):
                written = True
            fixed.append(statement)
        body = ';'.join(fixed)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, guard.start()) + 1:])[0]
        text = ''
        for depth, term in enumerate(new_terms):
            pad = indent + '  ' * depth
            text += ('' if depth == 0 else pad) + f'if ({term})\n{pad}{{\n'
        inner = indent + '  ' * len(new_terms)
        text += inner + body.strip().replace('\n', '\n' + '  ' * (len(new_terms) - 1)) + '\n'
        for depth in reversed(range(len(new_terms))):
            text += indent + '  ' * depth + '}' + ('\n' if depth else '')
        out.append((FAMILY, source[:guard.start()] + text + source[b:]))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
