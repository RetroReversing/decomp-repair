"""The other polarity of a branch the compiler lays out by the way the C is written.

gcc 2.7.2 puts the arm a condition falls into right after its test and jumps to the other, so `if (!(x & 0x10)) { A }
else { B }` and `if (x & 0x10) { B } else { A }` are the same program with opposite branch senses (`bnez` over A or
`beqz` over B), and the delay slot, the block order and which arm reaches the join by a jump all follow. m2c writes
the polarity its own control-flow recovery found, and decomp-repair's `branch_orientation` swaps the arms only where
`negate` can invert the condition, which is a bare comparison: never a bit test (`x & 0x10`), a `!`, or `&&`/`||`.

- `polarity_swapped_arms`: a braced `if (c) { A } else { B }` whose condition `negate` can't invert becomes
  `if (!c) { B } else { A }` (a `!(...)` is dropped instead of doubled).
- Identical negated bit tests are also flipped together, including branches with an else-if arm.
- `polarity_goto_tail`: m2c's `if (c) { T...; goto L; } R...` where R is the rest of the enclosing block and the
  `goto` leaves it becomes `if (!c) { R... } else { T...; goto L; }`: the layout of an N64 actor-update function's
  colour block, where the target puts the shared tail's arm second.
Only conditions with no side effects (no call, `++`, `--` or assignment), no label inside R, and no declaration in R.
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import parse, walk
from .pattern_repairs import close, negate

FAMILY = 'branch_polarity'
FAMILIES = (FAMILY,)
LIMIT = 12  # every `if` is read (a cap of 24 never reached the second half of a 1337-instruction function)

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


def _repeated_flag_variants(source, clean, opening, end):
    """Try identical negated bit tests together, including braceless else-if arms."""
    try:
        function = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    groups = {}
    for stmt, _ in walk(function):
        if stmt.kind != 'if':
            continue
        then, other = stmt.parts['then'], stmt.parts['other']
        if not then['block'] or not other:
            continue
        start, stop = stmt.parts['cond']
        cond = clean[start:stop].strip()
        if not cond.startswith('!(') or not re.search(r'(?<!&)&(?!&)\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\b', cond):
            continue
        if source[start:stop] != clean[start:stop]:
            continue
        flipped = negate_any(cond)
        if not flipped or flipped.startswith('!'):
            continue
        key = re.sub(r'\s+', '', cond)
        groups.setdefault(key, []).append((stmt, then, other, start, stop, flipped))
    proposals = []
    for sites in groups.values():
        if len(sites) < 2 or any(a[0].end > b[0].start for a, b in zip(sites, sites[1:])):
            continue
        text = source
        for stmt, then, other, start, stop, flipped in reversed(sites):
            arm = source[other['open']:other['close']]
            if not other['block']:
                pad = ' ' * (stmt.start - source.rfind('\n', 0, stmt.start) - 1)
                arm = '{\n' + pad + '  ' + arm + '\n' + pad + '}'
            swap = (flipped + source[stop:then['open']] + arm
                    + source[then['close']:other['open']] + source[then['open']:then['close']])
            text = text[:start] + swap + text[stmt.end:]
        proposals.append((FAMILY, text))
    return proposals


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    result = _repeated_flag_variants(source, clean, opening, end)
    tails = []

    def add(text):
        if text != source and (FAMILY, text) not in result:
            result.append((FAMILY, text))

    for hit in list(re.finditer(r'\bif\s*\(', clean[opening:end])):
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
        swap = (flipped + source[cond_end - 1:a] + '{' + source[b:tail_end]
                + '}\n' + ' ' * (start - source.rfind('\n', 0, start) - 1) + 'else ' + source[a:b])
        tails.append((paren + 1, tail_end, swap, _shape(clean[paren:tail_end])))
        add(source[:paren + 1] + swap + source[tail_end:])
    # The same goto tail in two loops of one function (m2c copies a loop per mesh format) is laid out by one rule:
    # alone, each flip changes which arm the other loop's tail cross-jumps with; together they gave 10585 -> 7206
    # (alone 9761 and 10075) on a 1337-instruction KMC GCC 2.7.2 collision sweep. Offer each like-shaped group whole.
    groups = {}
    for tail in tails:
        groups.setdefault(tail[3], []).append(tail)
    combined = []
    for group in groups.values():
        if len(group) < 2 or any(x[1] > y[0] for x, y in zip(group, group[1:])):
            continue
        text = source
        for begin, finish, swap, _ in reversed(group):
            text = text[:begin] + swap + text[finish:]
        if text != source and (FAMILY, text) not in combined:
            combined.append((FAMILY, text))
    return (combined + result)[:LIMIT]


def _shape(text):
    """A branch's text with its names and spacing blotted out: two copies of one statement run compare equal."""
    return re.sub(r'\s+', '', re.sub(r'\b' + IDENT + r'\b', 'x', re.sub(r'\b\d\w*', '0', text)))
