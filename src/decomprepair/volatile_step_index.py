"""Volatile step cursors, written back as the counter's multiples the compiler's own strength reduction steps.

A saved best that stood a loop's stepped variables (`spD4 += 3`, `spDC += 6`) in `volatile` locals, with a volatile
padding array to fill the frame, was scored by a search before it was read: the volatile hid two things at once. The
cursors do live in the stack frame of the target (`lw $t1,0xd4($sp); addiu $t1,$t1,3; sw $t1,0xd4($sp)`), but as
ordinary pseudo registers that the allocator spilled, not as volatile objects: the compiler made them itself, by
strength reduction of `counter * 3` and `counter * 6`, and gave them the lowest allocation priority. Written volatile
they take the frame's first slots, and every spilled pseudo after them lands eight bytes early (a frame 8 bytes short,
`lw $v0` where the target reloads through `$t1`); written as plain locals stepped beside the counter they take
registers the arguments need. Only the counter's multiples (`stepped_induction_index`) give the target's allocation.

Three things stand between such a source and that rewrite, and none of them is a step the chain keeps alone:

 - the `volatile` on the stepped locals (and a never-referenced volatile pad array that only filled the frame),
 - an identical-arm guard around the step statements (`if (c) { a += 3; i += 1; b += 6; } else { <the same> }`: m2c's
   two arms), which doubles every reference the allocator counts for the counter and the cursors and moves their
   priorities (the same guard written once scored 4084 -> 1277 on a 530-instruction function), and
 - the starts and steps sharing lines with other statements, which the all-at-once rewrite did not read.

This family does all of it and hands the result to `stepped_induction_index`, as one child: the stepped locals made
plain, the padding dropped, the identical arms around the steps written once, the cursors as the counter's multiples.
It offers a child only when every stage applied. On the function it came from the child alone scored worse than the
saved best (a frame and a loop-counter register still differ), so it is a step a search has to keep despite the score;
the exact judge decides.
"""
import re

from . import identical_arm_collapse_repairs, stepped_induction_index
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'volatile_step_index'
FAMILIES = (FAMILY,)
COLLAPSES = 6
_DECL = re.compile(rf'(?m)^(?P<lead>[ \t]*)volatile\s+(?P<type>[A-Za-z_][\w ]*?)\s+(?P<v>{IDENT})(?P<array>\s*\[[^\]\n]*\])?\s*;[ \t]*\n')


def _steps(clean, var):
    return len(re.findall(rf'\b{var}\s*(?:\+=\s*{NUMBER}|\+\+)\s*;', clean))


def _plain(part):
    """(edits, stepped variables): `volatile` dropped from the scalars that are only started, stepped and read, and
    from the volatile arrays nothing refers to."""
    body = part.clean[part.opening + 1:part.end - 1]
    edits, stepped = [], []
    for decl in _DECL.finditer(body):
        var = decl['v']
        others = body[:decl.start()] + body[decl.end():]
        uses = list(re.finditer(rf'\b{var}\b', others))
        if decl['array']:
            if not uses:
                edits.append((decl.start(), decl.end(), ''))
            continue
        starts = re.findall(rf'\b{var}\s*=\s*0\s*;', others)
        if not (_steps(others, var) and starts):
            continue
        # a store of anything but zero, or the address, would make the local a real memory object
        assigned = len(re.findall(rf'\b{var}\s*=(?!=)', others))
        if assigned != len(starts) or re.search(rf'&\s*{var}\b', others) or re.search(rf'\b{var}\b\s*(?:[-*/|&^]=|<<=|>>=|--)', others):
            continue
        edits.append((decl.start(), decl.end(), f"{decl['lead']}{decl['type']} {var};\n"))
        stepped.append(var)
    return [(part.opening + 1 + a, part.opening + 1 + b, text) for a, b, text in edits], stepped


def _collapsed(source, name, header, stepped):
    """The identical-arm guards that hold the stepped variables' steps, written once (each pass takes the collapse that
    removes the most duplicated steps)."""
    for _ in range(COLLAPSES):
        part = view(source, name)
        before = sum(_steps(part.clean, var) for var in stepped) if part else 0
        best = None
        for _, text in identical_arm_collapse_repairs.variants(source, name, header):
            after = view(text, name)
            count = sum(_steps(after.clean, var) for var in stepped) if after else before
            if count < before and (best is None or count < best[0]):
                best = (count, text)
        if best is None:
            break
        source = best[1]
    return source


def _without_unused(source, name, stepped):
    """The declarations of stepped variables that nothing refers to any more."""
    part = view(source, name)
    body = part.clean[part.opening + 1:part.end - 1] if part else ''
    edits = []
    for var in stepped:
        decl = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w ]*?\s+{var}\s*;[ \t]*\n', body)
        if decl and len(re.findall(rf'\b{var}\b', body)) == 1:
            edits.append((part.opening + 1 + decl.start(), part.opening + 1 + decl.end(), ''))
    return edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part or 'volatile' not in part.clean:
        return []
    edits, stepped = _plain(part)
    if not stepped:
        return []
    plain = edit(source, edits)
    out = []
    for text in dict.fromkeys([_collapsed(plain, name, header, stepped), plain]):
        for _, child in stepped_induction_index.variants(text, name)[:1]:
            if child != source and not any(re.search(rf'\b{var}\s*(?:\+=|\+\+)', child) for var in stepped):
                out.append((FAMILY, _without_unused(child, name, stepped)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}  # the registry: no caller wiring (registry.py)
