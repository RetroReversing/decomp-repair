"""A switch's jump table as wide as the target's range check.

gcc builds a jump table over the cases' lowest to highest value; the game's table can be wider when the source named
values that go to the default code. An N64 function's draft switched over 2..8 (`addiu v1, v0, -2; sltiu v0, v1, 7`)
where the game checked 1..9 (`-1`, `9`): exact with `case 1:` and `case 9:` written on the default arm. Values the
target's check spans beyond the cases are added there.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_range'
FAMILIES = (FAMILY,)

NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'


def ranges(asm):
    """Each jump-table check in the target: (lowest value, count)."""
    found = []
    lines = (asm or '').splitlines()
    for i, line in enumerate(lines):
        check = re.search(r'\bsltiu\s+\$\w+\s*,\s*\$(\w+)\s*,\s*(' + NUMBER + r')', line)
        if not check:
            continue
        low = 0
        for before in reversed(lines[max(0, i - 4):i]):
            bias = re.search(r'\baddiu\s+\$' + check[1] + r'\s*,\s*\$\w+\s*,\s*(' + NUMBER + r')', before)
            if bias:
                low = -int(bias[1], 0)
                break
        found.append((low, int(check[2], 0)))
    return found


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    checks = ranges(asm)
    result = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        head = opening + switch.end() - 1
        block_open = clean.find('{', close(clean, head) or head)
        block_close = close(clean, block_open, '{', '}')
        if not block_close:
            continue
        block = clean[block_open:block_close]
        cases = [int(v, 0) for v in re.findall(r'\bcase\s+(' + NUMBER + r')\s*:', block)]
        default = re.search(r'(?m)^([ \t]*)default\s*:', block)
        if not cases or not default:
            continue
        low, high = min(cases), max(cases)
        for start, count in checks:
            top = start + count - 1
            if start > low or top < high or (start, top) == (low, high) or count > 4 * (high - low + 1) + 8:
                continue
            missing = [v for v in range(start, top + 1) if v not in cases and (v < low or v > high)]
            labels = ''.join(f'{default[1]}case {v}:\n' for v in missing)
            at = block_open + default.start()
            text = source[:at] + labels + source[at:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:2]
