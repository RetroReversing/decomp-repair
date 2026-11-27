"""An empty case that goes where the default goes, added to a `switch` to give its compare tree the target's shape.

GCC 2.x builds a sparse `switch` as a tree balanced over every case label, the empty ones too. A label whose arm is
the default's has its own compare deleted afterwards (the branch and the jump after it go to one place), but the tree
it balanced stays: the root moves, or a node keeps a `slti` bound check in front of its last equality test. The value
cannot be read back from the target, so one child tries each gap between the labels. In a KMC GCC 2.7.2 -O1 function,
states {0, 2, 3, 4, 0x384} compiled with root 3 where the target compares 2 first: `case 1: break;` was exact. In two
more the same label gave the missing `slti`.
"""
import re

from .integer_repair_support import view

FAMILY = 'switch_empty_case'
FAMILIES = (FAMILY,)
_SWITCH = re.compile(r'(?<![\w])switch\s*\(')
_CASE = re.compile(r'(?<![\w])case\s+(-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*:')
_OTHER_CASE = re.compile(r'(?<![\w])case\b')
MAX_CHILDREN = 24


def _close(clean, i, opening, closing):
    depth = 0
    while i < len(clean):
        if clean[i] == opening:
            depth += 1
        elif clean[i] == closing:
            depth -= 1
            if not depth:
                return i
        i += 1
    return None


def _switches(part):
    """(offset of `{`, offset of its `}`, the body with nested switches blanked) of each switch in the function."""
    found = []
    for hit in _SWITCH.finditer(part.clean, part.opening, part.end):
        paren = _close(part.clean, hit.end() - 1, '(', ')')
        brace = part.clean.find('{', paren) if paren is not None else -1
        if brace < 0 or part.clean[paren + 1:brace].strip():
            continue
        end = _close(part.clean, brace, '{', '}')
        if end is not None:
            found.append((brace, end))
    out = []
    for brace, end in found:
        body = part.clean[brace:end]
        for inner, inner_end in found:
            if brace < inner and inner_end < end:
                body = body[:inner - brace] + ' ' * (inner_end - inner) + body[inner_end - brace:]
        out.append((brace, end, body))
    return out


def _gaps(values):
    """One unused value in every gap between the labels, then one below and one above them."""
    out = [a + 1 for a, b in zip(values, values[1:]) if b - a > 1]
    if values[0] > 0:
        out.append(values[0] - 1)
    out.append(values[-1] + 1)
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for brace, end, body in _switches(part):
        values = sorted({int(v, 0) for v in _CASE.findall(body)})
        if len(values) < 4 or len(_CASE.findall(body)) != len(_OTHER_CASE.findall(body)):
            continue
        default = re.search(r'(?<![\w])default\s*:', body)
        for value in _gaps(values):
            label = f'case {value}:' if -10 < value < 10 else f'case {hex(value)}:'
            if default:
                at = brace + default.start()
                text = f'{label} '
            else:
                at = end
                # the arm before may fall out of the switch without a `break;`
                before = body.rstrip()
                left = '' if re.search(r'(?:\bbreak|\bcontinue|\breturn\b[^;{}]*|\bgoto\s+\w+)\s*;$', before) else 'break; '
                text = f'{left}{label} break; '
            out.append((FAMILY, source[:at] + text + source[at:]))
            if len(out) >= MAX_CHILDREN:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 1500}
