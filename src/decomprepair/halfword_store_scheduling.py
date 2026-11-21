"""Pair a signed halfword load and its scheduled word store on old MIPS GCC."""
import re

from .csource import _blank, find

FLAG = '-fno-schedule-insns'
IDENT = r'[A-Za-z_]\w*'
ADDRESS = rf'(?P<{{}}>{IDENT})(?:\s*\+\s*{IDENT})?'
LOAD = re.compile(
    rf'\b(?P<value>{IDENT})\s*=\s*\*\s*\(\s*(?P<type>volatile\s+s32)\s*\*\s*\)'
    rf'\s*\(\s*{ADDRESS.format("src")}\s*\)\s*;'
)
STEP = rf'(?:\s*{IDENT}\s*(?:\+\+|\+=\s*(?:0[xX][\da-fA-F]+|\d+))\s*;)*'
TARGET = re.compile(
    rf'\blh\s+(\$\w+),\s*%lo\(({IDENT})\)\(\$\w+\)\s*\n'
    rf'(?:[^\S\n]*(?:addiu|addu|lui)\s+[^\n]+\n){{0,6}}'
    rf'[^\S\n]*sw\s+\1,\s*%lo\(({IDENT})\)\(\$\w+\)'
)


def probes(proj, fn, profile):
    """Use target symbols and the copied value to tie the C accesses to one instruction pair."""
    if proj.get('arch') != 'mips' or profile['toolchain'] != 'gcc-2.7.2-kmc':
        return []
    source = fn['best_source']
    span = find(source, fn['name'])
    if not span:
        return []
    target = re.sub(r'/\*[^\n]*?\*/', '', fn.get('asm') or '')
    pairs = {(hit[2], hit[3]) for hit in TARGET.finditer(target)}
    if not pairs:
        return []
    clean = _blank(source)
    flags = tuple(flag for flag in profile['flags'] if flag not in ('-fschedule-insns', FLAG)) + (FLAG,)
    result = []
    for load in LOAD.finditer(clean, *span):
        store = re.compile(
            rf'{STEP}\s*\*\s*\(\s*(?P<type>s32)\s*\*\s*\)'
            rf'\s*\(\s*{ADDRESS.format("dst")}\s*\)\s*=\s*{load["value"]}\s*;'
        ).match(clean, load.end(), span[1])
        if (store and (load['src'], store['dst']) in pairs
                and not re.search(rf'\b{load["value"]}\b', clean[load.end():store.start('type')])):
            child = (source[:load.start('type')] + 's16'
                     + source[load.end('type'):store.start('type')] + 'volatile '
                     + source[store.start('type'):])
            result.append((flags, child))
            if len(result) == 2:
                break
    return result
