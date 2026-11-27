"""Locals that only hold a copy of a field, written as the field wherever they are read.

m2c names what the compiler kept in a register, one local per load, and reuses the names:

    a0 = p->height; p->height = a0 + p->speed;           p->height = p->height + p->speed;
    v0 = p->height;                                      ...
    a1 = p->gravity;                              ->     p->y = p->base + (p->height >> 2);
    a0 = p->limit;                                       if (p->limit + 10 < p->y) {
    v1 = p->base + (v0 >> 2); p->y = v1;                     p->speed = -3;
    masked = v1 & 0xFFFF;
    if (a0 + 10 < masked) { ...; v0 = f(p, a1); }            f(p);

The game wrote the fields; gcc forwards the stored and loaded values by itself, in its own registers. The copies are
pseudos of their own and swap `$v0`/`$v1`, so removing them only pays off together, and a greedy chain never gets
there: on an N64 object update (SN GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`, 63 instructions) the copies taken one at a time
were each far worse (375 -> 510, 665, 140) and all together exact, once its clamped call result was stored in each arm
(`conditional_store_tested_arms`).

The single-statement `do { } while (0);` fences around the staging are opened in the combined children (they alone
kept the same child at 120 where it is exact without them). A copy is `v = F;` for a field `F` (`*(T *)((u8 *)p + K)`, `M2C_FIELD(p, T *, K)` or `p->member`) that `v`'s type holds
whole, or `w = x & 0xFFFF;` right after the store `F = x;` into a field of that width. A read of `v` becomes `F` only
when every path to it brings that same field and none passes a call or a store that may touch it (another member or
non-overlapping offset of the same base is taken not to). `field_copy_reread` writes every such read at once (and one
child per local); `field_copy_reread_arity` also drops a copy passed as a call's last argument, which m2c adds for a
register that merely held a value. Reading a field again assumes nothing else changed it: a candidate for the judge.
"""
import re

from . import local_flow, scaffold_strip
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'field_copy_reread'
ARITY_FAMILY = 'field_copy_reread_arity'
FAMILIES = (FAMILY, ARITY_FAMILY)
MAX_VARIABLES = 12

SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'long': 4}
_NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_CAST_FIELD = re.compile(rf'\*\s*\(\s*(?P<type>{IDENT})\s*\*\s*\)\s*\(\s*\(\s*(?:u8|s8|char)\s*\*\s*\)\s*'
                         rf'(?P<base>{IDENT})\s*\+\s*(?P<offset>{_NUMBER})\s*\)')
_MACRO_FIELD = re.compile(rf'M2C_FIELD\s*\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>{IDENT})\s*\*\s*,\s*'
                          rf'(?P<offset>{_NUMBER})\s*\)')
_MEMBER = re.compile(rf'(?P<base>{IDENT})\s*->\s*(?P<member>{IDENT})')
_ASSIGN = re.compile(r'\s*(?P<lhs>[^;=]+?)\s*(?P<op>(?:<<|>>|[-+*/%&|^])?=)(?!=)\s*(?P<rhs>.*?)\s*;?\s*', re.S)
_NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD', 'M2C_BITWISE'}


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _field(text):
    """(base, offset or member, size or None) when the whole expression is one field."""
    text = _unwrap(text)
    hit = _CAST_FIELD.fullmatch(text) or _MACRO_FIELD.fullmatch(text)
    if hit:
        size = SIZES.get(hit['type'])
        return (hit['base'], int(hit['offset'], 0), size) if size else None
    hit = _MEMBER.fullmatch(text)
    return (hit['base'], hit['member'], None) if hit else None


def _may_touch(stored, field):
    """May a store to `stored` change `field` (both as `_field` returns them)?"""
    if stored[0] != field[0]:
        return True
    if isinstance(stored[1], str) or isinstance(field[1], str):
        return stored[1] == field[1] or type(stored[1]) is not type(field[1])
    return stored[1] < field[1] + field[2] and field[1] < stored[1] + stored[2]


def _calls(text):
    return re.search(r'\(\s*\*\s*' + IDENT + r'\s*\)\s*\(', text) is not None or any(
        hit[1] not in _NOT_CALLS for hit in re.finditer(rf'\b({IDENT})\s*\(', text))


