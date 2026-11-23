"""A no-op copy-back (`a = b; b = a;`) taken out, with the statement after it read before the copy.

The search's `copy_back_set` adds `b = a;` after a copy `a = b;` to make `b` a pseudo set twice; saved bests carry it
long after the edit that wanted it. With the copy-back, cse keeps `a` as the register holding the value (the head of
the class), and the next read of `b` comes out reading `a`'s register: a pixel loop's `row = col - j;` after `level =
j; j = level;` was `subu $a0, $v0, $a1` where the target reads `j`'s own register (`subu $a0, $v0, $a2`). Written as
the game had it, `row = col - j; level = j;`, the read comes first and the copy follows (`move $a1, $a2` stays where
the scheduler puts it): 100 -> 95 on a 1133-instruction effect spawner (KMC GCC 2.7.2), where dropping the copy-back
alone was worse (125).

Children per copy-back: the pair without `b = a;`, and that with the next statement moved above `a = b;` when it
reads `b`, does not mention `a`, assigns a plain local other than `a`/`b` and has no call or increment.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'copy_back_drop'
FAMILIES = (FAMILY,)
LIMIT = 12

_PAIR = re.compile(rf'(?P<first>(?<=[;{{}}:])[ \t]*\n?[ \t]*(?P<a>{IDENT})\s*=\s*(?P<b>{IDENT})\s*;)'
                   rf'(?P<second>\s*(?P=b)\s*=\s*(?P=a)\s*;)')
_TYPES = {'u8', 's8', 'u16', 's16', 'u32', 's32', 'f32', 'f64', 'char', 'short', 'int', 'long', 'unsigned', 'signed',
          'void', 'float', 'double', 'sizeof'}
_NEXT = re.compile(rf'\s*(?P<stmt>(?P<dest>{IDENT})\s*=(?!=)[^;{{}}]*;)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        a, b = hit['a'], hit['b']
        if a == b:
            continue
        out.append(edit(source, [(hit.start('second'), hit.end('second'), '')]))
        following = _NEXT.match(part.clean, hit.end('second'))
        if not following:
            continue
        stmt = source[following.start('stmt'):following.end('stmt')]
        rhs = stmt.split('=', 1)[1]
        calls = [m[1] for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', rhs) if m[1] not in _TYPES]
        if (following['dest'] in (a, b) or not re.search(rf'\b{re.escape(b)}\b', rhs)
                or re.search(rf'\b{re.escape(a)}\b', stmt) or '++' in rhs or '--' in rhs or calls):
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start('a')) + 1:])[0]
        first = source[hit.start('a'):hit.end('first')]
        out.append(edit(source, [(hit.start('a'), hit.end('first'), stmt),
                                 (hit.start('second'), following.end('stmt'), '\n' + indent + first)]))
        if len(out) >= LIMIT:
            break
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
