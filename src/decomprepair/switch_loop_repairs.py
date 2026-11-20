"""Typed source hypotheses for switch arms, counted record loops and byte counters."""
import re
from difflib import SequenceMatcher

from .call_lifetime_repairs import block_path
from .csource import _blank
from .indexed_record_support import ACCESS, Records
from .integer_abi import scalar
from .integer_repair_support import IDENT, edit, locals_for, refs
from .pattern_repairs import close
from .permuter_macro_effects import DEFINE

CASE = 'signed_byte_carrier'
LOOP = 'halfword_loop_snapshot'
INDEX = 'record_index_snapshot'
STORES = 'record_flag_store_order'
COUNTER = 'narrow_counter_carrier'
EXACT = 'explicit_volatile_counter_store'
FAMILIES = (CASE, LOOP, INDEX, STORES, COUNTER, EXACT)
INDENT = r'[ \t]*'
LABEL = r'(?:case\b[^:\n]*|default)\s*:'
UNSAFE = r'\b(?:goto|continue|break|return|switch|for|while|do|if|else)\b|[{}]'
BLOCK_ENTRY = rf'(?m:^\s*{IDENT}\s*:)|\b(?:case|default|goto)\b'


def _line_insertion(source, position, declaration):
    indent = re.search(r'[ \t]*$', source[:position])[0]
    return position, position, declaration+'\n'+indent


def _fresh(context, stem):
    names = set(re.findall(IDENT, context))
    return next(stem+str(n or '') for n in range(len(names)+1) if stem+str(n or '') not in names)


def _root_local(part, position):
    return block_path(part, position) == [part.opening]


def _macros(context):
    items = {}
    for hit in DEFINE.finditer(re.sub(r'\\\r?\n', ' ', _blank(context))):
        parameters = set(re.findall(IDENT, hit[2] or ''))
        items.setdefault(hit[1], []).append((parameters, hit[3]))
    return items


def _macro_safe(text, macros, locals_):
    # Conservative for statement macros, token pasting and hidden access to a
    # local. An alias may hide an assignment or let the local's address escape.
    for name in set(re.findall(IDENT, text)) & macros.keys():
        versions = macros[name]
        if len(versions) != 1:
            return False
        params, body = versions[0]
        mentions = set(re.findall(IDENT, body))-params
        if mentions & (locals_ | macros.keys()) or re.search(r'[;#{}=&]|\+\+|--', body):
            return False
    return True


def _word_result(expr, model, context, macros):
    call = re.match(rf'^({IDENT})\s*\(', expr)
    if call:
        if call[1] not in macros or len(macros[call[1]]) != 1 or close(expr, call.end()-1) != len(expr):
            return False
        expr = macros[call[1]][0][1].strip()
    while expr.startswith('(') and close(expr, 0) == len(expr):
        expr = expr[1:-1].strip()
    cast = re.match(r'^\(([^()]*)\)\s*\(', expr)
    if cast and close(expr, cast.end()-1) == len(expr):
        return scalar(cast[1], context, 'mips') == (32, False)
    field = model.access(expr)
    return bool(field and not field.pointer and not field.dims and scalar(field.type, context, 'mips') == (32, False))


