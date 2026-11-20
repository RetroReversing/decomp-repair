"""KMC casts supported by a measured load or read-modify-write mismatch."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

REGISTER = r'\$\w+'
ADDRESS = rf'(?:-?(?:0x[0-9a-f]+|\d+))?\({REGISTER}\)'
MEMORY = re.compile(rf'(lbu?|lhu?|lw|lwc1|sw)\s+({REGISTER}),\s*({ADDRESS})')
LUI = re.compile(rf'lui\s+({REGISTER}),\s*(0x[0-9a-f]+|\d+)')
OR = re.compile(rf'or\s+({REGISTER}),\s*({REGISTER}),\s*({REGISTER})')
TYPES = {'f32': 'lwc1', 'float': 'lwc1', 's32': 'lw', 'u32': 'lw', 'int': 'lw'}
WIDTHS = {'u8': 8, 'unsigned char': 8, 'u16': 16, 'unsigned short': 16}


def load_gaps(rows):
    """Find corresponding loads from the same address and the unwanted float conversion."""
    gaps = set()
    for i, (marker, target, candidate) in enumerate(rows):
        want, have = MEMORY.fullmatch(target), MEMORY.fullmatch(candidate)
        if (marker == ' ' or not want or not have or want[3] != have[3]
                or have[1] not in ('lb', 'lbu', 'lh', 'lhu')):
            continue
        if want[1] == 'lw':
            gaps.add('lw')
        elif want[1] == 'lwc1':
            following = [text for _, _, text in rows[i+1:i+6] if text]
            move = re.compile(rf'mtc1\s+{re.escape(have[2])},\s*({REGISTER})')
            for j, text in enumerate(following[:-1]):
                if (match := move.fullmatch(text)) and any(
                        re.fullmatch(rf'cvt\.s\.w\s+{REGISTER},\s*{re.escape(match[1])}', op)
                        for op in following[j+1:]):
                    gaps.add('lwc1')
                    break
    return gaps


def typed_loads(source, header, part, rows):
    gaps = load_gaps(rows)
    if not gaps:
        return []
    known = _blank(header) + '\n' + part.clean
    ctype = '|'.join(TYPES)
    assignment = re.compile(
        rf'(?m)^[ \t]*(?P<dest>{IDENT})\s*=\s*(?P<load>\(\s*(?P<type>{ctype})\s*\)\s*\*\s*(?P<ptr>{IDENT}))\s*;')
    by_kind = {}
    for match in assignment.finditer(part.body):
        typ, pointer, dest = match['type'], match['ptr'], match['dest']
        kind = TYPES[typ]
        if kind not in gaps or not re.search(
                rf'\b(?:u8|s8|u16|s16|char|short)\s*\*\s*{re.escape(pointer)}\s*;', part.body):
            continue
        if not re.search(rf'\b{typ}\s+{re.escape(dest)}\s*(?=[;=,)])', known):
            continue
        start, end = match.span('load')
        start, end = part.opening+1+start, part.opening+1+end
        if re.search(r'/[*/]', source[start:end]):
            continue
        replacement = f'*({typ} *){pointer}' + '\n' * source[start:end].count('\n')
        by_kind.setdefault(kind, []).append((pointer, (start, end, replacement)))
    eligible = [choices[0] for choices in by_kind.values() if len(choices) == 1]
    result = [('kmc_typed_load', edit(source, [change])) for _, change in eligible]
    if len(eligible) == 2 and eligible[0][0] == eligible[1][0]:
        # A single load change can improve the score, while two branches may
        # need their own type to recover the target together.
        result.insert(0, ('kmc_typed_load', edit(source, [change for _, change in eligible])))
    return result


def missing_or_literals(rows):
    """Materialized high-word constants feeding a missing OR between a load and its store."""
    target = [(marker, text, candidate) for marker, text, candidate in rows if text]
    for i in range(1, len(target)-1):
        marker, instruction, candidate = target[i]
        if marker == ' ' or candidate or not (operation := OR.fullmatch(instruction)):
            continue
        load, store = (MEMORY.fullmatch(target[j][1]) for j in (i-1, i+1))
        if not (load and store and load[1] == 'lw' and store[1] == 'sw' and load[3] == store[3]
                and store[2] == operation[1] and load[2] in operation.groups()[1:]):
            continue
        constant = operation[3] if load[2] == operation[2] else operation[2]
        if constant == load[2]:
            continue
        for _, previous, _ in reversed(target[max(0, i-48):i-1]):
            if (upper := LUI.fullmatch(previous)) and upper[1] == constant:
                yield int(upper[2], 0) << 16
                break
            # A store or branch can end a local proof too. The matched example
            # keeps its upper immediate in a saved register across a direct call.
            if re.match(rf'\w+\s+{re.escape(constant)}(?:,|$)', previous):
                break
            if previous.startswith(('jal ', 'jalr ')) and not re.fullmatch(r'\$s[0-7]', constant):
                break


def truncated_literal(source, part, rows):
    literals = set(missing_or_literals(rows))
    if not literals:
        return []
    narrow = r'(?:u8|u16|unsigned\s+(?:char|short))'
    pattern = re.compile(rf'(?<!\|)\|(?!\|)\s*(?P<cast>\(\s*(?P<type>{narrow})\s*\)\s*)'
                         r'(?P<number>0[xX][\da-fA-F]+|[1-9]\d*)\b(?=\s*[);])')
    edits = []
    for match in pattern.finditer(part.body):
        value = int(match['number'], 0)
        width = WIDTHS[' '.join(match['type'].split())]
        if value not in literals or not 0 < value <= 0xffffffff or value & ((1 << width)-1):
            continue
        start, end = match.span('cast')
        start, end = part.opening+1+start, part.opening+1+end
        if re.search(r'/[*/]', source[start:end]):
            continue
        edits.append((start, end, '\n' * source[start:end].count('\n')))
    return [('kmc_truncated_literal', edit(source, edits))] if len(edits) == 1 else []


def variants(source, name, header, rows, flags=()):
    if not rows or not (part := view(source, name)) or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    result = [] if '-fstrict-aliasing' in flags else typed_loads(source, header, part, rows)
    return result + truncated_literal(source, part, rows)
