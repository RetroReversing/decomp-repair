"""m2c's `if (i < n) { do { ... i++; } while (i < n); }`, written back as the `for` loop it came from.

m2c rotates a counted loop into a guard and a `do`/`while`. gcc 2.7.2 rotates a `for` loop the same way, but marks where
the test was moved (`NOTE_INSN_LOOP_VTOP`), and the delay-slot filler (reorg.c `mostly_true_jump`) reads that note: a
branch that skips the body's tail to the counter step and the test is predicted taken, so its slot is filled from the
step (`beql ...; addiu i,i,1`) instead of from the first instruction after it. The rotated `do` has no note and gets
the other fill. A breadth-first walk over three queued levels (an N64 function) was 590 with the second level written
as the m2c `do` and 300 with `for (; i < n; i++)`; the other loop with the same shape did not change.

Offered per loop: the guard and the `while` test are the same text, the last statement of the `do` body steps the
counter named in that test by one, and the body has no `continue` (it would skip the step in the `do`, run it in the
`for`) or `goto`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'guarded_do_for'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'


def _norm(text):
    return re.sub(r'\s+', '', text)


def _step(text):
    """The counter a trailing `i++;` / `++i;` / `i += 1;` / `i = i + 1;` steps, and where the statement starts."""
    for pattern in (rf'({IDENT})\s*\+\+\s*;\s*$', rf'\+\+\s*({IDENT})\s*;\s*$', rf'({IDENT})\s*\+=\s*1\s*;\s*$'):
        hit = re.search(r'(?<![\w.>])' + pattern, text)
        if hit:
            return hit[1], hit.start()
    hit = re.search(rf'(?<![\w.>])({IDENT})\s*=\s*\1\s*\+\s*1\s*;\s*$', text)
    return (hit[1], hit.start()) if hit else (None, None)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for guard in re.finditer(r'\bif\s*\(', clean[span[0]:span[1]]):
        at = span[0] + guard.start()
        end = close(clean, span[0] + guard.end() - 1)
        if end is None:
            continue
        condition = clean[span[0] + guard.end():end - 1]
        opening = re.match(r'\s*\{\s*do\s*\{', clean[end:])
        if not opening:
            continue
        brace = end + opening.end() - 1
        body_end = close(clean, brace, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[body_end:]) if body_end else None
        if not tail:
            continue
        test_open = body_end + tail.end() - 1
        test_end = close(clean, test_open)
        after = re.match(r'\s*;\s*\}', clean[test_end:]) if test_end else None
        if not after or _norm(clean[test_open + 1:test_end - 1]) != _norm(condition):
            continue
        inside = clean[brace + 1:body_end - 1]
        counter, step_at = _step(inside)
        if not counter or not re.search(rf'(?<![\w.>]){counter}\b', condition):
            continue
        if re.search(r'\b(?:continue|goto)\b', inside):
            continue
        body = source[brace + 1:brace + 1 + step_at].rstrip()
        stop = test_end + after.end()
        loop = f'for (; {source[span[0] + guard.end():end - 1].strip()}; {counter}++) {{\n{body}\n}}'
        result.append((FAMILY, source[:at] + loop + source[stop:]))
    return result[:3]
