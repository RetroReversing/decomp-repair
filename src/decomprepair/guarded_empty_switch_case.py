"""Offer an empty final case when a target jump-table guard proves a larger range than the C switch.

A MIPS GCC function's eight-entry table dispatched cases 0 through 7, but m2c omitted the last three cases because
all went to the default. Its four explicit cases compiled to a five-entry table. Adding the empty `case 7: break;`
retained the behavior and restored the target's `sltiu` bound; in the enclosing function it improved the exact
judge from 54,270 to 54,120 at GCC 2.7.2 KMC -G0 -mips3 -mgp32 -mfp32 -O2, and from 12,085 to 11,935
in a diagnostic -O1 trial (one function, not a match).

Only a direct guarded table load and indirect jump supply a bound. If a function has several switches, offer each
compatible bound as a separate child: a bound by itself does not identify which C switch it belongs to. The new case
shares the existing default's body, or does nothing when there is no default, so the program's behavior is unchanged.
"""
import re

from .integer_repair_support import view
from .switch_empty_case import _CASE, _OTHER_CASE, _switches

FAMILY = 'guarded_empty_switch_case'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 24
MAX_BOUND = 256


def bounds(asm):
    """Counts proved by straight-line `sltiu; beqz; sll; lui; addu; lw; jr` dispatches."""
    lines = []
    for line in (asm or '').splitlines():
        line = re.sub(r'^\s*(?:/\*.*?\*/\s*)?', '', line).strip()
        if not line or line.endswith(':') or line.startswith(('glabel ', 'endlabel ', 'nonmatching ')):
            lines.append('')  # preserve block boundaries
        else:
            lines.append(re.sub(r'\s*,\s*', ', ', re.sub(r'\s+', ' ', line)))
    found = set()
    for i in range(len(lines) - 6):
        guard = re.fullmatch(r'sltiu \$(\w+), \$(\w+), (0x[0-9a-fA-F]+|\d+)', lines[i])
        if not guard:
            continue
        result, index, count = guard.groups()
        if result in (index, 'at'):
            continue
        branch, shift, high, add, load, jump = list(lines[i + 1:i + 7])
        if not re.fullmatch(rf'beqz \${result}, \S+', branch):
            continue
        if not re.fullmatch(rf'sll \${result}, \${index}, (?:2|0x2)', shift):
            continue
        table = re.fullmatch(r'lui \$at, %hi\((\w+)\)', high)
        if not table or not re.fullmatch(rf'addu \$at, \$at, \${result}', add):
            continue
        dest = re.fullmatch(rf'lw \$(\w+), %lo\({table[1]}\)\(\$at\)', load)
        if not dest or not re.fullmatch(rf'jr \${dest[1]}', jump):
            continue
        size = int(count, 16 if count.lower().startswith('0x') else 10)
        if 3 <= size <= MAX_BOUND:
            found.add(size)
    return sorted(found)


def variants(source, name, asm):
    counts = bounds(asm)
    part = view(source, name) if counts else None
    if not part:
        return []
    out = []
    for brace, end, body in _switches(part):
        matches = _CASE.findall(body)
        values = {int(v, 0) for v in matches}
        if not values or min(values) < 0 or len(matches) != len(_OTHER_CASE.findall(body)):
            continue
        default = re.search(r'(?<![\w])default\s*:', body)
        for count in counts:
            # Relabel an out-of-range no-op into a missing table slot. Both values
            # previously take the implicit no-op default, so behavior is unchanged.
            outside = [v for v in values if v >= count]
            if len(outside) == 1 and not default:
                for empty in re.finditer(r'(?<![\w])case\s+(-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*:\s*break\s*;', body):
                    if int(empty.group(1), 0) != outside[0]:
                        continue
                    start, stop = brace + empty.start(1), brace + empty.end(1)
                    for missing in range(count):
                        if missing not in values:
                            out.append((FAMILY, source[:start] + str(missing) + source[stop:]))
                            if len(out) >= MAX_CHILDREN:
                                return out
            value = count - 1
            if value in values or max(values) >= value:
                continue
            label = f'case {value}:'
            if default:
                at, text = brace + default.start(), label + ' '
            else:
                at = end
                before = body.rstrip()
                prefix = '' if re.search(r'(?:\bbreak|\bcontinue|\breturn\b[^;{}]*|\bgoto\s+\w+)\s*;$', before) else 'break; '
                text = prefix + label + ' break; '
            out.append((FAMILY, source[:at] + text + source[at:]))
            if len(out) >= MAX_CHILDREN:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 1500}
