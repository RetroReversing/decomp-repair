"""Bounded address, literal and floating-load temporaries learned from verified repairs.

These are scheduling hypotheses, never equivalence claims; the ordinary exact judge accepts them.
"""
import re

from . import m2cfix
from .csource import _blank, find

IDENT = r'[A-Za-z_]\w*'


def _python_close(text, start):
    depth = 0
    for i in range(start,len(text)):
        depth += (text[i]=='(')-(text[i]==')')
        if not depth:
            return i+1
    return None


close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def close(text, start):
        found = _scan.close_every(text, start, '(', ')', True, None)
        return _python_close(text, start) if found is NotImplemented else found


def statement_start(body, end):
    depth, start = 0, 1
    for i,ch in enumerate(body[:end]):
        depth += (ch=='(')-(ch==')')
        if depth==0 and ch in ';{}':
            start=i+1
    return start


def declaration_prefix(text):
    # Conservatively identify a declaration initializer. Never insert a statement ahead of it:
    # that would put the existing declaration after a statement in C89. Inline alternatives stay valid.
    return bool(re.match(r'\s*(?:(?:const|volatile|unsigned|signed|struct)\s+)*[A-Za-z_]\w*(?:\s+(?:\*\s*)*|\s*\*+\s*)[A-Za-z_]\w*\s*(?:\[[^]]*\])?\s*=',text))


