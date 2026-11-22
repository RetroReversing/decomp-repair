"""Fold reads through a fixed-offset byte cursor into its parallel base cursor."""

import re

from . import local_flow
from .allocator_call_guards import dominators
from .csource import _blank, find
from .integer_repair_support import IDENT, View, edit, integer
from .pattern_repairs import close

FAMILY = 'parallel_byte_cursor'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)'
INIT = re.compile(
    rf'(?<=[;{{}}])\s*(?P<alias>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*(?P<offset>{NUMBER})\s*;'
    r'\s*do\s*{'
)
STEP = rf'({IDENT})\s*\+=\s*({NUMBER})\s*;'
TAIL = re.compile(rf'(?:\s*{STEP})+\s*$')
BYTE = r'u8|unsigned\s+char'


def _local(part, name, types):
    decl = re.search(rf'(?<=[;{{}}])\s*(?:{types})\s*\*\s*{name}\s*;', part.clean[part.opening:part.end])
    if decl:
        prefix = part.clean[part.opening:part.opening + decl.start()]
        if prefix.count('{') == prefix.count('}') + 1:
            return decl
    return None


def _loop_edits(part, match, header):
    alias, base = match['alias'], match['base']
    if (alias == base or not _local(part, alias, rf'void|{BYTE}') or not _local(part, base, BYTE)
            or re.search(rf'(?m)^\s*#\s*define\s+(?:{alias}|{base})\b', header + '\n' + part.clean)):
        return []
    opening = match.end() - 1
    end = close(part.clean, opening, '{', '}')
    test = end and re.match(r'\s*while\s*\(', part.clean[end:part.end])
    test_end = test and close(part.clean, end + test.end() - 1)
    if not test_end or re.search(rf'\b{base}\b', part.clean[end:test_end]):
        return []
    before = part.clean[part.opening:match.start()]
    outside = before + ' ' + part.clean[test_end:part.end]
    # Outside the walk allow one declaration and one assignment to the base.
    # An enclosing block can otherwise shadow the byte pointer with another type.
    if (len(re.findall(rf'\b{base}\b', outside)) != 2
            or not re.search(rf'(?<=[;{{}}])\s*{base}\s*=(?!=)', before)):
        return []
    body = part.clean[opening + 1:end - 1]
    tail = TAIL.search(body)
    if not tail:
        return []
    inner = body[:tail.start()].rstrip()
    if ((inner and inner[-1] not in ';}') or inner.count('{') != inner.count('}')
            or re.search(rf'#|\b(?:goto|case|default|asm|__asm__)\b|\b{IDENT}\s*:(?!:)', inner)):
        return []
    steps = list(re.finditer(STEP, tail[0]))
    alias_steps = [step for step in steps if step[1] == alias]
    base_steps = [step for step in steps if step[1] == base]
    if len(alias_steps) != 1 or len(base_steps) != 1:
        return []
    stride = integer(base_steps[0][2])
    offset = integer(match['offset'])
    if not 0 < offset < stride or stride != integer(alias_steps[0][2]):
        return []
    # Each cursor is advanced exactly once at the bottom of the loop. Reject any
    # other alias use and allow only dereferences of the base in the loop body.
    reads = list(re.finditer(
        rf'\*\s*\(\s*(?:{BYTE})\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*'
        rf'\(\s*{alias}\s*\)\s*\+\s*(?P<offset>-?{NUMBER})\s*\)',
        body[:tail.start()],
    ))
    if (not reads or len(re.findall(rf'\b{alias}\b', part.body)) != len(reads) + 3
            or len(re.findall(rf'\b{base}\b', body[:tail.start()]))
            != len(re.findall(rf'(?<=[(=,])\s*\*\s*{base}\b(?!\s*\[)', body[:tail.start()]))):
        return []
    edits = []
    for read in reads:
        number = read['offset']
        displacement = -integer(number[1:]) if number.startswith('-') else integer(number)
        index = offset + displacement
        if not 0 <= index < stride:
            return []
        edits.append((opening + 1 + read.start(), opening + 1 + read.end(), f'{base}[{index}]'))
    return edits


def variants(source, name, header=''):
    """Propose only loads within the record shared by the two cursors."""
    span = find(source, name)
    if not span or 'do' not in source[span[0]:span[1]]:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    part = View(source, clean, opening, span[1])
    result = []
    for match in INIT.finditer(part.clean, part.opening + 1, part.end):
        edits = _loop_edits(part, match, header)
        if edits:
            result.append((FAMILY, edit(source, edits)))
    return (result + _indexed_variants(part, name, header))[:4]


