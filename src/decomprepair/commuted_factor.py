"""The two operands of one `*` or `+` exchanged, where the expression is too large for the per-statement swaps.

gcc 2.x expands the operands of a commutative operation as the source orders them, and the compiled instruction's own
operand order does not always show which came first: `(40.0f - a) / 40.0f * rows[id].speed` and
`rows[id].speed * ((40.0f - a) / 40.0f)` both emit `mul.s` with the quotient first, but only the second computes the
member's address before the quotient, which leaves a copy of the record offset in a branch's delay slot and the
record's pointer in another register. A KMC GCC 2.7.2 `-O1` function of 496 instructions stood at 310 on exactly those
rows and matched with the factors exchanged. `arithmetic_operand_order` exchanges only a top-level sum, and skips a
chained assignment.

One child per `*` or `+` node whose operands are neither literals nor have side effects, the nodes that join a compound
expression to a plain read first (the shape above). The value is the same for integers, floating point and pointer
offsets; the judge says whether the bytes are.
"""
from .expression_terms import PRECEDENCE, Types, bare, parse, pure, sites

FAMILY = 'commute_factor'
FAMILIES = (FAMILY,)
LIMIT = 24
OPERATORS = ('*', '+')
LITERALS = ('num',)
READS = ('id', 'member', 'index')


def _literal(node):
    node = bare(node)
    while node.kind in ('unary', 'cast') and node.kids:
        node = bare(node.kids[0])
    return node.kind in LITERALS


def _volatile(node, types):
    return any(n.op in types.volatile for n in node.walk() if n.kind == 'id') or any(
        n.kind == 'member' and n.info in types.volatile for n in node.walk())


def _exchanged(source, node):
    left, right = node.kids
    first = source[right.start:right.end]
    second = source[left.start:left.end]
    # `a / b * c` moved to the right of an operator of its own rank needs parentheses to stay one operand
    if left.kind == 'binary' and PRECEDENCE[left.op] <= PRECEDENCE[node.op]:
        second = f'({second})'
    return source[:node.start] + f'{first} {node.op} {second}' + source[node.end:]


def variants(source, name, header=''):
    """(family, source) for each exchanged pair; see the module's docstring."""
    types = Types(source, name, header)
    if not types.ok:
        return []
    mixed, others, seen = [], [], {source}
    for site in sites(source, types):
        if site.kind == 'declaration':
            continue
        root = parse(source, site.start, site.end, types.typedefs)
        if root is None:
            continue
        for node in root.walk():
            if node.kind != 'binary' or node.op not in OPERATORS:
                continue
            left, right = node.kids
            if not (pure(left) and pure(right)) or _literal(left) or _literal(right):
                continue
            # two volatile reads would change order
            if _volatile(left, types) and _volatile(right, types):
                continue
            child = _exchanged(source, node)
            if child in seen:
                continue
            seen.add(child)
            kinds = {bare(left).kind in READS, bare(right).kind in READS}
            (mixed if len(kinds) == 2 else others).append((FAMILY, child))
    return (mixed + others)[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
