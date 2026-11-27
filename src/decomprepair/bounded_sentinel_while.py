"""m2c's sentinel scan with a bound, written as the plain `while (A && B)` it stands for.

For `while (buf[i] == K && i < N)` (a leading-digit blanking loop) GCC computes both tests into registers and `and`s
them, so m2c writes the guard on the first element and a `do { } while (A & B)`:

    if ((tab[8] ^ 0x10) == 0) {
        i = 0;
        do { tab[i + 8] = 0; i++; } while (((tab[i + 8] ^ 0x10) == 0) & (i < 4));
    }

bounded_sentinel_while
    `[i = 0;] if (A0) { [i = 0;] do { B } while (A & (i < N)); }` becomes `i = 0; while (A && i < N) { B }` when A0 is
    A with `i` read as 0, `N` is a positive literal (so the bound holds at entry) and nothing in A has a side effect.

Measured on one match (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`): 540 -> 60 on a digit-string drawer, and 230
-> 60 on the state other repairs reached. The `while` form is what gives the target's `move $a3, $zero` before the
guard's load and the loop's copy of the array base. The exact judge decides every child."""
import re

from .c_scan import close, normal
from .integer_repair_support import IDENT, edit, view

FAMILY = 'bounded_sentinel_while'
FAMILIES = (FAMILY,)
LIMIT = 4
_IF = re.compile(r'\bif\s*\(')
_IMPURE = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|(?!sizeof\b)\b[A-Za-z_]\w*\s*\(|\bvolatile\b')
_BLOCKED = re.compile(r'\bgoto\b|\bcase\b|\bdefault\b|\bcontinue\b|\bbreak\b|^\s*[A-Za-z_]\w*\s*:(?!:)', re.M)
_BOUND = re.compile(r'\(?\s*(' + IDENT + r')\s*<\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)?')


def _strip_parens(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text) - 1:
        text = text[1:-1].strip()
    return text


def _split_and(text):
    """The two operands of a top-level `&` (not `&&`) or `&&` of `text`, or None."""
    depth = 0
    found = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '&' and depth == 0:
            width = 2 if text[i:i + 2] == '&&' else 1
            found.append((i, width))
            i += width
            continue
        i += 1
    if len(found) != 1:
        return None
    at, width = found[0]
    return text[:at].strip(), text[at + width:].strip()


def _at_zero(text, counter):
    """`text` with the counter read as 0 and the sums that leaves folded, normalised for comparison."""
    value = re.sub(r'(?<![\w.>])' + counter + r'\b', '0', text)
    value = re.sub(r'\b0\s*\+\s*', '', value)
    value = re.sub(r'\s*\+\s*0\b(?![xX])', '', value)
    return normal(value).replace(' ', '')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        opening = hit.end() - 1
        closing = close(clean, opening, '(', ')')
        if closing < 0:
            continue
        block = re.match(r'\s*\{', clean[closing + 1:])
        if not block:
            continue
        block_open = closing + block.end()
        block_close = close(clean, block_open)
        if block_close < 0 or re.match(r'\s*else\b', clean[block_close + 1:]):
            continue
        inner = re.fullmatch(r'\s*(?:(' + IDENT + r')\s*=\s*0\s*;\s*)?do\s*(\{.*\})\s*while\s*\((.*)\)\s*;\s*',
                             clean[block_open + 1:block_close], re.S)
        if not inner:
            continue
        body_start = block_open + 1 + inner.start(2)
        body_end = close(clean, body_start)
        if body_end != block_open + inner.end(2):
            continue
        test = clean[block_open + 1 + inner.start(3):block_open + 1 + inner.end(3)]
        operands = _split_and(test.strip())
        if not operands or _IMPURE.search(test) or _BLOCKED.search(clean[body_start:body_end]):
            continue
        sentinel, bound = operands
        limit = _BOUND.fullmatch(bound)
        if not limit or int(limit[2], 0) <= 0:
            continue
        counter = limit[1]
        if inner[1] and inner[1] != counter:
            continue
        guard = clean[opening + 1:closing]
        if _IMPURE.search(guard) or _at_zero(_strip_parens(guard), counter) != _at_zero(_strip_parens(sentinel), counter):
            continue
        start = hit.start()
        if not inner[1]:
            before = re.search(r'(?<![\w.>])' + counter + r'\s*=\s*0\s*;\s*$', clean[part.opening:start])
            if not before:
                continue
            start = part.opening + before.start()
        original = source[block_open + 1 + inner.start(3):block_open + 1 + inner.end(3)]
        first, second = _split_and(original.strip())
        loop = f'{counter} = 0; while ({first} && {second}) {source[body_start:body_end + 1]}'
        result.append((FAMILY, edit(source, [(start, block_close + 1, loop)])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
