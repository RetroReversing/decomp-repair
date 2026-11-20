"""Fold a staged signed half-offset and base load back into their consuming store.

A MIPS GCC display-list routine needed both operands in the same expression to share
a store tail. Replacing just the shift with division left the compiled bytes unchanged.
"""
import re

from .integer_repair_support import IDENT, locals_for, view

FAMILY = 'combined_half_offset_store'
FAMILIES = (FAMILY,)

# Four consecutive statements. Horizontal whitespace keeps the search within a
# basic block and prevents swallowing labels, declarations or intervening writes.
LINE = r'[ \t]*\n[ \t]*'
ASSIGN = r'[ \t]*=[ \t]*'
EXPR = r'[^;{}\n]+'
PATTERN = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<bits>{IDENT}){ASSIGN}(?P<product>{EXPR});{LINE}'
    rf'(?P<base>{IDENT}){ASSIGN}(?P<load>{EXPR});{LINE}'
    rf'(?P<half>{IDENT}){ASSIGN}\(s32\) *\( *(?P=bits) *\+ *\( *(?P=bits) *>> *(?:31|0x1[fF]) *\) *\) *>> *1 *;{LINE}'
    rf'(?P<dst>[^=;{{}}\n]+?){ASSIGN}(?:\(s32\) *)?\( *(?P=base) *\+ *(?P=half) *\) *;'
)


def _ordinary(expression):
    # Only m2c's integer arithmetic and explicit indirections. In particular
    # never reorder calls, increment expressions, volatile accesses or macros.
    return (re.fullmatch(r'[\w ()\t*+\-]+', expression)
            and not re.search(r'\+\+|--|\b\w+\s*\(|\bvolatile\b', expression))


def _private_uses(body, name):
    """Every other read needs a new definition in its own straight-line block."""
    assigned = False
    for line in body.splitlines():
        if re.search(r'[{}:#?]|\b(?:if|else|while|for|do|switch|goto|continue|break|return)\b', line):
            assigned = False
        if not re.search(rf'\b{name}\b', line):
            continue
        if re.fullmatch(rf'\s*(?:s32|u32)\s+{name}\s*;\s*', line):
            continue
        write = re.fullmatch(rf'\s*{name}\s*=\s*([^;]+);\s*', line)
        if write and not re.search(rf'\b{name}\b', write[1]):
            assigned = True
        elif not assigned:
            return False
    return True


def variants(source, name):
    if '>>' not in source:
        return []
    part = view(source, name)
    if not part:
        return []
    result = []
    for hit in PATTERN.finditer(part.body):
        temporaries = [hit[k] for k in ('bits', 'base', 'half')]
        if len(set(temporaries)) != 3:
            continue
        declarations = {m['name']: m['type'] for m in locals_for(part)}
        if [declarations.get(v) for v in temporaries] != ['u32', 's32', 's32']:
            continue
        expressions = [hit[k].strip() for k in ('product', 'load', 'dst')]
        if not all(_ordinary(expr) for expr in expressions):
            continue
        product, load, dst = expressions
        if '*' not in product or '*' not in load or '*' not in dst:
            continue
        operands = set(re.findall(r'\b' + IDENT, ' '.join(expressions)))
        if operands.intersection(temporaries):
            continue
        # Names used by the expressions must be ordinary local storage or casts,
        # not opaque identifiers that could expand to side effects.
        for operand in operands - {'char', 'void', 's32', 's16', 'u16', 's8', 'u8', 'u32'}:
            if not re.search(rf'(?:^|[;{{}}])\s*(?:void|char|[us](?:8|16|32))\s*\**\s*{operand}\s*;', part.body):
                break
        else:
            if all(_private_uses(part.body[:hit.start()], v) and
                   _private_uses(part.body[hit.end():], v) for v in temporaries):
                start = part.opening + 1
                replacement = f"{hit['indent']}{dst} = {load} + ((s32)({product}) / 2);"
                result.append((FAMILY, source[:start + hit.start()] + replacement + source[start + hit.end():]))
    return result
