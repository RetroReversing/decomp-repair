"""Try a typed record when an incoming base and index form a measured MIPS address."""
import re
from collections import defaultdict

from .compiler_shape_repairs import NUMBER, SCALARS, number
from .inferred_layout_repairs import CANONICAL, TYPE
from .integer_repair_support import IDENT, edit, split_args, view
from .measured_storage_repairs import strided_fields
from .mips_regions import ALU, CALLS, CONDITIONAL, JUMPS, LOADS, STORES
from .mips_returns import instructions

FAMILY = 'inferred_array_stride'
LOAD_TYPES = {'lb': 'signed char', 'lbu': 'unsigned char', 'lh': 'short', 'lhu': 'unsigned short',
              'lw': 'word', 'lwc1': 'float'}
STORE_WIDTHS = {'sb': 1, 'sh': 2, 'sw': 4, 'swc1': 4}
BYTE = r'(?:unsigned\s+char|signed\s+char|char|[su]8)'


def evidence(asm):
    """Read affine addresses in the straight-line entry, including shift/add multiplication."""
    state = {f'$a{i}': (tuple(int(i == j) for j in range(4)), 0) for i in range(4)}
    state['$zero'] = ((0, 0, 0, 0), 0)
    found = defaultdict(lambda: defaultdict(set))
    for line in instructions(asm)[:128]:
        op, *rest = line.split(None, 1)
        operands = rest[0] if rest else ''
        args = [arg.strip() for arg in operands.split(',')]
        if op in CALLS | CONDITIONAL | JUMPS or op in {'break', 'syscall'}:
            break
        if op == 'nop':
            continue
        if op in LOAD_TYPES or op in STORE_WIDTHS:
            access = re.fullmatch(rf'\s*({NUMBER})?\((\$\w+)\)', args[-1])
            if access and access[2] in state:
                coeffs, offset = state[access[2]]
                offset += number(access[1]) if access[1] else 0
                bases = [i for i, c in enumerate(coeffs) if c == 1]
                indices = [(i, c) for i, c in enumerate(coeffs) if 2 <= c <= 256]
                if len(bases) == len(indices) == 1 and sum(c != 0 for c in coeffs) == 2:
                    index, stride = indices[0]
                    if 0 <= offset < stride:
                        found[bases[0], index][stride, offset].add(LOAD_TYPES.get(op, STORE_WIDTHS.get(op)))
        if op in STORES:
            continue
        if op not in ALU | LOADS | {'lui'}:
            break
        dst = args[0]
        if dst == '$zero':
            continue
        value = None
        if op == 'move' and len(args) == 2:
            value = state.get(args[1])
        elif len(args) == 3 and args[1] in state:
            left, off = state[args[1]]
            if op in {'addu', 'subu', 'or'} and args[2] in state:
                right, right_off = state[args[2]]
                if op != 'or' or args[1] == '$zero' or args[2] == '$zero':
                    sign = -1 if op == 'subu' else 1
                    value = (tuple(a+sign*b for a,b in zip(left,right)), off+sign*right_off)
            elif op == 'sll' and re.fullmatch(NUMBER, args[2]) and 0 <= (shift := number(args[2])) <= 8:
                value = (tuple(c << shift for c in left), off << shift)
            elif op == 'addiu' and re.fullmatch(NUMBER, args[2]):
                immediate = number(args[2]) & 0xffff
                value = (left, off+(immediate if immediate < 0x8000 else immediate-0x10000))
        state.pop(dst, None)
        if value is not None:
            state[dst] = value
    return found


ACCESS = re.compile(
    rf'\bM2C_FIELD\s*\(\s*(?P<expr>\()?\s*(?P<cast>\(\s*{BYTE}\s*\*\s*\)\s*)?'
    rf'(?P<base>{IDENT})\s*\+\s*(?P<product>\()?\s*(?P<index>{IDENT})\s*\*\s*(?P<scale>{NUMBER})'
    rf'\s*(?(product)\))\s*(?(expr)\))\s*,\s*(?P<type>{TYPE})\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)'
)


