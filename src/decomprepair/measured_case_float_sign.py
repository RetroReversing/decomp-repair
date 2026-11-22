"""Exchange two case-local float signs when the MIPS diff shows the reverse pair."""
import re
import struct

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'measured_case_float_sign'
_HIGH = re.compile(r'lui\s+(\$\w+),\s*0x([\da-fA-F]+)')
_ARM = re.compile(
    rf'\bcase\s+(?:0[xX][\da-fA-F]+|\d+)\s*:\s*({IDENT})\s*=\s*'
    r'(-?(?:(?:\d+\.\d*|\.\d+)(?:e[+-]?\d+)?|\d+e[+-]?\d+)f)\s*;',
    re.I,
)


def _observed_pair(rows):
    changes = []
    for index, (kind, target, candidate) in enumerate(rows[:-2]):
        if kind != 'i' or not (left := _HIGH.fullmatch(target)) or not (right := _HIGH.fullmatch(candidate)):
            continue
        a, b = int(left[2], 16), int(right[2], 16)
        if left[1] != right[1] or a ^ b != 0x8000:
            continue
        after = rows[index + 1:index + 3]
        if any(marker != ' ' or before != current for marker, before, current in after):
            continue
        reg = re.escape(left[1])
        lo = re.fullmatch(rf'ori\s+{reg},\s*{reg},\s*0x([\da-fA-F]+)', after[0][1])
        if lo and re.fullmatch(rf'mtc1\s+{reg},\s*\$f\w+', after[1][1]):
            low = int(lo[1], 16)
            changes.append((a << 16 | low, b << 16 | low))
    if len(changes) != 2 or changes[0] != changes[1][::-1]:
        return set()
    return set(changes[0])


def variants(source, name, rows):
    observed = _observed_pair(rows)
    part = view(source, name) if observed else None
    if not part:
        return []
    pairs = []
    for switch in re.compile(r'\bswitch\s*\(').finditer(part.clean, part.opening, part.end):
        condition_end = close(part.clean, switch.end() - 1)
        if not condition_end or not (brace := re.match(r'\s*\{', part.clean[condition_end:])):
            continue
        opening = condition_end + brace.end() - 1
        end = close(part.clean, opening, '{', '}')
        if not end:
            continue
        by_name = {}
        for arm in _ARM.finditer(part.clean, opening + 1, end - 1):
            preceding = part.clean[opening + 1:arm.start()]
            if preceding.count('{') != preceding.count('}'):
                continue
            try:
                bits = int.from_bytes(struct.pack('>f', float(arm[2][:-1])), 'big')
            except (ValueError, OverflowError):
                continue
            if bits in observed:
                by_name.setdefault(arm[1], []).append((bits, arm))
        for sites in by_name.values():
            if len(sites) == 2 and {bits for bits, _ in sites} == observed:
                pairs.append([(*arm.span(2), arm[2][1:] if arm[2].startswith('-') else '-' + arm[2])
                              for _, arm in sites])
    return [(FAMILY, edit(source, pairs[0]))] if len(pairs) == 1 else []
