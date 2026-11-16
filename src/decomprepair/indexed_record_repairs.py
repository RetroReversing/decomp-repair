"""Bounded indexed-record copy, conversion and storage hypotheses.

Only declared scalar fields and pure indices participate. Raw target words gate
new subarray anchors and retained word reads; ordinary field ordering never
crosses calls or changes existing volatile access order. The caller compiles
complete candidates and remains the sole authority on linked bytes and data.
"""
import itertools
import re

from . import indexed_record_support as support
from .csource import _COMMENT_OR_STRING, _blank
from .integer_repair_support import IDENT, edit, integer

FAMILIES = ('indexed_record_base', 'indexed_record_word_capture', 'indexed_record_store_order',
            'indexed_record_counter', 'indexed_record_index_width', 'indexed_record_operand_order',
            'indexed_record_byte_capture', 'indexed_record_case_order', 'indexed_record_sequence',
            'indexed_record_conversion_order')
LIMIT = 32
SEQUENCE_LIMIT = 64


def rebase(source, name, header='', arch=None, asm=''):
    """Split constant record prefixes only when both anchors occur in raw target evidence."""
    model = support.part(source, name, header)
    if not model or arch not in {'mips', 'mipsel'}:
        return []
    anchors = support.indexed_bases(asm)
    edits, declarations = [], []
    pattern = rf'\b(D_[0-9A-Fa-f]{{8}})\[\s*(0x[0-9A-Fa-f]+|[0-9]+)\s*\+\s*({IDENT})\s*\]'
    groups = {}
    for hit in re.compile(pattern).finditer(model.part.clean, model.part.opening+1, model.part.end):
        groups.setdefault((hit[1], integer(hit[2]), hit[3]), []).append(hit)
    for (base, prefix, index), hits in groups.items():
        declaration = model.roots.get(base)
        idx = model.roots.get(index)
        if (not declaration or len(declaration.dims) != 1 or declaration.type not in model.types
                or declaration.volatile or not idx or idx.volatile or idx.type not in {'u16', 'u32', 's16', 's32', 'int'}):
            continue
        address = int(base[2:], 16)
        destination = address+prefix*model.size(declaration.type)[0]
        # Auto names are not address evidence on their own.
        if not 0 < prefix <= 64 or address not in anchors or destination not in anchors:
            continue
        alias = f'D_{destination:08X}'
        if alias in model.roots or re.search(rf'\b{alias}\b', header+source):
            continue
        if declaration.dims[0]:
            continue  # A known finite object may not be split into unrelated extern objects.
        for hit in hits:
            edits.append((hit.start(), hit.end(), f'{alias}[{index}]'))
        declarations.append(f'extern {declaration.type} {alias}[];\n')
    if not edits or len(declarations) > 2:
        return []
    last = max((root.declaration[1] for root in model.roots.values()
                if root.dims and root.type in model.types and root.declaration[1] < model.part.opening), default=0)
    if not last:
        return []
    # Root spans end immediately before the declaration's semicolon.
    point = source.find(';', last)+1
    edits.append((point, point, '\n'+''.join(declarations).rstrip('\n')))
    return [(FAMILIES[0], edit(source, edits))]


def _pure(expression):
    return bool(re.fullmatch(r'[\w\s.>\[\]()+*/&|^~<>-]+', expression)
                and not re.search(r'\+\+|--|\b'+IDENT+r'\s*\(|\b(?:sizeof|volatile)\b', expression))


def _conversion_macros(source):
    """Read one visible comma-assignment macro, with each formal evaluated once."""
    result = {}
    pattern = rf'(?m)^\s*#\s*define\s+({IDENT})\(({IDENT})\s*,\s*({IDENT})\)\s+\(\s*({IDENT})\s*=\s*\(\s*(float|f32)\s*\)\s*\(\s*\3\s*\)\s*,\s*(.+)\)\s*$'
    for hit in re.finditer(pattern, _blank(source)):
        macro, numerator, denominator, temp, typ, body = hit.groups()
        if ('#' in body or '\\' in body or re.search(r'\b__LINE__\b|\+\+|--|=(?!=)', body)
                or re.search(r'\b'+IDENT+r'\s*\(', body)
                or len(re.findall(rf'\b{numerator}\b', body)) != 1
                or re.search(rf'\b{denominator}\b', body)
                or not re.search(rf'/\s*{temp}\b', body)):
            continue
        result[macro] = (numerator, temp, typ, body)
    return result