def variants(source, name, header, observed):
    """Build a local record with explicit padding and a compile-time stride check."""
    if not observed or not (part := view(source, name)):
        return []
    context = header+'\n'+part.clean
    if (re.search(r'\b(?:volatile|restrict|asm|__asm__|__attribute__)\b', part.body)
            or re.search(r'^\s*#\s*(?:pragma|undef)\b', context, re.M)):
        return []
    signature = re.search(r'\b'+re.escape(name)+r'\s*\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not signature:
        return []
    params = [signature[1][a:b] for a,b in split_args(signature[1])]
    names = [re.search(r'\b('+IDENT+r')\s*$', param) for param in params]
    entries = {m[1]: i for i,m in enumerate(names) if m}
    groups = defaultdict(list)
    for hit in ACCESS.finditer(part.clean, part.opening+1, part.end-1):
        groups[hit['base'], hit['index']].append(hit)
    result = []
    for (base, index), sites in groups.items():
        if base not in entries or index not in entries:
            continue
        bi, ii = entries[base], entries[index]
        if not re.fullmatch(rf'\s*(?:{BYTE}|void)\s*\*\s*{base}\s*', params[bi]):
            continue
        if not re.fullmatch(rf'\s*(?:int|unsigned(?:\s+int)?|[su]32)\s+{index}\s*', params[ii]):
            continue
        # A local shadow, assignment, or arbitrary use can break entry-argument identity.
        if (len(re.findall(rf'\b{base}\b', part.body)) != len(sites)
                or len(re.findall(rf'\b{index}\b', part.body)) != len(sites)):
            continue
        if len({number(site['scale']) for site in sites}) != 1:
            continue
        if any(not site['cast'] and re.search(r'\bvoid\b',params[bi]) for site in sites):
            continue
        verified = observed.get((bi, ii), {})
        strides = {stride for stride,_ in verified}
        if len(strides) != 1:
            continue
        stride = next(iter(strides))
        record = '__repair_array_record'
        if record in context or '__repair_array_size' in context:
            continue
        fields, replacements = {}, []
        for site in sites:
            typ = ' '.join(site['type'].split())
            typ = CANONICAL.get(typ, typ)
            width, offset = SCALARS.get(typ), number(site['offset'])
            actual = verified.get((stride,offset), set())
            if (not width or offset % width or offset+width > stride or stride % width
                    or not actual or any(x not in {typ,width,'word' if width == 4 and typ != 'float' else None} for x in actual)
                    or fields.get(offset, (typ,width)) != (typ,width)
                    or re.search(r'/[*/]', source[site.start():site.end()])):
                break
            fields[offset] = (typ,width)
            replacements.append((site.start(),site.end(),f'(({record} *){base})[{index}].field_{offset:X}'))
        else:
            cursor, members = 0, []
            for offset, (typ,width) in sorted(fields.items()):
                if offset < cursor:
                    break
                if offset > cursor:
                    members.append(f'unsigned char pad_{cursor:X}[{offset-cursor}];')
                members.append(f'{typ} field_{offset:X};')
                cursor = offset+width
            else:
                if cursor < stride:
                    members.append(f'unsigned char pad_{cursor:X}[{stride-cursor}];')
                declaration = 'typedef struct { '+' '.join(members)+' } '+record+';'
                check = f'typedef char __repair_array_size[(sizeof({record}) == {stride}) ? 1 : -1];'
                result.append((FAMILY, edit(source, [(part.opening+1,part.opening+1,'\n'+declaration+'\n'+check+'\n'), *replacements])))
        if len(result) >= 2:
            break
    return result


def global_variants(source, name, header, groups):
    """A relocated field can have one unambiguous stride across multiple reaching indices."""
    by_symbol = defaultdict(set)
    for (_, stride), fields in groups.items():
        for symbol, width in fields.items():
            by_symbol[symbol].add((stride, width))
    by_stride = defaultdict(dict)
    for symbol, sizes in by_symbol.items():
        if len(sizes) == 1:
            stride, width = next(iter(sizes))
            by_stride[stride][symbol] = width
    views = sorted(by_stride.items())
    result = [(FAMILY, candidate) for _, candidate in
              strided_fields(source, name, header, views, minimum_symbols=1)]
    if not (part := view(source, name)):
        return result
    context = part.clean[:part.opening]+'\n'+header
    if re.search(r'\b(?:volatile|restrict|asm|__asm__|__attribute__)\b|^\s*#\s*pragma\b', context+part.body, re.M):
        return result
    for stride, fields in views:
        for symbol, width in fields.items():
            decl = re.findall(rf'\bextern\s+({TYPE})\s+{re.escape(symbol)}\s*\[\s*\]\s*;', context)
            if len(decl) != 1 or stride <= width or stride % width:
                continue
            typ = ' '.join(decl[0].split())
            if SCALARS.get(typ) != width:
                continue
            access = re.compile(rf'\b{re.escape(symbol)}\s*\[\s*({IDENT})\s*\*\s*({NUMBER})\s*\]')
            edits = []
            for hit in access.finditer(part.clean, part.opening+1, part.end-1):
                if number(hit[2])*width == stride and not re.search(r'/[*/]', source[hit.start():hit.end()]):
                    view_type = f'struct {{ {typ} value; unsigned char padding[{stride-width}]; }}'
                    edits.append((hit.start(), hit.end(), f'(({view_type} *){symbol})[{hit[1]}].value'))
            if edits and len(re.findall(rf'\b{re.escape(symbol)}\b', part.body)) == len(edits):
                result.append((FAMILY, edit(source, edits[:8])))
            if len(result) == 4:
                return result
    return result
