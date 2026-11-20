"""Narrow MIPS KMC type hypotheses backed by the candidate/target instruction diff."""

import re

from .integer_repair_support import IDENT, edit, view


def counter_gap(rows):
    """The target branches over a unit increment where KMC emitted a boolean add."""
    for first, second in zip(rows, rows[1:]):
        marker, branch, test = first
        _, increment, add = second
        if marker == ' ' or not re.match(r'(?:beq|bne)l?z?\s', branch):
            continue
        boolean = re.fullmatch(r'sltu\s+(\$\w+),\s*\$zero,\s*(\$\w+)', test)
        unit = re.fullmatch(r'addiu\s+(\$\w+),\s*\1,\s*(?:1|0x1)', increment)
        if (boolean and unit and boolean[2] in re.findall(r'\$\w+', branch)
                and re.fullmatch(rf'addu\s+{re.escape(unit[1])},\s*{re.escape(unit[1])},\s*{re.escape(boolean[1])}', add)):
            return True
    return False


def narrow_counter(source, part):
    for declaration in re.finditer(rf'\bs32\s+({IDENT})\s*;', part.body):
        name = re.escape(declaration[1])
        reference = rf'\b{name}\b'
        uses = list(re.finditer(reference, part.body))
        if len(uses) < 4:
            continue
        # Accept one zero initializer, a single increment and otherwise explicitly byte-masked reads.
        initializers = list(re.finditer(rf'{reference}\s*=\s*0\s*;', part.body))
        increments = list(re.finditer(rf'{reference}\s*(?:\+=\s*1|\+\+)\s*;', part.body))
        masked = list(re.finditer(rf'(?<=\()\s*({reference})\s*&\s*(?:0[xX][fF][fF]|255)\s*\)', part.body))
        if len(initializers) != 1 or len(increments) != 1 or not masked:
            continue
        starts = {declaration.start(1), initializers[0].start(), increments[0].start()}
        starts.update(match.start(1) for match in masked)
        if starts == {use.start() for use in uses}:
            # A shadowed declaration, escaping pointer, or any unmasked use fails the check above.
            return edit(source, [(part.opening+1+declaration.start(), part.opening+1+declaration.start()+3, 'u8')])
    return None


def float_forward(source, name, header, part, rows):
    # KMC promotes arguments at unprototyped calls. Require a changed conversion
    # into the first float argument register and a target call to that same callee.
    if not any(marker != ' ' and re.match(r'mov\.s\s+\$f12,', left)
               and re.match(r'cvt\.d\.s\s+\$f12,', right) for marker, left, right in rows):
        return None
    prefix = part.clean[:part.opening]
    signature = re.search(rf'\b{re.escape(name)}\s*\(\s*(s32|int)\s+({IDENT})\s*,\s*(f32|float)\s+({IDENT})\b[^()]*\)\s*$', prefix)
    if not signature or re.search(rf'\b{re.escape(name)}\s*\(', header):
        return None
    entry = signature[2]
    forwarding = re.search(rf'\b({IDENT})\s*\(\s*{re.escape(entry)}\s*\)', part.body)
    if not forwarding or len(re.findall(rf'\b{re.escape(entry)}\b', part.body)) != 1:
        return None
    callee = re.escape(forwarding[1])
    if re.search(rf'\b{callee}\b', header):
        return None
    # Bind the promotion mismatch to an adjacent direct call, including its delay slot.
    for i, (marker, left, right) in enumerate(rows):
        if (marker != ' ' and re.match(r'mov\.s\s+\$f12,', left)
                and re.match(r'cvt\.d\.s\s+\$f12,', right)
                and any(re.fullmatch(rf'jal\s+{callee}', row[1]) for row in rows[max(0, i-1):i+2])):
            break
    else:
        return None
    prototypes = list(re.finditer(rf'\b(?:f32|float)\s+{callee}\s*\((\s*)\)\s*;', prefix))
    if len(prototypes) != 1:
        return None
    arguments = re.findall(rf'\b{callee}\s*\(\s*({IDENT})\s*\)', part.body)
    if (len(arguments) < 2 or len(arguments) != len(re.findall(rf'\b{callee}\b', part.body))
            or len(arguments)+1 != len(re.findall(rf'\b{callee}\b', part.clean))):
        return None
    for argument in set(arguments) - {entry}:
        if not re.search(rf'\b(?:f32|float)\s+{re.escape(argument)}\b', prefix[signature.start():]):
            return None
    prototype = prototypes[0]
    return edit(source, [(*signature.span(1), signature[3]), (*prototype.span(1), signature[3])])


def variants(source, name, header, rows):
    if not rows or not (part := view(source, name)) or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    result = []
    if counter_gap(rows) and (candidate := narrow_counter(source, part)):
        result.append(('kmc_byte_counter', candidate))
    if candidate := float_forward(source, name, header, part, rows):
        result.append(('kmc_float_forward_prototype', candidate))
    return result
