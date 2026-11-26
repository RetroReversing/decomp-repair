"""An associative chain grouped another way: `a + b + c` as `a + (b + c)` or `(a + c) + b`, for `+ * | & ^`.

C groups `a + b + c` as `(a + b) + c`, and gcc 2.x builds the tree as written: the first partial result is what lives
in a register while the third operand is loaded, and which operands are combined first decides the registers, the
instruction order and, with constants, whether `0x300` is folded into an address. A whole-path audit of a KMC GCC 2.7.2
N64 game (`-G0 -mips3 -mgp32 -mfp32 -O2`) found one small stall finished by exactly this: `s + (i << 4) + 0x300` written
`s + ((i << 4) + 0x300)`. m2c prints chains left to right however the original grouped them.

For each chain of three to five operands (flattened through parentheses and nested groups of the same operator) the
children group two operands first (`(a + c) + b`, or `b + (a + c)` with the pair last), nest the chain to the right
(`a + (b + (c + d))`) or, for four operands, group two halves. Operand order inside a pair is kept (the commuted forms
are `arithmetic_operand_order`'s). A chain is only offered when every grouping is the same value in C for its types
(`expression_terms.exact_regrouping`):

- `| & ^`: always, for any integer type;
- `+ *` on an unsigned result, which wraps: always; on a signed result only when the operands' ranges (their declared
  types, literals, masks and shifts) prove no partial sum or product can overflow, since a regrouping could otherwise
  overflow where the source did not; for pointer arithmetic (`p + a + b`) always, as the source is only defined when its
  offsets stay inside one object;
- floating-point operands never (a regrouped sum rounds differently), nor do operands the reader cannot type, with a
  call, an assignment or a `volatile` name, nor a mix of integer types whose partial results would change type with the
  grouping.

A statement the reader cannot parse whole is read from its `=` on: m2c's `M2C_FIELD(p, s32 **, 4) = ...` names a
type where an argument goes, so the whole display-list word it stores had no children. A 73-instruction display-list
function (KMC GCC 2.7.2 `-O1`) stood at 60 on `(a << 12) + ((b << 11) + D_x)` and matched written
`(b << 11) + ((a << 12) + D_x)`.

It is a scheduling hypothesis: the value is the same, the judge says whether the bytes are.
"""
import re

from .expression_terms import Types, bare, chain, exact_regrouping, names, parse, regroupings, render, sites

FAMILY = 'reassociate'
FAMILIES = ('reassociate',)
LIMIT = 48
MOST_OPERANDS = 5
PER_CHAIN = 10


def _spine(node):
    yield node
    for kid in node.kids:
        inner = bare(kid)
        if inner.kind == 'binary' and inner.op == node.op:
            yield from _spine(inner)


def _value_start(source, start, end):
    """Where the assigned value begins: after the first plain `=` outside brackets, or None."""
    depth = 0
    for found in re.finditer(r'[()\[\]{}]|(?<![=!<>+\-*/%&|^])=(?!=)', source[start:end]):
        mark = found[0]
        if mark == '=':
            if not depth:
                return start + found.end()
        else:
            depth += 1 if mark in '([{' else -1
    return None


def variants(source, name, header='', int_bits=None):
    """(family, source) for each regrouped chain; see the module's docstring."""
    if int_bits not in (None, 32):
        return []
    types = Types(source, name, header)
    if not types.ok:
        return []
    result, seen = [], {source}
    for site in sites(source, types):
        if site.kind == 'declaration':
            continue
        root = parse(source, site.start, site.end, types.typedefs)
        if root is None and (value := _value_start(source, site.start, site.end)) is not None:
            root = parse(source, value, site.end, types.typedefs)
        if root is None:
            continue
        covered = set()
        for node in root.walk():
            if node.kind != 'binary' or id(node) in covered:
                continue
            info = chain(node)
            if info is None:
                continue
            covered.update(id(n) for n in _spine(node))
            op, operands, shape = info
            if not 3 <= len(operands) <= MOST_OPERANDS or not exact_regrouping(types, op, operands):
                continue
            if any(names(o) & types.volatile or any(n.kind == 'member' and n.info in types.volatile for n in o.walk())
                   for o in operands):
                continue
            texts = [source[o.start:o.end] for o in operands]
            for grouping in regroupings(len(operands), shape)[:PER_CHAIN]:
                text = source[:node.start] + render(grouping, texts, op) + source[node.end:]
                if text not in seen:
                    seen.add(text)
                    result.append((FAMILY, text))
    return result[:LIMIT]
