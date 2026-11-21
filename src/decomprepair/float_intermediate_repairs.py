"""Bounded floating product lifetime hypotheses; casts and multiplication order stay explicit.

An intermediate store may change rounding as well as allocation. These are proposals for the ordinary
judge, never an equivalence proof or permission to reassociate floating arithmetic.
"""
import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer, refs, view

LIMIT = 6
FLOAT = r'(?:float|double|f32|f64)'
ATOM = rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT})*'
DECL = re.compile(rf'\b(?P<type>{FLOAT})\s+(?P<name>{IDENT})\s*;')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto|for|while|do)\b', part.clean):
        return []
    declarations = [d for d in DECL.finditer(part.clean, part.opening+1, part.end)
                    if part.clean[part.opening+1:d.start()].rstrip()[-1:] in {'', ';', '{', '}'}]
    result = []
    for decl in declarations:
        variable = decl['name']
        if len(re.findall(rf'\b{FLOAT}\s+{variable}\b', part.body)) != 1 or re.search(rf'&\s*{variable}\b', part.body):
            continue
        # Adjacent assignments only. The first is a cast of one scalar; the second consumes it
        # once as the RHS of the first product. No calls, increments, indexing or control flow.
        pattern = re.compile(rf'(?<![\w.>]){variable}\s*=\s*(?P<cast>\(\s*{FLOAT}\s*\)\s*{ATOM})\s*;'
                             rf'(?P<gap>\s*)(?P<assignment>{ATOM}\s*=\s*[^;{{}}]+);')
        for assignment in pattern.finditer(part.clean, decl.end(), part.end):
            if part.clean[part.opening+1:assignment.start()].rstrip()[-1:] not in {';', '{', '}'}:
                continue
            expression = assignment['assignment']
            if re.search(r'\+\+|--|\?|,|\b(?:sizeof|return)\b|\b\w+\s*\(', expression):
                continue
            product = re.search(rf'\(\s*(?P<factor>{ATOM})\s*\*\s*{variable}\s*\)', expression)
            if not product or len(re.findall(rf'\b{variable}\b', expression)) != 1:
                continue
            hits = refs(part, decl)
            covered = [h for h in hits if assignment.start() <= h.start() < assignment.end()]
            # Earlier branch-local lifetimes may use this local too; its new value must be dead
            # after this pair. Do not guess dominance across a later write/loop or goto.
            if len(covered) != 2 or any(h.start() >= assignment.end() for h in hits):
                continue
            cast = source[assignment.start('cast'):assignment.end('cast')]
            factor = source[assignment.start('assignment')+product.start('factor'):
                            assignment.start('assignment')+product.end('factor')]
            if re.search(rf'\b{variable}\b', cast+factor):
                continue
            # Same-type locals whose earlier lifetime has ended can be the product temporary.
            choices = [variable]+[d['name'] for d in declarations if d['name']!=variable and d['type']==decl['type']
                                  and d.end()<assignment.start() and not re.search(rf'&\s*{d["name"]}\b',part.body)
                                  and len(re.findall(rf'\b{FLOAT}\s+{d["name"]}\b',part.body))==1
                                  and not any(h.start() >= assignment.start() for h in refs(part,d))]
            for temporary in choices[:3]:
                original = source[assignment.start('assignment'):assignment.end('assignment')]
                rewritten = original[:product.start()]+temporary+original[product.end():]
                replacement = f'{temporary} = {factor} * {cast};'+assignment['gap']+rewritten+';'
                candidate = edit(source, [(assignment.start(),assignment.end(),replacement)])
                if ('float_product_intermediate',candidate) not in result:
                    result.append(('float_product_intermediate',candidate))
                if len(result) >= LIMIT:
                    return result
    return result


REPEATED_FLOAT_PRODUCT = 'repeated_float_product_staging'
F32_REG = r'\$f\d+'
FLOAT_LITERAL = r'(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?[fF]'


def _multiply_conversion_sites(rows):
    """Count matching multiply/convert/transfer chains with different register use."""
    mul = re.compile(rf'mul\.s ({F32_REG}), ({F32_REG}), ({F32_REG})')
    convert = re.compile(rf'trunc\.w\.s ({F32_REG}), ({F32_REG})')
    move = re.compile(rf'mfc1 (\$\w+), ({F32_REG})')
    count = 0
    for product, cast, transfer in zip(rows, rows[1:], rows[2:]):
        a, b = (mul.fullmatch(op) for op in product[1:])
        c, d = (convert.fullmatch(op) for op in cast[1:])
        e, f = (move.fullmatch(op) for op in transfer[1:])
        if (a and b and c and d and e and f and a[1] == c[2] and b[1] == d[2]
                and c[1] == e[2] and d[1] == f[2] and e[1] == f[1] and a[1] != b[1]):
            count += 1
    return count


