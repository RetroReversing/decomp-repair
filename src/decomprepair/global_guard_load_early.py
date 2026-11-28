"""A global an `if` tests, read into a local above the global stores in front of the test.

    state = 1;                      staged = busy;
    dirty = 1;              ->      state = 1;
    if (busy == 0) {                dirty = 1;
        reload();                   if (staged == 0) {
    }                                   reload();
                                    }

Written the first way GCC loads the tested global where the test is. A target that loads it before the stores had it
in a local. The earlier read also lengthens how long the stored globals' high-address registers live, and loop.c moves
an address out of a loop only when `threshold * savings * lifetime` reaches the loop's size, so the same edit decides
whether `lui` of a stored global is hoisted (and then rematerialised through a reload register, `lui $t0`, instead of
`$v0`). A 377-instruction N64 frame-update loop (SN GCC 2.8.1, `-G0 -mips3 -O2`) went 605 -> 0 with one child; the
loop dump showed the address's lifetime go from 7 to 9 and its move from "not desirable" to done.

The tested name must be a non-volatile scalar or pointer global (declared `extern` in the source or the header), and
every statement passed over assigns another plain name without a call, so the test reads the value it read before. A
store through a pointer or into an array stops the walk, since it could write the tested global. Children read the
value above the whole run of stores and, when the run is longer than one, above its last store only. Proposals; the
byte judge decides."""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'global_guard_load_early'
FAMILIES = (FAMILY,)
LIMIT = 12

_IF = re.compile(r'(?m)^[ \t]*if\s*\(')
_CONSTANT = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*|NULL'
_TEST = re.compile(rf'\s*(?:!\s*)?(?P<name>{IDENT})\s*(?:(?:==|!=|<=|>=|<|>)\s*(?:{_CONSTANT})\s*)?(?=\)\s*$|&&|\|\|)')
_STORE = re.compile(rf'(?P<indent>[ \t]*)(?P<target>{IDENT})\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)(?P<value>[^;{{}}()?]*);[ \t]*')
_TYPE_WORD = r'(?:unsigned|signed|char|short|int|long|[su](?:8|16|32)|[A-Z]\w*)'


def _global_type(text, name):
    """The declared type of an `extern` scalar or pointer global, or None (an array, a volatile or no declaration)."""
    found = re.search(rf'\bextern\s+((?:{_TYPE_WORD}\s+)*{_TYPE_WORD})(\s*\**)\s*\b{name}\s*;', text)
    if not found:
        return None
    return found.group(1) + (' ' + found.group(2).strip() if found.group(2).strip() else '')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    declarations = header + '\n' + source
    body = part.clean[part.opening:part.end]
    local = next(f'staged_global{n}' for n in range(100) if not re.search(rf'\bstaged_global{n}\b', body))
    found = []
    for test in _IF.finditer(part.clean, part.opening, part.end):
        paren = test.end() - 1
        stop = close(part.clean, paren)
        if not stop:
            continue
        condition = part.clean[paren + 1:stop - 1]
        head = _TEST.match(condition + ')')
        if not head:
            continue
        tested = head.group('name')
        kind = _global_type(declarations, tested)
        if not kind:
            continue
        stores = []
        end = test.start()
        while True:
            start = part.clean.rfind('\n', 0, end - 1) + 1
            store = _STORE.fullmatch(part.clean[start:end].rstrip('\n'))
            if not store or store.group('target') == tested:
                break
            before = part.clean[:start].rstrip()
            if not before.endswith((';', '{', '}')):
                break
            stores.append((start, store.group('indent')))
            end = start
        if not stores:
            continue
        low = paren + 1 + head.start('name')
        high = paren + 1 + head.end('name')
        for start, indent in dict.fromkeys((stores[-1], stores[0])):
            changed = (source[:start] + f'{indent}{local} = {tested};\n' + source[start:low] + local + source[high:])
            found.append((FAMILY, changed[:part.opening + 1] + f'\n    {kind} {local};' + changed[part.opening + 1:]))
        if len(found) >= LIMIT:
            break
    return found[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