def _kills(text, field, names):
    """Whether this statement or condition may change what the field reads."""
    if _calls(text):
        return True
    hit = _ASSIGN.fullmatch(text)
    if hit:
        text_left, rest = hit['lhs'].strip(), hit['rhs']
        if re.search(r'(?<![=!<>])=(?!=)|\+\+|--', rest):
            return True
        if text_left == field[0]:
            return True
        if text_left in names or re.fullmatch(rf'(?:{IDENT}\s+)+\**\s*{IDENT}', text_left):
            return False
        stored = _field(text_left)
        return stored is None or _may_touch(stored, field)
    return re.search(r'(?<![=!<>])=(?!=)|<<=|>>=|\+\+|--', text) is not None


def _holds(declared, field, expression):
    """The local keeps every bit of the field, and reads as it does."""
    declared = ' '.join(declared.split())
    cast = _CAST_FIELD.fullmatch(_unwrap(expression)) or _MACRO_FIELD.fullmatch(_unwrap(expression))
    if not cast:
        return True  # a member's type is not in the text: the judge decides
    kind = cast['type']
    return declared == kind or (SIZES.get(declared, 0) == 4 and field[2] < 4)


def _stored_mask(flow, source, predecessors, index, rhs):
    """The field `x & mask` reads back, when the statement before stored `x` into a field of the mask's width."""
    hit = re.fullmatch(rf'(?P<value>{IDENT})\s*&\s*(?P<mask>0[xX][fF]{{2}}(?:[fF]{{2}})?|255|65535)[uU]?', _unwrap(rhs))
    if not hit:
        return None
    width = 1 if int(hit['mask'], 0) == 0xFF else 2
    before = predecessors.get(index, [])
    while len(before) == 1 and flow.part.clean[flow.nodes[before[0]].start:flow.nodes[before[0]].end].strip() == '0':
        before = predecessors.get(before[0], [])  # a `do { } while (0)` latch
    if len(before) != 1:
        return None
    node = flow.nodes[before[0]]
    store = _ASSIGN.fullmatch(flow.part.clean[node.start:node.end])
    names = {hit['value']}
    if store and store['op'] == '=' and _unwrap(store['rhs']) not in names:
        # `y = x; F = y;`: the store's value is a plain copy of `x` made just before it
        earlier = predecessors.get(before[0], [])
        if len(earlier) == 1:
            other = flow.nodes[earlier[0]]
            copy = _ASSIGN.fullmatch(flow.part.clean[other.start:other.end])
            if copy and copy['op'] == '=' and _unwrap(copy['rhs']) == hit['value']:
                names.add(copy['lhs'].split()[-1])
    if not store or store['op'] != '=' or _unwrap(store['rhs']) not in names:
        return None
    field = _field(store['lhs'])
    if not field or field[2] != width or not _CAST_FIELD.fullmatch(_unwrap(store['lhs'])) and not _MACRO_FIELD.fullmatch(
            _unwrap(store['lhs'])):
        return None
    start = node.start + store.start('lhs')
    text = source[start:node.start + store.end('lhs')]
    return (field, text) if re.search(r'\(\s*u(?:8|16)\s*\*', text) else None


