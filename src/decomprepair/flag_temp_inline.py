"""A flag temporary m2c assigns in several places, written as the mask test where it is read.

m2c keeps each `flags & K` it meets in a local (`var_v0_2 = flags & 4; ... if (var_v0_2 != 0)`), assigns the same value again
inside branches, and tests the temporary later. The original wrote `if (flags & 4)` where it tested. GCC 2.7.2 (KMC,
`-G0 -mips3 -mgp32 -mfp32 -O2`) numbers the pseudos by first mention, so each temporary was a pseudo of its own whose
set sits where m2c put it (an `andi` hoisted above a branch, a second one copied into a delay slot, a register held
across a call), and the temporaries' references raise the flag word's own priority and move the saved registers around it
(a 445-instruction N64 target picker: 3113 -> 2593 by this edit alone).

For a local assigned only as `v = x & K;` with one `x` and `K` everywhere, where `x` is assigned at most once in the function
(or is a parameter that is never assigned) and that assignment precedes every mention of `v`, each read of `v` becomes
`(x & K)` and the assignments go. A candidate for the exact judge, never a verdict.

A word that is assigned more than once (m2c's `hit = 0; ... hit = 1;` before `var_v0_2 = hit & 0xFF;`, written once per path
into the test, goto arms included) is accepted when the control flow shows that every read of `v` still holds `x & K`: on
every path to the read an assignment of `v` comes after the last write of `x` (KMC 2.7.2 `-O1`, a 73-instruction N64
handler: the last three register rows, 15 -> 0 with `entry_scheduling_scope`).
"""
import re

from .integer_repair_support import _address_taken, edit, locals_for, view
from .local_flow import analyze

FAMILY = 'flag_temp_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
_ASSIGN = re.compile(r'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*([A-Za-z_]\w*)[ \t]*&[ \t]*(0[xX][0-9a-fA-F]+|\d+)[ \t]*;[ \t]*\n')


def _writes(clean, name):
    return re.findall(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', clean)


def _parameter_or_local(source, part, name, word):
    header = part.clean[:part.opening]
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^()]*)\)\s*$', header.rstrip())
    return (any(d['name'] == word for d in locals_for(part))
            or bool(signature and re.search(rf'\b{re.escape(word)}\s*(?:,|$)', signature[1].strip())))


def _holds_at_reads(source, name, part, word, hits, reads):
    """Whether on every path to each read of the temporary, one of its assignments follows the last write of `word`."""
    if not _parameter_or_local(source, part, name, word) or _address_taken(part.body, word) or 'volatile' in part.body:
        return False
    flow = analyze(source, name)
    if flow is None:
        return False
    sets, kills = set(), set()
    for index, node in enumerate(flow.nodes):
        if any(node.start <= h.start(2) < node.end for h in hits):
            sets.add(index)
        elif _writes(part.clean[node.start:node.end], word):
            kills.add(index)
    before = {index: set() for index in range(len(flow.nodes))}
    for index, node in enumerate(flow.nodes):
        for child in node.successors:
            before[child].add(index)
    out = {index: index not in kills for index in before}

    def entering(index):
        return index != flow.entry and all(out[p] for p in before[index])

    changed = True
    while changed:
        changed = False
        for index in before:
            value = index in sets or (index not in kills and entering(index))
            if value != out[index]:
                out[index], changed = value, True
    for at in reads:
        node = flow.at(at)
        # a read in a statement that also writes the word (`if (x++ ... v)`) proves nothing
        if node is None or flow.nodes.index(node) in kills or not entering(flow.nodes.index(node)):
            return False
    return True


def _removal(clean, hit):
    """An assignment that is the whole of an arm or follows a label leaves an empty statement behind."""
    before = clean[:hit.start()].rstrip()
    return (hit.start(), hit.end(), '' if before.endswith(('{', '}', ';')) else ';\n')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    seen = {}
    for hit in _ASSIGN.finditer(clean, part.opening, part.end):
        seen.setdefault(hit[1], []).append(hit)
    by_var = []
    for var, hits in seen.items():
        if len({(h[2], h[3]) for h in hits}) != 1 or var == hits[0][2]:
            continue
        word, mask = hits[0][2], hits[0][3]
        if len(_writes(body, var)) != len(hits):
            continue
        assigned = {(h.start(), h.end()) for h in hits}
        first_write = re.search(rf'(?<![\w.>]){re.escape(word)}\s*=(?!=)', body)
        declaration = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*[ \t*]{re.escape(var)}[ \t]*;[ \t]*\n', body)
        reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', body)
                 if not any(a <= part.opening + m.start() < b for a, b in assigned)
                 and not (declaration and declaration.start() <= m.start() < declaration.end())]
        if not reads:
            continue
        unchanging = (len(_writes(body, word)) <= 1
                      and not any(part.opening + m.start() < min(a for a, _ in assigned) for m in reads)
                      and not (first_write and any(m.start() < first_write.start() for m in reads)))
        if not unchanging and not _holds_at_reads(source, name, part, word, hits, [part.opening + m.start() for m in reads]):
            continue
        edits = [_removal(clean, h) for h in hits]
        edits += [(part.opening + m.start(), part.opening + m.end(), f'({word} & {mask})') for m in reads]
        if declaration:
            edits.append((part.opening + declaration.start(), part.opening + declaration.end(), ''))
        by_var.append(edits)
    result = [edit(source, edits) for edits in by_var[:LIMIT]]
    if len(by_var) > 1:
        result.append(edit(source, [item for edits in by_var for item in edits]))
    return [(FAMILY, text) for text in result if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)