def _unused_float_locals(part, before):
    decl = rf'(?<=[;{{}}])\s*f32\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})*)\s*;'
    names = {name for match in re.finditer(decl, part.clean[:before])
             if block_path(part, match.start('names')) == [part.opening]
             for name in re.findall(IDENT, match['names'])}
    unused = sorted(name for name in names if len(re.findall(rf'\b{name}\b', part.body)) == 1)
    return names, unused


def _array_names(part):
    decl = rf'(?<=[;{{}}])\s*extern\s+f32\s+(?P<arrays>{IDENT}\s*\[\s*\](?:\s*,\s*{IDENT}\s*\[\s*\])*)\s*;'
    return {name for match in re.finditer(decl, ';' + part.clean[:part.opening])
            for name in re.findall(IDENT, match['arrays'])}


def _swapped_product_loads(rows):
    """Find two adjacent load/product chains that trade places without changing operands."""
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changed) != 4 or changed != list(range(changed[0], changed[0] + 4)):
        return None
    start = changed[0]
    target = [entry[1] for entry in rows[start:start + 4]]
    candidate = [entry[2] for entry in rows[start:start + 4]]
    if candidate != target[2:] + target[:2]:
        return None
    load = re.compile(rf'lwc1 ({F32_REG}), ({NUMBER})\((\$a[0-3])\)')
    product = re.compile(rf'mul\.s {F32_REG}, ({F32_REG}), {F32_REG}')
    a, b = load.fullmatch(target[0]), load.fullmatch(target[2])
    x, y = product.fullmatch(target[1]), product.fullmatch(target[3])
    if not a or not b or not x or not y or a[1] != x[1] or b[1] != y[1] or a[3] != b[3]:
        return None
    return integer(a[2]), integer(b[2])


def _stage_subtracted_product(source, name, rows):
    offsets = _swapped_product_loads(rows)
    if not offsets or offsets[0] == offsets[1] or not (part := view(source, name)):
        return []
    if re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.body):
        return []
    difference = re.compile(
        rf'(?m)^(?P<indent>[ \t]*){IDENT} = \((?P<left>{IDENT}) \* {IDENT}\) - '
        rf'(?P<subtracted>\((?P<right>{IDENT}) \* {IDENT}\));'
    )
    proposals = []
    for hit in difference.finditer(part.clean, part.opening + 1, part.end):
        if block_path(part, hit.start()) != [part.opening] or part.clean[:hit.start()].rstrip()[-1:] != ';':
            continue
        names, _ = _unused_float_locals(part, hit.start())
        if not set(re.findall(IDENT, hit[0])) <= names:
            continue
        bindings = []
        for operand in (hit['right'], hit['left']):
            assignments = list(re.compile(rf'\b{operand}\s*=(?!=)').finditer(part.clean, part.opening + 1, hit.start()))
            if len(assignments) != 1:
                break
            pos = assignments[0].end()
            field = re.match(rf'\s*M2C_FIELD\(({IDENT}), f32 \*, ({NUMBER})\);', part.clean[pos:])
            if not field or block_path(part, pos) != [part.opening] or re.search(rf'&\s*{operand}\b', part.body):
                break
            bindings.append((field[1], integer(field[2])))
        if len(bindings) != 2 or bindings[0][0] != bindings[1][0] or tuple(x[1] for x in bindings) != offsets:
            continue
        temporary = fresh(source, '', 'repair_subtracted_product')
        pos = hit.start()
        edits = [
            (part.opening + 1, part.opening + 1, f'\n    f32 {temporary};'),
            (pos, pos, f'{hit["indent"]}{temporary} = {hit["subtracted"]};\n'),
            (*hit.span('subtracted'), temporary),
        ]
        if source[hit.start():hit.end()] == hit[0]:
            proposals.append(('staged_subtracted_float_product', edit(source, edits)))
    return proposals if len(proposals) == 1 else []


