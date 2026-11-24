"""A global that a switch arm stores to after a call, written through a pointer the arm takes at its start.

    case 0x19: ...; setClipSlotValue(...); D_800FDB9C = 4; r = f(arg0, &D_800FDB9C); break;
 -> case 0x19: { u32 *cmd = &D_800FDB9C; ...; setClipSlotValue(...); *cmd = 4; r = f(arg0, &D_800FDB9C); break; }

A sound-sequence interpreter's handlers take the command word's address (`u32 *cmd`) and, after a call, write a new
opcode through it. The target holds the address in a saved register from the arm's start (`lui $s0; addiu $s0` among
the arm's first loads) and stores `sw $v0, ($s0)` after the call; m2c writes the store to the symbol itself, which GCC
emits as `lui $at; sw %lo(sym)($at)` after the call. On a 1315-instruction KMC GCC 2.7.2 interpreter (`-G0 -mips3
-mgp32 -mfp32 -O2`) two arms written this way took 14360 -> 13735 (one alone 13900).

`arm_global_store_pointer`
    In each top-level `case` arm that ends in `break;` and has no nested `case`/`default`, a statement `SYM = E;` that
    follows a call in the arm, where `SYM` is a scalar global the source declares (`extern T SYM;`): the arm becomes a
    block opening with `T *p = &SYM;` and the store is `*p = E;`. Children: every such arm at once, then each alone.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'arm_global_store_pointer'
FAMILIES = (FAMILY,)
LIMIT = 8
POINTER = 'ptr'


def _arms(clean, opening, end):
    labels = []
    depth = 0
    at = opening + 1
    while at < end - 1:
        char = clean[at]
        if char in '{(':
            depth += 1
        elif char in '})':
            depth -= 1
        elif depth == 0 and not re.match(r'\w', clean[at - 1]):
            hit = re.match(r'(?:case\b[^:;{}]*|default\s*):(?!:)', clean[at:end])
            if hit:
                labels.append((at, at + hit.end()))
                at += hit.end()
                continue
        at += 1
    return [(body, labels[n + 1][0] if n + 1 < len(labels) else end - 1) for n, (_, body) in enumerate(labels)]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    outside = _blank(source[:part.opening])
    globals_ = dict((m[2], m[1].strip()) for m in re.finditer(
        r'(?m)^\s*extern\s+((?:(?:unsigned|signed|volatile)\s+)*' + IDENT + r')\s+(' + IDENT + r')\s*;', outside))
    sites = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        paren = part.opening + switch.end() - 1
        after = close(clean, paren, '(', ')')
        brace = re.match(r'\s*{', clean[after:]) if after else None
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        for start, stop in _arms(clean, opening, end):
            text = clean[start:stop]
            final = re.search(r'\bbreak\s*;(?=\s*$)', text)
            if not final or re.search(r'\b(?:case|default)\b', text) or re.search(r'\b' + POINTER + r'\b', text):
                continue
            for store in re.finditer(r'(?:(?<=[;{}])|^)\s*(' + IDENT + r')\s*=(?!=)\s*([^;]*);', text):
                symbol = store[1]
                if symbol not in globals_ or '*' in globals_[symbol]:
                    continue
                before = text[:store.start(1)]
                if not re.search(r'\b(?!if\b|while\b|for\b|switch\b|return\b|sizeof\b)' + IDENT + r'\s*\(', before):
                    continue
                if re.search(r'\b' + re.escape(symbol) + r'\s*=(?!=)', before):
                    continue
                sites.append((start, start + final.end(), start + store.start(1), start + store.end(), symbol,
                              store[2].strip()))
                break
    if not sites:
        return []

    def apply(chosen):
        edits = []
        for arm_start, arm_end, store_start, store_end, symbol, value in chosen:
            kind = re.sub(r'\bvolatile\s+', '', globals_[symbol])
            edits.append((arm_start, arm_start, f'\n      {{\n        {kind} *{POINTER} = &{symbol};'))
            edits.append((store_start, store_end, f'*{POINTER} = {value};'))
            edits.append((arm_end, arm_end, '\n      }'))
        return edit(source, edits)

    results = [(FAMILY, apply(sites))]
    if len(sites) > 1:
        results.extend((FAMILY, apply([site])) for site in sites[:LIMIT])
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