def _case(model, context, declarations):
    p = model.part
    pattern = re.compile(
        rf'(?m)^({INDENT})({IDENT})\s*=\s*\(\s*(s8|signed\s+char)\s*\)'
        rf'({IDENT})\[\s*(\d+)\s*\]\s*-\s*(\x27[^\x27\n]\x27|[0-9]+)\s*;\n'
        rf'\1({IDENT})\s*=\s*\(\s*\3\s*\)\4\[\s*(\d+)\s*\]\s*-\s*(\x27[^\x27\n]\x27|[0-9]+)\s*;')
    array_pattern = rf'\b(?:char|s8|u8)\s+({IDENT})\s*\[\s*(\d+)\s*\]\s*;'
    for hit in pattern.finditer(p.source, p.opening+1, p.end):
        indent, first, kind, array, i, a, second, j, b = hit.groups()
        value = model.roots.get(array)
        if (not value or value.volatile or not value.dims or value.dims[0] <= max(int(i), int(j))
                or i == j or first == second or not {first, second} <= declarations.keys()
                or not re.search(array_pattern.replace('('+IDENT+')', re.escape(array)), p.body)
                or any(not _root_local(p, declarations[n].start()) for n in (first, second))
                or not p.clean[hit.start():hit.end()].strip().startswith(first)
                or scalar(kind, context, 'mips') != (8, True)):
            continue
        # The pair must belong to a case arm with no alternate entry between the loads.
        prefix = p.clean[p.opening:hit.start()]
        labels = list(re.finditer(rf'(?m)^\s*{LABEL}', prefix))
        if not labels or prefix.rstrip()[-1:] not in ':;' or not re.search(r'\bswitch\s*\(', prefix[:labels[-1].start()]):
            continue
        if re.search(r'[{}:]', prefix[labels[-1].end():]):
            continue
        decls = [d for d in declarations.values() if _root_local(p, d.start())]
        array_decl = re.search(array_pattern.replace('('+IDENT+')', re.escape(array)), p.clean)
        if not array_decl or not _root_local(p, array_decl.start()):
            continue
        anchor = min((d.start() for d in decls), default=array_decl.end())
        temp = _fresh(context, 'raw')
        replacement = f'{indent}{temp} = {array}[{i}];\n{indent}{first} = {temp} - {a};\n'
        replacement += f'{indent}{temp} = {array}[{j}];\n{indent}{second} = {temp} - {b};'
        yield edit(p.source, [_line_insertion(p.source, anchor, f'{kind} {temp};'),
                              (hit.start(), hit.end(), replacement)])


def _loop(model, context, declarations):
    p = model.part
    head = re.compile(rf'\bfor\s*\(\s*({IDENT})\s*=\s*0\s*;\s*\1\s*<\s*(\d+)\s*;\s*\)\s*{{')
    tail = re.compile(
        rf'(?m)^({INDENT})({IDENT})\s*=\s*({IDENT})\+\+\s*;\n'
        rf'\1({IDENT})\s*=\s*([^;\n]+);\n'
        rf'\1({ACCESS})\s*=\s*\4\s*;\n'
        rf'\1({IDENT}\s*=\s*[^;\n]+;)\n'
        rf'\1({ACCESS})\s*=\s*(0)\s*;\n'
        rf'\1({ACCESS})\s*=\s*({IDENT})\s*;\s*\Z')
    groups = {}
    macros = _macros(context)
    for loop in head.finditer(p.clean, p.opening+1, p.end):
        index, bound = loop.groups()
        loc = declarations.get(index)
        if not loc or scalar(loc['type'], context, 'mips') != (16, False) or not 1 <= int(bound) <= 65535:
            continue
        end = close(p.clean, loop.end()-1, '{', '}')
        if not end:
            continue
        body = p.clean[loop.end():end-1]
        hit = tail.search(body)
        if not hit:
            continue
        indent, old, step, value, expr, first, staged, second, zero, third, flag = hit.groups()
        if (index != step or not {old, value, flag}.issubset(declarations) or len({index, old, value, flag}) != 4
                or re.search(rf'&\s*\(*\s*{index}\b(?!\s*(?:->|\.|\[))',p.body)
                or scalar(declarations[old]['type'], context, 'mips') not in {(16,False),(32,False),(32,True)}
                or re.search(UNSAFE, body) or re.search(rf'(?<!\?)\b{IDENT}\s*:', body)
                or re.search(rf'\b{index}\b\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^-])?=(?!=))'
                             rf'|(?:\+\+|--|&)\s*\(*\s*{index}\b', body[:hit.start()])
                or '=' in expr or re.search(rf'\b{index}\b|\+\+|--', expr+' '+staged)
                or re.search(rf'(?<![.>])\b(?:{old}|{value})\b', expr+' '+staged)):
            continue
        if not staged.startswith(flag) or re.match(rf'{flag}\s*=', staged) is None:
            continue
        addresses = [re.sub(r'\s+', '', access).rsplit('.', 1) for access in (first, second, third)]
        if any(len(address) != 2 for address in addresses):
            continue
        root = addresses[0][0]
        if (any(address[0] != root for address in addresses) or root.count(f'[{old}]') != 1
                or re.search(rf'\b{index}\b', root) or len({address[1] for address in addresses}) != 3):
            continue
        types = [model.access(access) for access in (first, second, third)]
        array = model.roots.get(re.match(IDENT, root)[0])
        if (not array or array.pointer or not array.dims or not all(types)
                or scalar(declarations[value]['type'], context, 'mips') != (32, False)
                or not _macro_safe(body, macros, {index,old,value})
                or not _word_result(expr, model, context, macros)):
            continue
        if any(t.pointer or t.dims or scalar(t.type, context, 'mips') is None for t in types):
            continue
        # An ordinary temporary and assignment to an integer field allow the same
        # narrowing only when the first conversion cannot change the field value.
        field_width = scalar(types[0].type, context, 'mips')
        if field_width[1] or field_width[0] > 32:
            continue
        if re.search(rf'(?<![.>])\b(?:{old}|{value})\b', body[:hit.start()]):
            continue
        start = loop.end()+hit.start()
        stop = loop.end()+hit.start()+len(hit[0].rstrip())
        # Preserve the spelling of the staged read and of live expressions.
        expr_text = p.source[loop.end()+hit.start(5):loop.end()+hit.end(5)]
        staged_text = p.source[loop.end()+hit.start(7):loop.end()+hit.end(7)]
        groups.setdefault((index, old, value), []).append(
            (loop, start, stop, indent, first, second, third, expr_text, staged_text, zero, flag))
    for (index, old, value), loops in groups.items():
        if any(not _root_local(p, declarations[n].start()) for n in (index, old, value)):
            continue
        if any(not any(start <= ref.start() < stop for _,start,stop,*_ in loops)
               for decl in (declarations[old], declarations[value]) for ref in refs(p, decl)):
            continue
        temp = _fresh(context, 'offset')
        typ = declarations[index]['type']
        word = 'u32' if scalar('u32', context, 'mips') == (32, False) else 'unsigned int'
        changes = [(declarations[old].start(), declarations[old].end(), f'{word} {temp};')]
        d = declarations[value]
        old_line = p.clean.rfind('\n', 0, d.start())+1
        if not p.clean[old_line:d.start()].strip() and p.source[d.end():d.end()+1] == '\n':
            changes.append((old_line, d.end()+1, ''))
        else:
            changes.append((d.start(), d.end(), ''))
        def index_with(access, replacement, old=old):
            return re.sub(rf'\[\s*{old}\s*\]', f'[{replacement}]', access)

        for loop,start,stop,indent,first,second,third,expr,staged,zero,flag in loops:
            changes.extend([
                (loop.start(), loop.end(), f'for ({index} = 0; ({typ}){index} < {loop[2]}; {index}++) {{'),
                (start, stop, '\n'.join(indent+line for line in (
                    f'{index_with(first, index)} = {expr};', f'{temp} = {index};', staged,
                    f'{index_with(second, temp)} = {zero};', f'{index_with(third, temp)} = {flag};')))])
        yield edit(p.source, changes)


