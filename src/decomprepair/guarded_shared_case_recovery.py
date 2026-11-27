"""Recover an omitted switch case when target dispatch proves it shares a guarded else arm.

A large MIPS GCC 2.7.2 MIDI event handler's draft handled a zero argument in an else arm but omitted another
command that enters the same target block directly. Target dispatch compares both command values; the first
command's zero guard enters the adjacent instruction before the second command's call setup. Reintroducing the
missing case as a fallthrough improved one app judge from 7,560 to 6,895. The target dispatch is the evidence for
this behavior change: it is not an equivalence-preserving rewrite of the incomplete draft.
"""
import re

from .integer_repair_support import view
from .pattern_repairs import close
from .switch_empty_case import _CASE, _OTHER_CASE, _switches

FAMILY = 'guarded_shared_case_recovery'
FAMILIES = (FAMILY,)


def evidence(asm):
    """(guarded case, shared case) proved by direct dispatch and a zero guard entering the shared call."""
    insns, labels = [], {}
    for raw in (asm or '').splitlines():
        line = re.sub(r'/\*.*?\*/', '', raw).strip()
        label = re.fullmatch(r'(\.\w+):', line)
        if label:
            labels[label[1]] = len(insns)
        elif line and not line.startswith(('glabel ', 'endlabel ', 'nonmatching ')):
            insns.append(re.sub(r'\s+', ' ', line))
    dispatch = []
    for first, second in zip(insns, insns[1:]):
        load = re.fullmatch(r'(?:addiu|ori)\s+\$(\w+),\s*\$zero,\s*(0x[\da-fA-F]+|\d+)', first)
        branch = re.fullmatch(r'beq\s+\$(\w+),\s*\$(\w+),\s*(\.\w+)', second)
        if load and branch and branch[1] != branch[2] and load[1] in branch.groups()[:2] and branch[3] in labels:
            selector = branch[2] if branch[1] == load[1] else branch[1]
            dispatch.append((selector, int(load[2], 0), branch[3]))
    if len(insns) > 8192 or len(dispatch) > 64:
        return []
    out = set()
    for selector, guarded, entry in dispatch:
        start = labels[entry]
        for line in insns[start:start + 5]:
            guard = re.fullmatch(r'beqz\s+\$\w+,\s*(\.\w+)', line)
            if not guard or guard[1] not in labels:
                continue
            guard_at = labels[guard[1]]
            for other_selector, shared, shared_label in dispatch:
                shared_at = labels[shared_label]
                if (selector != other_selector or guarded == shared or shared_at - guard_at not in (0, 1)
                        or not any(re.match(r'jal\s+', call) for call in insns[shared_at:shared_at + 5])):
                    continue
                out.add((guarded, shared))
    return sorted(out)


def variants(source, name, asm):
    proofs = evidence(asm)
    part = view(source, name) if proofs else None
    if not part:
        return []
    out = []
    for brace, end, body in _switches(part):
        cases = list(_CASE.finditer(body))
        if len(cases) != len(_OTHER_CASE.findall(body)):
            continue
        values = {int(hit[1], 0) for hit in cases}
        for case in cases:
            guarded = int(case[1], 0)
            next_case = next((hit.start() for hit in cases if hit.start() > case.start()), len(body))
            start = brace + case.end()
            limit = brace + next_case
            head = re.match(r'\s*if\s*\(\s*[A-Za-z_]\w*\s*!=\s*0\s*\)', part.clean[start:limit])
            if not head:
                continue
            opening = re.match(r'\s*\{', part.clean[start + head.end():limit])
            if not opening:
                continue
            first = start + head.end() + opening.end() - 1
            after_first = close(part.clean, first, '{', '}')
            other = re.match(r'\s*else\s*\{', part.clean[after_first:limit]) if after_first else None
            if not other:
                continue
            second = after_first + other.end() - 1
            after_second = close(part.clean, second, '{', '}')
            if not after_second or not re.fullmatch(r'\s*break\s*;\s*', part.clean[after_second:limit]):
                continue
            if re.search(r'(?m)\b(?:goto|case|default)\b|^\s*[A-Za-z_]\w*\s*:', part.clean[first:after_second]):
                continue
            for proven_guard, shared in proofs:
                if proven_guard != guarded or shared in values:
                    continue
                # The guarded arm must still leave the switch when its test succeeds.
                text = (source[start:first + 1] + source[first + 1:after_first - 1] + '\n            break;\n'
                        + source[after_first - 1:after_first] + f'\n    case {hex(shared)}:\n        '
                        + source[second:after_second] + source[after_second:limit])
                out.append((FAMILY, source[:start] + text + source[limit:]))
                if len(out) >= 8:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
