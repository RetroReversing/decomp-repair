"""A statement that reads an element of a table, moved past the independent stores around it.

`statement_slide` refuses any statement with a subscript, so a store whose value comes from a table never moved, nor did
anything move past it. A 129-instruction N64 chain spawner (SN GCC 2.8.1 `-G0 -mips3 -O2 -mfp64`) needed
`record->size = (u32) (SizeTable[record->type] * K) >> 12;` one statement up in its entry block (above a word clear)
and two up in its last block (above a counter product and a constant store); each order was its own differing rows in
the scheduler's output, and no family offered either (`independent_statement_swap` refuses two stores of which one
value is read through the other's base).

The table is an `extern` array the function only reads: every mention in the function is a subscript that is never
assigned, stepped or address-taken. A symbol m2c declared as one value and the function only reads as `(&Sym)[i]`
(what `pointer_byte_step` writes for a scaled byte offset) is the same table. Reading it then depends on its index alone. That no store through a pointer reaches
the table is a hypothesis, as every reorder is; the exact judge decides.

table_read_statement_slide
    One child per statement and distance (up to `REACH`), shortest slides first, at most `LIMIT`. Only moves in which
    the moved statement, or one it passes, reads a table: the others are `statement_slide`'s own.
"""
import re

from .csource import _blank
from .field_offsets import Types
from .integer_repair_support import IDENT, view
from .pattern_repairs import close
from .statement_slide import _clash, _effects, _record_cells, _runs

FAMILY = 'table_read_statement_slide'
FAMILIES = (FAMILY,)
LIMIT = 40
REACH = 4
_ARRAY = re.compile(rf'\bextern\s+(?P<kind>(?:(?:const|volatile|unsigned|signed|struct)\s+)*{IDENT})\s+'
                    rf'(?P<name>{IDENT})\s*\[[^\]]*\]\s*;')
_ADDRESSED = re.compile(rf'\(\s*&\s*(?P<name>{IDENT})\s*\)\s*(?=\[)')
_SCALAR = re.compile(rf'\bextern\s+(?P<kind>(?:(?:const|volatile|unsigned|signed|struct)\s+)*{IDENT})\s+'
                     rf'(?P<name>{IDENT})\s*;')
_PLACEHOLDER = '__table_read'


def _tables(source, header, body):
    """The extern tables the function's `body` only reads by subscript: arrays, and values only read as `(&Sym)[i]`."""
    found = set()
    context = _blank(header or '') + '\n' + _blank(source)
    plain = _ADDRESSED.sub(lambda hit: hit['name'], body)
    for pattern, addressed in ((_ARRAY, False), (_SCALAR, True)):
        for declared in pattern.finditer(context):
            name = declared['name']
            word = rf'(?<![\w.>]){name}\b'
            if 'volatile' in declared['kind'] or addressed and len(re.findall(word, body)) != sum(
                    hit['name'] == name for hit in _ADDRESSED.finditer(body)):
                continue
            mentions = list(re.finditer(word, plain))
            if mentions and all(_only_read(plain, m) for m in mentions):
                found.add(name)
    return found


def _only_read(body, mention):
    before = body[:mention.start()].rstrip()
    if before.endswith(('&', '++', '--')) and not before.endswith('&&'):
        return False
    at = mention.end()
    while at < len(body) and body[at].isspace():
        at += 1
    if body[at:at + 1] != '[':
        return False
    while body[at:at + 1] == '[':
        end = close(body, at, '[', ']')
        if not end:
            return False
        at = end
        while at < len(body) and body[at].isspace():
            at += 1
    # a member of the element, an assignment or a step of it
    return not re.match(r'(?:\.|->|\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))', body[at:])


def _statement_effects(text, tables):
    """(writes, reads, whether it reads a table), or None when `statement_slide` could not read the statement even with
    its table reads taken out."""
    indexes = []
    text = _ADDRESSED.sub(lambda hit: hit['name'] if hit['name'] in tables else hit[0], text)
    while tables:
        hit = re.search(rf'(?<![\w.>])(?:{"|".join(sorted(tables))})\s*\[', text)
        if not hit:
            break
        opening = hit.end() - 1
        end = close(text, opening, '[', ']')
        if not end or text[end:].lstrip().startswith('['):
            return None
        indexes.append(text[opening + 1:end - 1])
        text = text[:hit.start()] + _PLACEHOLDER + text[end:]
    effects = _effects(text)
    if not effects:
        return None
    writes, reads = effects[0], effects[1] - {('v', _PLACEHOLDER)}
    for index in indexes:
        inner = _effects(f'{_PLACEHOLDER} = {index};')
        if not inner:
            return None
        reads = reads | inner[1]
    return writes, reads, bool(indexes)


def _commute(first, second):
    return bool(first and second) and not (_clash(first[0], second[0] | second[1]) or _clash(second[0], first[1]))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    tables = _tables(source, header, part.clean[part.opening:part.end])
    if not tables:
        return []
    types = Types(source, header) if '->' in part.clean else None
    found = []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end), minimum=2):
        texts = [source[s:e] for s, e in run]
        effects = [_statement_effects(_record_cells(text, types) if types else text, tables) for text in texts]
        for index in range(len(texts)):
            for step in range(1, REACH + 1):
                for sign in (1, -1):
                    target = index + sign * step
                    if not 0 <= target < len(texts):
                        continue
                    low, high = sorted((index, target))
                    passed = [effects[k] for k in range(low, high + 1) if k != index]
                    if not all(_commute(effects[index], other) for other in passed):
                        continue
                    if not (effects[index][2] or any(other[2] for other in passed)):
                        continue
                    order = list(range(len(texts)))
                    order.insert(target, order.pop(index))
                    child = source[:run[0][0]]
                    for k, was in enumerate(order):
                        gap = source[run[k - 1][1]:run[k][0]] if k else ''
                        child += gap + source[run[was][0]:run[was][1]]
                    found.append((step, child + source[run[-1][1]:]))
    result = []
    for _, child in sorted(found, key=lambda item: item[0]):
        if child != source and child not in result:
            result.append(child)
    return [(FAMILY, child) for child in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
