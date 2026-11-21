"""Recover the order of a volatile loop-bound read and an unconditional reset."""

import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .loaded_byte_repairs import declarators
from .pattern_repairs import close

FAMILY = 'guard_reset_scheduling'
DELAY_SLOT_FAMILY = 'guard_reset_delay_slot'
ZERO_MOVE = re.compile(r'move \$s[0-7], \$zero')
REG = r'\$\w+'
LOAD = re.compile(rf'lw (?P<reg>{REG}), %lo\((?P<symbol>{IDENT})\)\((?P=reg)\)')
RESET = re.compile(rf'sw \$zero, %lo\((?P<symbol>{IDENT})\)\((?P<base>{REG})\)')
PREFIX = re.compile(
    rf'(?<=[;{{}}])\s*do\s*{{\s*{{(?P<copies>'
    rf'\s*s32\s+(?P<first>{IDENT})\s*=\s*{IDENT}\s*;'
    rf'\s*s32\s+(?P<second>{IDENT})\s*=\s*{IDENT}\s*;'
    rf'\s*{IDENT}\s*=\s*(?P=first)\s*;\s*{IDENT}\s*=\s*(?P=second)\s*;)\s*}}'
    rf'(?P<resets>\s*(?P<reset>{IDENT})\s*=\s*0\s*;\s*(?P<index_reset>(?P<index>{IDENT})\s*=\s*0\s*;))'
    rf'\s*}}\s*while\s*\(\s*0\s*\)\s*;'
    rf'(?P<guard>\s*if\s*\(\s*(?P<bound>{IDENT})\s*>\s*0\s*\)\s*{{)'
)


def _sites(rows):
    target, candidate = ([row[side] for row in rows if row[side]] for side in (1, 2))
    for offset, (upper, load, address, store, branch) in enumerate(zip(
            target, target[1:], target[2:], target[3:], target[4:])):
        bound, reset = LOAD.fullmatch(load), RESET.fullmatch(store)
        if not bound or not reset:
            continue
        if (upper != f'lui {bound["reg"]}, %hi({bound["symbol"]})'
                or address != f'lui {reset["base"]}, %hi({reset["symbol"]})'
                or not branch.startswith(f'blez {bound["reg"]}, ') or candidate.count(store) != 1
                or candidate.count(load) != 1 or candidate.index(store) >= candidate.index(load)):
            continue
        key = reset['symbol'], bound['symbol']
        slot = target[offset + 5] if offset + 5 < len(target) else ''
        yield key, False
        if ZERO_MOVE.fullmatch(slot) and slot in candidate[:candidate.index(store)]:
            yield key, True


def variants(source, name, header, rows):
    """Keep the loop's repeated reads and place the first read before its reset."""
    sites = set(_sites(rows))
    if not sites or not (part := view(source, name)):
        return []
    locals_by_name = {decl['name']: decl for decl in locals_for(part)}
    new_name = 'initial_bound'
    while re.search(rf'\b{new_name}\b', source + '\n' + header):
        new_name += '_'
    result = []
    for match in PREFIX.finditer(part.clean, part.opening + 1, part.end):
        reset, bound, index = (match[key] for key in ('reset', 'bound', 'index'))
        if (((reset, bound), False) not in sites or len({reset, bound, index}) != 3
                or index not in locals_by_name or locals_by_name[index].start() > match.start()):
            continue
        if not all(re.search(rf'\bextern\s+volatile\s+s32\s+{symbol}\s*;', part.clean[:part.opening])
                   for symbol in (reset, bound)) or any(len(declarators(part.clean, symbol)) != 1 for symbol in (reset, bound)):
            continue
        end = close(part.clean, match.end() - 1, '{', '}')
        if end is None or re.match(r'\s*else\b', part.clean[end:]):
            continue
        if not re.search(rf'\bwhile\s*\([^;{{}}]*<\s*{bound}\s*\)\s*;', part.clean[match.end():end]):
            continue
        copies = source[match.start('copies'):match.end('copies')]
        resets = source[match.start('resets'):match.end('resets')]
        guard = source[match.start('guard'):match.start('bound')] + new_name + source[match.end('bound'):match.end()]
        indent = re.match(r'\s*', source[match.start():]).group().rsplit('\n', 1)[-1]
        prefix = f'\n{indent}do {{{copies} }} while (0);\n{indent}{{ s32 {new_name} = {bound};'
        scope_end = (end, end, f'\n{indent}}}')
        if ((reset, bound), True) in sites:
            clear = source[match.start('resets'):match.start('index_reset')]
            zero = source[match.start('index_reset'):match.end('index_reset')]
            # The one-shot block changes KMC's scheduling of the local zero.
            wrapped = f'{prefix}{clear}do {{ {zero} }} while (0);{guard}'
            result.append((DELAY_SLOT_FAMILY, edit(source, [(match.start(), match.end(), wrapped), scope_end])))
        result.append((FAMILY, edit(source, [(match.start(), match.end(), prefix + resets + guard), scope_end])))
    return result[:4]
