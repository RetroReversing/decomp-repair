"""Reuse the saved local holding either selected gain for a linked blend."""

import re
from collections import Counter, defaultdict
from itertools import combinations

from .balanced_clamp_predicates import _LUI, _ORI, _bits
from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .quadratic_sign_holder import _DONOR, _call
from .quadratic_sign_holder import _witnesses as _sample_witnesses
from .trig_axis_reuse import _DECL, _SAVED

FAMILY = 'saved_conditional_smoothing_gain'
_LITERAL = r'\d+\.\d+[fF]'
_MOVE = re.compile(r'mtc1 \$at, (\$f\d+)')
_MUL = re.compile(rf'mul\.s (\$f\d+), \1, ({_SAVED})')
_OTHER_MUL = re.compile(r'mul\.s (\$f\d+), \1, (\$f\d+)')
_LOAD = re.compile(rf'lwc1 (\$f\d+), ({NUMBER})\(\$\w+\)')
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+)\s*;\s*'
    rf'{IDENT}\s*=\s*\(\(\s*{IDENT}\s*-\s*(?P=old)\s*\)\s*\*\s*(?P<gain>{IDENT})\s*\)'
    rf'\s*\+\s*(?P=old)\s*;'
)
_WRITE = re.compile(rf'(?m)^[ \t]*(?P<var>{IDENT})\s*=\s*(?P<literal>{_LITERAL})\s*;')


def _site_counts(rows):
    constants = defaultdict(list)
    measured = Counter()
    for at in range(2, len(rows) - 1):
        _, left, right = rows[at]
        target, candidate = _MOVE.fullmatch(left), _MOVE.fullmatch(right)
        if target and candidate and target[1] != candidate[1]:
            high, low = _LUI.fullmatch(rows[at - 2][1]), _ORI.fullmatch(rows[at - 1][1])
            if high and low and all(a == b for _, a, b in rows[at - 2:at]):
                constants[target[1], candidate[1]].append((at, integer(high[1]) << 16 | integer(low[1])))
        mul, other_mul = _MUL.fullmatch(left), _OTHER_MUL.fullmatch(right)
        if not mul or not other_mul or mul[1] != other_mul[1] or mul[2] == other_mul[2]:
            continue
        load = _LOAD.fullmatch(rows[at - 2][1])
        if not load or any(a != b for _, a, b in (rows[at - 2], rows[at - 1], rows[at + 1])):
            continue
        scratch = mul[1]
        if (not re.fullmatch(rf'sub\.s {re.escape(scratch)}, \$f\d+, {re.escape(load[1])}', rows[at - 1][1])
                or not re.fullmatch(rf'add\.s \$f\d+, {re.escape(scratch)}, {re.escape(load[1])}', rows[at + 1][1])):
            continue
        pair = constants[mul[2], other_mul[2]][-2:]
        if len(pair) == 2 and at - pair[0][0] <= 80 and pair[0][1] != pair[1][1]:
            measured[integer(load[2]), frozenset(bits for _, bits in pair), mul[2]] += 1
    return measured


def _reaching_literal_writes(flow, parents, start, gain, writes):
    pending = list(parents[start])
    visited, reached = set(), set()
    while pending:
        at = pending.pop()
        if at in visited:
            continue
        visited.add(at)
        node = flow.nodes[at]
        if gain in node.defines:
            matching = [m for m in writes if node.start <= m.start('var') < node.end]
            if len(matching) != 1:
                return None
            reached.add(matching[0])
            continue
        if at == flow.entry or gain in node.uses or not parents[at]:
            return None
        pending.extend(parents[at])
    return sorted(reached, key=lambda m: m.start()) if len(reached) == 2 else None



def _feeds_only_blend(flow, definitions, blend, gain):
    pending = [later for definition in definitions for later in definition.successors]
    visited = set()
    while pending:
        at = pending.pop()
        if at in visited:
            continue
        visited.add(at)
        node = flow.nodes[at]
        if node is blend:
            continue
        if gain in node.uses:
            return False
        if gain not in node.defines:
            pending.extend(node.successors)
    return True


