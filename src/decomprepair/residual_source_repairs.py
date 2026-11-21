"""Small C hypotheses for measured branch, allocation and frame residuals."""
import itertools
import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, split_args, view
from .pattern_repairs import close

ADDRESS, BRANCH, CALL, ENTRY, FRAME = (
    'residual_address_order', 'residual_zero_exit', 'residual_call_lifetime',
    'residual_entry_lifetimes', 'residual_frame_address',
)


def part_for(source, name, header):
    if len(source)+len(header) > 100000:
        return None
    part = view(source, name)
    if not part or re.search(r'\b(?:class|template|asm|__asm__|setjmp|longjmp)\b', part.clean):
        return None
    # Position-based rewrites must retain comments and preprocessor continuations.
    if re.search(r'^\s*#|/\*|//', source[part.opening+1:part.end], re.M):
        return None
    return part


def address_order(source, name, header):
    part = part_for(source, name, header)
    if not part:
        return []
    narrow = set(re.findall(r'\b(?:u8|u16|unsigned\s+(?:char|short))\s+('+IDENT+r')\s*;', part.body))
    pattern = rf'\(\s*({IDENT})\s*\+\s*\(\s*({IDENT})\s*\*\s*([248])\s*\)\s*\)'
    sites = [m for m in re.compile(pattern).finditer(part.clean, part.opening+1) if m.end() < part.end and m[2] in narrow]
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')\b',header+'\n'+source,re.M))
    sites = [m for m in sites if not {m[1],m[2],'u8','u16'} & macros]
    return [(ADDRESS, edit(source, [(m.start(), m.end(), f'({m[1]} - (-({m[2]} * {m[3]})))')]))
            for m in sites[:3]]


def zero_exit(source, name, header):
    part = part_for(source, name, header)
    if not part:
        return []
    pattern = (rf'if\s*\(\s*(?P<index>{IDENT})\s*!=\s*(?P<value>{NUMBER})\s*\)\s*'
               rf'\{{\s*return\s+0\s*;\s*\}}\s*(?P<flag>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}]+);\s*'
               rf'(?P<label>{IDENT})\s*:\s*return\s+[^;{{}}]+;\s*\}}')
    hit = re.search(pattern, part.clean[part.opening+1:part.end])
    if not hit:
        return []
    flag, idx, val = hit['flag'], hit['index'], hit['value']
    label = hit['label']
    if (len(re.findall(rf'\b(?:s32|u32|int|unsigned)\s+{flag}\s*;',part.body)) != 1
            or re.search(rf'&\s*{flag}\b|\b(?:volatile|static|extern)\b[^;{{}}]*\b{flag}\b',part.body)
            or re.search(rf'^\s*#\s*define\s+(?:{flag}|{idx})\b',header+'\n'+source,re.M)):
        return []
    # The shared return must normalize exactly the scalar written by either path.
    old = hit[0][hit.start('label')-hit.start():]
    if not re.fullmatch(rf'{label}\s*:\s*return\s*\(*\s*{flag}\s*\)*\s*\?\s*\(*\s*1\s*\)*\s*:\s*\(*\s*0\s*\)*\s*;\s*\}}', old):
        return []
    expr = source[part.opening+1+hit.start('expr'):part.opening+1+hit.end('expr')]
    begin = part.opening+1+hit.start()
    end = part.opening+1+hit.start('label')
    positive = f'if ({idx} == {val}) {{ {flag} = {expr}; }} else {{ {flag} = 0; }}\n'
    shared = f'if ({idx} != {val}) {{ {flag} = 0; goto {label}; }}\n{flag} = {expr};\n'
    return [(BRANCH, edit(source, [(begin,end,choice)])) for choice in (positive,shared)]


def call_lifetimes(source, name, header):
    part = part_for(source, name, header)
    if not part or '__repair_call_value' in source+header:
        return []
    # Hoist only the sole effectful argument of a simple call statement. Require
    # an explicit pointer-return declaration to preserve the original value type.
    result = []
    if re.search(r'\bvolatile\b', source+header):
        return []
    for outer in re.compile(rf'(?<=[;{{}}])\s*({IDENT})\s*\(').finditer(part.clean, part.opening+1, part.end):
        stop = close(part.clean, outer.end()-1)
        if not stop or not re.match(r'\s*;', part.clean[stop:]):
            continue
        args = part.clean[outer.end():stop-1]
        spans = split_args(args)
        for i, (a,b) in enumerate(spans):
            nested = re.fullmatch(rf'\s*({IDENT})\s*\(.+\)\s*', args[a:b], re.S)
            if not nested or not all(re.fullmatch(rf'\s*(?:{IDENT}|{NUMBER})\s*', args[c:d])
                                     for j,(c,d) in enumerate(spans) if j != i):
                continue
            types = set(re.findall(rf'\b({IDENT})\s*\*\s*{nested[1]}\s*\([^;{{}}]*\)\s*;',
                                   part.clean[:part.opening]+'\n'+header))
            if len(types) != 1:
                continue
            other_names = [args[c:d].strip() for j,(c,d) in enumerate(spans) if j != i
                           and re.fullmatch(IDENT,args[c:d].strip())]
            prefix = part.clean[:outer.start(1)]
            if any(re.search(rf'\b{arg}\b',nested[0]) or re.search(rf'&\s*{arg}\b',part.body)
                   or not (re.search(rf'\bextern\s+{IDENT}\s+{arg}\s*\[',prefix+'\n'+header)
                           or re.search(rf'\b{IDENT}\s*\*?\s*{arg}\s*(?:[,);\[])',
                                        prefix[find(source,name)[0]:])) for arg in other_names):
                continue
            start = outer.start(1)
            value = source[outer.end()+a:outer.end()+b].strip()
            end = stop+re.match(r'\s*;',part.clean[stop:]).end()
            result.append((CALL, edit(source, [
                (start,start,f'{{ {types.pop()} *__repair_call_value = {value};\n'),
                (outer.end()+a,outer.end()+b,' __repair_call_value'), (end,end,' }')
            ])))
            if len(result) == 3:
                return result
    return result


