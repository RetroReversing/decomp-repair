"""A stored value read into a block local a few statements ahead of the store.

A source that writes `child->index = parent->index + 2;` after a run of constant stores compiles the read of
`parent->index` where the statement stands, behind that run. A target that has the read ahead of the run (`lhu` right
after the block's first store, the constants and their stores between it and the `addiu`) staged the value in a local
there:

    child->owner = self->owner;                  u16 __rise;
    child->kind = 2;                             child->owner = self->owner;
    child->state = 3;                 ->         __rise = self->index + 2;
    child->index = self->index + 2;              child->kind = 2;
                                                 child->state = 3;
                                                 child->index = __rise;

On a 77-instruction N64 function that spawns two linked entities (KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`) the
step took the plain source from 1010 to 0, with the local declared in each of the two blocks and of the stored
member's type (one function-level local scored 40, an `int` local worse). `temporary_hoist_block` moves such an
assignment only as far as it can prove every statement harmless, and stores through another pointer stop it.

The value may be a member read through a view of a global's address (`((View *) &gPair)->b`), as a draft whose record
was recovered from the assembly spells it (`asm_member_view`).

The read moves only over plain stores to members (or literal offsets) that the value does not read, and over
assignments to locals it does not use: no calls, labels or control flow. One child per distance; blocks that store the
same member over the same distance are also changed together, and that child comes first. The judge decides.
"""
import re

from .expression_terms import Types, bare, names, parse, pure, sites

FAMILY = 'staged_store_rise'
FAMILIES = (FAMILY,)
LIMIT = 32
LOCAL = '__rise'


def _number(node):
    node = bare(node)
    if node.kind != 'num':
        return None
    try:
        return int(node.op.rstrip('uUlL'), 0)
    except ValueError:
        return None


def _field(node):
    """Which field a memory lvalue names: ('member', name) or ('offset', n); None when it can't be told."""
    node = bare(node)
    if node.kind == 'member':
        return 'member', node.info
    if node.kind != 'unary' or node.op != '*':
        return None
    inner = bare(node.kids[0])
    while inner.kind == 'cast':
        inner = bare(inner.kids[-1])
    if inner.kind == 'id':
        return 'offset', 0
    if inner.kind == 'binary' and inner.op == '+':
        offset = _number(inner.kids[1])
        base = bare(inner.kids[0])
        while base.kind == 'cast':
            base = bare(base.kids[-1])
        if offset is not None and base.kind == 'id':
            return 'offset', offset
    return None


def _loads(node):
    """The fields an expression reads, or None when one of its loads is not a plain field of a variable."""
    node = bare(node)
    field = _field(node)
    if field:
        if node.kind == 'member':
            base = bare(node.kids[0])
            while base.kind == 'cast':  # a view of a variable or of a global's address, `((T *) &g)->m`
                base = bare(base.kids[-1])
            if base.kind == 'unary' and base.op == '&':
                base = bare(base.kids[0])
            if base.kind != 'id':
                return None
        return [field]
    if node.kind == 'index' or node.kind == 'member' or (node.kind == 'unary' and node.op == '*'):
        return None
    found = []
    for kid in node.kids:
        inner = _loads(kid)
        if inner is None:
            return None
        found += inner
    return found


def _store(types, source, site):
    """(target, value) of a statement `target = value;` without calls or other effects, or None."""
    if site.kind != 'expr' or site.statement is None or site.labeled:
        return None
    # (a cast to a record's typedef name, `((View *) p)->m`, needs the name; Types keeps only the scalar typedefs)
    records = re.findall(r'\}\s*([A-Za-z_]\w*)\s*;', source) if 'typedef' in source else ()
    root = parse(source, site.start, site.end, {*types.typedefs, *records})
    if root is None:
        return None
    root = bare(root)
    if root.kind != 'assign' or root.op != '=':
        return None
    target, value = bare(root.kids[0]), root.kids[1]
    if not pure(target) or not pure(value):
        return None
    return target, value


def _stageable(types, source, store):
    """(field written, fields read) for a store whose value is a field, or a field and a constant."""
    target, value = store
    written = _field(target)
    inner = bare(value)
    while inner.kind == 'cast':
        inner = bare(inner.kids[-1])
    if inner.kind == 'binary' and inner.op in ('+', '-') and _number(inner.kids[1]) is not None:
        inner = bare(inner.kids[0])
    if written is None or _field(inner) is None:
        return None
    read = _loads(value)
    return None if read is None else (written, read)


def _crossable(store, read, used):
    """A statement the read may move above: a store to a field it doesn't read, or to a local it doesn't use."""
    if store is None:
        return False
    target = store[0]
    if target.kind == 'id':
        return target.op not in used
    field = _field(target)
    return field is not None and all(field[0] == kind and field != (kind, which) for kind, which in read)


def _spelling(ty):
    if ty is None or ty.kind not in ('int', 'ptr') or (ty.kind == 'ptr' and ty.target is None):
        return None
    return ty.spelling if ty.kind == 'ptr' else f'{ty.spelling} '


def _found(source, types):
    """Each (statement to move above, store, field written, distance) of the function."""
    blocks = {}
    for site in sites(source, types):
        if site.kind != 'init':
            blocks.setdefault(site.block, []).append(site)
    for block, members in blocks.items():
        stores = [_store(types, source, site) for site in members]
        for at, store in enumerate(stores):
            shape = _stageable(types, source, store) if store else None
            if not shape:
                continue
            written, read = shape
            used = names(store[1])
            for distance in range(1, at + 1):
                before = members[at - distance]
                # a nested block between two statements leaves only blanks and braces; anything else stops the move
                between = source[before.end:members[at - distance + 1].start]
                if '{' in between or '}' in between or not _crossable(stores[at - distance], read, used):
                    break
                yield block, before, members[at], store, written, distance


def _changes(source, types, move):
    """The edits of one move: the declaration, the early assignment and the store of the local."""
    block, before, site, (target, value), _, _ = move
    line = source.rfind('\n', 0, before.statement) + 1
    indent = source[line:before.statement]
    gap = f'\n{indent}' if not indent.strip() else ' '
    ty = _spelling(types.of(target))
    return [(block + 1, block + 1, f'{gap}{ty}{LOCAL};'),
            (before.statement, before.statement, f'{LOCAL} = {source[value.start:value.end]};{gap}'),
            (value.start, value.end, LOCAL)]


def _rank(move):
    """Computed values before plain copies, then the shorter move."""
    return _field(move[3][1]) is not None, move[5]


def _apply(source, edits):
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name, header=''):
    if LOCAL in source or re.search(r'\b(?:volatile|asm|__asm__)\b', source):
        return []
    types = Types(source, name, header)
    if not types.ok:
        return []
    moves = [move for move in _found(source, types) if _spelling(types.of(move[3][0]))]
    # the same member staged over the same distance in several blocks: all of them at once, one per block
    groups = {}
    for move in moves:
        groups.setdefault((move[4], move[5]), {}).setdefault(move[0], move)
    out = []
    for group in sorted((g for g in groups.values() if len(g) > 1), key=lambda g: _rank(next(iter(g.values())))):
        # a block's declaration may only be added once, and every edit is against the same text
        out.append(_apply(source, [change for move in group.values() for change in _changes(source, types, move)]))
    for move in sorted(moves, key=_rank):
        out.append(_apply(source, _changes(source, types, move)))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
