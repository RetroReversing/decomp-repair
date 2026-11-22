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

from .call_lifetime_repairs import block_path
from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'volatile_reload'
SPLIT_FAMILY = 'split_volatile_pointer_reloads'
FAMILIES = (FAMILY, SPLIT_FAMILY)

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
    return split_reloads(source, name) + result

def split_reloads(source, name):
    """Give consecutive volatile snapshots separate local lifetimes without moving any access."""
    part = view(source, name)
    if (not part or not re.search(r'\*\s*volatile\b', part.clean[:part.opening])
            or re.search(r'\bgoto\b', part.body)):
        return []
    declared = re.findall(rf'\bextern\s+(?P<type>{IDENT})\s*\*\s*volatile\s+(?P<global>{IDENT})\s*;',
                          part.clean[:part.opening])
    result = []
    for kind, symbol in declared:
        assignment = re.compile(rf'(?P<local>{IDENT})\s*=\s*{symbol}\s*;')
        blocks = {}
        for hit in assignment.finditer(part.clean, part.opening + 1, part.end - 1):
            scope = block_path(part, hit.start())
            if (len(scope) == 2 and part.clean[scope[-1] + 1:hit.start()].rstrip()[-1:] in {'', ';'}
                    and re.search(r'\bif\s*\([^;{}]*\)\s*$', part.clean[part.opening + 1:scope[-1]])):
                blocks.setdefault(scope[-1], []).append(hit)
        for opening, loads in blocks.items():
            if not 2 <= len(loads) <= 8:
                continue
            end = close(part.clean, opening, '{', '}')
            if not end:
                continue
            block = part.clean[opening + 1:end - 1]
            if re.search(r'[{}#:]|\b(?:return|break|continue|goto|asm|__asm__)\b', block):
                continue
            changes = []
            for i, load in enumerate(loads):
                local = load['local']
                definitions = list(re.finditer(rf'\b{IDENT}\s*\*+\s*{local}\s*(?=[;=,\[])', part.body))
                if len(definitions) != 1 or not re.fullmatch(rf'{kind}\s*\*\s*{local}\s*', definitions[0][0]):
                    break
                if block_path(part, part.opening + 1 + definitions[0].start()) != [part.opening]:
                    break
                if re.search(rf'(?m)^\s*#\s*define[^\n]*\b(?:{local}|{symbol})\b|'
                             rf'(?<!&)&(?!&)\s*(?:\(\s*)*{local}\b', part.clean):
                    break
                if re.search(rf'\b{local}\b', part.clean[end:part.end]):
                    break
                stop = next((later.start() for later in loads[i + 1:] if later['local'] == local), end - 1)
                uses = part.clean[load.end():stop]
                if re.search(rf'\b{local}\s*(?:[+*/%&|^\-]?=(?!=)|\+\+|--)'
                             rf'|(?:\+\+|--|\.|->)\s*{local}\b', uses):
                    break
                fresh = f'__repair_pointer_reload_{i}'
                while re.search(rf'\b{fresh}\b', part.clean):
                    fresh += '_'
                edits = [(load.start('local'), load.end('local'), fresh)]
                edits.extend((load.end() + hit.start(), load.end() + hit.end(), fresh)
                             for hit in re.finditer(rf'\b{local}\b', uses))
                changes.append((f'{kind} *{fresh};', edits))
            else:
                for selected in [changes, *([item] for item in changes)]:
                    declarations = '\n' + '\n'.join(text for text, _ in selected) + '\n'
                    edits = [item for _, items in selected for item in items]
                    edits.append((part.opening + 1, part.opening + 1, declarations))
                    result.append((SPLIT_FAMILY, edit(source, edits)))
                if len(result) >= 8:
                    return result[:8]
    return result[:8]