def _index(model, context, declarations):
    p = model.part
    pat = re.compile(rf'(?m)^({INDENT})({IDENT})\s*=\s*&({IDENT}->{IDENT})\[\s*({IDENT})\s*\]\s*;')
    macros = _macros(context)
    for hit in pat.finditer(p.clean, p.opening+1, p.end):
        _, pointer, field, index = hit.groups()
        base = field.split('->')[0]
        ptr = model.roots.get(pointer)
        val = model.access(f'{field}[{index}]')
        base_decl = model.roots.get(base)
        if (not ptr or not ptr.pointer or ptr.volatile or not val or val.volatile or val.type != ptr.type
                or scalar(ptr.type, context, 'mips') is None or not base_decl or not base_decl.pointer
                or base_decl.volatile or base_decl.declaration[0] <= p.opening or not _root_local(p, base_decl.declaration[0])
                or not declarations.get(index) or scalar(declarations[index]['type'], context, 'mips') not in
                {(8, False), (16, False), (32, False)}):
            continue
        d = re.match(r'\s*;', p.clean[ptr.declaration[1]:])
        if (not d or not _root_local(p, ptr.declaration[0]) or re.search(r'\bgoto\b', p.body)
                or p.clean[:hit.start()].rstrip()[-1:] not in ';{'):
            continue
        pointer_refs = [
            ref for ref in re.compile(rf'\b{pointer}\b').finditer(p.clean, p.opening+1, p.end)
            if not ptr.declaration[0] <= ref.start() < ptr.declaration[1] and not hit.start() <= ref.start() < hit.end()
            and not re.search(r'(?:->|\.)\s*$', p.clean[:ref.start()])]
        writes = []
        reads = []
        path = block_path(p, hit.start())
        for ref in pointer_refs:
            star = re.search(r'\*\s*$', p.clean[:ref.start()])
            ref_path = block_path(p, ref.start())
            if not star or ref.start() < hit.end() or not ref_path or ref_path[:len(path)] != path:
                break
            access = (star.start(), ref.end())
            before, after = p.clean[:star.start()], p.clean[ref.end():]
            if re.match(r'\s*=(?!=)', after) and not before[before.rfind('\n')+1:].strip() and ref_path == path:
                writes.append(access)
            elif (re.search(r'[,(]\s*$', before) and re.match(r'\s*[,)]', after)):
                reads.append(access)
            else:
                break
        else:
            if len(writes) != 1 or not reads or writes[0][0] > reads[0][0]:
                continue
            stop = max(b for _, b in reads)
            span = p.clean[hit.end():stop]
            if (re.search(BLOCK_ENTRY, span)
                    or re.search(rf'&\s*\(*\s*(?:{base}|{index})\b(?!\s*(?:->|\.|\[))', p.body)
                    or re.search(rf'(?<![.>])\b{base}\b(?!\s*->)', span)
                    or re.search(rf'\b{index}\b', p.clean[hit.end():writes[0][0]])
                    or not _macro_safe(span, macros, {base,index,pointer})):
                continue
            temp = _fresh(context, 'stored')
            kind = 'u32' if scalar('u32', context, 'mips') == (32, False) else 'unsigned int'
            yield edit(p.source, [
                (ptr.declaration[0], ptr.declaration[1], f'{kind} {temp}'),
                (hit.start(2), hit.end(), f'{temp} = {index};'),
                *((a,b,f'{field}[{index}]') for a,b in writes),
                *((a,b,f'{field}[{temp}]') for a,b in reads)])


