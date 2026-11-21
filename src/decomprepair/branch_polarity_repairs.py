"""The other polarity of a branch the compiler lays out by the way the C is written.

gcc 2.7.2 puts the arm a condition falls into right after its test and jumps to the other, so `if (!(x & 0x10)) { A }
else { B }` and `if (x & 0x10) { B } else { A }` are the same program with opposite branch senses (`bnez` over A or
`beqz` over B), and the delay slot, the block order and which arm reaches the join by a jump all follow. m2c writes
the polarity its own control-flow recovery found, and decomp-repair's `branch_orientation` swaps the arms only where
`negate` can invert the condition, which is a bare comparison: never a bit test (`x & 0x10`), a `!`, or `&&`/`||`.

- `polarity_swapped_arms`: a braced `if (c) { A } else { B }` whose condition `negate` can't invert becomes
  `if (!c) { B } else { A }` (a `!(...)` is dropped instead of doubled).
- `polarity_goto_tail`: m2c's `if (c) { T...; goto L; } R...` where R is the rest of the enclosing block and the
  `goto` leaves it becomes `if (!c) { R... } else { T...; goto L; }`: the layout of an N64 actor-update function's
  colour block, where the target puts the shared tail's arm second.
Only conditions with no side effects (no call, `++`, `--` or assignment), no label inside R, and no declaration in R.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'branch_polarity'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def negate_any(condition):
    """`condition` inverted: a comparison flipped, a `!(..)` or `!x` unwrapped, anything else wrapped in `!(..)`."""
    text = condition.strip()
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\b' + IDENT + r'\s*\(', re.sub(r'\b(?:sizeof|M2C_\w+)\s*\(', '(', text)):
        return None  # a side effect or a call: evaluating it once is the program
    if text.startswith('!'):
        inner = text[1:].strip()
        if inner.startswith('(') and close(inner, 0) == len(inner):
            return inner[1:-1].strip()
        if re.fullmatch(r'\w+|\*?\(*\w+(?:->\w+|\[\w+\]|\.\w+)*\)*', inner):
            return inner
    flipped = negate(text)
    if flipped:
        return flipped
    return f'!({text})'


def _block_end(clean, at):
    """Index of the `}` closing the innermost block around `at`, and its `{`."""
    depth = 0
    for pos in range(at, len(clean)):
        if clean[pos] == '{':
            depth += 1
        elif clean[pos] == '}':
            if depth == 0:
                return pos
            depth -= 1
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    result = []

    def add(text):
        if text != source and (FAMILY, text) not in result:
            result.append((FAMILY, text))

    for hit in list(re.finditer(r'\bif\s*\(', clean[opening:end]))[:24]:
        start = opening + hit.start()
        paren = opening + hit.end() - 1
        cond_end = close(clean, paren)
        if not cond_end:
            continue
        cond = source[paren + 1:cond_end - 1]
        arm = re.compile(r'\s*\{').match(clean, cond_end)
        if not arm:
            continue
        a = arm.end() - 1
        b = close(clean, a, '{', '}')
        if not b:
            continue
        other = re.compile(r'\s*else\s*\{').match(clean, b)
        flipped = negate_any(cond)
        if flipped is None:
            continue
        if other:
            c = other.end() - 1
            d = close(clean, c, '{', '}')
            if not d or negate(cond):
                continue  # `branch_orientation` already swaps where a comparison inverts
            text = (source[:paren + 1] + flipped + source[cond_end - 1:a] + source[c:d] + source[b:c]
                    + source[a:b] + source[d:])
            add(text)
            continue
        then = clean[a:b]
        if not re.search(r'\bgoto\s+(' + IDENT + r')\s*;\s*\}$', then):
            continue
        tail_end = _block_end(clean, b)
        rest = clean[b:tail_end] if tail_end else ''
        if not tail_end or not rest.strip() or re.search(rf'(?m)^[ \t]*{IDENT}:|\bcase\b|\bdefault\b', rest) \
                or re.search(r'(?m)^[ \t]*(?:u8|s8|u16|s16|s32|u32|f32|int|char|void)\b[^;()]*;', rest):
            continue
        text = (source[:paren + 1] + flipped + source[cond_end - 1:a] + '{' + source[b:tail_end]
                + '}\n' + ' ' * (start - source.rfind('\n', 0, start) - 1) + 'else ' + source[a:b] + source[tail_end:])
        add(text)
    return result[:6]
