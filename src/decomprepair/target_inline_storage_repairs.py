"""Source candidates for measured inline, address, and storage differences."""

import math
import re
import struct

from .compiler_phase_repairs import fresh
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, split_args
from .operand_lifetime_repairs import _escaped, _in_scope, _visible
from .pattern_repairs import close
from .target_conversion_order_repairs import F32, SIGNED, UNSIGNED, _context, _local, _refs, _result
from .target_guard_width_repairs import BYTE, _fields
from .target_memory_repairs import WORD, _statement

SHORT = r'(?:s16|(?:signed\s+)?short(?:\s+int)?)'


def shared_signed_return(data, _evidence):
    part, _, _, header = data
    helper = re.compile(rf'\bstatic\s+(?:inline|__inline__)\s+{SIGNED}\s+(?P<fn>{IDENT})\s*\([^{{}};]*\)\s*{{')
    for hit in helper.finditer(part.clean,0,part.opening):
        end = close(part.clean,hit.end()-1,'{','}')
        if not end or end>=part.opening:
            continue
        callee = hit['fn']
        # A local inline helper can change return spelling only when every
        # visible call already observes the signed halfword result.
        context = _blank(header)+'\n'+part.clean[:hit.start()]+'\n'+part.clean[end:]
        if not re.search(rf'\(\s*{SHORT}\s*\)\s*{callee}\s*\(',part.body):
            continue
        if re.search(rf'\b{callee}\b',re.sub(rf'\(\s*{SHORT}\s*\)\s*{callee}\s*\(','(',context)):
            continue
        body = part.clean[hit.end():end-1]
        fail = list(re.finditer(r'\bif\s*\([^;{}]+\)\s*(?:{\s*)?(?P<value>return\s+0\s*;)\s*(?:})?',body))
        final = re.search(rf'\breturn\s+(?P<value>{IDENT}|{NUMBER})\s*;\s*$',body)
        if len(fail)<2 or not final or body[:final.start()].count('{')!=body[:final.start()].count('}') or len(re.findall(r'\breturn\b',body))!=len(fail)+1:
            continue
        if re.search(r'\b(?:goto|switch|do|while|for)\b|(?:^|[;{}])\s*\w+\s*:',body):
            continue
        local = fresh(part.source,header,'repair_status')
        label = fresh(part.source,header,'repair_return')
        changes = [(hit.end(),hit.end(),f' int {local}; ')]
        changes.extend((hit.end()+m.start('value'),hit.end()+m.end('value'),
                        f'{{ {local} = 0; goto {label}; }}') for m in fail)
        changes.append((hit.end()+final.start(),hit.end()+final.end(),
                        f'{local} = {final["value"]}; {label}: return (short){local}; '))
        return _result('inline_shared_signed_halfword_return',part,changes)
    return []


