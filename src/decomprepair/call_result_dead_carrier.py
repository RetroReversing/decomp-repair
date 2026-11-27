"""A call's result carried by a local the function has finished with, with an address load before the addition.

`p = table; angle = measure(x, y) + 0x800;` loads the table's address before the call (or after the addition). The
target (GCC 2.8.1, SN N64) loaded it between them, in `$v1` because `$v0` holds the result:
`jal; lui v1; addiu s5,v1; addiu v0,v0,0x800`. The game kept the result in an `int` local that was dead there:

    shade = measure(x, y);
    p = table;
    angle = shade + 0x800;

A fresh local does not do it (255 where the dead one gave 10 on a 195-instruction N64 effect function): the carrier's
other live ranges set its priority. So every `int` local of the result's type that is dead at that point is offered.

The same function's last rows were a scratch value in that local, `bit = random() & 2; e->flag = bit * 0x10;`, which the
target kept in `$v0`: written into the one statement that reads it (`call_result_temp_inline`, 10 -> 0). It is offered
when the local's next mention after that statement is an assignment, so nothing else sees the value.

Neither rewrite is offered inside a loop. A candidate: the judge decides.
"""
import re

from .c_scan import enclosing_block, header_before
from .integer_repair_support import IDENT, edit, view

CARRIER = 'call_result_dead_carrier'
INLINE = 'call_result_temp_inline'
FAMILIES = (CARRIER, INLINE)
LIMIT = 12
_INTEGERS = r'(?:s32|int|long)'
_ADDRESS = rf'(?P<pointer>{IDENT})[ \t]*=[ \t]*(?P<address>&?[ \t]*{IDENT})[ \t]*;'
_SUM = (rf'(?P<result>{IDENT})[ \t]*=[ \t]*(?P<call>{IDENT}\s*\((?:[^();]|\([^();]*\))*\))\s*'
        rf'(?P<rest>[+\-]\s*(?:0[xX][0-9A-Fa-f]+|\d+))[ \t]*;')
_PAIRS = (re.compile(rf'(?<![\w.>]){_ADDRESS}\s*{_SUM}'), re.compile(rf'(?<![\w.>]){_SUM}\s*{_ADDRESS}'))
_STAGE = re.compile(rf'(?<=[;{{}}])(?P<lead>\s*)(?P<temp>{IDENT})[ \t]*=(?!=)(?P<expr>[^;{{}}=]*);'
                    r'(?P<gap>\s*)(?P<use>[^;{}]*;)')


def _integers(clean, part):
    found = {}
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<type>{_INTEGERS})[ \t]+(?P<names>{IDENT}(?:[ \t]*,[ \t]*{IDENT})*)[ \t]*;',
                           clean[part.opening:part.end]):
        for name in re.findall(IDENT, hit['names']):
            found[name] = hit['type']
    return {name: kind for name, kind in found.items()
            if not re.search(rf'&\s*{name}\b(?!\s*[\w(])', clean[part.opening:part.end])}


def _in_loop(clean, opening, at):
    brace = enclosing_block(clean, at, opening + 1)
    while brace >= 0:
        if re.search(r'\b(?:for|while|do)\b', header_before(clean, brace)):
            return True
        brace = enclosing_block(clean, brace, opening + 1)
    return False


def _dead_after(clean, part, name, at):
    """Whether `name`'s next mention after `at` writes it (or there is none)."""
    later = re.compile(rf'(?<![\w.>])(?<!->){name}\b').search(clean, at, part.end)
    if not later:
        return True
    return (clean[:later.start()].rstrip()[-1:] in ';{}'
            and bool(re.match(r'\s*=(?!=)', clean[later.end():]))
            and not re.search(rf'\b{name}\b', clean[later.end():clean.find(';', later.end())]))


def _carriers(source, part):
    clean = part.clean
    integers = _integers(clean, part)
    result = []
    for pattern in _PAIRS:
        for hit in pattern.finditer(clean, part.opening, part.end):
            target, pointer = hit['result'], hit['pointer']
            kind = integers.get(target)
            if (not kind or pointer == target or pointer in integers or _in_loop(clean, part.opening, hit.start())
                    or re.search(rf'\b(?:{pointer}|{target})\b', hit['call'])):
                continue
            indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, hit.start()) + 1:])[0]
            call = source[hit.start('call'):hit.end('call')]
            address = source[hit.start('address'):hit.end('address')]
            for name, other in integers.items():
                if (name == target or other != kind or re.search(rf'\b{name}\b', clean[hit.start():hit.end()])
                        or not _dead_after(clean, part, name, hit.end())):
                    continue
                text = (f'{name} = {call};\n{indent}{pointer} = {address};\n'
                        f'{indent}{target} = {name} {source[hit.start("rest"):hit.end("rest")]};')
                result.append((CARRIER, edit(source, [(hit.start(), hit.end(), text)])))
    return result


def _inlines(source, part):
    clean = part.clean
    integers = _integers(clean, part)
    result = []
    at = part.opening + 1
    while True:
        hit = _STAGE.search(clean, at, part.end)
        if not hit:
            return result
        at = hit.end('expr') + 1
        temp, use = hit['temp'], hit['use']
        mentions = list(re.finditer(rf'(?<![\w.]){temp}\b', use))
        if (temp not in integers or len(mentions) != 1 or re.search(rf'\b{temp}\b', hit['expr'])
                or re.match(r'\s*(?:if|for|while|do|switch|return|goto|else)\b', use)
                or re.search(rf'\+\+|--|&\s*{temp}\b|\b{temp}\s*(?:[+\-*/%&|^]|<<|>>)?=(?!=)|&&|\|\||\?', use)
                or re.search(r'\+\+|--', hit['expr']) or re.search(rf'{IDENT}\s*\(', use)
                or _in_loop(clean, part.opening, hit.start('temp'))
                or not _dead_after(clean, part, temp, hit.end('use'))):
            continue
        expr = source[hit.start('expr'):hit.end('expr')].strip()
        if not (expr.startswith('(') and expr.endswith(')')):
            expr = f'({expr})'
        offset = hit.start('use') + mentions[0].start()
        result.append((INLINE, edit(source, [(hit.start('temp'), hit.start('use'), ''),
                                             (offset, offset + len(temp), expr)])))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    return (_carriers(source, part) + _inlines(source, part))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 121}