def entry_lifetimes(source, name, header):
    part = part_for(source, name, header)
    if not part or '__repair_entry_' in source+header:
        return []
    start = find(source, name)[0]
    signature = re.search(rf'\b{name}\s*\(([^()]*)\)\s*$', part.clean[start:part.opening])
    if not signature:
        return []
    pointers = [m.groups() for a,b in split_args(signature[1])
                if (m := re.fullmatch(rf'\s*({IDENT}\s*\*)\s*({IDENT})\s*',signature[1][a:b]))]
    if len(pointers) != 3:
        return []
    # Keep the state pointer in its existing storage. Two immutable incoming
    # pointers can use local carriers without rereading pointed-to data.
    pointers = pointers[1:]
    for _, ptr in pointers:
        if re.search(rf'(?:[.&]|->)\s*{ptr}\b|\b{ptr}\s*(?:[+\-*/]?=(?!=)|\+\+|--)|\b{IDENT}\s*\*\s*{ptr}\b', part.body):
            return []
    first = re.search(rf'(?<=[;{{}}])\s*{IDENT}\s*=\s*\*[^;]+;\s*(?={IDENT}\s*=)', part.clean[part.opening:part.end])
    if not first:
        return []
    at = part.opening+first.start()
    while source[at].isspace():
        at += 1
    result = []
    for order in itertools.permutations(pointers):
        names = {p:f'__repair_entry_{p}' for _,p in order}
        declarations = ''.join(f'{typ}{names[p]} = {p};\n' for typ,p in order)
        edits = [(m.start(),m.end(),names[m[0]]) for m in
                 re.compile(r'\b(?:'+'|'.join(names)+r')\b').finditer(part.clean, at, part.end)]
        if all(any(new==alias for _,_,new in edits) for alias in names.values()):
            result.append((ENTRY, edit(source, [(at,at,declarations),*edits])))
    return result


def frame_address(source, name, header):
    part = part_for(source, name, header)
    if not part:
        return []
    out = []
    declarations = re.compile(rf'(?<=[;{{}}])\s*(?P<type>{IDENT})\s*\*\s*(?P<local>{IDENT})\s*;')
    for decl in declarations.finditer(part.clean, part.opening, part.end):
        local = decl['local']
        pattern = (rf'\b{local}\s*=\s*(\(\s*{IDENT}\s*\*\s*\)\s*\(\s*'
                   rf'\(\s*(?:u8|char)\s*\*\s*\)\s*&\s*({IDENT})\s*\+\s*({IDENT})\s*\))\s*;')
        assignment = re.search(pattern, part.body)
        store = re.search(rf'(?<=;)\s*\*\s*{local}\s*=\s*({IDENT}\s*\([^;{{}}]+\))\s*;', part.body)
        if not assignment or not store or assignment.end() > store.start():
            continue
        offset = assignment[3]
        if len(re.findall(rf'\b(?:s32|u32|int|unsigned)\s+{offset}\s*;',part.body)) != 1:
            continue
        if (len(re.findall(rf'\b{local}\b', part.body)) != 3
                or re.search(rf'\b{offset}\s*(?:[-+*/]?=(?!=)|\+\+|--)|&\s*{offset}\b',part.body[assignment.end():store.end()])
                or re.search(rf'&\s*{offset}\b', part.body)
                or '__repair_frame_result' in source+header):
            continue
        typ = decl['type']
        call = re.match(IDENT, store[1])[0]
        if not re.search(rf'\b{typ}\s+{call}\s*\(',header+'\n'+part.clean[:part.opening]):
            continue
        start = part.opening+1
        addresses = [assignment[1]]
        terms = list(re.finditer(rf'\b{offset}\s*=\s*({IDENT})\s*\*\s*({NUMBER})\s*;',part.body[:assignment.start()]))
        if len(terms) == 1:
            root = terms[0][1]
            changed = rf'&\s*{root}\b|\b{root}\s*(?:[-+*/]?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{root}\b'
            if (len(re.findall(rf'\b(?:s32|u32|int|unsigned)\s+{root}\s*;',part.body)) == 1
                    and not re.search(changed,part.body[terms[0].end():store.end()])
                    and not re.search(rf'&\s*{root}\b',part.body)):
                addresses.insert(0,re.sub(rf'\b{offset}\b',f'({root} * {terms[0][2]})',assignment[1]))
        for address in addresses:
            out.append((FRAME, edit(source, [(decl.start(),decl.end(),''),
                (start+assignment.start(),start+assignment.end(),''),
                (start+store.start(),start+store.end(),
                 f'\n{{ {typ} __repair_frame_result = {store[1]}; *({address}) = __repair_frame_result; }}')])))
        if len(out) == 2:
            break
    return out


