"""Relabel explicit cases using a closed permutation of linked destinations."""

import re
from collections import Counter, defaultdict

from .call_lifetime_repairs import block_path
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'linked_switch_labels'
CASE = re.compile(r'\bcase\s+(-?(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*))\s*:')


def variants(source, name, differences):
    return (_relabel(source, name, differences) + empty_arm_variants(source, name, differences)
            + default_swap_variants(source, name, differences))


def _relabel(source, name, differences):
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
    # A `goto` is no reason to decline: the edit only exchanges case numbers, and a label's target is untouched by it.
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
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


EMPTY_ARM = 'linked_switch_empty_arm'


def empty_arm_variants(source, name, differences):
    """Cases the target sends to the switch's join, written as an arm of their own that only breaks.

    A switch whose arms assign a preset value (`v = 1; switch (k) { case 4: v &= f(); break; default: v = 0; }`)
    keeps the preset for the kinds a developer listed with nothing to do (`case 10: case 11: break;`). Without those
    labels the kinds fall to `default:`, and the compiled table sends them to the default arm's code while the
    target's table sends them past it: the judge's "linked jump-table differences" rows, every instruction equal.
    The rows name the cases and the one destination the target gives them; that destination is not where any case of
    the compiled table goes (it is the code after the switch, which only a `break` reaches), so no relabelling of the
    existing arms can reach it. The proposal takes those labels out of the arms that hold them (an arm is never left
    without a label) and writes them as a new `case a: case b: break;` group in front of the arm that holds
    `default:`, or after the last arm when there is none. One proposal per switch; the judge decides."""
    if not 1 <= len(differences) <= 64 or len({row['table'] for row in differences}) != 1:
        return []
    targets = {row['target'] for row in differences}
    if len(targets) != 1 or targets & {row['candidate'] for row in differences}:
        return []
    moved = sorted({row['case'] for row in differences})
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    out = []
    for switch in re.compile(r'\bswitch\s*\(').finditer(part.clean, part.opening + 1, part.end - 1):
        after = close(part.clean, switch.end() - 1)
        opening = re.match(r'\s*{', part.clean[after:part.end]) if after else None
        if not opening:
            continue
        brace = after + opening.end() - 1
        end = close(part.clean, brace, '{', '}')
        if not end:
            continue
        scope = [*block_path(part, brace), brace]
        marks = [hit for hit in re.compile(r'\b(?:case|default)\b').finditer(part.clean, brace + 1, end - 1)
                 if block_path(part, hit.start()) == scope]
        spans = []  # (start, end, value or None for default) of each label
        for hit in marks:
            label = CASE.match(part.clean, hit.start())
            default = re.compile(r'default\s*:').match(part.clean, hit.start())
            if label:
                spans.append((label.start(), label.end(), int(label[1], 0)))
            elif default:
                spans.append((default.start(), default.end(), None))
        if not spans or len(spans) != len(marks) or sum(span[2] is None for span in spans) > 1:
            continue
        groups, group = [], []
        for number, span in enumerate(spans):
            group.append(span)
            stop = spans[number + 1][0] if number + 1 < len(spans) else end - 1
            if part.clean[span[1]:stop].strip():
                groups.append(group)
                group = []
        if group:
            continue
        values = {span[2] for span in spans if span[2] is not None}
        removals = []
        for value in moved:
            if value not in values:
                continue
            owner = next(group for group in groups if any(span[2] == value for span in group))
            if len(owner) < 2:
                removals = None
                break
            removals.append(next(span[:2] for span in owner if span[2] == value))
        if removals is None:
            continue
        holder = next((group for group in groups if any(span[2] is None for span in group)), None)
        if holder is None and not all(value in values for value in moved):
            continue  # a case with no label and no default is outside the switch
        at = holder[0][0] if holder else end - 1
        lead = re.search(r'[ \t]*$', source[:at])[0] if holder else ''
        at -= len(lead)
        hexed = any('x' in source[span[0]:span[1]].lower() for span in spans if span[2] is not None)
        text = ' '.join(f'case {value:#x}:' if hexed else f'case {value}:' for value in moved) + ' break;\n'
        out.append((EMPTY_ARM, edit(source, [*[(a, b, '') for a, b in removals], (at, at, lead + text)])))
    return list(dict.fromkeys(out))[:2]


DEFAULT_SWAP = 'linked_switch_default_swap'


def default_swap_variants(source, name, differences):
    """Two cases that trade destinations when one has an arm's label and the other only falls to `default:`.

    The table rows say case 7 goes where the compiled table sends case 12 and the other way round;
    `linked_switch_labels` exchanges two written labels, but here only one is written (`case 12: call(); default:
    return;`: the arm carries the label the game gave the join, and the game's `case 7:` for the arm is the case the
    draft left out because m2c merged it into `default:`). An N64 dispatcher (`-G0 -mips3 -mgp32 -mfp32 -O2`) was 1
    (every instruction equal, two table words swapped) with `case 12:` on the call arm and exact with `case 7:
    call(); case 12: default: return;`. The proposal renames the written label to the missing case and writes the
    written one in front of `default:` (an arm is never left without a label). One proposal per switch; the judge
    decides."""
    if len(differences) != 2 or len({row['table'] for row in differences}) != 1:
        return []
    first, second = differences
    if (first['case'] == second['case'] or first['target'] != second['candidate']
            or second['target'] != first['candidate']):
        return []
    cases = (first['case'], second['case'])
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    out = []
    for switch in re.compile(r'\bswitch\s*\(').finditer(part.clean, part.opening + 1, part.end - 1):
        after = close(part.clean, switch.end() - 1)
        opening = re.match(r'\s*{', part.clean[after:part.end]) if after else None
        if not opening:
            continue
        brace = after + opening.end() - 1
        end = close(part.clean, brace, '{', '}')
        if not end:
            continue
        scope = [*block_path(part, brace), brace]
        marks = [hit for hit in re.compile(r'\b(?:case|default)\b').finditer(part.clean, brace + 1, end - 1)
                 if block_path(part, hit.start()) == scope]
        labels = {}
        default = None
        for hit in marks:
            label = CASE.match(part.clean, hit.start())
            if label:
                labels[int(label[1], 0)] = label
            elif re.compile(r'default\s*:').match(part.clean, hit.start()):
                default = hit
        if default is None or len(labels) + 1 != len(marks):
            continue
        written = [case for case in cases if case in labels]
        missing = [case for case in cases if case not in labels]
        if len(written) != 1:
            continue
        old, new = written[0], missing[0]
        label = labels[old]
        spell = (lambda value: f'{value:#x}') if 'x' in label[1].lower() else str
        lead = re.search(r'[ \t]*$', source[:default.start()])[0]
        indent = lead if source[:default.start()].endswith('\n' + lead) else ''
        out.append((DEFAULT_SWAP, edit(source, [(label.start(1), label.end(1), spell(new)),
                                                (default.start(), default.start(),
                                                 f'case {spell(old)}:\n{indent}')])))
    return list(dict.fromkeys(out))[:2]


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