def _stores(model, context, declarations):
    p = model.part
    pat = re.compile(
        rf'(?m)^({INDENT})({IDENT})\s*=\s*(\*\s*\(\s*volatile\s+({IDENT})\s*\*\s*\)\s*&({ACCESS}))\s*;\n'
        rf'\1({ACCESS})\s*=\s*0\s*;\n\1({ACCESS})\s*=\s*\2\s*;')
    # The layout with a live record index is the useful alternative. Other arms
    # intentionally keep their staged allocation and observable access order.
    for hit in pat.finditer(p.clean, p.opening+1, p.end):
        indent, temp, _, kind, load, zero, dest = hit.groups()
        z, d, src = [model.access(x) for x in (zero, dest, load)]
        if (not all((z, d, src)) or src.type != kind or src.volatile or not z.volatile or d.volatile
                or z.pointer or d.pointer or src.pointer or z.dims or d.dims or src.dims
                or zero.rsplit('.', 1)[0] != dest.rsplit('.', 1)[0] or zero == dest
                or not re.match(rf'{IDENT}->{IDENT}\[\s*{IDENT}\s*\]\[\s*{IDENT}\s*\]\.', dest)
                or temp not in declarations
                or scalar(d.type, context, 'mips') != (8, False)
                or scalar(declarations[temp]['type'], context, 'mips') != (8, False)):
            continue
        following = p.clean[hit.end():p.end].lstrip()
        if not following.startswith('}') or p.clean[:hit.start()].rstrip()[-1:] not in '{;':
            continue
        # Every other use must be after a new assignment to the staging local.
        # No jump can bypass those assignments.
        if re.search(r'\bgoto\b', p.body) or not _reassigned(p, declarations[temp], after=hit.end()):
            continue
        expression = p.source[hit.start(3):hit.end(3)]
        yield edit(p.source, [(hit.start(), hit.end(), f'{indent}{dest} = {expression};\n{indent}{zero} = 0;')])


def _reassigned(part, declaration, after):
    writes = {}
    for ref in refs(part, declaration):
        if ref.start() < after:
            continue
        path = tuple(block_path(part, ref.start()))
        if re.match(r'\s*=(?!=)', part.clean[ref.end():]):
            if part.clean[:ref.start()].rstrip()[-1:] not in '{;':
                return False
            writes[path] = ref.end()
        elif path not in writes or re.search(UNSAFE+r'|'+BLOCK_ENTRY, part.clean[writes[path]:ref.start()]):
            return False
    return True