def buffer_preparation(source, name, header):
    """Share a global buffer address across adjacent formatting and notification calls."""
    part = part_for(source, name, header)
    local = '__repair_message_buffer'
    if not part or local in source+header:
        return []
    pattern = re.compile(
        rf'(?<=[;{{}}])\s*(?P<first>{IDENT})\s*\(\s*(?P<cast>\(\s*char\s*\*\s*\)\s*&\s*(?P<symbol>{IDENT}))'
        rf'[^;{{}}]*;\s*(?P<second>{IDENT})\s*\([^;{{}}]*?\b{IDENT}\b\s*,\s*(?P<address>&\s*(?P=symbol))\s*,'
    )
    out = []
    context = part.clean[:part.opening]+'\n'+header
    for hit in pattern.finditer(part.clean, part.opening+1, part.end):
        symbol = hit['symbol']
        if hit['first'] == hit['second'] or not re.search(rf'\bextern\s+{IDENT}\s+{symbol}\s*;',context):
            continue
        if re.search(rf'\b{IDENT}\s+{symbol}\b',part.body):
            continue
        second_end = close(part.clean,part.clean.find('(',hit.start('second')))
        semicolon = re.match(r'\s*;',part.clean[second_end:]) if second_end else None
        if not semicolon:
            continue
        end = second_end+semicolon.end()
        result = edit(source, [(hit.start('first'),hit.start('first'),
                                f'{{ char *{local} = (char *)&{symbol};\n'),
                               (*hit.span('cast'),local),
                               (*hit.span('address'),f'(__typeof__(&{symbol})){local}'),
                               (end,end,' }')])
        out.append(('residual_call_buffer', result))
        if len(out) == 2:
            break
    return out


def duplicate_call_setup(source, name, header):
    """Give equivalent assignment sequences two allocator paths using an initialized parameter."""
    part = part_for(source,name,header)
    if not part:
        return []
    signature = part.clean[find(source,name)[0]:part.opening]
    arg = re.search(rf'\(\s*(?:s32|u32|int|unsigned\s+int)\s+({IDENT})\s*[,)]',signature)
    if not arg:
        return []
    arg = arg[1]
    if re.search(rf'\b{arg}\s*(?:[-+*/]?=(?!=)|\+\+|--)|&\s*{arg}\b|\b{IDENT}\s+{arg}\s*;',part.body):
        return []
    pattern = (rf'\belse\s*\{{(?P<setup>(?:\s*{IDENT}\s*=(?!=)\s*[^;{{}}]+;){{2,5}})'
               rf'\s*(?=do\s*\{{\s*{IDENT}\s*\()')
    out = []
    for hit in re.compile(pattern).finditer(part.clean,part.opening+1,part.end):
        start,end = hit.span('setup')
        block = source[start:end]
        if not re.search(rf'=\s*{IDENT}\s*\(',block):
            continue
        out.append((CALL,edit(source,[(start,end,f'\nif ({arg}) {{{block}\n}} else {{{block}\n}}')])))
        if len(out) == 2:
            break
    return out


def forward_second_pointer(source, name, header, callee):
    """Make one evidenced forwarded pointer explicit in the candidate and its prototype."""
    part = part_for(source,name,header)
    if not part or not re.fullmatch(IDENT,callee):
        return []
    signature = part.clean[find(source,name)[0]:part.opening]
    args = re.search(r'\(([^()]*)\)\s*$',signature)
    params = split_args(args[1]) if args else []
    if len(params) < 2:
        return []
    a,b = params[1]
    arg = re.fullmatch(rf'\s*({IDENT})\s*\*\s*({IDENT})\s*',args[1][a:b])
    if not arg or re.search(rf'\b{callee}\b',header):
        return []
    typ, pointer = arg.groups()
    prototype = list(re.finditer(rf'\b(?:f32|float)\s+{callee}\s*\(\s*{IDENT}\s*\*\s*(?:{IDENT})?\s*(?P<end>\))\s*;',
                                 part.clean[:part.opening]))
    if len(prototype) != 1 or len(re.findall(rf'\b{callee}\b',part.body)) != 1:
        return []
    call = re.search(rf'\b{callee}\s*\(',part.body)
    if not call:
        return []
    at = part.opening+call.end()
    end = close(part.clean,at)
    if not end or len(split_args(part.clean[at+1:end-1])) != 1:
        return []
    declaration = prototype[0].start('end')
    return [(ENTRY, edit(source,[(declaration,declaration,f', {typ} *'),(end-1,end-1,f', {pointer}')]))]
