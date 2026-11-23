"""A guarded `do { } while` counted loop, written as the `for` the compiler was given (GCC 2.7.2, KMC, N64).

    if (n > 0) { i = 0; do { BODY i += 1; } while (i < n); }

is how m2c (and the saved bests built on it) spell a loop the game wrote as `for (i = 0; i < n; i++) { BODY }`. The two
compile to the same loop, but not to the same frame: jump.c copies a `for`'s test in front of the loop *before* cse and
the copy leaves stale pseudos that reload gives frame slots, so a function whose counted loop was a `for` has a frame 8
bytes larger than the one with the explicit guard, and every stack row after the prologue differs (a 417-instruction
input handler, 840 -> 770: the frame, the loop counter's register order and the spill slots all matched once the loop
was the `for`; before it the only rows left were stack offsets).

Offered for `if (BOUND > 0) { [declarations] C = 0; do { BODY C += 1; } while (C < BOUND); }` (also `0 < BOUND`, and
`C++;` or `++C;` for the step) when the body has no `continue` (the `for` step would then run where the `do`'s did
not). The `if` goes with its braces; the declarations stay. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_do_to_for'
FAMILIES = (FAMILY,)
_IF = re.compile(r'\bif\s*\(')
_SHAPE = re.compile(
    rf'\A(?P<pre>(?:\s*[A-Za-z_][\w \t*]*;)*)\s*(?P<c>{IDENT})\s*=\s*0\s*;\s*do\s*\{{(?P<body>.*)\}}\s*'
    rf'while\s*\(\s*(?P=c)\s*<\s*(?P<bound>[^;]+?)\s*\)\s*;\s*\Z', re.S)


def _plain(text):
    """The operand with spacing and one layer of outer parentheses ignored."""
    text = re.sub(r'\s+', '', text)
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1]
    return text


def _guarded_bound(cond):
    """BOUND of `BOUND > 0` or `0 < BOUND`, else None."""
    cond = cond.strip()
    for pattern in (r'(?P<b>.+?)\s*>\s*0', r'0\s*<\s*(?P<b>.+)'):
        hit = re.fullmatch(pattern, cond, re.S)
        if hit:
            return hit['b']
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if not shut:
            continue
        bound = _guarded_bound(clean[hit.end():shut - 1])
        block = re.match(r'\s*\{', clean[shut:])
        if bound is None or not block:
            continue
        open_at = shut + block.end() - 1
        end = close(clean, open_at, '{', '}')
        if not end or re.match(r'\s*else\b', clean[end:]):
            continue
        shape = _SHAPE.match(clean[open_at + 1:end - 1])
        if not shape or _plain(shape['bound']) != _plain(bound):
            continue
        counter = shape['c']
        body_at = open_at + 1 + shape.start('body')
        body = clean[body_at:open_at + 1 + shape.end('body')]
        # the step is the body's last statement
        tail = re.search(rf'(?:{IDENT}\s*\+=\s*1|{IDENT}\s*\+\+|\+\+\s*{IDENT})\s*;\s*\Z', body)
        if not tail or counter not in tail[0] or re.search(r'\bcontinue\b', body):
            continue
        main = source[body_at:body_at + tail.start()].rstrip()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:])[0]
        pre = source[open_at + 1:open_at + 1 + shape.end('pre')].strip('\n')
        bound_text = source[hit.end() + clean[hit.end():shut - 1].index(bound):][:len(bound)]
        loop = (f'{indent}  for ({counter} = 0; {counter} < {bound_text}; {counter}++)\n{indent}  {{'
                f'{main}\n{indent}  }}')
        out.append((FAMILY, edit(source, [(hit.start(), end, f'{{\n{pre}\n{loop}\n{indent}}}' if pre.strip() else f'{{\n{loop}\n{indent}}}')])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
