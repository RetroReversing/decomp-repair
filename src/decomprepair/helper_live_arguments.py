"""A call of a helper that takes no parameters, passed the addresses the function has just computed.

A target can hold three freshly computed pointers in `$a0`-`$a2` up to a `jal` whose callee reads none of them: the
original call named them (an unprototyped call), and without that the allocator gives the same values other registers.
On an N64 model loader (SN GCC 2.8.1), `helper();` after `nodes = ...; entry = ...; header = ...;` had the header
pointer in `$a1`; `helper(nodes, entry, header);` put it in `$a2` (40 -> exact with the other steps). The callee ignores
extra arguments in the o32 calling convention, so the program is the same. Offered for a statement `name();` whose
prototype in the source is `(void)` or `()`, with two or three of the locals assigned before it, in every order.
"""
import itertools
import re

from .csource import _blank, find

FAMILY = 'helper_live_arguments'
FAMILIES = (FAMILY,)
LIMIT = 36
POOL = 4

_CALL = re.compile(r'(?m)^[ \t]*(?P<callee>[A-Za-z_]\w*)\([ \t]*\)[ \t]*;')
_ASSIGN = re.compile(r'(?<![\w.>])(?P<v>[A-Za-z_]\w*)[ \t]*=(?!=)[ \t]*(?P<rhs>[^;{}]+);')


def variants(source, name, arch=''):
    if arch and not arch.startswith('mips'):
        return []
    span = find(source, name)
    if not span:
        return []
    brace = source.find('{', span[0])
    clean = _blank(source)
    out = []
    calls = [m for m in _CALL.finditer(source, brace) if clean[m.start('callee')] != ' ']
    for call in calls[:2]:
        callee = call['callee']
        prototype = re.search(rf'(?m)^(?P<head>[^\n=()]*\b{callee})[ \t]*\([ \t]*(?:void)?[ \t]*\)[ \t]*;', source[:span[0]])
        if not prototype:
            continue
        pool = []
        for m in _ASSIGN.finditer(clean, brace, call.start()):
            # an address-like value: a sum or a member read, not a constant or a call's result
            if re.search(r'\+|->|\bobj\b', m['rhs']) and '(' + ')' not in m['rhs']:
                if m['v'] in pool:
                    pool.remove(m['v'])
                pool.append(m['v'])
        pool = pool[-POOL:]
        for count in (3, 2):
            for chosen in itertools.permutations(reversed(pool), count):
                child = source[:call.start()] + call.group().replace('()', f"({', '.join(chosen)})") + source[call.end():]
                child = child[:prototype.start()] + prototype['head'] + '();' + child[prototype.end():]
                out.append((FAMILY, child))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 1200}
