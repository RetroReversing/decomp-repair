"""A global pointer the game reloads after each store through it: declared `volatile`.

When code stores through a global pointer several times, gcc 2.7.2 keeps the pointer in a register across the
stores; a game whose code loads it again from memory before each store had a pointer that could change (an
interrupt, or a `volatile` declaration in its header). Two N64 functions setting four fields through one global
pointer were about 1000 points off with m2c's `extern void *D;` and 40 and 80 with `extern void *volatile D;`.
`volatile` only adds loads, so the meaning is the same; the family offers it for each extern pointer global that is
stored through at least twice in the function, one global at a time, and carries the qualifier to m2c's
`T **__base_D = &D;` locals so they still compile.
"""
import re

from .csource import _blank, find

FAMILY = 'volatile_reload'
FAMILIES = (FAMILY,)

EXTERN_POINTER = re.compile(r'^([ \t]*extern\s+[\w\s]*?\w[\s*]*?)\*\s*([A-Za-z_]\w*)\s*;', re.M)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    result = []
    for m in EXTERN_POINTER.finditer(clean, 0, span[0]):
        glob = m[2]
        if 'volatile' in m[0]:
            continue
        # (a store through the pointer: `*(T *)((char *)(D) + off) =`, `D->f =`, `((T *)D)[i] =`)
        stores = re.findall(rf'(?:\(\s*{glob}\s*\)|\b{glob}\b)[^;=]*?[\]\)]\s*=(?!=)|\b{glob}\s*->\s*\w+\s*=(?!=)', body)
        if len(stores) < 2:
            continue
        text = source[:m.start()] + source[m.start():m.end()].replace(f'*{glob}', f'*volatile {glob}').replace(
            f'* {glob}', f'*volatile {glob}') + source[m.end():]
        offset = len(text) - len(source)
        start, end = span[0] + offset, span[1] + offset
        local = re.sub(rf'(\bvoid\s*)\*\s*\*\s*(__base_{glob}\b)', r'\1*volatile *\2', text[start:end])
        text = text[:start] + local + text[end:]
        if text != source:
            result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result
