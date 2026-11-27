"""A scaled index split into `x = count; x <<= k;` on a scratch int that an earlier or later byte test also holds.

A loader reads a magic byte, tests it, and later turns a halfword count into a byte offset:

    if (data[0] == 'M') { ... }
    ...
    offset = obj->count * 0x10;

and every other spelling leaves the zero extension of the count in `$v0` where the target has `andi $v1, $v0, 0xffff;
sll $v1, $v1, 4`. The game's C reused one `int` for both values and shifted it in place:

    temp = data[0];
    if (temp == 'M') { ... }
    ...
    temp = obj->count;
    temp <<= 4;

A variable set in two blocks is allocated by global.c, after local-alloc gave `$v0` to the block's short values, and the
in-place shift puts the extension in the same register (SN GCC 2.8.1, -O2; 20 -> exact on one N64 model loader;
splitting alone and reusing alone were both worse or no better). The rewrite is offered for a local assigned a power of
two multiple or a shift of a memory read, with the split alone and with each equality test of a memory read against a
constant as the second holder, provided the local is not live there.
"""
import re

from .case_temporary_repairs import DECLARATION
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'scale_scratch_reuse'
FAMILIES = (FAMILY,)
LIMIT = 24

_READ = r'(?:\*\s*\([^()]*\*\)\s*\([^()]*\)|[A-Za-z_]\w*(?:(?:->|\.)\w+|\[[^][;]*\])+)'
_SCALE = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?P<v>[A-Za-z_]\w*)[ \t]*=[ \t]*(?P<x>{_READ})[ \t]*(?P<op>\*|<<)[ \t]*(?P<k>0[xX][0-9a-fA-F]+|\d+);')
_TEST = re.compile(rf'(?m)^(?P<ind>[ \t]*)if[ \t]*\([ \t]*(?P<read>{_READ}|[A-Za-z_]\w*)[ \t]*(?P<cmp>==|!=)[ \t]*(?P<c>\'\\?.\'|-?(?:0[xX][0-9a-fA-F]+|\d+))[ \t]*\)')
_TYPES = {'s32', 'u32', 'int', 'unsigned int', 'unsigned', 'long'}


def _shift(op, k):
    value = int(k, 0)
    if op == '<<':
        return value
    return value.bit_length() - 1 if value > 1 and value & (value - 1) == 0 else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    brace = source.find('{', span[0])
    end = close(_blank(source), brace, '{', '}')
    if end is None or end < 0:
        return []
    clean = _blank(source)
    types = {m['name']: ' '.join(m['type'].split()) for m in DECLARATION.finditer(source, brace, end)}
    out = []
    for site in _SCALE.finditer(source, brace, end):
        var, shift = site['v'], _shift(site['op'], site['k'])
        if shift is None or types.get(var) not in _TYPES or re.search(rf'&\s*{var}\b', clean[brace:end]):
            continue
        split = f"{site['ind']}{var} = {site['x']};\n{site['ind']}{var} <<= {shift};"
        uses = [m.start() for m in re.finditer(rf'(?<![\w.])(?<!->){var}\b', clean[brace:end])]
        uses = [brace + u for u in uses if not DECLARATION.match(source, source.rfind('\n', 0, brace + u) + 1)]
        if not uses:
            continue
        for test in _TEST.finditer(source, brace, end):
            read = test['read']
            if not re.search(r'->|\[|\*', read) and types.get(read) not in _TYPES:
                continue
            at = test.start()
            # the local must be dead at the test: before its first mention, or after its last one
            if not (at < uses[0] or at > uses[-1]) or var == read:
                continue
            holder = f"{test['ind']}{var} = {read};\n{test['ind']}if ({var} {test['cmp']} {test['c']})"
            edits = sorted([(site.start(), site.end(), split), (test.start(), test.end(), holder)], reverse=True)
            child = source
            for lo, hi, text in edits:
                child = child[:lo] + text + child[hi:]
            out.append((FAMILY, child))
            if len(out) >= LIMIT:
                return out
        out.append((FAMILY, source[:site.start()] + split + source[site.end():]))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
