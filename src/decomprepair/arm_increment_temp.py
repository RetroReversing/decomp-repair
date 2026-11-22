"""A cursor's incremented value written through one temporary shared by every arm that stores it.

GCC 2.7.2's first scheduler schedules a basic block backwards. When an insn becomes ready because its last
consumer was just scheduled and it is a "birthing" insn (`sched.c birthing_insn_p`: it sets a pseudo that is live
afterwards and that has exactly one set in the function) it gets the launch priority, so it is placed immediately
before that consumer and ahead of any unrelated insn of equal priority. A display-list cursor bump
(`D_cursor = dl + 1;`, an `addiu` feeding one store) is such an insn, and in the arm that also computes a value from
a just-loaded global (`slot - 0x80000000`) it was placed after that value's `subu`, where the target has the `addiu`
first. Written through a temporary assigned in both arms (`next = dl + 1; D_cursor = next;`) the pseudo has two sets,
is not birthing, gets no boost, and the two insns keep the order the loads give them. Found on a KMC N64 draw
function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 183 instructions, 60 -> 0): either arm alone changed nothing,
both together matched. The reading of `birthing_insn_p` is from the compiler's sched.c; that it is the cause here
is read from the `-dS` ready-list trace (the addiu showed priority 7f000001 and was picked before the subu).

Offered when two or more statements `G = P + K;` store the same global `G` (not a local) from the same pointer local
`P` of the function, one declaration `TYPE *P;`, with a literal `K`: each becomes `T = P + K; G = T;`, with `T`
declared after the function's leading declarations, all in one child. A candidate: the judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'arm_increment_temp'
FAMILIES = (FAMILY,)
NAME = 'cursor_next'
STORE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<glob>{IDENT})\s*=\s*(?P<ptr>{IDENT})\s*\+\s*(?P<step>{NUMBER})\s*;[ \t]*$')
DECLARATION = re.compile(rf'^[ \t]*(?:{IDENT}[ \t]+)+\**[ \t]*{IDENT}(?:\[\d+\])?[ \t]*(?:=[^;()]*)?;[ \t]*$')


def _pointer_type(clean, ptr):
    found = re.search(rf'(?m)^[ \t]*(?P<type>(?:{IDENT}[ \t]+)*{IDENT}[ \t]*\*+)[ \t]*{re.escape(ptr)}[ \t]*;', clean)
    if not found:
        return None
    base, stars = re.fullmatch(r'(.*?)\s*(\*+)', found['type'], re.S).groups()
    return f"{re.sub(r'[ \t]+', ' ', base)} {stars}"



def _after_declarations(clean, part):
    """The offset just after the last leading declaration line of the function body."""
    position, last = part.opening + 1, part.opening + 1
    for line in clean[part.opening + 1:part.end].splitlines(keepends=True):
        text = line.strip()
        if text and not DECLARATION.match(line.rstrip('\n')):
            break
        position += len(line)
        if text:
            last = position
    return last


def variants(source, name):
    part = view(source, name)
    if not part or re.search(rf'\b{NAME}\b', source):
        return []
    groups = {}
    for hit in STORE.finditer(part.clean, part.opening, part.end):
        groups.setdefault((hit['glob'], hit['ptr']), []).append(hit)
    for (glob, ptr), hits in groups.items():
        local = re.search(rf'(?m)^[ \t]*(?:{IDENT}[ \t]+)+\**[ \t]*{re.escape(glob)}\b', part.clean[part.opening:part.end])
        kind = _pointer_type(part.clean[part.opening:part.end], ptr)
        if len(hits) < 2 or local or not kind:
            continue
        edits = [(hit.start(), hit.end(), f"{hit['indent']}{NAME} = {ptr} + {hit['step']};\n{hit['indent']}{glob} = {NAME};")
                 for hit in hits]
        at = _after_declarations(part.clean, part)
        edits.append((at, at, f'    {kind}{NAME};\n'))
        return [(FAMILY, edit(source, sorted(edits)))]
    return []
