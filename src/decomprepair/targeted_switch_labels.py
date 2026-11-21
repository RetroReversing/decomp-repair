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


ZERO_BOUND = re.compile(
    r'^lui (?P<mode>\$\w+), %hi\((?P<selector>[A-Za-z_]\w*)\)\n'
    r'lw (?P=mode), %lo\((?P=selector)\)\((?P=mode)\)\n'
    r'addiu \$sp, \$sp, -\w+\n'
    r'addiu (?P<index>\$\w+), (?P=mode), -(?:0x)?1\n'
    r'sltiu (?P<guard>\$\w+), (?P=index), (?P<count>0x[0-9a-fA-F]+|[1-9][0-9]*)\n'
    r'beqz (?P=guard), \.L\w+\n'
    r'sw \$ra, \w+\(\$sp\)\n'
    r'sll (?P<offset>\$\w+), (?P=index), (?:0x)?2\n'
    r'lui (?P<table_base>\$\w+), %hi\((?P<table>[A-Za-z_]\w*)\)\n'
    r'addu (?P=table_base), (?P=table_base), (?P=offset)\n'
    r'lw (?P<destination>\$\w+), %lo\((?P=table)\)\((?P=table_base)\)\n'
    r'jr (?P=destination)\b'
)


def zero_bound_variants(source, name, asm):
    """Recover a one-based table and remove an unused parameter's spurious home store."""
    part = view(source, name)
    if not part or 'sltiu' not in asm:
        return []
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    instructions = (' '.join(line.split()) for line in assembly.splitlines())
    prefix = '\n'.join(line for line in instructions if re.match(r'^[a-z][a-z0-9.]* \$', line))
    target = ZERO_BOUND.match(prefix)
    if not target:
        return []
    body = part.body
    switch = re.match(
        rf'^(?:\s*(?:unsigned\s+(?:int|long)|long|int|[su](?:8|16|32))\s+\w+\s*;)*'
        rf'\s*switch\s*\(\s*{target["selector"]}\s*\)\s*{{',
        body,
    )
    bound = int(target['count'], 0)
    if not switch or bound < 3:
        return []
    brace = part.opening + switch.end()
    end = close(part.clean, brace, '{', '}')
    if not end:
        return []
    zero = re.compile(r'\s*case\s+(?:0|0[xX]0+)\s*:\s*break\s*;').match(part.clean, brace + 1, end)
    if not zero:
        return []
    scope = [*block_path(part, brace), brace]
    outer_labels = [hit for hit in re.compile(r'\b(?:case|default)\b').finditer(part.clean, zero.end(), end)
                    if block_path(part, hit.start()) == scope]
    cases = [CASE.match(part.clean, hit.start()) for hit in outer_labels]
    if not cases or not all(cases):
        return []  # An explicit default or an unevaluated label may handle zero differently.
    values = {int(case[1], 0) for case in cases}
    if min(values) != 1 or max(values) != bound:
        return []
    definition = re.compile(
        rf'\b{re.escape(name)}\s*\(\s*(?P<volatile>volatile\s+)'
        r'(?:unsigned\s+int|u32)\s+(?P<unused>[A-Za-z_]\w*)\s*,'
    )
    parameter = list(definition.finditer(part.clean, 0, part.opening))
    if len(parameter) != 1 or re.search(rf'\b{parameter[0]["unused"]}\b', body):
        return []
    candidate = edit(source, [(*zero.span(), ''), (*parameter[0].span('volatile'), '')])
    return [('switch_zero_bound', candidate)]
