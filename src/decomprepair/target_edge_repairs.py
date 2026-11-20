"""Bounded C repairs for measured MIPS control, memory, and register differences."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, integer
from .operand_lifetime_repairs import _visible
from .pattern_repairs import close
from .target_conversion_order_repairs import F32, F64, SIGNED, UNSIGNED, _context, _local, _refs, _result
from .target_memory_repairs import WORD, _statement

HALF = r'(?:u16|unsigned\s+short(?:\s+int)?)'
FIELD = rf'{IDENT}\s*->\s*{IDENT}'


def increment_edge(data, _evidence):
    part, _, _, header = data
    loop_head = re.compile(rf'\bfor\s*\([^;{{}}]*;\s*(?P<i>{IDENT})\s*(?:<|!=)\s*(?:{IDENT}|{NUMBER})\s*;'
                           rf'\s*(?P<step>(?P=i)\s*(?:\+\+|\+=\s*1))\s*\)\s*{{')
    for loop in loop_head.finditer(part.clean,part.opening+1,part.end-1):
        opening = loop.end()-1
        end = close(part.clean,opening,'{','}')
        if not end or not _local(data,loop['i'],WORD,loop.start()):
            continue
        body = part.clean[opening+1:end-1]
        arms = list(re.finditer(r'\bif\s*\([^;{}]+\)\s*{\s*(?P<edge>continue\s*;)\s*}',body))
        if len(arms)!=1 or re.search(r'\b(?:for|while|do|goto|continue)\b',body[:arms[0].start()] + body[arms[0].end():]):
            continue
        start = opening+1+arms[0].start()
        prefix = part.clean[opening+1:start].rstrip()
        if not _statement(part,start) and not re.search(r'\bcase\s+[\w+-]+\s*:$',prefix):
            continue
        arm = arms[0]
        label = fresh(part.source,header,'repair_check_next')
        return _result('continue_edge_increment',part,[
            (*loop.span('step'),''),
            (opening+1+arm.start('edge'),opening+1+arm.end('edge'),f'{loop["step"]}; goto {label};'),
            (end-1,end-1,f' {loop["step"]}; {label}: ; '),
        ])
    # Some drafts already have the shared increment label in a do-loop.
    shared = re.compile(rf'if\s*\([^;{{}}]+\)\s*{{\s*(?P<jump>goto\s+(?P<label>{IDENT})\s*;)\s*}}')
    for guard in shared.finditer(part.clean,part.opening+1,part.end-1):
        path = block_path(part,guard.start())
        if len(path)<2 or not re.search(r'\bdo\s*$',part.clean[:path[-1]]):
            continue
        end = close(part.clean,path[-1],'{','}')
        step = re.search(rf'\b{guard["label"]}\s*:\s*(?P<step>(?P<i>{IDENT})\s*(?:\+\+|\+=\s*1)\s*;)\s*$',
                         part.clean[guard.end():end-1]) if end else None
        tail = re.match(rf'\s*while\s*\(\s*{step["i"]}\s*(?:<|!=)',part.clean[end:]) if step else None
        if not tail or not _local(data,step['i'],WORD,guard.start()):
            continue
        if block_path(part,guard.end()+step.start())!=path:
            continue
        label = fresh(part.source,header,'repair_check_next')
        return _result('continue_edge_increment',part,[
            (*guard.span('jump'),f'{step["step"]} goto {label};'),
            (end-1,end-1,f' {label}: ; '),
        ])
    return []


def float_call_reuse(data, pairs):
    part, params, _, header = data
    pattern = re.compile(rf'(?P<first>(?P<copy>{IDENT})\s*=\s*(?P<callee>{IDENT})\s*\(\s*(?P<arg>{IDENT})\s*\)\s*;)'
                         rf'(?P<gap>\s*(?:{IDENT}\s*=\s*)?(?P<second>{IDENT})\s*\([^;{{}}]*\)\s*;)'
                         rf'\s*(?P<reuse>(?P=arg)\s*=\s*(?P=copy)\s*;)')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        arg,copy = hit['arg'],hit['copy']
        if ((hit['callee'],hit['second']) not in pairs or arg==copy or not _statement(part,hit.start())
                or arg not in {p[2] for p in params if p and re.fullmatch(F32,p[1])}
                or not all(_local(data,v,F32,hit.start()) for v in (arg,copy))
                or _refs(hit['gap'],arg)
                or not all(re.search(rf'\b{F32}\s+{callee}\s*\(',header+'\n'+part.clean[:part.opening])
                           for callee in (hit['callee'],hit['second']))):
            continue
        return _result('float_call_result_parameter_reuse',part,[
            (*hit.span('first'),f'{arg} = {hit["callee"]}({arg}); {copy} = {arg};'),
            (*hit.span('reuse'),''),
        ])
    return []


def narrow_multiply(data, _evidence):
    part, _, _, header = data
    shape = re.compile(rf'(?P<setup>(?P<out>{IDENT})\s*=\s*(?P<field>{FIELD})\s*;)\s*'
                       rf'(?P=out)\s*=\s*(?P<other>{IDENT})\s*\*\s*(?P=out)\s*;')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        base, member = re.findall(IDENT,hit['field'])
        record = re.search(rf'\bstruct\s+({IDENT})\s*\*\s*{base}\s*[,)]',part.clean[:part.opening])
        if not record or hit['out']==hit['other'] or not _statement(part,hit.start()) or not all(
            _local(data,hit[k],WORD,hit.start()) for k in ('out','other')
        ):
            continue
        fields = re.search(rf'\bstruct\s+{record[1]}\s*{{([^{{}}]+)}}',header+'\n'+part.clean[:part.opening])
        if not fields or not re.search(rf'(?:^|;)\s*{HALF}\s+{member}\s*;',fields[1]):
            continue
        if not _local(data,hit['out'],SIGNED,hit.start()):
            continue  # Preserve the original integer promotions.
        local = fresh(part.source,header,'repair_scale')
        return _result('narrow_multiply_operand',part,[(hit.start(),hit.end(),
            f'{{ unsigned short {local} = {hit["field"]}; {hit["out"]} = {hit["other"]} * {local}; }}')])
    return []


def duplicate_bias(data, _evidence):
    part, _, _, _ = data
    pattern = re.compile(rf'(?P<dst>{IDENT})\s*=\s*\(\s*{F64}\s*\)\s*(?P<input>{IDENT})\s*;'
                         rf'\s*if\s*\(\s*\(\s*{SIGNED}\s*\)\s*(?P=input)\s*<\s*0\s*\)'
                         rf'\s*{{\s*(?P=dst)\s*\+=\s*(?:4294967296(?:\.0+)?|0x1p32)\s*;\s*}}')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if (_statement(part,hit.start()) and _local(data,hit['input'],UNSIGNED,hit.start())
                and _local(data,hit['dst'],F64,hit.start())):
            return _result('remove_duplicate_unsigned_double_bias',part,[
                (hit.start('input'),hit.start('input'),'(int)')
            ])
    return []


def packed_copy(data, _evidence):
    part, _, _, header = data
    # An external source and a local array are distinct complete objects.
    # Require every byte of the three copies and keep the offsets identical.
    copy = re.compile(rf'\*\s*\(\s*{UNSIGNED}\s*\*\s*\)\s*\(\s*(?P<dst>{IDENT})\s*\+\s*(?P<d>{NUMBER})\s*\)'
                      rf'\s*=\s*\*\s*\(\s*(?:const\s+)?{UNSIGNED}\s*\*\s*\)'
                      rf'\s*\(\s*(?P<src>{IDENT})\s*\+\s*(?P<s>{NUMBER})\s*\)\s*;')
    hits = list(copy.finditer(part.clean,part.opening+1,part.end))
    for a,b,c in zip(hits,hits[1:],hits[2:]):
        if (not _statement(part,a.start()) or part.clean[a.end():b.start()].strip()
                or part.clean[b.end():c.start()].strip()):
            continue
        dst,src = a['dst'],a['src']
        offsets = [integer(a[k]) for k in ('d','s')]
        if (dst==src or any((h['dst'],h['src'])!=(dst,src) or
                            [integer(h[k]) for k in ('d','s')]!=[x+4*i for x in offsets]
                            for i,h in enumerate((b,c),1))):
            continue
        byte = r'(?:u8|unsigned\s+char|char)'
        local = re.search(rf'\b{byte}\s+{dst}\s*\[\s*({NUMBER})\s*\]\s*;',part.clean[part.opening+1:a.start()])
        global_ = re.search(rf'\bextern\s+const\s+{byte}\s+{src}\s*\[\s*({NUMBER})\s*\]\s*;',
                            header+'\n'+part.clean[:part.opening])
        if (not local or not global_ or any(offset+12>integer(m[1]) for offset,m in zip(offsets,(local,global_)))
                or re.search(rf'\b{byte}\s+\**\s*{src}\b',part.body)
                or len(re.findall(rf'\b{byte}\s+\**\s*{dst}\b',part.body))!=1):
            continue
        tag = fresh(part.source,header,'repair_packed_words')
        return _result('packed_unaligned_record_copy',part,[(a.start(),c.end(),
            f'{{ struct {tag} {{ unsigned int words[3]; }} __attribute__((packed)); '
            f'*(struct {tag} *)(void *)({dst} + {a["d"]}) = '
            f'*(const struct {tag} *)(const void *)({src} + {a["s"]}); }}')])
    return []


def saved_float_zero(data, callees):
    part, _, _, header = data
    for loop in re.finditer(r'\b(?:do\s*{|for\s*\([^{}]*\)\s*{)',part.clean[part.opening+1:part.end-1]):
        start,end_brace = part.opening+1+loop.start(),part.opening+loop.end()
        end = close(part.clean,end_brace,'{','}')
        if not end or not _statement(part,start):
            continue
        if loop[0].startswith('do'):
            tail = re.match(r'\s*while\s*\([^;{}]*\)\s*;',part.clean[end:part.end])
            if not tail:
                continue
            end += tail.end()
        call = re.match(rf'\s*(?P<callee>{IDENT})\s*\((?P<args>[^;{{}}()]*)\)\s*;',part.clean[end:part.end])
        if not call or call['callee'] not in callees:
            continue
        zero = r'0\.0[fF]'
        stores = list(re.finditer(rf'{IDENT}(?:\s*->|\s*\[\s*{IDENT}\s*\]\s*\.)\s*{IDENT}\s*=\s*(?P<zero>{zero})\s*;',part.clean[end_brace+1:end]))
        args = list(re.finditer(rf'(?<![\w.]){zero}(?![\w.])',call['args']))
        if len(stores)<2 or len(args)!=1:
            continue
        argpos = call['args'][:args[0].start()].count(',')
        prototype = re.search(rf'\b{call["callee"]}\s*\(([^();{{}}]+)\)\s*;',header+'\n'+part.clean[:part.opening])
        if not prototype:
            continue
        types = prototype[1].split(',')
        if argpos<4 or argpos>=len(types) or not re.fullmatch(rf'\s*{F32}(?:\s+{IDENT})?\s*',types[argpos]):
            continue
        local = fresh(part.source,header,'repair_zero')
        changes = [(end_brace+1+m.start('zero'),end_brace+1+m.end('zero'),local) for m in stores]
        offset = end+call.start('args')
        return _result('float_zero_loop_and_call',part,[
            *changes,(offset+args[0].start(),offset+args[0].end(),local),
            (start,start,f'{{ float {local} = 0.0f; '),(end+call.end(),end+call.end(),' }'),
        ])
    return []


def exchange_store_arms(data, _evidence):
    part, _, _, _ = data
    pattern = re.compile(rf'if\s*\((?P<test>{IDENT}\s*(?:==|!=)\s*0)\)\s*{{\s*'
                         rf'(?P<a>(?P<out>{IDENT})\s*=\s*[^;{{}}]+;)\s*goto\s+(?P<label>{IDENT})\s*;\s*}}'
                         rf'\s*(?P<b>(?P=out)\s*=\s*[^;{{}}]+;)\s*(?P=label)\s*:\s*'
                         rf'(?:{FIELD}|\*\s*{IDENT})\s*=\s*(?P=out)\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if not _statement(part,hit.start()) or len(re.findall(rf'\bgoto\s+{hit["label"]}\b',part.body))!=1:
            continue
        test = hit['test'].replace('==','!=') if '==' in hit['test'] else hit['test'].replace('!=','==')
        return _result('shared_store_branch_polarity',part,[
            (*hit.span('test'),test),(*hit.span('a'),part.source[slice(*hit.span('b'))]),
            (*hit.span('b'),part.source[slice(*hit.span('a'))]),
        ])
    return []


def packed_key(data, signatures):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<out>{IDENT})\s*=\s*\(\s*(?P<word>{IDENT})\s*>>\s*(?P<r>{NUMBER})\s*\)'
                         rf'\s*\|\s*\(\s*\(\s*(?P<p>{IDENT})\s*\[\s*(?P<a>{NUMBER})\s*\]\s*\)\s*<<\s*(?P<x>{NUMBER})\s*\)'
                         rf'\s*\|\s*\(\s*\(\s*(?P=p)\s*\[\s*(?P<b>{NUMBER})\s*\]\s*\)\s*<<\s*(?P<y>{NUMBER})\s*\)\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if (tuple(integer(hit[k]) for k in ('r','a','x','b','y')) not in signatures
                or not _statement(part,hit.start()) or not _local(data,hit['word'],UNSIGNED,hit.start())
                or not _local(data,hit['out'],WORD,hit.start())
                or not re.search(rf'\b(?:const\s+)?(?:u8|unsigned\s+char)\s*\*\s*{hit["p"]}\s*[,)]',
                                 part.clean[:part.opening])):
            continue
        a,b,c = [fresh(part.source,header,f'repair_key_{k}') for k in range(3)]
        return _result('interleaved_packed_key',part,[(hit.start(),hit.end(),
            f'{{ unsigned int {a}; int {b}, {c}; {a} = {hit["word"]} >> {hit["r"]}; '
            f'{b} = {hit["p"]}[{hit["a"]}]; {b} <<= {hit["x"]}; '
            f'{c} = {hit["p"]}[{hit["b"]}]; {c} <<= {hit["y"]}; {hit["out"]} = ({a} | {b}) | {c}; }}')])
    return []


def interleaved_field(data, _evidence):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<first>(?P<p>{IDENT})->(?P<field>{IDENT})\s*-=\s*(?P<input>{IDENT})\s*;)\s*'
                         rf'(?P<stores>(?:(?P=p)->{IDENT}\s*=\s*{NUMBER}\s*;\s*){{2}})')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if not _statement(part,hit.start()) or not _local(data,hit['input'],F32,hit.start()):
            continue
        fields = re.findall(r'->\s*('+IDENT+')',hit['stores'])
        record = re.search(rf'\bstruct\s+({IDENT})\s*\*\s*{hit["p"]}\s*[,)]',part.clean[:part.opening])
        if len(set([hit['field'],*fields]))!=3 or not record:
            continue
        members = re.search(rf'\bstruct\s+{record[1]}\s*{{([^{{}}]+)}}',header+'\n'+part.clean[:part.opening])
        if (not members or not re.search(rf'\b{F32}\s+{hit["field"]}\s*;',members[1])
                or not all(re.search(rf'\b(?:{HALF}|s16|short)\s+(?:{IDENT}\s*,\s*)*{v}\s*(?=,|;)',members[1]) for v in fields)):
            continue
        name = fresh(part.source,header,'repair_field')
        domain = f'{hit["p"]}->{hit["field"]}'
        return _result('interleaved_float_field_update',part,[(hit.start(),hit.end(),
            f'{{ float {name} = {domain}; {hit["stores"]} {name} -= {hit["input"]}; {domain} = {name}; }}')])
    return []


def adjacent_call(data, witnesses):
    part, _, _, header = data
    for first,second,symbol,neighbor,delta in sorted(witnesses):
        context = header+'\n'+part.clean[:part.opening]
        if not all(re.search(rf'\bextern\s+(?:[^;{{}}]+\s)?{v}\s*;',context) and not _refs(part.body,neighbor)
                   for v in (symbol,neighbor)):
            continue
        calls = list(re.finditer(rf'\b(?:{first}|{second})\s*\([^;{{}}()]+\)\s*;',part.body))
        uses = [m for m in calls if re.search(rf'(?<=[(,])\s*&\s*{symbol}\s*(?=[,)])',m[0])]
        if len(uses)!=2 or uses[0][0].split('(')[0].strip()!=first or uses[1][0].split('(')[0].strip()!=second:
            continue
        hit = re.search(rf'(?<=[(,])\s*&\s*{symbol}\s*(?=[,)])',uses[1][0])
        start = part.opening+1+uses[1].start()+hit.start()
        return _result('adjacent_symbol_second_call',part,[
            (start,start+len(hit[0]),f'(void *)((unsigned int)&{neighbor} + {delta}U)')
        ])
    return []


def variants(source,name,header,evidence):
    if not evidence:
        return []
    data = _context(source,name,header)
    labels = data
    label_repairs = (increment_edge,exchange_store_arms)
    if not labels and any(fn in label_repairs for fn,_ in evidence):
        labels = _context(re.sub(r'\bgoto\b','jump',source),name,header)
        actual = _visible(source,name,header)
        labels = (actual[0],*labels[1:]) if labels and actual else None
    result = []
    for repair,signature in evidence:
        selected = labels if repair in label_repairs else data
        if selected:
            result.extend(repair(selected,signature))
    return result