def _reload_evidence(asm):
    accesses = support.indexed_bases(asm, memory=True)
    pairs = sum(1 for i, (epoch, pc, op, address) in enumerate(accesses) if op == 43
                and any(e == epoch and 0 < p-pc <= 20 and o == 35 and a == address
                        for e, p, o, a in accesses[i+1:i+5]))
    return pairs >= 2 and bool(re.search(r'\bcvt\.d\.w\b', asm))


def word_captures(source, name, header='', arch=None, asm=''):
    """Retain a stored unsigned word before its byte neighbour and convert after that store."""
    model = support.part(source, name, header)
    if not model or arch not in {'mips', 'mipsel'} or not _reload_evidence(asm):
        return []
    macros = _conversion_macros(source)
    if not macros:
        return []
    store = rf'(?P<obj>{support.ACCESS})\.(?P<word>{IDENT})\s*=\s*(?P<value>{support.FIELD});\s*\n(?P<indent>[ \t]*)'
    store += rf'(?P=obj)\.(?P<byte>{IDENT})\s*=\s*(?P<bytevalue>{support.FIELD});\s*\n[ \t]*'
    store += rf'(?P=obj)\.(?P<result>{IDENT})\s*=\s*(?P<macro>{IDENT})\((?P<num>[^,;{{}}]+),\s*(?P=obj)\.(?P=word)\);'
    sites = []
    for hit in re.compile(store).finditer(model.part.clean, model.part.opening+1, model.part.end):
        if hit['macro'] not in macros or not _pure(hit['num']):
            continue
        word, byte, result = (model.access(hit['obj']+'.'+hit[k]) for k in ['word', 'byte', 'result'])
        value, bytevalue = model.access(hit['value']), model.access(hit['bytevalue'])
        num = model.access(hit['num'].strip())
        floating = model.roots.get(macros[hit['macro']][1])
        if (not word or word.type != 'u32' or word.dims or not byte or not result or not value or not bytevalue
                or byte.size != 1 or result.size != 1 or byte.volatile or result.volatile
                or value.volatile or bytevalue.volatile or not num or num.volatile or num.size != 4 or num.pointer or num.dims
                or not floating or floating.volatile or floating.type not in {'f32', 'float'}
                or len({word.offset, byte.offset, result.offset}) != 3):
            continue
        sites.append(hit)
    if not 2 <= len(sites) <= 12:
        return []
    temp = '__repair_record_word'
    while re.search(rf'\b{temp}\b', header+source):
        temp += '_'
    edits, qualified = [], set()
    for hit in sites:
        formal, floating, typ, body = macros[hit['macro']]
        body = re.sub(rf'\b{formal}\b', hit['num'].strip(), body)
        word = model.access(hit['obj']+'.'+hit['word'])
        if not word.volatile and word.declaration not in qualified:
            a, b = word.declaration
            declaration = source[a:b]
            # Only the actual word field is qualified, never its record or byte peers.
            at = a+len(declaration)-len(declaration.lstrip())
            edits.append((at, at, 'volatile '))
            qualified.add(word.declaration)
        indent, obj = hit['indent'], hit['obj']
        lines = [f'{obj}.{hit["word"]} = {hit["value"]};', f'{temp} = {obj}.{hit["word"]};',
                 f'{obj}.{hit["byte"]} = {hit["bytevalue"]};', f'{floating} = ({typ}){temp};',
                 f'{obj}.{hit["result"]} = {body};']
        edits.append((hit.start(), hit.end(), ('\n'+indent).join(lines)))
    # Place the word in the existing declaration run; legacy C89 compilers reject
    # a declaration after statements. A private top-level local has no escape.
    anchor = re.search(r'\b(?:f32|float)\s+'+re.escape(macros[sites[0]['macro']][1])+r'\s*;', model.part.body)
    if not anchor:
        return []
    at = model.part.opening+1+anchor.end()
    edits.append((at, at, f'\n    u32 {temp};'))
    return [(FAMILIES[1], edit(source, edits))]


