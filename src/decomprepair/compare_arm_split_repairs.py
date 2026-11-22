"""A lookup with two arms and one compare after them, written with the compare in each arm.

A helper that finds a value in one of two tables and compares it with the key it was given:

    y = key;
    if (flag) x = A[(u8)y]; else { u8 *row = B + (n << 4); x = row[k]; }
    if (x == (u8)y) return 1;
    return 0;

gcc 2.7.2's first jump pass merges the identical tails of two arms and gives the one compare after the join a single
register pair, so both arms use the same registers. A KMC N64 helper's target has the arms' temporaries swapped
(`andi $v1` and `lbu $v0` in one, the reverse in the other): its compare was in each arm, and only the jump pass after
register allocation merged them, once the registers happened to mirror each other. Getting there took four edits that
a one-step search never measured (255 -> 80 -> 60 -> 0 on that function, each from the one before):

1. the compare moves into each arm, with the first arm written `!=` and the second `==`, so the first pass leaves
   their tails different (written alike they stay apart and the arms never mirror: 755);
2. the copy of the key is pinned: `y = key; key = 0; key = y;` stops cse forwarding the key into the arms, which would
   delete the copy and leave the key in a register that outranks it (80);
3. the first arm tests the loaded byte in the condition, not through a local (60);
4. the second arm's address is built in two locals, a base and an offset (0: it reorders the `lui`/`sll` pair).

Each child adds one more of them, in this order.
"""
import re

from .csource import _blank

FAMILY = 'compare_into_arms'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
PATTERN = re.compile(
    rf'(?P<indent>[ \t]*)(?P<y>{IDENT})\s*=\s*(?P<key>{IDENT})\s*;[ \t]*\n'
    rf'[ \t]*if\s*\((?P<flag>[^\n;]+)\)\s*'
    rf'(?P<arm1>{{?\s*(?P<x>{IDENT})\s*=\s*(?P<table>{IDENT})\s*\[\s*\(\s*u8\s*\)\s*(?P=y)\s*\]\s*;\s*}}?)\s*'
    rf'else\s*{{\s*'
    rf'(?P<ptype>(?:u8|char|unsigned\s+char))\s*\*\s*(?P<row>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*'
    rf'(?P<offset>\([^;]*\)|[^;]+?)\s*;\s*'
    rf'(?P=x)\s*=\s*(?P=row)\s*\[\s*(?P<index>{IDENT})\s*\]\s*;\s*}}\s*'
    rf'if\s*\(\s*(?P=x)\s*==\s*\(\s*u8\s*\)\s*(?P=y)\s*\)\s*return\s+1\s*;\s*return\s+0\s*;')


def _strip(expression):
    expression = expression.strip()
    if expression.startswith('(') and expression.endswith(')'):
        depth = 0
        for at, char in enumerate(expression):
            depth += char == '('
            depth -= char == ')'
            if depth == 0 and at < len(expression) - 1:
                return expression
        return expression[1:-1]
    return expression


def _build(g, direct, split):
    i, y, x, key = g['i'], g['y'], g['x'], g['key']
    table, row = g['table'], g['row']
    first = (f'if ({table}[(u8){y}] != (u8){y})\n{i}    return 0;\n{i}  return 1;' if direct else
             f'{x} = {table}[(u8){y}];\n{i}  if ({x} != (u8){y})\n{i}    return 0;\n{i}  return 1;')
    address = (f'{g["ptype"]} *__repair_base = {g["base"]};\n{i}  u32 __repair_off = {g["offset"]};\n'
               f'{i}  {g["ptype"]} *{row} = __repair_base + __repair_off;' if split
               else f'{g["ptype"]} *{row} = {g["base"]} + ({g["offset"]});')
    return (f'{i}{y} = {key};\n{i}{key} = 0;\n{i}{key} = {y};\n{i}if ({g["flag"]})\n{i}{{\n{i}  {first}\n{i}}}\n'
            f'{i}else\n{i}{{\n{i}  {address}\n{i}  {x} = {row}[{g["index"]}];\n{i}  if ({x} == (u8){y})\n'
            f'{i}    return 1;\n{i}  return 0;\n{i}}}')


