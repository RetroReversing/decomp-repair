"""Relabel explicit cases using a closed permutation of linked destinations."""

import re
from collections import Counter, defaultdict

from .call_lifetime_repairs import block_path
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'linked_switch_labels'
CASE = re.compile(r'\bcase\s+(-?(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*))\s*:')


def variants(source, name, differences):
    if not 2 <= len(differences) <= 32:
        return []
    # A default entry or a destination introduced by a different switch
    # cannot be assigned to an explicit source arm from these rows.
    if len({row['table'] for row in differences}) != 1:
        return []
    if Counter(row['target'] for row in differences) != Counter(row['candidate'] for row in differences):
        return []
    desired = defaultdict(list)
    current = defaultdict(list)
    for row in sorted(differences, key=lambda row: row['case']):
        desired[row['target']].append(row['case'])
        current[row['candidate']].append(row['case'])
    mapping = {old: new for address, cases in current.items()
               for old, new in zip(cases, desired[address])}
    if len(mapping) != len(differences) or mapping.keys() != set(mapping.values()):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    candidates = []
    for switch in re.compile(r'\bswitch\s*\(').finditer(part.clean, part.opening+1, part.end-1):
        after = close(part.clean, switch.end()-1)
        opening = re.match(r'\s*{', part.clean[after:part.end]) if after else None
        if not opening:
            continue
        brace = after + opening.end()-1
        end = close(part.clean, brace, '{', '}')
        if not end:
            continue
        scope = [*block_path(part, brace), brace]
        labels = [hit for hit in CASE.finditer(part.clean, brace+1, end-1)
                  if block_path(part, hit.start()) == scope]
        label_count = sum(block_path(part, hit.start()) == scope for hit in
                          re.compile(r'\bcase\b').finditer(part.clean, brace+1, end-1))
        literals = {int(hit[1], 0): hit for hit in labels}
        if len(literals) != label_count or not mapping.keys() <= literals.keys():
            continue
        candidates.append(edit(source, [(literals[old].start(1), literals[old].end(1), literals[new][1])
                                        for old, new in mapping.items()]))
        if len(candidates) > 1:
            return []  # No source-to-table association for two possible switches.
    return [(FAMILY, candidate) for candidate in candidates if candidate != source]
