"""The element a block's member stores share, taken as a pointer at the block's head.

A record writer that stores `out[n].x0 = ...; out[n].y0 = ...;` through a pointer parameter compiles with the element's
address built where the first store needs it. A target that builds it earlier (the index read into `$v0` at the loop
head, the address ready before the reads the stores use) took the pointer first (after the loop's own exit test):

    for (...) {                         for (...) {
        a = table[...];                     element = &out[n];
        ...                       ->        a = table[...];
        out[n].x0 = ...a...;                ...
        out[n].y0 = ...a...;                element->x0 = ...a...;

`repeated_element_pointer` does the global-table form for one run of statements; this one is for a pointer parameter or
local and puts the address ahead of everything else in the block. A 209-instruction N64 triangle emitter (SN GCC 2.8.1
`-G0 -mips3 -O2`) went 1320 -> 850 with it (measured with the app's judge; one function).

`variants` looks for three or more member stores `P[I].m = ...;` standing directly in one braced block, `P` a pointer
the function declares `T *P` and never assigns, `I` a plain local or parameter that nothing in the block changes before
the last of those stores, neither with its address taken. The judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'element_pointer_block_head'
FAMILIES = (FAMILY,)
LIMIT = 4
STORES = 3
IDENT = r'[A-Za-z_]\w*'
STORE = re.compile(rf'(?<![\w.>])(?P<base>{IDENT})\s*\[\s*(?P<index>{IDENT})\s*\](?=\s*\.\s*{IDENT}\s*=(?!=))')
DECLARATION = re.compile(rf'\s*(?!(?:return|goto|else|case)\b)(?:(?:const|struct|union|unsigned|signed|register)\s+)*'
                         rf'{IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*(?:\[[^\]]*\]\s*)?(?:=[^;{{}}]*)?(?:,[^;{{}}]*)?;')


def _blocks(clean, opening, end):
    """(open, close) of every braced block of the function, its body included."""
    for at in range(opening, end):
        if clean[at] == '{':
            stop = close(clean, at, '{', '}')
            if stop:
                yield at, stop - 1


def _direct(clean, low, high, at):
    """Whether `at` stands in the block (low, high) itself, not in a block or statement nested in it."""
    depth = 0
    for ch in clean[low + 1:at]:
        depth += ch == '{'
        depth -= ch == '}'
    before = clean[low + 1:at].rstrip()
    return not depth and (not before or before[-1] in ';{}')


def _changed(text, name):
    return re.search(rf'(?<![\w.>]){name}\s*(?:\+\+|--|(?:[-+*/%|&^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{name}\b', text)


def _exit_test(clean, at, high):
    """The end of an `if (c) break;` / `if (c) goto L;` / `if (c) { return x; }` that begins at `at`, or None."""
    head = re.compile(r'\s*if\s*\(').match(clean, at, high)
    test = close(clean, head.end() - 1, '(', ')') if head else None
    if not test:
        return None
    leave = re.compile(r'\s*(\{)?\s*(?:break|continue|return\b[^;{}]*|goto\s+\w+)\s*;(?(1)\s*\})').match(clean, test, high)
    if not leave or re.compile(r'\s*else\b').match(clean, leave.end(), high):
        return None
    return leave.end()


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end] or re.search(r'\b(?:asm|__asm__|volatile)\b', clean[opening:end]):
        return []
    function = clean[span[0]:end]
    taken = re.search(r'\belement\w*\b', function)
    pointer, number = 'element', 1
    while taken and re.search(rf'\b{pointer}\b', function):
        number += 1
        pointer = f'element{number}'
    out = []
    for low, high in _blocks(clean, opening, end):
        groups = {}
        for hit in STORE.finditer(clean, low + 1, high):
            if _direct(clean, low, high, hit.start()):
                groups.setdefault((hit['base'], hit['index']), []).append(hit)
        for (base, index), hits in groups.items():
            if len(hits) < STORES or base == index:
                continue
            kind = re.search(rf'\b((?:(?:const|struct|union|unsigned|signed)\s+)*{IDENT})\s*\*\s*{base}\s*(?=[,;)=])',
                             function)
            if not kind or _changed(clean[opening:end], base) \
                    or re.search(rf'&\s*(?:{base}|{index})\b(?!\s*(?:\[|->|\.))', function):
                continue
            if not re.search(rf'\b{IDENT}[ \t*]+{index}\s*(?=[;,)=\[])|,\s*{index}\s*(?=[,;])', function):
                continue
            start = low + 1
            while (declared := DECLARATION.match(clean, start, high)):
                start = declared.end()
            while (left := _exit_test(clean, start, high)):  # a loop's exit test stays first
                start = left
            last = hits[-1].start()
            # a label would let a jump skip the assignment; a change of the index would move the element
            if _changed(clean[start:last], index) or re.search(rf'(?m)^\s*(?!default\b){IDENT}\s*:(?!:)',
                                                               clean[start:last]) \
                    or re.search(r'\bcase\b|\bdefault\s*:', clean[start:last]):
                continue
            text = source
            for hit in reversed(hits):
                member = clean.index('.', hit.end())
                text = text[:hit.start()] + f'{pointer}->' + text[member + 1:].lstrip(' \t')
            following = source[start:high]
            line = following.lstrip('\n').split('\n')[0]
            indent = re.match(r'[ \t]*', line)[0] or '    '
            text = text[:start] + f'\n{indent}{pointer} = &{base}[{index}];' + text[start:]
            body = text.index('\n', opening) + 1
            text = text[:body] + f'    {" ".join(kind[1].split())} *{pointer};\n' + text[body:]
            out.append((FAMILY, text))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 905}  # registry.py
