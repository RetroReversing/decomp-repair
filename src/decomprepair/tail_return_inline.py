"""m2c's result local at the exits, returned directly, and the last two-way exit the other way round.

m2c keeps one result variable and writes every exit through it:

    var = x;                                   if (c1) {
    if (c1) { return var; }                        return x;
    if (!(c2)) { return x - A; }       ->       }
    var = x + B;                                if (c2) {
    return var;                                     return x + B;
                                                }
                                                return x - A;

The result variable is one more value for the allocator, and the exit written last is the one the compiler lays out
last. On a KMC GCC 2.7.2 -O1 arctangent (an N64 function of 115 instructions) the direct returns alone left the score
where it was (425), the exchanged last exits alone made it worse (770), and both together gave 65, the step after
which `float_local_merge` and `default_into_then` finished the match. So the two are offered as one child.

`return_local_inline`: every `V = E; return V;` written `return E;`, and every `V = X; if (c) { return V; }` written
`if (c) { return X; }` when `c` names neither `V` nor `X` and nothing reads `V` before the next time it is set. `V` is
a plain local of the function's own return type, so no conversion is lost. `return_local_inline_flip`: the same, with
a closing `if (c) { return A; } return B;` also written `if (!c) { return B; } return A;`.
"""
import re

from .csource import _blank
from .integer_repair_support import view
from .pattern_repairs import close, negate

FAMILY = 'return_local_inline'
FLIPPED = 'return_local_inline_flip'
FAMILIES = (FAMILY, FLIPPED)

IDENT = r'[A-Za-z_]\w*'
TYPE = r'(?:(?:unsigned|signed)\s+)?[A-Za-z_]\w*[\s*]+'


def _locals(source, clean, name, opening, end):
    """The plain locals declared with the function's own return type."""
    header = re.search(rf'(?m)^[ \t]*(?P<type>{TYPE}?){re.escape(name)}\s*\(', clean[:opening])
    if not header:
        return []
    returned = re.sub(r'\b(?:static|extern|inline)\b|\s', '', header['type'])
    found = []
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<type>{TYPE})(?P<v>{IDENT})\s*;', clean[opening:end]):
        v = hit['v']
        if (re.sub(r'\s', '', hit['type']) == returned and returned != 'void'
                and not re.search(rf'&\s*{v}\b', clean[opening:end])):
            found.append(v)
    return found


def _depth(text):
    return text.count('{') - text.count('}')


def _unread_after(clean, opening, at, end, v):
    """True when the next mention of `v` after `at` sets it afresh on every path, or there is none.

    Only a guard at the function's own level in a body without a `goto` is read: no loop around it, so nothing before
    it runs again, and an assignment inside a later block would not cover the other path.
    """
    if _depth(clean[opening:at]) != 1 or re.search(r'\bgoto\b', clean[opening:end]):
        return False
    mention = re.search(rf'\b{v}\b', clean[at:end])
    if not mention:
        return True
    start = at + mention.start()
    before = clean[:start].rstrip()
    return _depth(clean[at:start]) == 0 and before.endswith((';', '{', '}')) and bool(re.match(rf'{v}\s*=(?!=)\s*(?:(?!\b{v}\b)[^;])*;', clean[start:end]))


def _edits(source, clean, opening, end, v):
    """(start, end, text) of every exit of the local `v` that can be returned directly."""
    edits = []
    direct = rf'(?<![\w.>])\b{v}\s*=(?!=)\s*(?P<e>[^;{{}}]+);\s*return\s+{v}\s*;'
    for hit in re.finditer(direct, clean[opening:end]):
        start, stop = opening + hit.start(), opening + hit.end()
        # the pair must be two statements of one block, not the body of an `if` without braces
        if clean[:start].rstrip().endswith((';', '{', '}')):
            edits.append((start, stop, f"return {source[opening + hit.start('e'):opening + hit.end('e')].strip()};"))
    guarded = (rf'\b{v}\s*=(?!=)\s*(?P<x>{IDENT})\s*;(?P<gap>\s*)if\s*\((?P<c>[^{{}};]*)\)\s*{{'
               rf'(?P<inner>\s*)return\s+(?P<r>{v})\s*;')
    for hit in re.finditer(guarded, clean[opening:end]):
        start = opening + hit.start()
        brace = opening + hit.start() + hit[0].index('{')
        stop = close(clean, brace, '{', '}')
        names = set(re.findall(IDENT, hit['c']))
        if (not stop or v in names or hit['x'] in names or hit['x'] == v
                or clean[opening + hit.end():stop - 1].strip()
                or not clean[:start].rstrip().endswith((';', '{', '}'))
                or re.match(r'\s*else\b', clean[stop:end])
                or not _unread_after(clean, opening, stop, end, v)):
            continue
        edits.append((start, opening + hit.start('gap') + len(hit['gap']), ''))
        edits.append((opening + hit.start('r'), opening + hit.end('r'), hit['x']))
    return edits


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def _flip(source, name):
    """The closing `if (c) { return A; } return B;` with the test inverted and the two values exchanged."""
    part = view(source, name)
    if not part:
        return None
    clean = _blank(source)
    tail = None
    for tail in re.finditer(r'\bif\s*\((?P<c>[^{};]*)\)\s*{\s*return\s+(?P<a>[^;{}]+);\s*}\s*'
                            r'return\s+(?P<b>[^;{}]+);(?=\s*}\s*$)', clean[:part.end]):
        pass
    if not tail or tail.start() < part.opening or re.search(r'\belse\s*$', clean[:tail.start()]):
        return None
    inverse = negate(source[tail.start('c'):tail.end('c')])
    if not inverse:
        return None
    a, b = (source[tail.start(k):tail.end(k)] for k in 'ab')
    return _apply(source, [(tail.start('c'), tail.end('c'), inverse), (tail.start('a'), tail.end('a'), b),
                           (tail.start('b'), tail.end('b'), a)])


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    edits = [edit for v in _locals(source, clean, name, part.opening, part.end)
             for edit in _edits(source, clean, part.opening, part.end, v)]
    if not edits:
        return []
    inlined = _apply(source, edits)
    flipped = _flip(inlined, name)
    return ([(FLIPPED, flipped)] if flipped else []) + [(FAMILY, inlined)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