def store_orders(source, name, header='', arch=None, asm=''):
    """Order distinct ordinary byte stores, including nested indexed global records."""
    model = support.part(source, name, header)
    if not model:
        return []
    pattern = rf'(?P<a>(?P<obj>{support.ACCESS})\.(?P<left>{IDENT})\s*=\s*(?P<x>0|{support.FIELD});)(?P<gap>\s*\n[ \t]*)(?P<b>(?P=obj)\.(?P<right>{IDENT})\s*=\s*(?P<y>0|{support.FIELD});)'
    sites = []
    for hit in re.compile(pattern).finditer(model.part.clean, model.part.opening+1, model.part.end):
        if (hit['x'] == '0') == (hit['y'] == '0'):
            continue
        a, b = model.access(hit['obj']+'.'+hit['left']), model.access(hit['obj']+'.'+hit['right'])
        rhs = model.access(hit['y'] if hit['x'] == '0' else hit['x'])
        rhs_expression = hit['y'] if hit['x'] == '0' else hit['x']
        zero_field = hit['left'] if hit['x'] == '0' else hit['right']
        if (not a or not b or not rhs or a.offset == b.offset or a.size != 1 or b.size != 1
                or a.volatile or b.volatile or rhs.volatile or rhs.dims or rhs.pointer):
            continue
        if re.sub(r'\s+', '', rhs_expression) == re.sub(r'\s+', '', hit['obj']+'.'+zero_field):
            continue  # The zero store supplies a value read by its neighbouring store.
        following_call = bool(re.match(r'\s*'+IDENT+r'\s*\(', model.part.clean[hit.end():]))
        sites.append((hit, following_call))
    if not 2 <= len(sites) <= 16:
        return []
    result = []
    for zero_first, preserve_call in itertools.product((False, True), (True, False)):
        edits = []
        for hit, following_call in sites:
            if preserve_call and following_call or (hit['x'] == '0') == zero_first:
                continue
            edits.append((hit.start(), hit.end(), source[hit.start('b'):hit.end('b')]+hit['gap']+source[hit.start('a'):hit.end('a')]))
        if edits:
            result.append((FAMILIES[2], edit(source, edits)))
    return list(dict.fromkeys(result))


def counter_storage(source, name, header='', arch=None, asm=''):
    """Try private byte-counter/word-array qualifications at an existing record update."""
    model = support.part(source, name, header)
    if not model or arch not in {'mips', 'mipsel'}:
        return []
    anchors = support.indexed_bases(asm)
    pattern = rf'\bu8\s+({IDENT})\s*=\s*(D_[0-9A-Fa-f]{{8}})\s*;\s*({support.ACCESS})\s*=\s*({support.FIELD});\s*\2\s*=\s*\1\s*\+\s*1;'
    result = []
    for hit in re.compile(pattern).finditer(model.part.clean, model.part.opening+1, model.part.end):
        counter, target = model.roots.get(hit[2]), model.access(hit[3])
        if (not counter or counter.type != 'u8' or counter.dims or not target or target.type != 'u32'
                or target.dims or int(hit[2][2:], 16) not in anchors or counter.volatile and target.volatile):
            continue
        edits = []
        for value in (counter, target):
            if value.volatile:
                continue
            a, b = value.declaration
            text = source[a:b]
            qualifier = re.search(r'\b(?:u8|u32)\b', text)
            if not qualifier:
                break
            edits.append((a+qualifier.start(), a+qualifier.start(), 'volatile '))
        else:
            if edits:
                result.append((FAMILIES[3], edit(source, edits)))
    return result[:2]


