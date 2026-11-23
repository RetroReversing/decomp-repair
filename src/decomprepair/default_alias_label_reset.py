"""A switch's run of empty case labels in front of `default:` removed, with the label just below the lowest case added.

m2c lists every value that falls into the default arm as an empty `case N:` label (`case 3: case 4: case 5: default:`).
GCC 2.7.2 lowers a small `switch` to a tree of compares over the labels' values, and a label that shares the default's
arm still takes a node: the same function compiled with the labels written out scored 3871 and, with the three removed,
2651; the target's tree (`beq 1`, `slti 2`, `beq 2`: the lowest case has a left neighbour) needed the arm's labels to be the
two real cases and one extra below them (`case 0:` shared with `default:`), 2451 in all. Each half alone is worse than the
pair: adding the label to the unreduced list scored 3851 (`default_neighbour_case`, one label on top of three aliases),
removing the aliases alone 2651 (`switch_range_trim` removes aliases only outside a target range check). One match
needed both, so this offers them as one child. Matched on a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) player update
routine of 1137 instructions (one step of a chain from 4316 to 60). The compiler's reason (stmt.c's balanced case tree
over the sorted labels) is a hypothesis; the exact judge decides.

default_alias_label_reset
    For each `switch` with `default:` preceded by a run of empty numeric `case N:` labels, one child with the run
    removed and one with the run removed and `case m-1:` written before `default:` (m the lowest remaining numeric label,
    at least 1, when m - 1 is not already a label and at least two numeric labels with a body remain). A run that is the
    switch's only labels is left alone (it would leave no `case`). At most 8 children."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'default_alias_label_reset'
FAMILIES = (FAMILY,)
LIMIT = 8
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_RUN = re.compile(rf'(?P<run>(?:[ \t]*(?<![\w.])case[ \t]+{_NUMBER}[ \t]*:[ \t]*\n(?:[ \t]*\n)*)+)(?P<indent>[ \t]*)(?<![\w.])default[ \t]*:')
_SWITCH = re.compile(r'\bswitch\s*\([^{};]*\)\s*\{')
_CASE = re.compile(rf'(?<![\w.])case\s+({_NUMBER})\s*:')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for hit in _SWITCH.finditer(clean, span[0], span[1]):
        open_at = hit.end() - 1
        stop = close(clean, open_at, '{', '}')
        if not stop:
            continue
        block = clean[open_at + 1:stop - 1]
        if re.search(r'\bswitch\b', block):
            continue  # (a nested switch's labels are not this one's)
        found = _RUN.search(block)
        if not found:
            continue
        run_at = open_at + 1 + found.start('run')
        default_at = open_at + 1 + found.start('indent')
        kept = [int(m[1], 0) for m in _CASE.finditer(block[:found.start('run')] + block[found.end():])]
        if not kept:
            continue
        out.append(source[:run_at] + source[default_at:])
        low = min(kept)
        if len(kept) >= 2 and low >= 1 and low - 1 not in kept:
            out.append(source[:run_at] + found['indent'] + f'case {low - 1}:\n\n' + source[default_at:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67}
