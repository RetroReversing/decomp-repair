"""Recover paired decode lifetimes and a proven wide object clear."""

import re

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, INTEGER, edit
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible
from .pattern_repairs import close

DECODERS = 'paired_decoder_byte_reuse'
WIDE_CLEAR = 'aligned_wide_zero_clear'


def paired_decoders(source, name, header):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    if re.search(r'\bgoto\b',part.body):
        return []
    types = _typed_locals(part,INTEGER)
    tests = re.compile(rf'\bif\s*\(\s*(?P<high>{IDENT})\s*&\s*(?:0[xX]80|128)[uU]?\s*\)\s*{{')
    captures = []
    for branch in tests.finditer(part.clean,part.opening+1,part.end-1):
        left_end = close(part.clean,branch.end()-1,'{','}')
        alt = re.match(r'\s*else\s*{',part.clean[left_end:]) if left_end else None
        right_start = left_end+alt.end() if alt else None
        right_end = close(part.clean,right_start-1,'{','}') if right_start else None
        if not right_end:
            continue
        arms = (part.clean[branch.end():left_end-1],part.clean[right_start:right_end-1])
        assigns = [re.match(rf'\s*({IDENT})\s*=(?!=)\s*([^;{{}}]+);',arm) for arm in arms]
        if not all(assigns) or assigns[0][1]!=assigns[1][1]:
            continue
        destination,high = assigns[0][1],branch['high']
        shift = re.search(rf'\b{high}\s*&\s*(?:0[xX]7[fF]|127)[uU]?\s*\)\s*<<\s*8\b',assigns[0][2])
        source_byte = re.search(rf'\b({IDENT})\s*\|',assigns[0][2])
        if not shift or not source_byte or not re.search(rf'\b{high}\b',assigns[1][2]):
            continue
        low = source_byte[1]
        if len({destination,high,low})!=3 or not all(v in types and not _escaped(part.body,v)
                and _in_scope(part,types[v][1],branch.start()) for v in (low,destination)):
            continue
        if types[low][0]!=types[destination][0] or types[low][0] not in {'s32','int','signed int','u32','unsigned int'}:
            continue
        if re.search(rf'#\s*define\s+[^\n]*\b(?:{low}|{destination})\b|'
                     rf'volatile\s+[^;{{}}\n]*\b(?:{low}|{destination})\b',context):
            continue
        if any(re.search(rf'\b{low}\b',arm[m.end():]) for arm,m in zip(arms,assigns)):
            continue
        if len(re.findall(rf'\b{destination}\s*=(?!=)',part.body))!=2:
            continue
        # Stop at the end of the containing scope. Every destination read
        # must be dominated by this if/else, with the original low byte dead.
        block = block_path(part,branch.start())
        scope_end = close(part.clean,block[-1],'{','}')
        post = part.clean[right_end:scope_end-1]
        later = re.search(rf'\b{low}\s*=(?!=)\s*[^;{{}}]+\[\s*1\s*\]\s*;',post)
        limit = right_end+later.start() if later else scope_end-1
        before = part.clean[types[destination][1]:branch.start()]
        if re.search(rf'\b{destination}\b',before[before.find(';')+1:]) or re.search(
                rf'\b{destination}\b',part.clean[limit:part.end-1]):
            continue
        middle = part.clean[right_end:limit]
        if re.search(rf'\b{low}\b',middle) or not re.search(rf'\b{destination}\b',middle):
            continue
        init = re.search(rf'\b{low}\s*=\s*[^;{{}}]+\[\s*1\s*\]\s*;\s*$',part.clean[:branch.start()])
        if not init:
            # A preliminary sentinel guard may test both bytes before the
            # decode. Use the most recent plain assignment to the low byte.
            earlier = list(re.finditer(rf'\b{low}\s*=(?!=)\s*([^;{{}}]+);',part.clean[:branch.start()]))
            if not earlier or not re.search(r'\[\s*1\s*\]\s*$',earlier[-1][1]):
                continue
        sites = [(origin+m.start(1),origin+m.end(1),low) for origin,m in zip((branch.end(),right_start),assigns)]
        sites += [(right_end+m.start(),right_end+m.end(),low) for m in
                  re.finditer(rf'(?<![.>\w]){destination}\b',middle)]
        captures.append((low,destination,sites))
        if len(captures)>2:
            return []
    if len(captures)!=2 or captures[0][1]==captures[1][1]:
        return []
    edits = [edit_ for _,_,sites in captures for edit_ in sites]
    if len({(start,end) for start,end,_ in edits})!=len(edits):
        return []
    return [(DECODERS,edit(source,edits))]


def aligned_clear(source, name, header, objects):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    out = []
    for symbol in sorted(objects):
        wide = re.search(rf'(?:^|[;}}])\s*(?:extern\s+)?(?:u64|s64|unsigned\s+long\s+long|long\s+long)'
                         rf'\s+{symbol}\s*;',context[:len(context)-len(part.clean)+part.opening])
        if not wide or re.search(rf'\bvolatile\b[^;{{}}]*\b{symbol}\b|#\s*define\s+{symbol}\b',context):
            continue
        word = rf'\(\(\s*(?:u32|s32|unsigned\s+int|int)\s*\*\s*\)\s*&\s*{symbol}\s*\)'
        pattern = re.compile(rf'{word}\s*\[\s*(?P<a>[01])\s*\]\s*=\s*0[uU]?\s*;'
                             rf'\s*{word}\s*\[\s*(?P<b>[01])\s*\]\s*=\s*0[uU]?\s*;')
        for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
            if hit['a']==hit['b'] or part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('',';','{','}'):
                continue
            out.append((WIDE_CLEAR,edit(source,[(hit.start(),hit.end(),f'{symbol} = 0;')])))
            if len(out)==2:
                return out
    return out
