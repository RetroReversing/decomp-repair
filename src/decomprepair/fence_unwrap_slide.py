"""A one-statement `do { } while (0)` fence opened, and the statement it held slid past its neighbours, as one child.

A search that could not move a statement often wraps it in a fence instead: the fence adds loop-depth weight and a
scheduling boundary, and that can pay for itself where the statement sits. Opened alone, the statement is worse again;
slid alone it cannot move, because `statement_slide` moves simple statements and a fence is not one. In a KMC GCC 2.7.2
`-O2 -fno-expensive-optimizations` N64 function (49 instructions, a chunked transfer loop) the saved best held
`do { total = 0; } while (0);` above the first call: opened in place it scored 445, the fence 60, and the plain
`total = 0;` after the call 0. Above the call the constant was the nearest earlier insn to the `jal`, so reorg filled
the call's delay slot with it; below it the slot took the prologue's last register save, as the target has. Two steps
that a greedy chain cannot take one at a time, so they are one child here. A hypothesis like every family's; the judge
decides.

Children (`fence_unwrap_slide`): for each fence holding one simple statement (an assignment or `x += k;`, no call, no
braces), `statement_slide`'s children of the opened source that move that statement or move a neighbour across it,
shortest slides first, at most `LIMIT`.
"""
import re

from . import statement_slide
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'fence_unwrap_slide'
FAMILIES = (FAMILY,)
LIMIT = 8

FENCE = re.compile(r'(?m)^(?P<indent>[ \t]*)do[ \t]*\{[ \t]*(?P<body>[^{};\n]*;)[ \t]*\}[ \t]*'
                   r'while[ \t]*\([ \t]*0[ \t]*\)[ \t]*;[ \t]*$')
SIMPLE = re.compile(r'\s*[A-Za-z_]\w*(?:\s*(?:\[[^\[\]]*\]|->\s*\w+|\.\s*\w+))*\s*(?:[-+*/&|^]|<<|>>)?=\s*[^;(){}]*;\s*$')


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out, seen = [], set()
    for fence in FENCE.finditer(clean, opening, end):
        body = source[fence.start('body'):fence.end('body')]
        if not SIMPLE.match(body) or '==' in body:
            continue
        # the indent of the source line: a marker comment before `do` is blanked into the match's indent
        line = re.match(r'[ \t]*', source[fence.start():]).group() + body.strip()
        opened = source[:fence.start()] + line + source[fence.end():]
        index = opened[:fence.start()].count('\n')
        for child in statement_slide.variants(opened, name, header):
            text = child[1] if isinstance(child, tuple) else child
            lines = text.split('\n')
            if text == opened or text in seen or (index < len(lines) and lines[index] == line):
                continue
            seen.add(text)
            out.append((FAMILY, text))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