def _blend_sites(part, flow, declarations, macros, desired):
    parents = [[] for _ in flow.nodes]
    indexes = {}
    for index, node in enumerate(flow.nodes):
        indexes[id(node)] = index
        for successor in node.successors:
            parents[successor].append(index)
    writes = defaultdict(list)
    for write in _WRITE.finditer(part.clean, part.opening + 1, part.end):
        writes[write['var']].append(write)
    sites = []
    for hit in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        gain = hit['gain']
        field = _field(hit['field'], part.clean[:part.opening])
        blend = flow.at(hit.start('gain'))
        if (gain not in flow.names or not field or not blend
                or any(gain in flow.nodes[n].live for n in blend.successors)
                or not _in_scope(part, declarations[gain].start(), hit.start('gain'))):
            continue
        pair = _reaching_literal_writes(flow, parents, indexes[id(blend)], gain, writes[gain])
        if not pair or any(m.end() > hit.start() for m in pair):
            continue
        definitions = [flow.at(m.start('var')) for m in pair]
        if any(node is None for node in definitions) or not _feeds_only_blend(flow, definitions, blend, gain):
            continue
        segment = part.clean[pair[0].start():hit.end()]
        if re.search(r'\b(?:goto|case|default)\b|(?m:^[ \t]*[A-Za-z_]\w*\s*:)', segment):
            continue
        key = field[1], frozenset(_bits(m['literal']) for m in pair)
        if (key in desired and not macros & set(re.findall(IDENT, segment))
                and len(re.findall(rf'\b{gain}\b', segment)) == 3):
            sites.append((key, pair, hit, segment))
    return sites


def variants(source, name, rows, *, header=''):
    measured = _site_counts(rows)
    visible = _visible(source, name, header) if 1 <= sum(measured.values()) <= 4 else None
    if not visible:
        return []
    part, context = visible
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if any(alias.strip() != 'float' for alias in typedefs):
        return []
    _, donors, _ = _sample_witnesses(rows)
    if not donors:
        return []
    available = _typed_locals(part, r'(?:f32|float)')
    declarations = {m['name']: m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in available and m.start() == available[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    sites = _blend_sites(part, flow, declarations, macros, {key[:2] for key in measured})
    proposals = []
    for donor in _DONOR.finditer(part.clean, part.opening + 1, part.end):
        holder = donor['holder']
        if holder not in flow.names or available[holder][0] in macros or macros & set(re.findall(IDENT, donor[0])):
            continue
        registers = {register for *call, bits, register in donors
                     if tuple(call) == _call(donor) and bits == _bits(donor['gain'])}
        for register in sorted(registers):
            wanted = {key[:2]: count for key, count in measured.items() if key[2] == register}
            if not wanted:
                continue
            eligible = []
            for key, pair, hit, segment in sites:
                if (key not in wanted or available[hit['gain']][0] in macros or re.search(rf'\b{holder}\b', segment)
                        or not _in_scope(part, declarations[holder].start(), hit.start('gain'))
                        or any(not _in_scope(part, declarations[holder].start(), m.start('var'))
                               or not flow.dead(holder, m.start('var')) for m in pair)):
                    continue
                eligible.append((key, [m.span('var') for m in pair] + [hit.span('gain')]))
            count = sum(wanted.values())
            if len(eligible) > count + 2:
                continue
            # Changing every observed lifetime can perturb another block. Also
            # retain bounded alternatives that leave one of those sites alone.
            for size in range(count, max(1, count - 1) - 1, -1):
                for group in combinations(eligible, size):
                    if any(total > wanted[key] for key, total in Counter(key for key, _ in group).items()):
                        continue
                    ranges = sorted((min(a for a, _ in items), max(b for _, b in items)) for _, items in group)
                    if any(a_end > b_start for (_, a_end), (b_start, _) in zip(ranges, ranges[1:])):
                        continue
                    entry = (FAMILY, edit(source, [(a, b, holder) for _, items in group for a, b in items]))
                    if entry not in proposals:
                        proposals.append(entry)
                    if len(proposals) == 4:
                        return proposals
    return proposals
