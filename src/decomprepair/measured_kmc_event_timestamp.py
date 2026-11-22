"""Propose a target-led event initialization order for KMC-generated MIPS."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'lw \$v0, 8\(\$s0\)\nlw \$v1, 28\(\$s1\)\nlw \$a0, 216\(\$v0\)\n'
    r'addiu \$v0, \$zero, (?P<code>\d+)\nsh \$v0, 8\(\$a2\)\n'
    r'(?:andi \$v0, \$s2, 255\nsw \$v0, 12\(\$a2\)|swc1 \$f20, 12\(\$a2\))\n'
    r'sw \$zero, \(\$a2\)\naddu \$v1, \$v1, \$a0\nsw \$v1, 4\(\$a2\)'
)


def _pattern(order):
    event = rf'(?P<event>{IDENT})'
    fields = {
        'type': rf'M2C_FIELD\(@, s16 \*, 8\)\s*=\s*(?P<code>{NUMBER})\s*;',
        'next': r'M2C_FIELD\(@, s32 \*, 0\)\s*=\s*0\s*;',
        'payload': rf'M2C_FIELD\(@, (?P<kind>s32|f32) \*, (?:0x[Cc]|12)\)\s*=\s*'
                   rf'(?P<value>\(s32\)\s*\((?P<intarg>{IDENT})\s*&\s*0xFF\)|(?P<floatarg>{IDENT}))\s*;',
        'time': rf'M2C_FIELD\(@, s32 \*, 4\)\s*=\s*(?P<expr>\(s32\)\s*\('
                rf'M2C_FIELD\((?P<clock>{IDENT}), s32 \*, 0x1[Cc]\)\s*\+\s*'
                rf'M2C_FIELD\(M2C_FIELD\((?P<voice>{IDENT}), void \*\*, 8\), s32 \*, 0x[Dd]8\)\))\s*;',
    }
    parts = []
    for field in order:
        parts.append(f'(?P<{field}>' + fields[field].replace('@', event) + ')')
        event = r'(?P=event)'
    return re.compile(r'\s*'.join(parts))


_PATTERNS = [_pattern(order) for order in (('payload', 'time', 'type', 'next'),
                                          ('type', 'next', 'time', 'payload'))]


def variants(source, name, header, rows):
    if not 30 <= len(rows) <= 45:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    hit = _TARGET.search(target)
    if not hit:
        return []
    candidate = normalized_integer_lines(right for _, _, right in rows if right)
    calls = [i for i, line in enumerate(candidate) if line.startswith('jal ')]
    if not calls or not any(re.fullmatch(r'(?:sh \$v0, 8|sw \$v0, 12)\(\$a2\)', line)
                            for line in candidate[calls[0]:calls[0] + 8]):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|__repair_time)\b', part.clean):
        return []
    part.end = end
    draft = next((m for pattern in _PATTERNS if (m := pattern.search(part.body))), None)
    if not draft or integer(draft['code']) != int(hit['code']):
        return []
    arg = draft['intarg'] or draft['floatarg']
    kind = 's32' if draft['intarg'] else 'f32'
    if draft['kind'] != kind:
        return []
    sig = re.search(rf'\bvoid {re.escape(name)}\(void \*({IDENT}), void \*({IDENT}), '
                    rf'{kind} ({IDENT})\)\s*$', part.clean[:part.opening])
    if not sig or sig.groups() != (draft['clock'], draft['voice'], arg):
        return []
    if len({draft['clock'], draft['voice'], arg, draft['event']}) != 4:
        return []
    start = part.opening + 1
    original = source[start + draft.start():start + draft.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    # This is a target-led hypothesis: staging reads can change behavior if the
    # allocated event aliases its inputs. Only the byte judge can accept it.
    line_start = source.rfind('\n', 0, start + draft.start()) + 1
    whitespace = source[line_start:start + draft.start()]
    if whitespace.strip():
        return []
    sep = '\n' + whitespace
    replacement = (f'__repair_time = {draft["expr"]};' + sep + draft['type'] + sep
                   + draft['payload'] + sep + draft['next'] + sep
                   + f'M2C_FIELD({draft["event"]}, s32 *, 4) = __repair_time;')
    fixed = edit(source, [(start, start, '\n    s32 __repair_time;'),
                          (start + draft.start(), start + draft.end(), replacement)])
    return [('measured_kmc_event_timestamp', fixed)]
