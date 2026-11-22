"""A union that shares one register between a pointer phase and an integer phase, written as two plain locals.

`phase_union_repairs` (and the m2c-era drafts that carry `__repair_phase_storage`) share storage between disjoint phases
so that one pseudo serves both. That wins when the allocator needs the saved register for something else and loses when the
second phase's value would live in a call-clobbered register of its own: the union member is one pseudo from the function's
first assignment to its last use, so it stays in a saved register across calls that the second phase never crosses. In a
374-instruction N64 effect spawner (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) the union held an optional pointer
argument and, later, a layout constant that was passed to one call; the target holds the constant in `$a1` (a pseudo of
its own, never live across a call) where the union kept it in `$s0`.

`phase_storage_split` replaces a local `union { T a; U b; } NAME;` whose members are only ever read and written as
`NAME.a` / `NAME.b` with the locals `NAME_a` and `NAME_b`. It assumes the phases are disjoint, as the union that was
written for them did: no member is read after the other was written (the function is not type-punning). Alone it can score
worse (1397 -> 1458 on that function: the freed register shifts other choices); it is the first of the steps that matched
it, so `phase_storage_split_narrow_share` offers it together with `narrow_test_share` (1458 -> 1223 as the pair, in the
sequence of six edits recorded in docs/COMPILER_MATCHING_LEARNINGS.md). The judge decides.
"""
import re

from . import narrow_test_share_repairs
from .integer_repair_support import IDENT, edit, view

FAMILY = 'phase_storage_split'
COMBINED = 'phase_storage_split_narrow_share'
FAMILIES = (FAMILY, COMBINED)
UNION = re.compile(rf'(?m)^(?P<indent>[ \t]*)union\s*(?:{IDENT})?\s*{{(?P<members>[^{{}}]*)}}\s*(?P<name>{IDENT})\s*;[ \t]*\n?')
MEMBER = re.compile(rf'\s*(?P<type>(?:(?:unsigned|signed|const|volatile)\s+)*{IDENT}(?:\s+{IDENT})?[\s*]*?)\b(?P<member>{IDENT})\s*;')


def split(source, name):
    """The function with its first splittable local union written as plain locals, or None."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return None
    for union in UNION.finditer(part.clean, part.opening, part.end):
        members, cursor = [], 0
        text = union['members']
        while cursor < len(text.rstrip()):
            member = MEMBER.match(text, cursor)
            if not member:
                members = []
                break
            members.append((member['type'].strip(), member['member']))
            cursor = member.end()
        local = union['name']
        names = [member for _, member in members]
        if len(members) < 2 or len(set(names)) != len(names):
            continue
        uses = [hit for hit in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', part.clean[part.opening:part.end])]
        members_used = [hit for hit in re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*\.\s*(?:{"|".join(map(re.escape, names))})\b',
                                                    part.clean[part.opening:part.end])]
        if len(uses) != len(members_used) + 1 or not members_used:
            continue  # the union is used whole (addressed, copied or passed), or only as the declaration
        edits = [(union.start(), union.end(),
                  ''.join(f'{union["indent"]}{kind} {local}_{member};\n' for kind, member in members))]
        for hit in members_used:
            start = part.opening + hit.start()
            edits.append((start, part.opening + hit.end(), f'{local}_' + re.sub(rf'^{re.escape(local)}\s*\.\s*', '', hit.group())))
        return edit(source, edits)
    return None


def variants(source, name):
    plain = split(source, name)
    if not plain:
        return []
    result = [(FAMILY, plain)]
    result += [(COMBINED, text) for _, text in narrow_test_share_repairs.variants(plain, name)]
    return result
