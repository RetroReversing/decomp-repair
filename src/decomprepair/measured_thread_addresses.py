"""Recover independently relocated queue and stack addresses in a thread setup."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$a0, %hi\((?P<queue>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=queue)\)\n'
    rf'lui \$a1, %hi\((?P<messages>{IDENT})\)\naddiu \$a1, \$a1, %lo\((?P=messages)\)\n'
    rf'addiu \$a2, \$zero, 1\nsw \$ra, \d+\(\$sp\)\njal (?P<createqueue>{IDENT})\nsw \$s0, \d+\(\$sp\)\n'
    rf'lui \$s0, %hi\([^\n]+\)\naddiu \$s0, \$s0, %lo\([^\n]+\)\n'
    r'move \$a0, \$s0\naddiu \$a1, \$zero, 10\n'
    rf'lui \$a2, %hi\((?P<entry>{IDENT})\)\naddiu \$a2, \$a2, %lo\((?P=entry)\)\n'
    rf'lui \$v0, %hi\((?P<stack>{IDENT})\)\naddiu \$v0, \$v0, %lo\((?P=stack)\)\n'
    rf'sw \$v0, 16\(\$sp\)\naddiu \$v0, \$zero, 127\nmove \$a3, \$zero\n'
    rf'jal (?P<createthread>{IDENT})\nsw \$v0, 20\(\$sp\)\n'
    rf'jal (?P<start>{IDENT})\nmove \$a0, \$s0'
)
_SOURCE = re.compile(
    rf'(?P<createqueue>{IDENT})\(\(char \*\)&(?P<queuebase>{IDENT}) \+ (?P<queueoffset>{NUMBER}), '
    rf'(?P<message>\(char \*\)&(?P<messagebase>{IDENT}) \+ (?P<messageoffset>{NUMBER})), 1\);\s*'
    rf'(?P<local>{IDENT}) = \(char \*\)&(?P<threadbase>{IDENT}) \+ (?P<threadoffset>{NUMBER});\s*'
    rf'(?P<createthread>{IDENT})\((?P=local), 0xA, &(?P<entry>{IDENT}), 0, '
    rf'(?P<stack>\(char \*\)&(?P<stackbase>{IDENT}) \+ (?P<stackoffset>{NUMBER})), 0x7F\);\s*'
    rf'(?P<start>{IDENT})\((?P=local)\);'
)


def variants(source, name, header, rows, resolve):
    if not resolve or len(rows) != 32:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    hit = _TARGET.search(target)
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if (not hit or ('lui $a1, %hi(' + hit['messages'] + ')', '') not in changes
            or ('lui $v0, %hi(' + hit['stack'] + ')', '') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.search(part.body)
    if (not draft or any(draft[key] != hit[key] for key in ('createqueue', 'createthread', 'start', 'entry'))
            or hit['messages'] == hit['stack']):
        return []
    for role in ('queue', 'message', 'stack'):
        actual = hit['messages' if role == 'message' else role]
        base = resolve(draft[role + 'base'])
        if base is None or base + integer(draft[role + 'offset']) != resolve(actual):
            return []
    context = part.clean + _blank(header)
    additions = []
    for symbol in (hit['messages'], hit['stack']):
        if re.search(rf'\b{symbol}\b', context):
            if not re.search(rf'\bextern char {symbol}\[\];', context):
                return []
        else:
            additions.append(f'extern char {symbol}[];\n')
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening])
    if not signature:
        return []
    start = part.opening + 1
    changes = [(start + draft.start(role), start + draft.end(role), f'(char *)&{hit[symbol]}')
               for role, symbol in (('message', 'messages'), ('stack', 'stack'))]
    if additions:
        changes.append((signature.start(), signature.start(), ''.join(additions) + '\n'))
    return [('measured_thread_symbol_addresses', edit(source, changes))]