def split_byte_address(data, _evidence):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<stmt>return\s+|{IDENT}\s*=\s*)\*\s*\(\s*(?P<base>{IDENT})\s*\+\s*'
                         rf'(?P<offset>\(?\s*(?P<index>{IDENT})\s*(?:\*|<<)\s*{NUMBER}\s*\)?)\s*\)\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        base = hit['base']
        types = re.findall(rf'\b((?:const\s+)?{BYTE}|(?:const\s+)?(?:signed\s+)?char)\s*\*\s*{base}\s*(?=[,);])',
                           part.clean[:hit.start()])
        if (len(types)!=1 or not _statement(part,hit.start()) or not _local(data,hit['index'],WORD,hit.start())
                or hit['offset'].count('(')!=hit['offset'].count(')') or _escaped(part.body,base)):
            continue
        name = fresh(part.source,header,'repair_byte_address')
        return _result('split_indexed_byte_address',part,[(hit.start(),hit.end(),
            f'{{ {types[0]} *{name} = {base}; {name} += {hit["offset"]}; {hit["stmt"]}*{name}; }}')])
    return []


def reuse_dead_float(data, callees):
    part, _, declarations, _ = data
    assign = re.compile(rf'(?P<dst>{IDENT})\s*=\s*(?P<expr>[^;{{}}]+);')
    hits = [m for m in assign.finditer(part.clean,part.opening+1,part.end-1) if _statement(part,m.start())]
    for index,late in enumerate(hits):
        dst = late['dst']
        if not _local(data,dst,F32,late.start()) or declarations[dst][0][1]==part.opening or _refs(late['expr'],dst):
            continue
        suffix = part.clean[late.end():part.end-1]
        call = re.match(rf'\s*(?:{IDENT}\s*=\s*)?(?P<callee>{IDENT})\s*\([^;{{}}]*\)\s*;',suffix)
        if not call or call['callee'] not in callees or _refs(call[0],dst) or not _refs(suffix[call.end():],dst):
            continue
        candidates = []
        for earlier in reversed(hits[:index]):
            old = earlier['dst']
            middle = part.clean[earlier.end():late.start()]
            if (old==dst or _refs(suffix,old) or _refs(late['expr'],old)
                    or not _local(data,old,F32,earlier.start()) or not _local(data,old,F32,late.start())
                    or declarations[old][0][1]==part.opening or not _refs(middle,old) or _refs(middle,dst)
                    or re.search(r'[{}:]|\b(?:if|switch|for|do|while|goto|return)\b',middle)
                    or re.search(rf'\b{F32}\s+(?:\w+\s*,\s*)*{dst}\b',suffix)):
                continue
            uses = re.finditer(rf'\b{dst}\b',suffix)
            changes = [(*late.span('dst'),old)]
            changes.extend((late.end()+m.start(),late.end()+m.end(),old) for m in uses
                           if not re.search(r'(?:->|\.)\s*$',suffix[:m.start()]))
            candidates.extend(_result('reuse_dead_float_across_call',part,changes))
            if len(candidates)==2:
                break
        if candidates:
            return candidates
    return []


def unsigned_byte_entry(data, _evidence):
    part, _, _, _ = data
    shape = re.compile(rf'(?P<i>{IDENT})\s*=\s*0\s*;\s*if\s*\(\s*(?P<test>!?\s*(?P<count>{IDENT})(?:\s*==\s*0)?)'
                       rf'\s*\)\s*(?:{{\s*)?return(?:\s+[^;{{}}]+)?\s*;\s*(?:}}\s*)?')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        count,index = hit['count'],hit['i']
        if (count==index or not _statement(part,hit.start()) or not _local(data,index,SIGNED,hit.start())
                or not re.fullmatch(rf'!\s*{count}|{count}\s*==\s*0',hit['test'])):
            continue
        declaration = re.search(rf'\b{BYTE}\s+{count}\s*(?=[=,;)])',part.clean[:hit.start()])
        if (not declaration or _escaped(part.body,count)
                or len(re.findall(rf'\b(?:{BYTE}|{WORD})\s+\**\s*{count}\b',part.clean[:part.end]))!=1
                or not re.search(rf'\b(?:for|do|while)\b[^{{}};]*|\b{index}\s*\+\+',part.clean[hit.end():part.end])):
            continue
        if declaration.start()>part.opening and not _in_scope(part,declaration.start(),hit.start()):
            continue
        return _result('zero_index_unsigned_byte_entry',part,[(*hit.span('test'),f'{index} >= {count}')])
    return []


def coordinate_blocks(data, _evidence):
    part, _, _, _ = data
    expr = re.compile(rf'(?P<dst>{IDENT})\s*=\s*(?P<a>{IDENT})->(?P<x>{IDENT})\s*-\s*(?P<b>{IDENT})->(?P<y>{IDENT})\s*;')
    items = list(expr.finditer(part.clean,part.opening+1,part.end-1))
    for a,b,c in zip(items,items[1:],items[2:]):
        group = (a,b,c)
        if (not _statement(part,a.start()) or any(part.clean[x.end():y.start()].strip() for x,y in ((a,b),(b,c)))
                or len({m['dst'] for m in group})!=3 or len({(m['a'],m['b']) for m in group})!=1
                or not all(_local(data,m['dst'],F32,m.start()) for m in group)
                or not all(_fields(data,a[side],[(m[field],F32) for m in group])
                           for side,field in (('a','x'),('b','y')))):
            continue
        return _result('coordinate_difference_scopes',part,[
            (m.start(),m.end(),'do { '+part.source[m.start():m.end()]+' } while (0);') for m in group
        ])
    return []


def pointer_volatile(source,name,header,symbols):
    visible = _visible(source,name,header)
    if not visible:
        return []
    part,context = visible
    for symbol in sorted(symbols):
        declarations = list(re.finditer(rf'\bextern\s+(?P<type>(?:const\s+)?(?:struct\s+)?{IDENT})\s*\*\s*{symbol}\s*;',
                                       part.clean[:part.opening]))
        if (len(declarations)!=1 or _refs(header,symbol) or
                re.search(rf'^\s*#\s*define\s+{symbol}\b',context,re.M)):
            continue
        decl = declarations[0]
        base = decl['type']
        loaded = re.compile(rf'\*\s*\(\s*{re.escape(base)}\s*\*\s*volatile\s*\*\s*\)\s*&\s*{symbol}\b')
        sites = list(loaded.finditer(part.clean,part.opening+1,part.end-1))
        other = part.clean[:decl.start()]+part.clean[decl.end():part.opening]+part.clean[part.end:]
        if (len(sites)<2 or _refs(loaded.sub('',part.body),symbol) or _refs(other,symbol)
                or any(re.match(r'\s*(?:=(?!=)|[+*/%&|^<>-]=|\+\+|--)',part.clean[m.end():]) for m in sites)):
            continue
        # Every earlier access was already volatile and used a pointer to
        # the same pointee type. Keep pointee qualifiers and the access count.
        pos = part.clean.index(symbol,decl.end('type'),decl.end())
        changes = [(pos,pos,'volatile '),*((m.start(),m.end(),symbol) for m in sites)]
        return [('direct_volatile_pointer_object',edit(source,changes))]
    return []


def narrow_arm_calls(data, profiles):
    part, _, _, header = data
    pattern = re.compile(r'if\s*\([^;{}]+\)\s*{(?P<a>[^{}]+)}\s*else\s*{(?P<b>[^{}]+)}')
    narrow = r'(?:u8|u16|unsigned\s+(?:char|short))'
    setup = re.compile(rf'\s*(?P<dst>{IDENT})\s*=\s*\(\s*(?P<type>{narrow})\s*\)\s*(?P<value>{IDENT})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        arms = [setup.match(hit[k]) for k in ('a','b')]
        if not all(arms) or arms[0].groups()!=arms[1].groups() or not _statement(part,hit.start()):
            continue
        dst,typ,value = arms[0].groups()
        if dst==value or not all(_local(data,v,WORD,hit.start()) for v in (dst,value)) or _refs(part.clean[hit.end():part.end],dst):
            continue
        width = 8 if typ in {'u8','unsigned char'} else 16
        callees = profiles.get(width,set())
        changes = []
        sequences = []
        for key,arm in zip(('a','b'),arms):
            tail = hit[key][arm.end():]
            offset = hit.start(key)+arm.end()
            called = list(re.finditer(rf'\s*(?P<fn>{IDENT})\s*\((?P<args>[^();{{}}]*)\)\s*;',tail))
            if len(called)<2 or ''.join(m[0] for m in called).strip()!=tail.strip():
                break
            sequence = []
            edits = [(hit.start(key)+arm.start(),offset,'')]
            for m in called:
                fn = m['fn']
                types = re.findall(rf'\b{fn}\s*\(([^();{{}}]*)\)\s*;',header+'\n'+part.clean[:part.opening])
                if len(set(types))!=1:
                    break
                args = split_args(m['args'])
                formal = types[0].split(',')
                matches = [(i,a,b) for i,(a,b) in enumerate(args) if m['args'][a:b].strip()==dst]
                if len(matches)!=1 or len(args)!=len(formal) or len(re.findall(rf'\b{dst}\b',m['args']))!=1:
                    break
                position,a,b = matches[0]
                if (fn,position) not in callees or not re.fullmatch(rf'\s*{typ}(?:\s+{IDENT})?\s*',formal[position]):
                    break
                start = offset+m.start('args')
                edits.append((start+a,start+b,f' ({typ}){value}'))
                sequence.append((fn,position))
            if len(sequence)!=len(called):
                break
            changes.extend(edits)
            sequences.append(sequence)
        if len(sequences)==2 and sequences[0]==sequences[1]:
            return _result('narrow_index_at_calls_in_both_arms',part,changes)
    return []


def missing_noop_case(data, values):
    part, _, _, _ = data
    for switch in re.finditer(rf'\bswitch\s*\(\s*{IDENT}\s*\)\s*{{',part.clean[part.opening+1:part.end-1]):
        opening = part.opening+switch.end()
        end = close(part.clean,opening,'{','}')
        if not end:
            continue
        body = part.clean[opening+1:end-1]
        if re.search(r'\bswitch\b',body):
            continue
        default = re.search(r'\bdefault\s*:\s*break\s*;',body)
        cases = {integer(m[1]) for m in re.finditer(rf'\bcase\s+({NUMBER})\s*:',body)}
        if not default or len(cases)>5:
            continue
        for value in sorted(values-cases):
            if value+1 not in cases or value+2 not in cases:
                continue
            pos = opening+1+default.start()
            return _result('explicit_noop_switch_case',part,[(pos,pos,f'case {value}: ')])
    return []


def multiply_constant(data, values):
    part, _, _, header = data
    for value in sorted(values):
        matches = []
        for m in re.finditer(rf'\b(?P<x>{IDENT})\s*\*\s*(?P<const>{NUMBER})\b',part.clean[part.opening+1:part.end-1]):
            absolute = part.opening+1+m.start()
            if (integer(m['const'])==value and not re.search('[lL]',m['const'])
                    and _local(data,m['x'],WORD,absolute)):
                before = part.clean[part.opening+1:absolute].rsplit(';',1)[-1]
                if re.search(r'\b(?:case|sizeof|_Static_assert)\b|\[',before):
                    continue
                matches.append(m)
        if len(matches)<3 or len({m['const'] for m in matches})!=1:
            continue
        name = fresh(part.source,header,'repair_multiplier')
        spelling = matches[0]['const']
        typ = 'unsigned int' if spelling.lower().endswith('u') else 'int'
        return _result('shared_literal_multiplier',part,[
            (part.opening+1,part.opening+1,f' {typ} {name} = {spelling}; '),
            *((part.opening+1+m.start('const'),part.opening+1+m.end('const'),name) for m in matches),
        ])
    return []


def float_bits(data, values):
    part, _, _, _ = data
    shape = re.compile(rf'\*\s*\(\s*{UNSIGNED}\s*\*\s*\)\s*&\s*(?P<p>{IDENT})->(?P<f>{IDENT})\s*=\s*(?P<bits>{NUMBER})\s*;')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        bits = integer(hit['bits'])
        if (bits not in values or not _statement(part,hit.start()) or not _fields(data,hit['p'],[(hit['f'],F32)])):
            continue
        raw = bits.to_bytes(4,'big')
        value = struct.unpack('>f',raw)[0]
        if not math.isfinite(value):
            continue
        literal = format(value,'.9g')
        if '.' not in literal and 'e' not in literal:
            literal += '.0'
        if struct.pack('>f',float(literal))!=raw:
            continue
        return _result('typed_float_literal_store',part,[(hit.start(),hit.end(),f'{hit["p"]}->{hit["f"]} = {literal}f;')])
    return []


def variants(source,name,header,evidence):
    if not evidence:
        return []
    data = _context(source,name,header)
    out = []
    for rewrite,signature in evidence:
        if rewrite is pointer_volatile:
            out.extend(rewrite(source,name,header,signature))
        elif data:
            out.extend(rewrite(data,signature))
    return out