def conversion_orders(source, name, header='', arch=None, asm=''):
    """Move an existing conversion past one ordinary store to a disjoint byte field."""
    model = support.part(source, name, header)
    if not model:
        return []
    pattern = rf'(?P<a>(?P<temp>{IDENT})\s*=\s*\(\s*(?:f32|float)\s*\)(?P<obj>{support.ACCESS})\.(?P<word>{IDENT});)(?P<gap>\s*\n[ \t]*)(?P<b>(?P=obj)\.(?P<byte>{IDENT})\s*=\s*(?P<rhs>{support.FIELD});)'
    changes = []
    for hit in re.compile(pattern).finditer(model.part.clean, model.part.opening+1, model.part.end):
        word, byte, rhs = model.access(hit['obj']+'.'+hit['word']), model.access(hit['obj']+'.'+hit['byte']), model.access(hit['rhs'])
        temp = model.roots.get(hit['temp'])
        if (not word or not byte or not rhs or not temp or temp.type not in {'f32', 'float'} or temp.volatile
                or word.type != 'u32' or word.dims or byte.size != 1 or byte.volatile or rhs.volatile
                or word.offset < byte.offset+byte.size and byte.offset < word.offset+word.size):
            continue
        changes.append((hit.start(), hit.end(), source[hit.start('b'):hit.end('b')]+hit['gap']+source[hit.start('a'):hit.end('a')]))
    return [(FAMILIES[-1], edit(source, changes))] if changes else []


def index_widths(source, name, header='', arch=None, asm=''):
    """Keep a proven unsigned-halfword value in a word carrier without changing its value."""
    model = support.part(source, name, header)
    if not model:
        return []
    result = []
    for hit in re.compile(rf'\bu16\s+({IDENT})\s*=\s*({IDENT})\s*;').finditer(model.part.clean, model.part.opening+1, model.part.end):
        variable, rhs = hit.groups()
        value = model.roots.get(rhs)
        tail = model.part.clean[hit.end():model.part.end]
        if (not value or value.type != 'u16' or value.volatile or value.dims or value.pointer
                or re.search(rf'(?<!&)&\s*{variable}\b|\b{variable}\s*(?:\+\+|--|[+*/%&|^-]?=(?!=))|\bsizeof\b', tail)):
            continue
        # An immutable index's width is unobserved outside its subscript uses.
        uses = list(re.finditer(rf'\b{variable}\b', tail))
        if not uses or any(tail[:u.start()].rstrip()[-1:] != '[' or tail[u.end():].lstrip()[:1] != ']' for u in uses):
            continue
        result.append((FAMILIES[4], edit(source, [(hit.start(), hit.end(), f'u32 {variable} = {rhs} & 0xFFFF;')])))
    return result[:2]


def operand_orders(source, name, header='', arch=None, asm=''):
    """Commute pure member-array subscripts as complete source alternatives."""
    model = support.part(source, name, header)
    if not model:
        return []
    groups = {}
    for hit in re.compile(rf'\b({IDENT}->{IDENT})\[({IDENT})\]').finditer(model.part.clean, model.part.opening+1, model.part.end):
        base, index = model.access(hit[1]), model.roots.get(hit[2])
        if base and base.dims and not base.volatile and index and not index.volatile and not index.pointer:
            groups.setdefault(hit[1], []).append(hit)
    result = []
    for _, hits in sorted(groups.items(), key=lambda item: -len(item[1]))[:2]:
        if len(hits) >= 2:
            result.append((FAMILIES[5], edit(source, [(h.start(), h.end(), f'{h[2]}[{h[1]}]') for h in hits])))
    return result


