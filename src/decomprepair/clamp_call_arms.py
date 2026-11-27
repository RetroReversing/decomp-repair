"""A value clamped into a local and passed on once, written as the call made in each arm of the test.

    a = obj[id].alpha;
    if (a >= 0xAA) {
        a = 0x64;
    }
    set_alpha(gfxp, a);

KMC GCC 2.7.2 -O1 writes the clamp's branch around the constant's load alone (an annulled `beql`, or an extra
`andi` for a narrow local). A 489-instruction N64 screen renderer instead branches over the constant with the call's
first argument in the delay slot, both paths joining at one `jal`: two calls cross-jumped after allocation.

    if (obj[id].alpha < 0xAA) {
        set_alpha(gfxp, obj[id].alpha);
    } else {
        set_alpha(gfxp, 0x64);
    }

The exact judge scored the best spelling of the clamp 320 and this one 0. Why the layout differs is a hypothesis
(cross-jumping, not confirmed in the compiler source).

Children (`clamp_call_arms`, bounded): the call in each arm with the test negated (the order above) and with the test as
written and the arms swapped. Only when the local is read by that call alone after the clamp, and the value it was
loaded from has no call, assignment or step.
"""
import re

from .csource import _blank, find

FAMILY = 'clamp_call_arms'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0x[0-9A-Fa-f]+|\d+)U?'
CLAMP = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<v>{IDENT})[ \t]*=[ \t]*(?P<value>[^;{{}}=\n]+);[ \t]*\n'
    rf'[ \t]*if[ \t]*\([ \t]*(?P=v)[ \t]*(?P<op>>=|<=|==|!=|>|<)[ \t]*(?P<limit>{NUMBER})[ \t]*\)\s*'
    rf'(?P<brace>\{{\s*)?(?P=v)[ \t]*=[ \t]*(?P<other>{NUMBER});(?(brace)\s*\}})[ \t]*\n'
    rf'[ \t]*(?P<call>{IDENT}[ \t]*\((?P<args>[^;{{}}\n]*)\));')
OPPOSITE = {'>=': '<', '<': '>=', '>': '<=', '<=': '>', '==': '!=', '!=': '=='}


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def _plain(expr):
    return not re.search(rf'{IDENT}\s*\(|\+\+|--', expr)


def rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    result = []
    for hit in CLAMP.finditer(clean, start, end):
        local = hit['v']
        value = source[hit.start('value'):hit.end('value')].strip()
        read = re.compile(rf'(?<![\w.>]){local}\b')
        if not _plain(value) or read.search(value) or len(read.findall(hit['args'])) != 1:
            continue
        if not re.search(rf'(?:^|,)[ \t]*{local}[ \t]*(?:,|$)', hit['args']):
            continue
        # the local must not be read after the call: the new arms no longer set it
        later = read.search(clean, hit.end(), end)
        if later and not re.match(rf'{local}[ \t]*=(?!=)', clean[later.start():]):
            continue
        indent = hit['indent']
        inner = indent + '    '
        call = source[hit.start('call'):hit.end('call')]
        offset = hit.start('args') - hit.start('call')
        args = hit['args']
        at = read.search(args)

        lo, hi = offset + at.start(), offset + at.end()

        def made(argument, call=call, lo=lo, hi=hi):
            return call[:lo] + argument + call[hi:] + ';'

        simple = re.fullmatch(r'[\w.>\[\]-]+', value) is not None
        tested = value if simple else f'({value})'
        op, limit, other = hit['op'], hit['limit'], hit['other']
        for test, first, second in ((f'{tested} {OPPOSITE[op]} {limit}', value, other),
                                    (f'{tested} {op} {limit}', other, value)):
            split = (f'{indent}if ({test}) {{\n{inner}{made(first)}\n{indent}}} else {{\n'
                     f'{inner}{made(second)}\n{indent}}}')
            text = source[:hit.start()] + split + source[hit.end():]
            if text not in result:
                result.append(text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}
