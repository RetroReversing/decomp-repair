"""Offer a bounded float lifetime carrier with an allocator-weight scope.

On one KMC -O1 function the combined child took an exact judge from 272 to 0.
The byte-derived float stays within the signed 32-bit range; its integer copy
ANDed with its complement is always zero. The one-shot scope and zero expression
are search scaffolding and should be disclosed when a match uses them.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .run_weight_scope import _statement_end

FAMILY = 'bounded_float_zero_scope'
NUM = r'-?(?:\d+\.\d*|\.\d+)[fF]'


def variants(source, name, asm, flags=(), header=''):
    if '-O1' not in flags or not re.search(r'\bsdc1\s+\$(?:f20|fs0)\b', asm or '', re.I) or not re.search(r'\bsdc1\s+\$(?:f22|fs1)\b', asm or '', re.I):
        return []
    context = _blank(source) + '\n' + _blank(header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:s8|s32|f32)\b|\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s8|s32|f32)\s*;', context):
        return []
    typedefs = re.findall(r'\btypedef\s+([^;]+?)\s+s8\s*;', context)
    if any(t.strip() not in ('signed char', 'unsigned char', 'char') for t in typedefs):
        return []
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|goto|asm|__asm__|setjmp|longjmp|for|while|do|switch|case|default)\b', body) or re.search(r'(?m)^\s*#', body):
        return []
    floats = [n for d in re.findall(r'(?m)^\s*f32\s+(' + IDENT + r'(?:\s*,\s*' + IDENT + r')*)\s*;', body)
              for n in re.findall(IDENT, d)]
    ints = re.findall(r'(?m)^\s*s32\s+(' + IDENT + r')\s*;', body)
    inputs = set(re.findall(r'\bextern\s+s8\s+(' + IDENT + r')\s*;', context))
    outputs = set(re.findall(r'\bextern\s+s32\s+(' + IDENT + r')\s*;', context))
    result = []
    for floating in floats:
        if floats.count(floating) != 1:
            continue
        f = re.escape(floating)
        if (re.search(r'&\s*' + f + r'\b|(?:\+\+|--)\s*' + f + r'\b|\b' + f + r'\s*(?:\+\+|--)', body)
                or re.search(r'\b(?!(?:if|while|for|switch|sizeof)\b)' + IDENT + r'\s*\([^;{}]*\b' + f + r'\b', body)):
            continue
        writes = list(re.finditer(r'\b' + f + r'\s*(?P<op>(?:<<|>>|[+\-*/%&|^])?=)(?!=)\s*(?P<rhs>[^;]+);', body))
        if not writes or writes[0]['op'] != '=' or writes[0]['rhs'].strip() not in inputs:
            continue
        input_name = writes[0]['rhs'].strip()
        if (re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(input_name) + r'\b', context)
                or re.search(r'\b(?:s8|u8|s16|u16|s32|u32|int|char|short|long|float|double)\s+' + re.escape(input_name) + r'\b', body)
                or re.search(r'\b' + re.escape(input_name) + r'\b', part.clean[max(part.clean.rfind(';', 0, part.opening), part.clean.rfind('}', 0, part.opening)) + 1:part.opening])):
            continue
        macros = re.findall(r'(?m)^\s*#\s*define\b(?:[^\n\\]|\\\n)*', context)
        if any(re.search(r'\b' + f + r'\b', macro) for macro in macros):
            continue
        prefix = body[:writes[0].start()]
        if (prefix.count('{') - prefix.count('}') != 1
                or not re.search(r'(?m)^[ \t]*$', prefix[prefix.rfind('\n') + 1:])
                or re.search(r'\b(?:if|else|while|for|switch)\b[^;{}]*$', prefix.rstrip())):
            continue
        if any(w['op'] not in ('=', '+=', '-=') or not re.fullmatch(NUM, w['rhs'].strip()) for w in writes[1:]):
            continue
        if sum(abs(float(w['rhs'].strip()[:-1])) for w in writes[1:]) > 10000:
            continue
        start_match = re.match(r'\s*if\s*\(\s*' + f + r'\s*[<>]\s*' + NUM + r'\s*\)', body[writes[0].end():])
        if not start_match:
            continue
        block_start = part.opening + writes[0].end() + start_match.start() + len(start_match[0]) - len(start_match[0].lstrip())
        block_end = _statement_end(part.clean, block_start, part.end)
        if block_end < 0 or re.search(r'\b(?:break|continue|goto|case|default)\b|(?<![\w?:])' + IDENT + r'\s*:(?!:)', part.clean[block_start:block_end]):
            continue
        for store in re.finditer(r'\b(' + IDENT + r')\s*=\s*0\s*;', body[block_end - part.opening:]):
            out = store[1]
            if out not in outputs:
                continue
            start = block_end + store.start()
            stop = block_end + store.end()
            for carrier in ints:
                c = re.escape(carrier)
                if re.search(r'\b' + c + r'\b', part.clean[stop:part.end]) or re.search(r'&\s*' + c + r'\b', body):
                    continue
                if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:' + c + '|' + f + '|' + re.escape(out) + r')\b', context):
                    continue
                replacement = f'{{ {carrier} = (s32){floating}; {out} = {carrier} & ~{carrier}; }}'
                result.append((FAMILY, edit(source, [(block_start, block_start, 'do { '),
                                                      (block_end, block_end, ' } while (0);'),
                                                      (start, stop, replacement)])))
    return result[:32]


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'asm', 'flags', 'header'), 'archs': ('mips',), 'order': 42}
