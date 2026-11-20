"""Preserve call argument positions and split specific computed lifetimes."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .csource import _blank, find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer, split_args, view
from .pattern_repairs import close

FLOAT_ARGUMENTS = 'float_argument_evaluation_order'
DIVIDE_SQUARE = 'in_place_float_divide_square'
FINAL_OFFSET = 'final_indexed_store_offset'
FLOAT = r'(?:f32|float|f64|double)'
F32 = {'float','f32'}


def _visible(source, name, header):
    part = view(source,name)
    if not part:
        return None
    context = _blank(header)+'\n'+part.clean
    if re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#\s*include\b',context,re.M):
        return None
    return part, context


def _typed_locals(part, types):
    result = {}
    for decl in re.finditer(rf'\b({types})\s+({IDENT}(?:\s*,\s*{IDENT})*)\s*;',part.body):
        offset = part.opening+1+decl.start()
        if part.clean[part.opening+1:offset].rstrip()[-1:] not in ('',';','{','}'):
            continue
        for name in re.findall(IDENT,decl[2]):
            # Only one visible declaration with this spelling. Reject pointers
            # as well as a scalar shadow in a nested scope.
            count = len(re.findall(rf'\b(?:{types}|void|char|int|float|double)\s+\**\s*'
                                   rf'{name}(?=\s*[,;=\[)])',part.body))
            if count <= 1 and name not in result:
                result[name] = (decl[1],offset)
            else:
                result.pop(name,None)
    return result


def _escaped(text, name):
    return re.search(rf'(?<!&)&(?!&)\s*\(*\s*{name}\b',text)


def _plain_expression(text, context):
    if re.search(r'[=?;{},]|\b(?:volatile|sizeof|typeof)\b|\+\+|--|\b\w+\s*\(',text):
        return False
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+')',context,re.M))
    return not macros.intersection(re.findall(IDENT,text))


def _in_scope(part, declaration, position):
    path = block_path(part,declaration)
    return declaration < position and path==block_path(part,position)[:len(path)]


def float_argument_order(source, name, header, calls):
    data = _visible(source,name,header)
    if not data:
        return []
    part, context = data
    if re.search(r'\bvolatile\b',context):
        return []
    types = _typed_locals(part,FLOAT)
    result = []
    for callee, positions in sorted(calls):
        for call in re.compile(rf'(?<![.>\w]){callee}\s*\(').finditer(part.clean,part.opening+1,part.end-1):
            end = close(part.clean,call.end()-1)
            if not end:
                continue
            args = [(a+call.end(),b+call.end()) for a,b in split_args(part.clean[call.end():end-1])]
            if max(positions)>=len(args):
                continue
            x,y = (part.clean[a:b].strip() for a,b in (args[i] for i in positions))
            if x in types and y in types and x!=y and {types[x][0],types[y][0]} <= F32:
                # Two adjacent assignments may already stage the arguments.
                # Swap evaluation only. The ABI positions stay as written.
                ordered = rf'(?P<one>{x}\s*=(?!=)\s*[^;{{}}]+;)\s*(?P<two>{y}\s*=(?!=)\s*[^;{{}}]+;)'
                pattern = re.compile(ordered)
                second_order = re.compile(rf'(?P<one>{y}\s*=(?!=)\s*[^;{{}}]+;)\s*(?P<two>{x}\s*=(?!=)\s*[^;{{}}]+;)')
                options = [*pattern.finditer(part.clean,max(part.opening+1,call.start()-500),call.start()),
                           *second_order.finditer(part.clean,max(part.opening+1,call.start()-500),call.start())]
                if options:
                    pair = max(options,key=lambda match:match.start())
                    first,second = (pair[g].split('=',1) for g in ('one','two'))
                    lhs,rhs = first[0].strip(),second[0].strip()
                    between = part.clean[pair.end():call.start()]
                    if (block_path(part,pair.start())==block_path(part,call.start())
                            and part.clean[part.opening+1:pair.start()].rstrip()[-1:] in ('',';','{','}')
                            and all(_in_scope(part,types[v][1],pair.start()) and not _escaped(part.body,v) for v in (x,y))
                            and _plain_expression(first[1][:-1],context) and _plain_expression(second[1][:-1],context)
                            and not re.search(rf'\b{lhs}\b',second[1]) and not re.search(rf'\b{rhs}\b',first[1])
                            and not re.search(rf'[{{}}:]|\b(?:{x}|{y})\b',between)):
                        new = edit(source,[(*pair.span('one'),source[slice(*pair.span('two'))]),
                                           (*pair.span('two'),source[slice(*pair.span('one'))])])
                        if new not in [s for _,s in result]:
                            result.append((FLOAT_ARGUMENTS,new))
                            if len(result)>=4:
                                return result
                        continue
            # Stage two computed arguments only with an explicit float
            # prototype, a standalone call, and side-effect-free operands.
            if part.clean[part.opening+1:call.start()].rstrip()[-1:] not in ('',';','{','}'):
                continue
            following = re.match(r'\s*;',part.clean[end:])
            if not following:
                continue
            prototypes = re.findall(rf'\b{callee}\s*\(([^();{{}}]+)\)\s*;',
                                    _blank(header)+'\n'+part.clean[:find(source,name)[0]])
            if len(set(prototypes))!=1:
                continue
            prototype = [prototypes[0][a:b].strip() for a,b in split_args(prototypes[0])]
            if len(prototype)!=len(args) or any(not re.fullmatch(rf'(?:f32|float)(?:\s+{IDENT})?',prototype[i]) for i in positions):
                continue
            if not all(_plain_expression(part.clean[a:b],context) for a,b in args):
                continue
            if not all(re.search(r'[+*/-]', e) for e in (x,y)):
                continue
            names = [fresh(source,header,f'repair_arg_{i}') for i in positions]
            changes = [(*args[i],f' {n}') for i,n in zip(positions,names)]
            decls = [f'float {n} = {e};' for n,e in zip(names,(x,y))]
            stop = end+following.end()
            for order in (decls,decls[::-1]):
                result.append((FLOAT_ARGUMENTS,edit(source,[
                    (call.start(),call.start(),'{ '+' '.join(order)+' '),(stop,stop,' }'),*changes])))
            if len(result)>=4:
                return result[:4]
    return result


def divide_square(source, name, header, widths):
    data = _visible(source,name,header)
    if not data:
        return []
    part, context = data
    if re.search(r'\bvolatile\b',context):
        return []
    types = _typed_locals(part,FLOAT)
    pattern = re.compile(rf'(?P<quot>{IDENT})\s*=(?!=)\s*(?P<num>{IDENT})\s*/\s*'
                         rf'(?P<den>{IDENT}|\(\s*{IDENT}\s*[-+]\s*{IDENT}\s*\))\s*;')
    out = []
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        q,x = hit['quot'],hit['num']
        if not all(v in types and not _escaped(part.body,v) and _in_scope(part,types[v][1],hit.start()) for v in (q,x)):
            continue
        if q==x or types[q][0]!=types[x][0] or ('s' if types[x][0] in F32 else 'd') not in widths:
            continue
        if not _plain_expression(hit['den'],context) or part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('',';','{','}'):
            continue
        if re.search(rf'\b{x}\b',part.clean[hit.end():part.end]) or re.search(rf'\b{q}\b',hit['den']):
            continue
        den_names = set(re.findall(IDENT,hit['den']))
        if any(v not in types or types[v][0]!=types[x][0] or not _in_scope(part,types[v][1],hit.start()) for v in den_names):
            continue
        before = part.clean[part.opening+1:hit.start()]
        labels = set(re.findall(r'(?:^|[;{}])\s*('+IDENT+r')\s*:',before))
        if labels.intersection(re.findall(r'\bgoto\s+('+IDENT+r')\s*;',part.clean[hit.end():part.end])):
            continue
        tail = part.clean[hit.end():part.end]
        statement = re.match(r'\s*[^;{}]+;',tail)
        squares = list(re.finditer(rf'\b{q}\s*\*\s*{q}\b',statement[0])) if statement else []
        if (len(squares)!=1 or len(re.findall(rf'\b{q}\b',tail))!=2
                or re.search(r'\?|&&|\|\||\b(?:if|while|for|switch)\s*\(',statement[0])):
            continue
        square = squares[0]
        out.append((DIVIDE_SQUARE,edit(source,[
            (hit.start(),hit.end(),f"{x} /= {hit['den']}; {x} *= {x};"),
            (hit.end()+square.start(),hit.end()+square.end(),x),
        ])))
        if len(out)==2:
            break
    return out


def final_offset(source, name, header, strides):
    data = _visible(source,name,header)
    if not data:
        return []
    part, context = data
    types = _typed_locals(part,INTEGER)
    initialize = re.compile(rf'(?P<offset>{IDENT})\s*=(?!=)\s*(?P<index>{IDENT})\s*\*\s*(?P<stride>{NUMBER})\s*;')
    out = []
    for hit in initialize.finditer(part.clean,part.opening+1,part.end-1):
        offset = hit['offset']
        if integer(hit['stride']) not in strides or offset==hit['index'] or offset not in types:
            continue
        if not _in_scope(part,types[offset][1],hit.start()) or _escaped(part.body,offset):
            continue
        if not re.search(rf'\b{offset}\b',part.clean[part.opening+1:hit.start()]):
            continue
        if not _plain_expression(hit[0].split('=',1)[1][:-1],context):
            continue
        store = re.compile(rf'\s*\*\s*\([^;{{}}=]+\*+\s*\)\s*\([^;{{}}=]*\+\s*{offset}\s*\)\s*'
                           r'=(?!=)\s*[^;{}]+;')
        end = hit.end()
        count = 0
        while (following := store.match(part.clean,end,part.end-1)) and count<8:
            end = following.end()
            count += 1
        tail = part.clean[end:part.end]
        if count<3 or re.search(rf'\b{offset}\b',tail):
            continue
        labels = set(re.findall(r'(?:^|[;{}])\s*('+IDENT+r')\s*:',part.body[:hit.start()-part.opening-1]))
        if labels.intersection(re.findall(r'\bgoto\s+('+IDENT+r')\s*;',tail)):
            continue
        if re.search(rf'#\s*define\s+[^\n]*\b{offset}\b',context):
            continue
        if part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('',';','{','}',':'):
            continue
        temp = fresh(source,header,'repair_insert_offset')
        region = re.sub(rf'\b{offset}\b',temp,source[hit.start():end])
        out.append((FINAL_OFFSET, edit(source,[(hit.start(),end,'{ '+types[offset][0]+' '+region+' }')])))
        if len(out)==2:
            break
    return out
