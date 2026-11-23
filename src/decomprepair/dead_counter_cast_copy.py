"""A parameter's cast, and the local that already holds it, written as one copy kept in a dead loop counter.

After a scan loop the function stores through a slot computed from the same narrow parameter twice: once as the
argument of an inline helper (`inline_fn(((u8) action))`) and once as the local m2c kept (`id | (value << 8)`), where
`id = (u8) action;` was set a few statements earlier. The hand-written original used one halfword local for both, and
that local was the loop counter, dead after the loop. Sharing the counter's pseudo changes GCC 2.7.2's allocation (its
reference count and live range grow, so the global allocator ranks it ahead of the others, global.c) and the
zero-extension is recomputed at the store, not carried from the earlier `id`. A slot setter (KMC GCC 2.7.2,
`-O2 -G0 -mips3`) stood at 115 and at 65 with this one step, the chain's next steps closing it to 20 and then 15; the
reading of the allocator is a hypothesis the measurement agrees with, and the judge decides each child.

The child (`dead_counter_cast_copy`, one per qualifying statement) puts `C = (E);` before a statement that mentions the
cast `E` of a parameter, and replaces `E` and a local `V` that was last assigned `V = E;` in the same or an enclosing
block (nothing assigned in between) by `C` in that statement, where `C` is an integer local declared in the function that
is not mentioned after the statement and is assigned in a loop before it (a counter). `E` is a one-cast expression of a
parameter or local that nothing in the statement or between the assignment and the statement writes.
"""
import re

from .csource import _blank, find

FAMILY = 'dead_counter_cast_copy'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'
INTEGERS = r'(?:u8|s8|u16|s16|u32|s32|int|short|char|unsigned(?:\s+(?:int|short|char))?)'
CAST = rf'\(\s*\(\s*(?:u8|s8|u16|s16)\s*\)\s*{IDENT}\s*\)|\(\s*(?:u8|s8|u16|s16)\s*\)\s*{IDENT}'


def _statement_bounds(clean, position, opening):
    """The `;`-terminated statement holding `position`, as (begin, end) with end after the `;`."""
    begin = max(clean.rfind(';', opening, position), clean.rfind('{', opening, position), clean.rfind('}', opening, position)) + 1
    depth = 0
    for index in range(position, len(clean)):
        depth += clean[index] in '([{'
        depth -= clean[index] in ')]}'
        if depth < 0:
            return None
        if clean[index] == ';' and depth == 0:
            return begin, index + 1
    return None


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    params = set(re.findall(rf'\b{IDENT}(?=\s*[,)])', clean[start:opening]))
    counters = [n for n in re.findall(rf'\b(?:s16|u16|s32|u32|int|short)\s+({IDENT})\s*;', clean[opening:end])]
    counters += [n for decl in re.findall(r'\b(?:s16|u16|s32|u32|int|short)\s+([^;()]+);', clean[opening:end]) for n in re.findall(IDENT, decl)]
    result = []
    for statement in re.finditer(r'[^;{}]+;', clean[opening:end]):
        begin, stop = opening + statement.start(), opening + statement.end()
        text = clean[begin:stop]
        for cast in dict.fromkeys(re.findall(CAST, text)):
            inner_cast = re.fullmatch(r'\(\s*(\(\s*\w+\s*\)\s*\w+)\s*\)', cast.strip())
            value = inner_cast[1] if inner_cast else cast.strip()
            param = re.findall(IDENT, value)[-1]
            if param not in params and param not in counters:
                continue
            locals_assigned = re.finditer(rf'(?<![\w.>])({IDENT})\s*=(?!=)\s*{re.escape(value)}\s*;', clean[opening:begin])
            held = None
            for hit in locals_assigned:
                held = hit
            if held is None or held[1] in params:
                continue
            between = clean[opening + held.end():begin]
            if re.search(rf'(?<![\w.>])(?:{held[1]}|{param})\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\+\+|--', between + text.replace(held[1] + ' ', ' ')):
                continue
            depth = 0
            enclosing = True
            for char in between:
                depth += char == '{'
                depth -= char == '}'
                if depth < 0:
                    enclosing = False
                    break
            if not enclosing or not re.search(rf'(?<![\w.>]){held[1]}\b', text):
                continue
            for counter in dict.fromkeys(counters):
                if counter == held[1] or re.search(rf'(?<![\w.>]){counter}\b', clean[stop:end]):
                    continue
                if not re.search(rf'(?<![\w.>]){counter}\b', clean[opening:begin]):
                    continue
                if re.search(rf'(?<![\w.>]){counter}\b', text):
                    continue
                inner = source[begin:stop]
                inner = re.sub(re.escape(cast), counter, inner)
                inner = re.sub(rf'(?<![\w.>]){held[1]}\b', counter, inner)
                replaced = f'{counter} = {value}; ' + inner.lstrip()
                child = source[:begin] + (source[begin:stop][:len(source[begin:stop]) - len(source[begin:stop].lstrip())]) + replaced + source[stop:]
                if child != source and child not in result:
                    result.append(child)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
