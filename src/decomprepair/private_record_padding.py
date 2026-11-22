"""Try removing private padding and moving one neighboring array."""
import re

from .integer_repair_support import edit, view

FAMILY = 'private_record_padding'

RECORD = re.compile(r'(?m)^([ \t]*)struct\s*\{([^{}]+)\}\s*([A-Za-z_]\w*)\s*;\n')
PAD = re.compile(r'(?m)^[ \t]+u32\s+(pad[A-Z]\w*)\s*;\n')
NEIGHBORS = re.compile(
    r'(?P<array>[ \t]*[A-Za-z_]\w*\s+[A-Za-z_]\w*\[[1-9]\d*\];\n)'
    r'(?P<scalars>(?:[ \t]*volatile s32\s+[A-Za-z_]\w*;\n){1,2})'
)


def variants(source, name, rows, header=''):
    """Try the joint layout change when the candidate frame has eight extra bytes."""
    target_frame = re.compile(r'addiu \$sp, \$sp, -(0x[\da-fA-F]+|\d+)')
    if not rows:
        return []
    _, target, candidate = rows[0]
    target_size, candidate_size = target_frame.fullmatch(target), target_frame.fullmatch(candidate)
    if not target_size or not candidate_size or int(candidate_size[1], 0) - int(target_size[1], 0) != 8:
        return []
    part = view(source, name)
    if not part:
        return []
    start = part.opening + 1
    start += len(part.clean[start:]) - len(part.clean[start:].lstrip('\n'))
    record = RECORD.match(part.clean, start)
    if not record:
        return []
    neighbors = NEIGHBORS.match(part.clean, record.end())
    if not neighbors:
        return []
    pads = list(PAD.finditer(record[2]))
    if len(pads) != 2 or any(len(re.findall(r'\b'+re.escape(pad[1])+r'\b', part.clean + header)) != 1
                            for pad in pads):
        return []
    if re.search(r'\b(?:sizeof|offsetof|__builtin_offsetof)\b', part.body):
        return []
    tail = part.clean[record.end():part.end]
    uses = list(re.finditer(r'\b'+re.escape(record[3])+r'\b', tail))
    if not uses or any(not re.match(r'\s*\.\s*[A-Za-z_]\w*', tail[use.end():]) for use in uses):
        return []
    changes = [(record.start(2)+pad.start(), record.start(2)+pad.end(), '') for pad in pads]
    changes.append((neighbors.start(), neighbors.end(),
                    source[slice(*neighbors.span('scalars'))] + source[slice(*neighbors.span('array'))]))
    return [(FAMILY, edit(source, changes))]
