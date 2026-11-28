"""Offer an initialized loop index as a zero-valued call-argument carrier.

On a KMC MIPS O1 function, `constant | (i & ~i)` in two identical call
positions changed an outgoing argument's register and matched the target,
10 to 0. The expression is allocation scaffolding: it is always the same
constant and must be disclosed. Only an unescaped initialized integer loop
index with no body writes or incoming jumps is offered.
"""
import re

from .call_site_prototype_repairs import split_args
from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'loop_zero_call_argument'
LIMIT = 24


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    context = source + '\n' + header
    if re.search(r'\b__(?:LINE|COUNTER)__\b', context):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define\b(?:[^\n\\]|\\\n)*', context)
    locals_ = {d['name']: d for d in locals_for(part) if d['type'] in {'s32', 'u32', 'int', 'signed int', 'unsigned int'}}
    result = []
    pattern = rf'\bfor\s*\(\s*({IDENT})\s*=\s*0\s*;[^;{{}}]*;\s*\1\s*\+\+\s*\)\s*{{'
    for loop in re.finditer(pattern, part.clean[part.opening:part.end]):
        index = loop[1]
        if index not in locals_ or any(re.search(r'\b' + re.escape(index) + r'\b', m) for m in macros):
            continue
        opening = part.opening + loop.end() - 1
        end = close(part.clean, opening, '{', '}')
        if not end:
            continue
        body = part.clean[opening + 1:end - 1]
        if re.search(rf'\b{re.escape(index)}\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*{re.escape(index)}\b', body):
            continue
        labels = set(re.findall(rf'(?:^|[;{{}}])\s*({IDENT})\s*:(?!:)', body)) - {'case', 'default'}
        outside = part.clean[part.opening:opening] + part.clean[end:part.end]
        if any(re.search(r'\bgoto\s+' + re.escape(label) + r'\s*;', outside) for label in labels):
            continue
        # A case nested in a switch outside this loop can enter without its initializer.
        switches = []
        for hit in re.finditer(r'\bswitch\s*\(', body):
            paren = opening + 1 + hit.end() - 1
            after = close(part.clean, paren)
            brace = re.match(r'\s*{', part.clean[after:end]) if after else None
            stop = close(part.clean, after + brace.end() - 1, '{', '}') if brace else None
            if stop:
                switches.append((after + brace.end() - 1, stop))
        if any(not any(a < opening + 1 + h.start() < b for a, b in switches)
               for h in re.finditer(r'\b(?:case|default)\b', body)):
            continue
        calls = {}
        for call in re.finditer(r'\b(' + IDENT + r')\s*\(', body):
            callee = call[1]
            if callee in {'if', 'while', 'for', 'switch', 'sizeof', 'return'} or any(re.search(r'\b' + re.escape(callee) + r'\b', m) for m in macros):
                continue
            at = opening + 1 + call.start()
            if part.clean[opening + 1:at].rstrip()[-1:] not in {';', '{', '}', ':'}:
                continue
            paren = opening + 1 + call.end() - 1
            after = close(part.clean, paren)
            if not after or not re.match(r'\s*;', part.clean[after:end]):
                continue
            args = split_args(source[paren + 1:after - 1])
            calls.setdefault(callee, []).append((at, after, args))
        for callee, sites in calls.items():
            if len(sites) != 2 or len(sites[0][2]) != len(sites[1][2]) or not 7 <= len(sites[0][2]) <= 12:
                continue
            for pos in range(4, len(sites[0][2])):
                literal = sites[0][2][pos].strip()
                if literal != sites[1][2][pos].strip() or not re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|\d+)', literal) or int(literal, 16 if literal.lower().startswith('0x') else 10) > 0x7fffffff:
                    continue
                edits = []
                for start, stop, args in sites:
                    changed = list(args)
                    changed[pos] = literal + ' | (' + index + ' & ~' + index + ')'
                    edits.append((start, stop, callee + '(' + ', '.join(changed) + ')'))
                result.append((FAMILY, edit(source, edits)))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