def _plan(flow, source, variable):
    """(edits, replaced) for one local: its reads written as the field, its dead copies removed."""
    clean = flow.part.clean
    name = variable['name']
    if re.search(rf'(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])=)', clean):
        return []
    predecessors = {}
    for index, node in enumerate(flow.nodes):
        for child in node.successors:
            predecessors.setdefault(child, []).append(index)
    definitions = {}
    for index, node in enumerate(flow.nodes):
        if name not in node.defines:
            continue
        hit = _ASSIGN.fullmatch(clean[node.start:node.end])
        if not hit or hit['lhs'].strip() != name or hit['op'] != '=':
            continue
        start, end = node.start + hit.start('rhs'), node.start + hit.end('rhs')
        field = _field(clean[start:end])
        if field and _holds(variable['type'], field, clean[start:end]):
            definitions[index] = (field, source[start:end].strip())
        else:
            definitions[index] = _stored_mask(flow, source, predecessors, index, clean[start:end])
    reads = {}  # node -> set of replacement texts, or None among them where a path may have changed the field
    uses_of = {}
    for index, value in definitions.items():
        uses_of[index] = set()
        pending = [(child, False) for child in flow.nodes[index].successors]
        seen = set()
        while pending:
            at, dirty = pending.pop()
            if (at, dirty) in seen:
                continue
            seen.add((at, dirty))
            node = flow.nodes[at]
            text = clean[node.start:node.end]
            if name in node.uses:
                uses_of[index].add(at)
                unsafe = value is None or dirty
                if not unsafe and _calls(text) and not re.search(rf'\(\s*[^()]*\b{name}\b', text):
                    unsafe = True
                reads.setdefault(at, set()).add(None if unsafe else value[1])
            if name in node.defines:
                continue
            if value is not None and not dirty:
                dirty = _kills(text, value[0], flow.names)
            pending.extend((child, dirty) for child in node.successors)
    good = {at: next(iter(texts)) for at, texts in reads.items() if len(texts) == 1 and None not in texts}
    edits = []
    for at, text in good.items():
        node = flow.nodes[at]
        part = clean[node.start:node.end]
        hit = _ASSIGN.fullmatch(part)
        skip = hit.end('lhs') if hit and hit['lhs'].strip() == name else 0
        replacement = f'({_unwrap(text)})'
        for use in re.finditer(rf'(?<![\w.>])(?<!->){name}\b', part):
            if use.start() >= skip:
                edits.append((node.start + use.start(), node.start + use.end(), replacement))
    for index, used in uses_of.items():
        if definitions[index] is not None and used and used <= set(good):
            node = flow.nodes[index]
            stop = node.end
            edits.append((node.start, stop, ''))
    return edits


def _tidy(text):
    """A fence whose only statement was a removed copy goes too."""
    return re.sub(r'\bdo\s*\{\s*\}\s*while\s*\(\s*0\s*\)\s*;', '', text)


def _apply(source, edits):
    ordered = sorted(set(edits))
    taken, kept = -1, []
    for start, end, new in ordered:
        if start < taken:
            return None  # a copy whose own definition reads it: leave the whole child out
        kept.append((start, end, new))
        taken = end
    return _tidy(edit(source, kept))


def _rewrite(source, name, only=None):
    flow = local_flow.analyze(source, name)
    if not flow:
        return None, []
    edits, changed = [], []
    for variable in flow.locals:
        if only and variable['name'] != only:
            continue
        found = _plan(flow, source, variable)
        if found:
            edits += found
            changed.append(variable['name'])
        if len(changed) >= MAX_VARIABLES:
            break
    if not edits:
        return None, []
    return _apply(source, edits), changed


def _drop_trailing_copies(source, name):
    """Each call's last argument that is a local holding a field, left out."""
    flow = local_flow.analyze(source, name)
    if not flow:
        return source
    clean = flow.part.clean
    copies = set()
    for node in flow.nodes:
        hit = _ASSIGN.fullmatch(clean[node.start:node.end])
        if hit and hit['op'] == '=' and hit['lhs'].strip() in flow.names and _field(hit['rhs']):
            copies.add(hit['lhs'].strip())
    edits = []
    for node in flow.nodes:
        part = clean[node.start:node.end]
        for call in re.finditer(rf'\b({IDENT})\s*\(', part):
            if call[1] in _NOT_CALLS:
                continue
            stop = close(clean, node.start + call.end() - 1)
            if not stop:
                continue
            tail = re.search(rf',\s*({IDENT})\s*\)$', clean[node.start + call.end() - 1:stop])
            if tail and tail[1] in copies:
                begin = node.start + call.end() - 1 + tail.start()
                edits.append((begin, stop - 1, ''))
    return edit(source, edits) if edits else source


def _open_fences(text, name):
    """The copies' `do { } while (0)` wrappers hold the stores apart as long as they stand: open them with the copies."""
    return scaffold_strip.unfence(text, name) or text


def variants(source, name):
    result = []
    text, changed = _rewrite(source, name)
    if text and text != source:
        result.append((FAMILY, _open_fences(text, name)))
    dropped = _drop_trailing_copies(source, name)
    if dropped != source:
        arity, _ = _rewrite(dropped, name)
        if arity:
            result.insert(0, (ARITY_FAMILY, _open_fences(arity, name)))
    if len(changed) > 1:
        for variable in changed:
            single, _ = _rewrite(source, name, only=variable)
            if single and all(single != other for _, other in result):
                result.append((FAMILY, single))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