def _counter(model, context, declarations, ordinary_stores):
    p = model.part
    pat = re.compile(rf'(?m)^({INDENT})({IDENT})\s*=\s*({IDENT})\s*\+\s*1\s*;')
    for hit in pat.finditer(p.clean, p.opening+1, p.end):
        indent, dest, snap = hit.groups()
        decl, value = declarations.get(snap), model.roots.get(dest)
        if (not decl or not _root_local(p, decl.start()) or not value or value.pointer or value.dims
                or value.declaration[1] >= p.opening
                or scalar(value.type, context, 'mips') != (8, False)
                or scalar(decl['type'], context, 'mips') != (8, False)):
            continue
        before = p.clean[p.opening+1:hit.start()]
        captured = list(re.finditer(rf'(?m)^({INDENT}){snap}\s*=\s*{dest}\s*;', before))
        if len(captured) != 1:
            continue
        start = p.opening+1+captured[0].end()
        if (block_path(p, start) != block_path(p, hit.start()) or re.search(r'\bgoto\b', p.body)
                or p.clean[:hit.start()].rstrip()[-1:] != ';'
                or re.search(UNSAFE+r'|'+BLOCK_ENTRY+r'|\b'+re.escape(snap)+r'\b', p.clean[start:hit.start()])):
            continue
        for width, kind in ((16, 'u16'), (8, 'u8')):
            if scalar(kind, context, 'mips') != (width, False):
                kind = 'unsigned short' if width == 16 else 'unsigned char'
            temp = _fresh(context, 'newIndex')
            changes = [_line_insertion(p.source, decl.start(), f'{kind} {temp};'),
                       (hit.start(), hit.end(), f'{indent}{temp} = {snap} + 1;\n{indent}{dest} = {temp};')]
            yield COUNTER, edit(p.source, changes)
            for a,b,replacement in ordinary_stores:
                if start < a < hit.start():
                    yield EXACT, edit(p.source, changes+[(a,b,replacement)])


def _ordinary_stores(model):
    p = model.part
    pat = re.compile(rf'(?m)^({INDENT})\(\s*\*\(\s*volatile\s+({IDENT})\s*\*\s*\)\s*&({ACCESS})\s*\)'
                     rf'(?=\s*=\s*{ACCESS}\s*;)')
    for hit in pat.finditer(p.clean, p.opening+1, p.end):
        indent, kind, field = hit.groups()
        value = model.access(field)
        if (value and not value.volatile and not value.pointer and not value.dims
                and value.type == kind and value.size == 4 and re.fullmatch(rf'{IDENT}->{IDENT}\[\s*{IDENT}\s*\]',field)):
            yield hit.start(), hit.end(), indent+field


def variants(source, name, header='', *, include_exact_only=False):
    if len(source)+len(header) > 128000:
        return []
    model = Records(source, name, header)
    if not model.part:
        return []
    context = header+'\n'+source
    decls = {d['name']: d for d in locals_for(model.part)}
    # This cast is an explicit observable access in the input. A caller must
    # route the diagnostic alternative through its exact-only judge.
    ordinary_stores = list(_ordinary_stores(model)) if include_exact_only else ()
    return ([(family, candidate) for family, propose in ((CASE,_case),(LOOP,_loop),(INDEX,_index),(STORES,_stores))
             for candidate in propose(model, context, decls)]
            +list(_counter(model, context, decls, ordinary_stores)))


def combine(source, first, second, family, name, header=''):
    """Reapply an independently measured repair and require the same disjoint line edits."""
    base, left, right = [s.splitlines(keepends=True) for s in (source, first, second)]
    if max(map(len, (base,left,right))) > 1200:
        return None
    changes = []
    for branch in (left, right):
        matched = SequenceMatcher(None, base, branch, autojunk=False)
        changes.extend((a,b,branch[c:d]) for tag,a,b,c,d in matched.get_opcodes() if tag != 'equal')
    ordered = sorted(changes)
    if any(b > c or a == c for (a,b,_),(c,_,_) in zip(ordered,ordered[1:])):
        return None
    current = base[:]
    for a,b,lines in reversed(ordered):
        current[a:b] = lines
    combined = ''.join(current)
    return next((child for label,child in variants(first,name,header) if label == family and child == combined),None)