def _indexed_variants(part, name, header):
    """Use the walking pointer where a fixed pointer is indexed by the same stride."""
    context = _blank(header) + '\n' + part.clean
    if re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp)\b', part.body):
        return []
    flow = None
    out = []
    for loop in re.finditer(r'\bdo\s*{', part.clean, re.M):
        opening = loop.end() - 1
        if not part.opening < opening < part.end:
            continue
        end = close(part.clean, opening, '{', '}')
        if not end:
            continue
        condition = re.match(rf'\s*while\s*\(\s*(?P<index>{IDENT})\s*<\s*(?P<count>{IDENT})\s*\)', part.clean[end:])
        if not condition or re.search(r'\b(?:while|for|do)\b', part.clean[opening + 1:end - 1]):
            continue
        index, count = condition['index'], condition['count']
        if not re.search(rf'\b(?:{BYTE})\s+{count}\s*;', part.clean[part.opening:opening]):
            continue
        body = part.clean[opening + 1:end - 1]
        pair = re.search(rf'\b(?P<base>{IDENT})\s*\+=\s*(?P<stride>{NUMBER})\s*;\s*{index}\s*\+=\s*1\s*;', body)
        if not pair or re.search(rf'\b{count}\b', body):
            continue
        base, stride = pair['base'], integer(pair['stride'])
        old = part.clean[part.opening:opening]
        aliases = list(re.finditer(rf'\b(?P<alias>{IDENT})\s*=\s*{base}\s*\+\s*(?P<offset>{NUMBER})\s*;', old))
        aliases = [hit for hit in aliases if re.search(rf'\b{hit["alias"]}\s*\[\s*(?:\(\(s32\)\s*\(\s*)?{index}\b', body)]
        initial = list(re.finditer(rf'\b{index}\s*=\s*0\s*;', old))
        if len(aliases) != 1 or len(initial) != 1 or not 1 < stride <= 32:
            continue
        alias = aliases[0]['alias']
        offset = integer(aliases[0]['offset'])
        if any(len(re.findall(rf'\b(?:{BYTE})\s*\*\s*{pointer}\s*(?=[;=])', old)) != 1
               for pointer in (base, alias)):
            continue
        if not re.search(rf'\b(?:u32|s32|int|unsigned\s+int)\s+{index}\s*;', old):
            continue
        if any(re.search(rf'\b{name}\b', old[after:])
               for name, after in ((base, aliases[0].end()), (alias, aliases[0].end()), (index, initial[0].end()))):
            continue
        if not 0 < offset < stride or len({alias, base, index, count}) != 4:
            continue
        names = rf'(?:{alias}|{base}|{index}|{count})'
        if re.search(rf'(?m)^\s*#\s*define[^\n]*\b{names}\b|(?<!&)&(?!&)\s*(?:\(\s*)*{names}\b', context):
            continue
        reads = list(re.finditer(
            rf'\b{alias}\s*\[\s*(?:\(\(s32\)\s*\(\s*{index}\s*\*\s*{stride}\s*\)\s*\)\s*-\s*(?P<sub>{NUMBER})'
            rf'|{index}\s*\*\s*{stride})\s*\]', body))
        if not reads or len(re.findall(rf'\b{alias}\b', body)) != len(reads):
            continue
        if len(re.findall(rf'\b{index}\b', body)) != len(reads) + 1:
            continue
        if len(re.findall(rf'\b{base}\b', body)) != 1 + len(re.findall(rf'\b{base}\s*\[', body)):
            continue
        # A macro that hides an update or a transfer is outside the CFG.
        for macro in re.finditer(rf'(?m)^\s*#\s*define\s+({IDENT})[^\n]*', context):
            if re.search(rf'\b{macro[1]}\b', body) and re.search(r'[;{{}}#\\]|\b(?:goto|return|break|continue)\b',
                                                                  macro[0].lstrip()[1:]):
                break
        else:
            macro = None
        if macro:
            continue
        if flow is None:
            flow = local_flow.analyze(part.source, name)
            if not flow:
                return []
            dominates = dominators(flow)
            node_ids = {id(node): i for i, node in enumerate(flow.nodes)}
        nodes = {i for i, node in enumerate(flow.nodes) if opening < node.start < end + condition.end()}
        first = min(nodes, key=lambda i: flow.nodes[i].start, default=None)
        init_at = [flow.at(part.opening + item.start()) for item in (aliases[0], initial[0])]
        if first is None or any(not node or node_ids[id(node)] not in dominates.get(first, set()) for node in init_at):
            continue
        incoming = [(node, i) for j, node in enumerate(flow.nodes) if j not in nodes
                    for i in node.successors & nodes]
        if len(incoming) != 1 or incoming[0][1] != first or incoming[0][0].start >= opening:
            continue
        advance = flow.at(opening + 1 + pair.start())
        increment = flow.at(opening + 1 + pair.end() - 2)
        if not advance or not increment or increment is advance:
            continue
        increment_id = node_ids[id(increment)]
        if [node for node in flow.nodes if increment_id in node.successors] != [advance]:
            continue
        # The two updates execute together. A forward branch may skip both;
        # a back edge inside the body could overflow the bounded counter.
        if any(i in nodes and flow.labels[label] in nodes and flow.nodes[flow.labels[label]].start < flow.nodes[i].start
               for i, label in flow.gotos):
            continue
        changes = []
        for read in reads:
            field = offset - (integer(read['sub']) if read['sub'] else 0)
            if not 0 <= field < stride:
                break
            changes.append((opening + 1 + read.start(), opening + 1 + read.end(), f'{base}[{field}]'))
        else:
            out.append((FAMILY, edit(part.source, changes)))
    return out
