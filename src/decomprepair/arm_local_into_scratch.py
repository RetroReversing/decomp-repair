"""A value just loaded for a test, kept in the function's own scratch local for the arm that follows it.

m2c names a load `t` and tests it (`t = tbl[k]->kind; if (t != want) { ... }`), and the arm that follows uses `t` in
some places and the function's long-lived scratch local `v` (the one an earlier arm assigned) in others. The target has
a single register for all of the arm's reads: the loaded value was assigned to the scratch variable the arm goes on
using, the way the game's one `kind` variable was assigned twice (`move $s2, $v1` in the branch's delay slot: the test
compares the load's own register, the arm reads `$s2`). Left as two names, the load is a short pseudo that
the allocator gives a register of its own (and the saved register the scratch had, free by then, goes unused), and every
later read of the arm differs by that register.

The rewrite assigns the load to the scratch local as the first statement of the arm and reads the scratch in the arm:

    t = load();                              t = load();
    if (t != want) {                         if (t != want) {
                                                 v = t;
        use(t); use(v);              ->          use(v); use(v);
    }                                        }

It is a repair for a function whose arm reads both names where only the scratch's earlier value could have been meant
(m2c's mix of the two comes from the register `v` lived in): the rewrite changes what the arm's reads of `v` see, which
the judge accepts only when the bytes agree. Only for integer locals of one width and signedness declared at the top of
the function, a block that holds no label, a scratch local with no mention after the block, no loop in the function.
"""
import re

from .case_temporary_repairs import DECLARATION, GOTO_LABEL, _mentions
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'arm_local_into_scratch'
FAMILIES = (FAMILY,)

LIMIT = 8
_WORD = {'s32': 's32', 'int': 's32', 'long': 's32', 'signed int': 's32', 'signed long': 's32',
         'u32': 'u32', 'unsigned int': 'u32', 'unsigned long': 'u32', 'u32 ': 'u32',
         's16': 's16', 'short': 's16', 'u16': 'u16', 'unsigned short': 'u16', 's8': 's8', 'u8': 'u8'}
_TEST = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<local>[A-Za-z_]\w*)[ \t]*=(?!=)[^;{}\n]*;[ \t]*\n'
    r'[ \t]*if[ \t]*\((?P<cond>[^;{}\n]*)\)[ \t]*\{[ \t]*\n')


def _kind(text):
    return _WORD.get(' '.join(text.split()))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:for|while|do)\b|\bvolatile\b|\basm\b', clean[opening:end]):
        return []
    types = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if clean[opening + 1:m.start()].count('{') - clean[opening + 1:m.start()].count('}') != 0:
            continue
        kind = _kind(m['type'].replace('register', ''))
        if kind and m['name'] not in types:
            types[m['name']] = kind
    result = []
    for hit in _TEST.finditer(clean, opening + 1, end):
        local = hit['local']
        if local not in types or not _mentions(local).search(hit['cond']):
            continue
        block_open = clean.rfind('{', hit.start(), hit.end())
        block_end = close(clean, block_open, '{', '}')
        if not block_end:
            continue
        inner = clean[block_open + 1:block_end - 1]
        if GOTO_LABEL.search(inner) or not _mentions(local).search(inner):
            continue
        for scratch, kind in types.items():
            if scratch == local or kind != types[local] or not _mentions(scratch).search(inner):
                continue
            if _mentions(scratch).search(clean, block_end, end) or re.search(
                    r'&\s*' + re.escape(scratch) + r'\b', clean[opening:end]):
                continue
            if re.search(r'(?<![\w.>])' + re.escape(scratch) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', inner):
                continue
            indent = re.match(r'\n([ \t]*)', source[block_open + 1:])
            indent = indent.group(1) if indent else hit['indent'] + '    '
            body = _mentions(local).sub(scratch, source[block_open + 1:block_end - 1])
            text = source[:block_open + 1] + f'\n{indent}{scratch} = {local};' + body + source[block_end - 1:]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
