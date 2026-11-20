"""Small source edits for measured MIPS scheduling and register mismatches."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, integer
from .operand_lifetime_repairs import _escaped, _visible
from .pattern_repairs import close
from .target_conversion_order_repairs import F32, SIGNED, UNSIGNED, _context, _local, _refs, _result
from .target_memory_repairs import WORD, _statement

LOAD = rf'{IDENT}\s*\[[^\[\];{{}}]+\]'
MEMBER = rf'{IDENT}\s*->\s*{IDENT}'


def offset_shift(data, shifts):
    part, _, _, _ = data
    pattern = re.compile(
        rf'(?P<type>{WORD}\s+)?(?P<var>{IDENT})\s*=\s*(?P<scale>[^;{{}}]+);\s*'
        rf'(?P<base>(?:{IDENT}\s*\*\s*)?{IDENT}\s*=\s*(?:{MEMBER}|{LOAD}|{IDENT})\s*;)\s*'
        rf'(?P=var)\s*=\s*\(\s*(?P=var)\s*<<\s*(?P<shift>{NUMBER})\s*\)\s*-\s*{NUMBER}\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        var, scale = hit['var'], hit['scale']
        if (not _statement(part,hit.start()) or integer(hit['shift']) not in shifts
                or not re.fullmatch(r'[\w\s()+*<>-]+',scale) or not re.search(r'<<|\*',scale)
                or re.search(r'\+\+|--|(?:^|[(+<>-])\s*\*',scale)
                or not all(_local(data,x,WORD,hit.start()) for x in re.findall(r'\b[A-Za-z_]\w*\b',scale))
                or _refs(hit['base'],var) or _refs(scale,var)
                or _escaped(part.body,var)
                or (not hit['type'] and not _local(data,var,WORD,hit.start()))):
            continue
        tail = re.search(r'\(\s*'+var+r'\s*<<\s*'+re.escape(hit['shift'])+r'\s*\)',hit[0][hit.end('base')-hit.start():])
        start = hit.end('base')+tail.start()
        typ = hit['type'].strip() if hit['type'] else data[2][var][0][0]
        # Preserve the conversion through the original word type before shifting.
        return _result('offset_initializer_final_shift',part,[
            (*hit.span('scale'),f'(({typ})({scale})) << {hit["shift"]}'),
            (start,start+len(tail[0]),var),
        ])
    return []


def clamp_fallback(data, values):
    part, _, _, _ = data
    pattern = re.compile(
        rf'(?P<init>(?P<var>{IDENT})\s*=\s*(?P<value>{NUMBER})\s*;)\s*'
        rf'if\s*\((?P<test>[^;{{}}]+)\)\s*{{\s*'
        rf'(?P<assign>(?P=var)\s*=\s*\(\s*{UNSIGNED}\s*\)\s*(?:{IDENT}|\([^;{{}}]+\))\s*;)\s*}}')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        var = hit['var']
        if (integer(hit['value']) not in values or not _local(data,var,WORD,hit.start())
                or not _statement(part,hit.start()) or _refs(hit['test'],var)
                or _refs(hit['assign'].split('=',1)[1],var)):
            continue
        after = part.clean[hit.end():part.end]
        if not re.match(rf'\s*(?:{MEMBER}|{LOAD}|\*\s*{IDENT})\s*=\s*{var}\s*;',after):
            continue
        return _result('clamp_fallback_on_store_edge',part,[
            (*hit.span('init'),''),(hit.end(),hit.end(),f' else {{ {var} = {hit["value"]}; }}')
        ])
    goto_store = re.compile(
        rf'(?P<init>(?P<var>{IDENT})\s*=\s*(?P<value>{NUMBER})\s*;)\s*'
        rf'if\s*\((?P<test>[^;{{}}]+)\)\s*{{\s*(?P<jump>goto\s+(?P<label>{IDENT})\s*;)\s*}}'
        rf'\s*(?P=var)\s*=\s*\(\s*{UNSIGNED}\s*\)\s*{IDENT}\s*;\s*'
        rf'(?P=label)\s*:\s*(?:{MEMBER}|{LOAD}|\*\s*{IDENT})\s*=\s*(?P=var)\s*;')
    for hit in goto_store.finditer(part.clean,part.opening+1,part.end-1):
        var = hit['var']
        if (integer(hit['value']) in values and _local(data,var,WORD,hit.start())
                and _statement(part,hit.start()) and not _refs(hit['test'],var)):
            return _result('clamp_fallback_on_store_edge',part,[
                (*hit.span('init'),''), (hit.start('jump'),hit.start('jump'),f'{var} = {hit["value"]}; ')
            ])
    return []


def shared_zero(data):
    part, _, _, header = data
    first = re.compile(rf'\bif\s*\([^;{{}}]+\)\s*{{\s*(?P<zero>(?P<var>{IDENT})\s*=\s*0[uU]?\s*;)'
                       rf'\s*goto\s+(?P<done>{IDENT})\s*;\s*}}')
    for hit in first.finditer(part.clean,part.opening+1,part.end-1):
        var, done = hit['var'],hit['done']
        if not _local(data,var,WORD,hit.start()) or not _statement(part,hit.start()):
            continue
        # A zeroing fallthrough immediately before the shared exit is also
        # a valid destination for the bound-failure edge.
        tail = re.compile(rf'(?P<zero>\b{var}\s*=\s*0[uU]?\s*;)\s*(?:}}\s*)?{done}\s*:\s*return\s+{var}\s*;')
        for end in tail.finditer(part.clean,hit.end(),part.end-1):
            if (block_path(part,end.start()) != block_path(part,hit.start())
                    and part.clean[block_path(part,end.start())[-1]+1:end.start()].strip()):
                continue
            if not _local(data,var,WORD,end.start()) or not _statement(part,end.start()) or not re.search(
                r'\bwhile\b|\b(?:NULL|0)\b\s*\)',part.clean[hit.end():end.start()]
            ):
                continue
            destination = fresh(part.source,header,'repair_absent')
            jump = re.search(rf'\bgoto\s+{done}\b',hit[0])
            pos = hit.start()+jump.end()-len(done)
            return _result('common_zero_result_label',part,[
                (*hit.span('zero'),''),(pos,pos+len(done),destination),
                (end.start('zero'),end.start('zero'),destination+': '),
            ])
    return []


def float_store_boundary(data):
    part, _, _, _ = data
    pattern = re.compile(rf'(?P<base>{IDENT})->(?P<a>{IDENT})\s*=\s*(?P<x>{IDENT})\s*;'
                         rf'(?P<gap>\s*)(?P=base)->(?P<b>{IDENT})\s*=\s*(?P<y>{IDENT})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if (_statement(part,hit.start()) and hit['a']!=hit['b']
                and all(_local(data,hit[k],F32,hit.start()) for k in ('x','y'))
                and not re.search(r'\bdo\s*{\s*}\s*while\s*\(\s*0\s*\)',part.body)):
            return _result('float_output_store_boundary',part,[(hit.start('gap'),hit.start('gap'),' do {} while (0);')])
    return []


def signed_mask(data):
    part, _, _, header = data
    pattern = re.compile(rf'\(\s*(?P<count>{IDENT})\s*&\s*(?P<mask>{NUMBER})\s*\)'
                         rf'\s*<\s*(?P<bound>{IDENT})\b(?=\s*[);])')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        bound, count = hit['bound'],hit['count']
        if (integer(hit['mask'])!=65535 or not _local(data,count,WORD,hit.start())
                or not (_local(data,bound,SIGNED,hit.start()) or (
                    bound not in data[2] and _refs(header+'\n'+part.clean[:part.opening],bound)
                    and re.search(rf'\bextern\s+{SIGNED}\s+{bound}\s*;',header+'\n'+part.clean[:part.opening])
                ))):
            continue
        return _result('signed_masked_loop_bound',part,[(hit.start(),hit.end(),f'(int)(unsigned short){count} < {bound}')])
    return []


def previous_record(data, strides):
    part, _, _, _ = data
    pattern = re.compile(rf'&\s*(?P<base>{IDENT})\s*\[\s*(?P<index>{IDENT})\s*-\s*1\s*\]')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        base,index = hit['base'],hit['index']
        declaration = re.search(rf'\b(?P<type>(?:const\s+)?(?:struct\s+)?{IDENT})\s*\*\s*{base}\s*(?=[,);])',
                                part.clean[:part.opening])
        if (not declaration or base in data[2] or not _local(data,index,SIGNED,hit.start())
                or re.search(rf'\b{IDENT}\s+\*\s*{base}\b',part.body)):
            continue
        # The compiler knows the declared record stride. Use a signed byte
        # displacement so a valid access to the preceding element still works.
        typ = declaration['type']
        char = 'const unsigned char' if typ.startswith('const ') else 'unsigned char'
        repl = f'(({typ} *)(({char} *){base} + (long)({index} - 1) * (long)sizeof(*{base})))'
        if strides:
            return _result('previous_record_index_before_scaling',part,[(hit.start(),hit.end(),repl)])
    return []


def numerator(data):
    part, _, _, header = data
    for guard in re.finditer(rf'\bif\s*\(\s*{IDENT}\s*>\s*0\s*\)\s*{{',part.body):
        opening = part.opening+guard.end()
        end = close(part.clean,opening,'{','}')
        if not end:
            continue
        body = part.clean[opening+1:end-1]
        hits = list(re.finditer(rf'\b(?P<one>1\.0[fF])\s*/\s*{IDENT}\b',body))
        if not hits or not re.search(r'\b(?:for|while|do)\b',body):
            continue
        var = fresh(part.source,header,'repair_one')
        changes = [(opening+1,opening+1,f' float {var} = 1.0f; ')]
        changes.extend((opening+1+h.start('one'),opening+1+h.end('one'),var) for h in hits)
        return _result('guarded_float_numerator',part,changes)
    return []


def float_word(data):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<base>{IDENT})->(?P<field>{IDENT})\s*=\s*(?P<a>{IDENT})\s*\*\s*(?P<b>{IDENT})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        base,field = hit['base'],hit['field']
        record = re.search(rf'\bstruct\s+({IDENT})\s*\*\s*{base}\s*[,)]',part.clean[:part.opening])
        if (not record or not _statement(part,hit.start())
                or not all(_local(data,hit[k],F32,hit.start()) for k in ('a','b'))):
            continue
        fields = re.search(rf'\bstruct\s+{record[1]}\s*{{([^{{}}]+)}}',header+'\n'+part.clean[:part.opening])
        if not fields or not re.search(rf'(?:^|;)\s*{F32}\s+{field}\s*;',fields[1]):
            continue
        var = fresh(part.source,header,'repair_float_word')
        # KMC's word lvalue and union can express a four-byte bit copy
        # without an arithmetic conversion back to integer.
        return _result('computed_float_word_store',part,[(hit.start(),hit.end(),
            f'{{ union {{ float value; unsigned int bits; }} {var}; {var}.value = {hit["a"]} * {hit["b"]}; '
            f'*(unsigned int *)(void *)&{base}->{field} = {var}.bits; }}')])
    return []


def selector(part, context, symbols):
    pattern = re.compile(
        rf'(?P<half>(?P<h>{IDENT})\s*=\s*(?P<hread>{MEMBER}|{LOAD}|{IDENT})\s*;)\s*'
        rf'(?P<byte>(?P<b>{IDENT})\s*=\s*(?P<table>{IDENT})\s*\[\s*(?P<index>{IDENT}|{NUMBER})\s*\]\s*;)\s*'
        rf'if\s*\(\s*(?P=b)\s*\)\s*{{\s*(?P<out>{IDENT})\s*=\s*(?P=h)\s*\|\s*(?P<yes>{NUMBER})\s*;\s*}}'
        rf'\s*else\s*{{\s*(?P=out)\s*=\s*(?P=h)\s*\|\s*(?P<no>{NUMBER})\s*;\s*}}')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        table = hit['table']
        if (table not in symbols or not _statement(part,hit.start()) or len({hit['h'],hit['b'],hit['out']})!=3
                or _refs(hit['hread'],hit['b']) or _refs(hit['index'],hit['h'])
                or not re.search(rf'\bextern\s+(?:u8|unsigned\s+char)\s+{table}\s*\[[^\]]*\]\s*;',context)
                or re.search(rf'\b{IDENT}\s+\**{table}\s*(?=[;=\[])',part.body)
                or re.search(r'\bvolatile\b',context)
                or any(_escaped(part.body,v) for v in (hit['h'],hit['b'],hit['out']))):
            continue
        return _result('selector_byte_before_halfword',part,[(hit.start(),hit.end(),
            f'{hit["b"]} = ((volatile unsigned char *){table})[{hit["index"]}]; '
            f'{hit["half"]} {hit["out"]} = {hit["b"]} ? ({hit["h"]} | {hit["yes"]}) : '
            f'({hit["h"]} | {hit["no"]});')])
    return []


def volatile_record(part, context, symbols):
    for symbol in sorted(symbols):
        decl = re.search(rf'\bextern\s+((?:struct\s+)?{IDENT})\s*\*\s*volatile\s+{symbol}\s*;',context)
        if not decl or re.search(rf'\b{IDENT}\s+\**\s*{symbol}\s*(?=[;=\[])',part.body):
            continue
        typ = decl[1]
        pattern = re.compile(rf'\b(?P<base>{IDENT})\s*=\s*{symbol}\s*;\s*'
                             rf'(?:return\s+|{IDENT}\s*=\s*)(?P<expr>(?P=base)\s*\+\s*(?P<index>{IDENT}))\s*;')
        for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
            base,index = hit['base'],hit['index']
            if (not _statement(part,hit.start()) or _escaped(part.body,base)
                    or not re.search(rf'\b{typ}\s*\*\s*{base}\s*;',part.body[:hit.start()-part.opening-1])
                    or not re.search(rf'\b{WORD}\s+{index}\s*(?=[;,)=])',part.clean[:hit.start()])):
                continue
            expr = f'({typ} *)(((unsigned int){index} * (unsigned int)sizeof(*{base})) + (unsigned int){base})'
            return _result('volatile_record_word_address',part,[(*hit.span('expr'),expr)])
    return []


def variants(source, name, header, evidence):
    if not evidence:
        return []
    # The shared-label candidate preserves a goto that was already in the
    # source. The other rewrites do not need to admit unstructured control.
    data = _context(source,name,header)
    label_data = data
    if not label_data and any(fn in (shared_zero,clamp_fallback) for fn,_ in evidence):
        masked = re.sub(r'\bgoto\b','jump',source)
        label_data = _context(masked,name,header)
        visible = _visible(source,name,header)
        if label_data and visible:
            label_data = (visible[0],*label_data[1:])
    visible = _visible(source,name,header)
    out = []
    for repair,args in evidence:
        if repair in (selector,volatile_record):
            if visible:
                part, context = visible
                macro_names = set(re.findall(rf'^\s*#\s*define\s+({IDENT})',context,re.M))
                if not macro_names.intersection(re.findall(IDENT,part.body)):
                    out.extend(repair(part,context,*args))
        elif repair in (shared_zero,clamp_fallback):
            if label_data:
                out.extend(repair(label_data,*args))
        elif data:
            out.extend(repair(data,*args))
    return out