def byte_cases(source, name, header='', arch=None, asm=''):
    """Stage adjacent byte decodes and order independent case-local scalar assignments."""
    model = support.part(source, name, header)
    if not model:
        return []
    assignment = rf'({IDENT})\s*=\s*({IDENT})\[([0-9]+)\]\s*-\s*(\x27[^\x27\\]\x27)\s*;'
    visible = _COMMENT_OR_STRING.sub(lambda m: m[0] if m[0].startswith("'") else
                                    re.sub(r'[^\n]', ' ', m[0]), source)
    result = []
    for hit in re.finditer(assignment+r'\s*\n[ \t]*'+assignment, visible[model.part.opening+1:model.part.end]):
        first, base, index, constant, second, base2, index2, constant2 = hit.groups()
        value = model.roots.get(base)
        if (first == second or base != base2 or not value or value.type != 'char' or value.volatile or len(value.dims) != 1
                or any(k not in model.roots for k in [first, second]) or int(index) >= value.dims[0] or int(index2) >= value.dims[0]):
            continue
        if any(model.roots[k].volatile or model.roots[k].pointer or model.roots[k].dims
               or k in model.macros or re.search(rf'(?<!&)&(?!&)\s*\(*\s*{k}\b', model.part.body)
               for k in [first, second]):
            continue
        temp = '__repair_byte'
        while re.search(rf'\b{temp}\b', source+header):
            temp += '_'
        at = model.part.opening+1
        text = f'{{ char {temp} = {base}[{index}]; {first} = {temp} - {constant}; {temp} = {base}[{index2}]; {second} = {temp} - {constant2}; }}'
        result.append((FAMILIES[6], edit(source, [(at+hit.start(), at+hit.end(), text)])))
        break
    # Only a complete, call-free three-assignment case; no control or memory stores
    # can move. Its byte reads are from one ordinary local array.
    cases = re.finditer(r'\bcase\s+[^:;{}]+:\s*([^{}:]+?)\bbreak\s*;', visible[model.part.opening+1:model.part.end])
    for case in cases:
        statements = list(re.finditer(r'(?m)^[ \t]*('+IDENT+r'\s*=\s*[^;{}]+;)', case[1]))
        if len(statements) != 3 or len({re.match(IDENT, m[1])[0] for m in statements}) != 3:
            continue
        remainder = case[1]
        for statement in reversed(statements):
            remainder = remainder[:statement.start()]+remainder[statement.end():]
        if remainder.strip():
            continue
        reads = [re.fullmatch(assignment, m[1]) for m in statements]
        if sum(bool(r) for r in reads) != 2 or not any(re.fullmatch(IDENT+r'\s*=\s*0;', m[1]) for m in statements):
            continue
        arrays = {r[2] for r in reads if r}
        if len(arrays) != 1:
            continue
        array = model.roots.get(next(iter(arrays)))
        if not array or array.volatile or array.type != 'char' or len(array.dims) != 1:
            continue
        destinations = [re.match(IDENT, m[1])[0] for m in statements]
        if any(v not in model.roots or model.roots[v].volatile or model.roots[v].dims or model.roots[v].pointer
               or re.search(rf'(?<!&)&(?!&)\s*\(*\s*{v}\b', model.part.body) for v in destinations):
            continue
        a = model.part.opening+1+case.start(1)+statements[0].start(1)
        b = model.part.opening+1+case.start(1)+statements[-1].end(1)
        indent = re.search(r'[ \t]*$', source[:a])[0]
        original = [m[1] for m in statements]
        orders = [tuple(reversed(original))]+list(itertools.permutations(original))
        for ordered in dict.fromkeys(orders):
            text = ('\n'+indent).join(ordered)
            if text != source[a:b]:
                result.append((FAMILIES[7], edit(source, [(a, b, text)])))
        break
    return result[:6]


def variants(source, name, header='', arch=None, asm=''):
    """Finite ordinary candidates; components reparse their own source and retain guards."""
    functions = (rebase, word_captures, conversion_orders, store_orders, counter_storage, index_widths, operand_orders, byte_cases)
    result = []
    for function in functions:
        result.extend(function(source, name, header, arch, asm))
    return list(dict.fromkeys(sequences(source, name, header, arch, asm)+result[:LIMIT]))


def sequences(source, name, header='', arch=None, asm=''):
    """Compose a finite repeated-copy recipe; every component reparses its actual parent.

    No compiler result or saved manual source is an input. A stored-word conversion
    repeated at two or more declared records earns this page even in a large body.
    The caller's ordinary trial budget covers every resulting whole-function compile.
    """
    if not word_captures(source, name, header, arch, asm):
        return []
    current = source
    for generate in (rebase, word_captures, conversion_orders, counter_storage, index_widths):
        choices = generate(current, name, header, arch, asm)
        if choices:
            current = choices[0][1]
    captured = [text for family, text in byte_cases(current, name, header, arch, asm) if family == FAMILIES[6]]
    if captured:
        current = captured[0]
    cases = [current]+[text for family, text in byte_cases(current, name, header, arch, asm) if family == FAMILIES[7]]
    result = []
    for case in cases:
        orders = [text for _, text in store_orders(case, name, header, arch, asm)]+[case]
        for ordered in orders:
            operands = [text for _, text in operand_orders(ordered, name, header, arch, asm)]+[ordered]
            for candidate in operands:
                if candidate != source:
                    result.append(('indexed_record_sequence', candidate))
                if len(result) >= SEQUENCE_LIMIT:
                    return list(dict.fromkeys(result))
    return list(dict.fromkeys(result))