def _assigned_in(name, text):
    return re.search(r'(?<![\w.>])'+name+r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*'+name+r'\b|\b'+name+r'\s*(?:\+\+|--)|&\s*'+name+r'\b',text)


def _sum_operands(text, start, end):
    """(start, end) of each top-level operand of a sum in text[start:end]; [] when it isn't a sum at top level."""
    parts, depth, begin = [], 0, start
    for i in range(start, end):
        ch = text[i]
        depth += (ch in '([') - (ch in ')]')
        if depth == 0 and ch == '+' and text[i+1:i+2] not in '+=' and text[i-1:i] != '+':
            parts.append((begin, i))
            begin = i+1
    if not parts or depth:
        return []
    return parts + [(begin, end)]


def variants(source, name):
    span = find(source,name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{',*span)
    body = clean[opening:span[1]]
    if '#' in body or re.search(r'\bvolatile\b|__repair_(?:addr|literal|cmp|operand)',clean):
        return []
    result = []

    def raw(a,b):
        return source[opening+a:opening+b]

    def add(family, edits):
        merged={}
        for a,b,replacement in edits:
            merged[a,b]=merged.get((a,b),'')+replacement
        candidate=source
        for (a,b),text in sorted(merged.items(),reverse=True):
            candidate=candidate[:opening+a]+text+candidate[opening+b:]
        if candidate!=source and candidate not in [s for _,s in result]:
            result.append((family,candidate))

    # Keep the field macro, including its type/offset; only split its effective address.
    for m in list(re.finditer(r'\bM2C_FIELD\s*\(',body))[:16]:
        end=close(body,m.end()-1)
        if not end:
            continue
        args=m2cfix._split_top_level(body[m.end():end-1])
        if len(args)!=3 or not re.search(r'[+*]',args[0]) or not re.fullmatch(r'\s*'+IDENT+r'\s*\*\s*',args[1]):
            continue
        base=args[0].strip()
        # Nested field macros are loads; arbitrary function calls and writes must not move.
        calls=re.findall(r'\b('+IDENT+r')\s*\(',base)
        if any(c!='M2C_FIELD' for c in calls) or re.search(r'\+\+|--|[=;{}]',base):
            continue
        at=statement_start(body,m.start())
        prefix=body[at:m.start()]
        if re.search(r'\b(?:for|while|do|return|goto|else)\b',prefix):
            continue
        expr=raw(m.end(),m.end()+len(args[0])).strip()
        for inline in (False,True):
            if not inline and declaration_prefix(prefix):
                continue
            replacement='__repair_addr' if not inline else f'(__repair_addr = (char *)({expr}))'
            edits=[(1,1,'\nchar *__repair_addr;\n'),(m.end(),m.end()+len(args[0]),replacement)]
            if not inline:
                edits.append((at,at,f'\n__repair_addr = (char *)({expr});\n'))
            add('address_temporary',edits)
        if sum(f=='address_temporary' for f,_ in result)>=6:
            break

    # A load that is one operand of a sum, in a statement of its own first. address_temporary splits a field's whole
    # address; here the base pointer chain is only part of it: `p = (i * 0x18) + M2C_FIELD(M2C_FIELD(o, void **,
    # 0x6C), s32 *, 4);` scheduled the index between the two loads, where an N64 game loaded the chain first.
    outside=clean[:span[0]]+clean[span[1]:]
    globals_={g:' '.join(t.split()) for t,g in re.findall(r'(?m)^[ \t]*extern\s+((?:unsigned\s+|signed\s+)?'+IDENT+r'(?:\s*\*)*)\s*('+IDENT+r')\s*;',outside)
              if t.split()[-1] not in ('M2C_UNK','void') and not _assigned_in(g,body)}
    for m in list(re.finditer(r'(?m)^[ \t]*(?P<lhs>'+IDENT+r')\s*=(?!=)\s*',body))[:24]:
        stop=body.find(';',m.end())
        if stop<0 or re.search(r'[{}]',body[m.end():stop]):
            continue
        # the assignment is the whole statement (a plain `x = ...;`, not a declaration or a loop's step)
        if body[statement_start(body,m.start('lhs')):m.start('lhs')].strip():
            continue
        for start,end in _sum_operands(body,m.end(),stop):
            operand=body[start:end].strip()
            # (a global the function doesn't change is a load too: an N64 function loaded `D_800E41DC` before
            # computing `arg0 * 0x68` for the sum, exact with it in a statement first)
            if operand in globals_:
                kind=globals_[operand]
            else:
                if not re.match(r'M2C_FIELD\s*\(',operand) or close(operand,operand.find('('))!=len(operand):
                    continue
                args=m2cfix._split_top_level(operand[operand.find('(')+1:-1])
                typed=re.fullmatch(r'\s*(?P<t>'+IDENT+r'(?:\s*\*)*)\s*\*\s*',args[1]) if len(args)==3 else None
                calls=re.findall(r'\b('+IDENT+r')\s*\(',operand)
                if not typed or any(c!='M2C_FIELD' for c in calls) or re.search(r'\+\+|--|[=;{}]',operand):
                    continue
                kind=' '.join(typed['t'].split())
            lead=len(body[start:end])-len(body[start:end].lstrip())
            add('operand_temporary',[(1,1,f'\n{kind} __repair_operand;\n'),
                                     (m.start('lhs'),m.start('lhs'),f'__repair_operand = {raw(start+lead,start+lead+len(operand))};\n'
                                      +re.match(r'[ \t]*',body[m.start():])[0]),
                                     (start+lead,start+lead+len(operand),'__repair_operand')])
        if sum(f=='operand_temporary' for f,_ in result)>=4:
            break

    # Plain casts in imported sources deserve the same address experiment as m2c macros.
    for m in list(re.finditer(r'\*\s*\(\s*(?:s16|u16|s32|u32|f32|f64|short|int|float|double)\s*\*\s*\)\s*\(',body))[:6]:
        end=close(body,m.end()-1)
        if not end:
            continue
        expr=raw(m.end(),end-1)
        if not re.search(r'[+*]',expr) or re.search(r'\b'+IDENT+r'\s*\(|\+\+|--|[=;{}]',expr):
            continue
        at=statement_start(body,m.start())
        if declaration_prefix(body[at:m.start()]) or re.search(r'\b(?:for|while|do|return|goto|else)\b',body[at:m.start()]):
            continue
        add('address_temporary',[(1,1,'\nchar *__repair_addr;\n'),
                                 (at,at,f'\n__repair_addr = (char *)({expr});\n'),
                                 (m.end(),end-1,'__repair_addr')])

    # Only small literal arithmetic/comparison operands, not field offsets, array bounds or masks.
    for m in list(re.finditer(r'(?P<op>\*|>=|<=|>|<)\s*(?P<n>0x[0-9a-fA-F]+|\d+)(?P<u>[uU]?)(?![\w.])',body))[:12]:
        number=int(m['n'],0) if m['n'].startswith('0x') else int(m['n'])
        if number not in (0,1,2,4,8,16,32):
            continue
        at=statement_start(body,m.start())
        prefix=body[at:m.start()]
        if re.search(r'\b(?:for|while|do|sizeof|else)\b',prefix) or re.search(r'<<|>>',body[max(0,m.start()-1):m.start()+2]):
            continue
        # A '*' can be a declaration/pointer cast; require a value immediately to its left.
        if m['op']=='*' and not re.search(r'[\w)\]]\s*$',prefix):
            continue
        if declaration_prefix(prefix):
            continue
        typ='unsigned int' if m['u'] else 'int'
        add('constant_local',[(1,1,f'\n{typ} __repair_literal;\n'),
                              (at,at,f'\n__repair_literal = {m["n"]}{m["u"]};\n'),
                              (m.start('n'),m.end(),'__repair_literal')])
        if sum(f=='constant_local' for f,_ in result)>=4:
            break

    # Materialize the two float loads without negating/swapping the comparison (NaN behavior stays).
    field=r'M2C_FIELD\([^;{}]*?,\s*(f32|f64)\s*\*,\s*(?:0x[0-9a-fA-F]+|\d+)\s*\)'
    for m in list(re.finditer(r'\bif\s*\(',body))[:12]:
        end=close(body,m.end()-1)
        if not end:
            continue
        if body[statement_start(body,m.start()):m.start()].strip():
            continue
        cond=body[m.end():end-1]
        match=re.fullmatch(r'\s*('+field+r')\s*(<|>|<=|>=)\s*('+field+r')\s*',cond)
        if not match or match[2]!=match[5]:
            continue
        left,right,typ=match[1],match[4],match[2]
        for reverse in (False,True):
            for copy in (False,True):
                assigns=[f'__repair_cmp_l = {left};',f'__repair_cmp_r = {right};']
                if reverse:
                    assigns.reverse()
                if copy:
                    assigns.append('__repair_cmp_c = __repair_cmp_r;')
                right_name='__repair_cmp_c' if copy else '__repair_cmp_r'
                decl=f'\n{typ} __repair_cmp_l; {typ} __repair_cmp_r;'+(f' {typ} __repair_cmp_c;' if copy else '')+'\n'
                add('comparison_load',[(1,1,decl),(m.start(),m.start(),'\n'.join(assigns)+'\n'),
                                       (m.end(),end-1,f'__repair_cmp_l {match[3]} {right_name}')])
        break
    return result
