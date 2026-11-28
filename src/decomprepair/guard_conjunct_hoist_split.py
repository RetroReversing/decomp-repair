"""`if (a && b && c) { p = table; ... }` as `if (a && b) { p = table; if (c) { ... } }`.

A pointer or constant the guarded block starts with can have been set by the original between two tests of the guard. The
target then builds its address before the last test (`lui $v1, %hi(table)` ahead of the final `lw`/`sltiu`/`beqz`, the
`addiu` in that branch's delay slot), which no spelling of one `&&` chain gives: every test of the chain comes before
the block's first statement. A particle-quad builder (SN GCC 2.8.1, `-G0 -mips3 -O2`, a 205-instruction N64 function;
one function) went from 921 to 6 with this one change.

Only for an `if` with no `else` whose condition is a top-level `&&` chain. The statements moved are the leading
assignments of a local from a name, an address or a number (nothing that can fault or call), whose local is not
address-taken, is not read by the tests it moves above and is not named after the block, so the meaning is the same.
One child for each place in the chain, the last test first. A candidate rewrite; the judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, view
from .pattern_repairs import close

FAMILY = 'guard_conjunct_hoist_split'
FAMILIES = (FAMILY,)
LIMIT = 8
SAFE = rf'(?:&\s*{IDENT}|{IDENT}|-?{NUMBER}|-?[0-9]+\.[0-9]*[fF]?)'
ASSIGNMENT = re.compile(rf'\s*(?P<name>{IDENT})\s*=(?!=)\s*(?:\(\s*{IDENT}(?:\s+{IDENT})?[\s*]*\)\s*)?{SAFE}\s*;')


def _cuts(condition):
    """Offsets of the top-level `&&` of a condition; none when a top-level `||` or `?` binds looser than the chain."""
    depth, found = 0, []
    for hit in re.finditer(r'[()\[\]]|&&|\|\||\?', condition):
        token = hit[0]
        depth += token in '(['
        depth -= token in ')]'
        if depth == 0 and token in ('||', '?'):
            return []
        if depth == 0 and token == '&&':
            found.append(hit.start())
    return found


def _local(body, name):
    """`name` is declared in the function's body and its address is never taken."""
    declared = re.search(rf'(?m)^\s*(?:(?:struct|union|unsigned|signed|register|const)\s+)*{IDENT}[\s*]+'
                         rf'(?:{IDENT}\s*,[\s*]*)*{name}\s*(?:[;,=])', body)
    return bool(declared) and not re.search(rf'(?<![&\w\])])\s*&\s*{name}\b', body)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        cond_open = part.opening + hit.end() - 1
        cond_close = close(clean, cond_open)
        brace = re.match(r'\s*\{', clean[cond_close:part.end]) if cond_close else None
        if not brace:
            continue
        block_open = cond_close + brace.end() - 1
        block_close = close(clean, block_open, '{', '}')
        if not block_close or re.match(r'\s*else\b', clean[block_close:part.end]):
            continue
        condition = clean[cond_open + 1:cond_close - 1]
        cuts = _cuts(condition)
        if not cuts:
            continue
        moved, at = [], block_open + 1
        while True:
            statement = ASSIGNMENT.match(clean, at, block_close - 1)
            if (not statement or not _local(part.body, statement['name'])
                    or re.search(rf'\b{statement["name"]}\b', clean[block_close:part.end])):
                break
            moved.append((statement['name'], source[at:statement.end()].strip()))
            at = statement.end()
        if not moved or not clean[at:block_close - 1].strip():
            continue
        line = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        raw = source[cond_open + 1:cond_close - 1]
        rest = source[at:block_close - 1].strip('\n').rstrip()
        for cut in reversed(cuts):
            first, second = raw[:cut].strip(), raw[cut + 2:].strip()
            if any(re.search(rf'\b{local}\b', condition[cut:]) for local, _ in moved):
                continue
            head = ''.join(f'{indent}    {text}\n' for _, text in moved)
            body = ''.join(('    ' + row if row.strip() else '') + '\n' for row in rest.split('\n'))
            text = (source[:start] + f'if ({first}) {{\n{head}{indent}    if ({second}) {{\n{body}'
                    + f'{indent}    }}\n{indent}}}' + source[block_close:])
            result.append((FAMILY, text))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}
