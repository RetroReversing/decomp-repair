"""Separate an incoming pointer from the local reassigned during traversal."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'mutable_parameter_local'
POINTER_PARAMETER = re.compile(rf'\s*((?:const\s+)?(?:struct\s+)?{IDENT}\s*\*)\s*({IDENT})\s*')
LOCAL = re.compile(rf'\s*(?:(?:struct\s+)?{IDENT}\s+)+\**\s*{IDENT}\s*'
                   rf'(?:=\s*(?:{IDENT}|[\d.]+[fFuU]?))?\s*;')


def variants(source, function, header=''):
    part = view(source, function)
    if not part or re.search(r'\b(?:goto|asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    signature = list(re.finditer(rf'\b{re.escape(function)}\s*\(([^()]*)\)\s*$', part.clean[:part.opening]))
    if not signature or not re.search(r'\b(?:do|for|while)\b', part.body):
        return []
    parameters = signature[0]
    first = part.opening + 1
    placements = [first]
    while local := LOCAL.match(part.clean, placements[-1], part.end):
        placements.append(local.end())
    # GCC can allocate the incoming copy differently depending on which existing
    # initializations precede it. Keep only the edges of the declaration block.
    placements = list(dict.fromkeys([placements[-1], *placements[-2:-1], first]))
    result = []
    cursor = parameters.start(1)
    for text in parameters[1].split(','):
        param = POINTER_PARAMETER.fullmatch(text)
        if param:
            kind, name = param.groups()
            if (re.search(rf'(?<![.>\w]){re.escape(name)}\s*=(?!=)', part.body)
                    and not re.search(rf'&\s*{re.escape(name)}\b', part.body)
                    and not re.search(r'\b(?:volatile|restrict)\b', kind)):
                incoming = name + 'Input'
                if not re.search(rf'\b{incoming}\b', source+'\n'+header):
                    for position in placements:
                        result.append((FAMILY, edit(source, [
                            (cursor+param.start(2), cursor+param.end(2), incoming),
                            (position, position, f'\n    {kind} {name} = {incoming};'),
                        ])))
        cursor += len(text)+1
        if len(result) >= 6:
            break
    return result[:6]
