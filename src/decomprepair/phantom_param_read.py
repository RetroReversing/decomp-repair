"""A parameter's spill slot read as an uninitialised local, written as the parameter, with its rival's weight raised.

m2c names the stack slots a function reads `spNN`. When the target spills a parameter (a `u16` argument loaded from the
caller's frame into a register and stored to a local slot because no saved register was left for it) and later
reloads it from that slot, m2c sees the reload of a slot it never saw written and declares an `spNN` that nothing
assigns, so the draft reads an uninitialised local (`field = sp1E;`) beside the parameter it really is. The stray
slot gives the function a frame slot of its own (8 bytes on a 157-instruction KMC N64 effect spawner, `gcc-2.7.2-kmc
-G0 -mips3 -mgp32 -mfp32 -O2 -fno-strength-reduce`), and the parameter's own uses stay few, which is why the draft's
parameter was the one spilled. Reading the parameter instead removes the slot, but the parameter then has one more
reference and wins a saved register from the parameter the target keeps there (`global.c` ranks
`floor_log2 (refs) * refs / live`): that swap scored 368 -> 1866 alone. Wrapping the rival's only statement in a
`do { } while (0)` (flow.c counts a reference once more for every loop round it: one more reference at no cost) restores
the order, and with the identical-arm guard on the parameter written once (`identical_arm_collapse`) the pair gave 225;
the library's `goto_join_argument_copy`, `callee_parameter_width` and `debug_statement_boundary` then gave 160, 100 and
0 (the 0 matched). Each edit alone is worse or neutral, so they are one child here.

Offered when a function has a local of an integer type that nothing assigns (no `=`, no `&`, no `++`) and the body
reads, and parameters of that type: one child per parameter (up to FIRST, the ones between the parameters m2c did copy
into other `spNN` slots first), with the identical-arm guards on it collapsed, and one more per rival parameter
(narrow, read in exactly one plain statement) with that statement wrapped. The weight is a hypothesis read from the
allocation table. A candidate for the exact judge, never a verdict."""
import re

from .identical_arm_collapse_repairs import variants as collapse
from .integer_repair_support import IDENT, INTEGER, edit, view

FAMILY = 'phantom_param_read'
FAMILIES = (FAMILY,)
LIMIT = 40
CHOICES = 4
NARROW = re.compile(r'\b(?:u8|s8|u16|s16|unsigned\s+(?:char|short)|signed\s+(?:char|short)|char|short)\b')
STATEMENT = re.compile(r'(?<=[;{}])(?P<lead>[ \t\r\n]*)(?P<s>[^;{}]*;)')


def _parameters(part):
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head and ')' in head else ''
    found = []
    for piece in signature.split(','):
        m = re.fullmatch(rf'\s*(?P<type>.+?[\s*])(?P<name>{IDENT})\s*', piece)
        if m:
            found.append((re.sub(r'\s+', ' ', m['type']).strip(), m['name']))
    return found


def _phantoms(part):
    """(type, name, declaration span) of the integer locals nothing assigns that the body reads."""
    out = []
    for m in re.finditer(rf'(?m)^[ \t]*(?P<type>{INTEGER})[ \t]+(?P<name>{IDENT})[ \t]*;[ \t]*\n', part.clean[part.opening:part.end]):
        name = m['name']
        rest = part.clean[part.opening + m.end():part.end]
        reads = re.findall(rf'(?<![\w.>]){name}\b', rest)
        if reads and not re.search(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|&\s*{name}\b|(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)|\b{name}\s*\[', rest):
            out.append((m['type'], name, (part.opening + m.start(), part.opening + m.end())))
    return out


def _order(parameters, same, part):
    """The same-type parameters with those lying between the ones m2c copied into other slots first."""
    index = {name: i for i, (_t, name) in enumerate(parameters)}
    copied = sorted(index[m['arg']] for m in re.finditer(rf'(?m)^[ \t]*sp\w+\s*=\s*(?P<arg>{IDENT})\s*;', part.clean)
                    if m['arg'] in index)
    if len(copied) >= 2:
        low, high = copied[0], copied[-1]
        return sorted(same, key=lambda n: (not low < index[n] < high, index[n]))
    return same


def _collapse(text, name, parameter):
    """`text` with the identical-arm guards on `parameter` written once."""
    for _ in range(4):
        guard = len(re.findall(rf'\bif\s*\(\s*{parameter}\s*\)', text))
        for _family, child in collapse(text, name):
            if len(re.findall(rf'\bif\s*\(\s*{parameter}\s*\)', child)) < guard:
                text = child
                break
        else:
            break
    return text


def _rivals(text, name, parameters, chosen):
    """(parameter, statement span) for narrow parameters read in exactly one plain statement."""
    part = view(text, name)
    out = []
    for kind, other in parameters:
        if other == chosen or not NARROW.search(kind) or '*' in kind:
            continue
        reading = [m for m in STATEMENT.finditer(part.clean, part.opening + 1, part.end)
                   if re.search(rf'(?<![\w.>]){other}\b', m['s'])]
        if len(reading) != 1:
            continue
        statement = reading[0]['s']
        if re.match(r'\s*(?:if|while|for|switch|return|do|else|case)\b', statement) or '=' not in statement:
            continue
        out.append((other, (reading[0].start('s'), reading[0].end())))
    return out


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b|^\s*#', part.body, re.M):
        return []
    parameters = _parameters(part)
    found = []
    for kind, phantom, (lo, hi) in _phantoms(part):
        same = [n for t, n in parameters if t == kind]
        for chosen in _order(parameters, same, part)[:CHOICES]:
            text = edit(source, [(lo, hi, '')])
            text = re.sub(rf'(?<![\w.>]){phantom}\b', chosen, text)
            text = _collapse(text, name, chosen)
            found.append((FAMILY, text))
            for other, (a, b) in _rivals(text, name, parameters, chosen):
                found.append((FAMILY, edit(text, [(a, b, 'do { ' + text[a:b] + ' } while (0);')])))
    result = []
    for family, text in found:
        if text != source and text not in [t for _, t in result]:
            result.append((family, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)