def repeated_products(source, name, rows):
    """Stage the same interpolation across conversions without reordering products."""
    if _multiply_conversion_sites(rows) < 2 or not (part := view(source, name)):
        return _stage_subtracted_product(source, name, rows)
    if re.search(r'\b(?:goto|for|while|do|asm|__asm__)\b', part.body):
        return []
    # Anchor at a statement so the added assignment never escapes an unbraced arm.
    anchor = r'(?m)^(?P<indent>[ \t]*)'
    interpolation = (
        rf'\(\s*\(\s*1\.0[fF]\s*-\s*(?P<weight>{IDENT})\s*\)\s*\*\s*(?P<left>{IDENT})'
        rf'\s*\[\s*(?P<index>{IDENT})\s*\]\s*\+\s*(?P=weight)\s*\*\s*(?P<right>{IDENT})'
        rf'\s*\[\s*(?P=index)(?:\s*\+\s*1)?\s*\]\s*\)'
    )
    scaled = re.compile(
        anchor + rf'(?P<out>\*\s*{IDENT}|{IDENT})\s*=\s*(?P<cast>\(s32\)\s*\()?'
        rf'(?P<factor>{IDENT})\s*\*\s*(?P<interp>{interpolation})\s*\*\s*'
        rf'(?P<gain>{FLOAT_LITERAL})(?(cast)\s*\))\s*;'
    )
    bridge = re.compile(anchor + rf'(?P<out>{IDENT})\s*=\s*(?P<factor>{IDENT})\s*\*\s*(?P<interp>{interpolation})\s*;')
    arrays = _array_names(part)
    groups = {}
    for m in scaled.finditer(part.clean, part.opening + 1, part.end):
        if {m['left'], m['right']} <= arrays and part.clean[:m.start()].rstrip()[-1:] in ';{}':
            key = re.sub(r'\s+', '', m['interp'])
            groups.setdefault(key, []).append(m)
    result = []
    for key, sites in groups.items():
        if len(sites) != 3:
            continue
        a, b, c = sites
        linked = [m for m in bridge.finditer(part.clean, a.end(), b.start())
                  if re.sub(r'\s+', '', m['interp']) == key and part.clean[:m.start()].rstrip()[-1:] in ';{}']
        if len(linked) != 1:
            continue
        intermediate = linked[0]
        names, unused = _unused_float_locals(part, a.start())
        carrier = intermediate['out']
        if not unused or {a['weight'], a['factor'], carrier, c['out']} - names:
            continue
        if (a['factor'] != intermediate['factor'] or b['factor'] != carrier or c['factor'] != carrier
                or not a['cast'] or not b['cast'] or c['cast']
                or not all(re.fullmatch(rf'\*\s*{IDENT}', site['out']) for site in (a, b))):
            continue
        temporary = unused[0]
        edits = [(m.start(), m.end(), _stage_scaled(source, m, temporary)) for m in sites]
        expr = source[intermediate.start('interp'):intermediate.end('interp')]
        prefix = intermediate['indent']
        edits.append((intermediate.start(), intermediate.end(),
                      f'{prefix}{temporary} = {expr};\n{prefix}{carrier} = {intermediate["factor"]} * {temporary};'))
        last = _final_interpolation(part, interpolation, c.end(), carrier, arrays)
        if any(source[start:end] != part.clean[start:end] for start, end, _ in edits):
            continue
        if last and source[last[0]:last[1]] == part.clean[last[0]:last[1]]:
            result.append((REPEATED_FLOAT_PRODUCT, edit(source, edits + [last])))
        result.append((REPEATED_FLOAT_PRODUCT, edit(source, edits)))
    return result[:4]


def _stage_scaled(source, match, temporary):
    indent = match['indent']
    product = source[match.start('factor'):match.end('interp')]
    cast = '(s32)(' if match['cast'] else ''
    suffix = ')' if cast else ''
    return (f'{indent}{temporary} = {product};\n'
            f'{indent}{match["out"]} = {cast}{temporary} * {match["gain"]}{suffix};')


def _final_interpolation(part, interpolation, after, carrier, arrays):
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<out>\*\s*{IDENT})\s*=\s*\(s32\)\s*'
        rf'\(\s*(?P<interp>{interpolation})\s*\*\s*(?P<gain>{FLOAT_LITERAL})\s*\)\s*;\s*}}\s*$'
    )
    last = pattern.search(part.clean, after, part.end)
    if (not last or {last['left'], last['right']} - arrays
            or part.clean[:last.start()].rstrip()[-1:] not in ';{}'
            or re.search(rf'&\s*\(*\s*{carrier}\b', part.body)):
        return None
    # There are no subsequent statements, so the old carrier's final value is dead.
    expr = part.source[last.start('interp') + 1:last.end('interp') - 1]
    end = part.clean.index(';', last.end('gain')) + 1
    prefix = last['indent']
    out = last['out']
    return last.start(), end, f'{prefix}{carrier} = {expr}; {out} = (s32)({carrier} * {last["gain"]});'