def variants(source, name):
    clean = _blank(source)
    result = []
    for hit in PATTERN.finditer(clean):
        if re.search(rf'\b{hit["key"]}\b', clean[hit.end():].split('\n}', 1)[0]):
            continue  # the key is read again later: pinning it would change what it holds
        g = {'i': hit['indent'], 'y': hit['y'], 'x': hit['x'], 'key': hit['key'], 'table': hit['table'],
             'row': hit['row'], 'base': hit['base'], 'index': hit['index'], 'ptype': ' '.join(hit['ptype'].split()),
             'flag': source[hit.start('flag'):hit.end('flag')],
             'offset': _strip(source[hit.start('offset'):hit.end('offset')])}
        for direct, split in ((False, False), (True, False), (True, True)):
            candidate = source[:hit.start()] + _build(g, direct, split) + source[hit.end():]
            if candidate not in [c for _, c in result]:
                result.append((FAMILY, candidate))
    return (result + masked_copy_variants(source, name))[:6]


def masked_copy_variants(source, name):
    """Split a byte-masked helper compare into arms and narrow its private key copy.

    The helper must be exactly an equality of a masked integer with a byte. Narrowing is safe only when all
    uses of the copied key are that helper's argument or an equivalently masked array index.
    """
    from .integer_repair_support import edit, view
    from .pattern_repairs import close

    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b|^\s*#', part.body, re.M):
        return []
    helper = re.search(
        rf'\b(?:inline\s+static|static\s+inline)\s+int\s+({IDENT})\s*\(\s*s32\s+({IDENT})\s*,\s*u8\s+({IDENT})\s*\)\s*'
        rf'{{\s*return\s*\(\s*\2\s*&\s*0[xX][fF][fF]\s*\)\s*==\s*\3\s*;\s*}}', part.clean)
    if not helper:
        return []
    for copy in re.finditer(rf'\bs32\s+({IDENT})\s*;', part.clean[part.opening + 1:]):
        key = copy[1]
        decl_start = part.opening + 1 + copy.start()
        if key in (helper[2], helper[3]) or len(re.findall(rf'\bs32\s+{key}\s*;', part.body)) != 1:
            continue
        for branch in re.finditer(r'\bif\s*\(', part.clean[decl_start:]):
            start = decl_start + branch.start()
            cond = close(part.clean, start + branch.group().rfind('('))
            if not cond:
                continue
            arm = re.match(r'\s*{', part.clean[cond:])
            if not arm:
                continue
            a = cond + arm.end() - 1
            b = close(part.clean, a, '{', '}')
            if not b:
                continue
            other = re.match(r'\s*else\s*{', part.clean[b:])
            if not other:
                continue
            c = b + other.end() - 1
            d = close(part.clean, c, '{', '}')
            if not d:
                continue
            tail = re.match(rf'\s*if\s*\(\s*{helper[1]}\s*\(\s*{key}\s*,\s*({IDENT})\s*\)\s*\)\s*{{\s*return\s+1\s*;\s*}}', part.clean[d:])
            if not tail:
                continue
            value = tail[1]
            if len(re.findall(rf'\bu8\s+{value}\s*;', part.body)) != 1:
                continue
            bodies = part.clean[a + 1:b - 1] + '\n' + part.clean[c + 1:d - 1]
            if re.search(r'\b(?:if|else|for|while|do|switch|return|break|continue)\b|[?:]', bodies):
                continue
            if not all(re.search(rf'\b{value}\s*=', part.clean[x + 1:y - 1]) for x, y in ((a, b), (c, d))):
                continue
            # No other reads or writes: a single copy, one masked index, and the helper call.
            uses = re.sub(rf'\b{key}\s*=\s*{IDENT}\s*;', '', part.clean[decl_start:part.end])
            uses = re.sub(rf'\b{key}\s*&\s*0[xX][fF][fF]\b', '', uses)
            uses = re.sub(rf'\b{helper[1]}\s*\(\s*{key}\s*,', '', uses)
            uses = re.sub(rf'\bs32\s+{key}\s*;', '', uses)
            if re.search(rf'\b{key}\b', uses) or len(re.findall(rf'\b{key}\s*=\s*{IDENT}\s*;', part.clean[decl_start:part.end])) != 1:
                continue
            label = '__repair_compare_no'
            if re.search(rf'\b{label}\b', source):
                continue
            check = f'\nif (!{helper[1]}({key}, {value})) goto {label};\n'
            reverse = f'\nif (!{helper[1]}({value}, {key})) goto {label};\n'
            # Both arguments are bytes, so reversing this equality is equivalent. It can change
            # the operand order after GCC merges the separately allocated branch tails.
            return [(FAMILY, edit(source, [(decl_start, decl_start + 3, 'u8'),
                                         (b - 1, b - 1, check), (d - 1, d - 1, second),
                                         (d, d + tail.end(), f'\nreturn 1; {label}:;')]))
                    for second in (check, reverse)]

    return []
