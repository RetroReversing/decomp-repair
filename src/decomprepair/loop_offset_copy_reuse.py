"""A count read several times by one statement before a loop, read there through a copy that the compiler keeps: the
copy is a variable the later loop also uses (its counter, or a byte offset stepped beside it).

SN64 GCC 2.8.1 (`-G8 -mips3 -O2 -mfp32`), a 141-instruction N64 animation-player init: the target loads the count
(`lh $v1, 0xC($a1)`), stores it, then copies it (`addu $a1, $v1, $zero`) and builds the allocation size
`n * 36 + n * 36 + n * 12 + ...` from the copy. Every spelling of a plain copy (`m = n;` before the size, in or out of
a `do { } while (0)` fence, a helper, `p->count` reads) compiled to no `move` at all. Read in the `-ds`/`-dl` dumps:

- cse keeps one register per equivalence class and rewrites the copy's uses to the class's first register; a new
  register only becomes the first (`make_regs_eqv`) when it lives outside the current cse block and longer than the
  old one. The do-while(0) fences split cse1's blocks, but after loop.c the rerun of cse sees one block up to the loop,
  so the copy's uses become `n` again and the copy is deleted (`m` was gone from `.cse2`).
- Even a surviving copy is tied to its source by local-alloc (`combine_regs`, the source dies at the copy) unless the
  destination is not local to one block.
- A variable the later loop uses lives across blocks: cse2 makes it the class head (its last use is in the loop) and
  global.c allocates it apart from `n`. The loop's counter does that (110 -> 30, the copy then in the counter's
  register); a byte offset stepped beside the counter (`off = 0; ... off += sizeof(*joints)`, the record read as
  `((T *)(off + (s32) joints))->f`, the offset first as in the target's `addu $v0, $a1, $v0`) takes the register
  the target has, and a float constant the loop reads set into a local at the head of the guard keeps the target's
  preheader order (the constant's load before the offset's `move`): 30 -> 0 with the loop as `i = 0; if (i < n) {
  ..; do { ..; i++; off += ..; } while (i < n); }`.

Children: the statement's reads through the loop counter (`i = n;` before it); the statement through a new byte offset
that the loop steps, with the loop's float globals set into locals at the guard's head; the same without them.
Needs a `for (i = 0; i < B; i++)` loop with a braced body and no `break`/`continue`/`goto`/label, a statement before it
that reads a word local three or more times and assigns nothing to it, and, for the offset children, records read in
the body as `E[i]` where `E` does not mention the counter.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILIES = ('loop_counter_copy_reuse', 'loop_offset_copy_reuse', 'loop_offset_copy_reuse_plain')
LIMIT = 6

_IDENT = r'[A-Za-z_]\w*'
_WORD = r'(?:s32|u32|int|signed\s+int|unsigned\s+int|unsigned)'
_ESCAPE = re.compile(r'\b(?:goto|break|continue|return|switch)\b|(?:^|[;{}])\s*' + _IDENT + r'\s*:(?!:)')


def _fresh(clean, base):
    name, n = base, 2
    while re.search(r'\b' + name + r'\b', clean):
        name, n = f'{base}{n}', n + 1
    return name


def _for_loops(clean, lo, hi):
    for m in re.finditer(r'\bfor\s*\(\s*(' + _IDENT + r')\s*=\s*0\s*;', clean[lo:hi]):
        paren = lo + m.end() - len(m[0]) + m[0].index('(')
        stop = close(clean, paren)
        if stop is None:
            continue
        parts = clean[paren + 1:stop - 1].split(';')
        var = m[1]
        if len(parts) != 3:
            continue
        bound = re.fullmatch(r'\s*' + var + r'\s*<\s*([^;]+?)\s*', parts[1])
        step = re.fullmatch(r'\s*(?:' + var + r'\s*\+\+|\+\+\s*' + var + r'|' + var + r'\s*\+=\s*1)\s*', parts[2])
        brace = stop
        while brace < hi and clean[brace].isspace():
            brace += 1
        if not bound or not step or brace >= hi or clean[brace] != '{':
            continue
        end = close(clean, brace, '{', '}')
        if end is None:
            continue
        yield lo + m.start(), end, brace, var, bound[1]


def _statement_before(clean, opening, loop_start, counter):
    """[(start, end, var)] of the simple statements before the loop that read a word local three or more times."""
    found = []
    decls = dict.fromkeys(re.findall(r'(?:^|(?<=[;{}]))\s*' + _WORD + r'\s+(' + _IDENT + r')\s*;', clean[opening:loop_start]))
    for m in re.finditer(r'[^;{}]+;', clean[opening + 1:loop_start]):
        text = m[0]
        start = opening + 1 + m.start() + (len(text) - len(text.lstrip()))
        for var in decls:
            if var == counter:
                continue
            reads = re.findall(r'(?<![\w.>])' + var + r'\b', text)
            if len(reads) >= 3 and not re.search(r'(?<![\w.>])' + var + r'\s*(?:[-+*/%&|^]?=(?!=)|\+\+|--)', text):
                found.append((start, opening + 1 + m.end(), var))
    return found


def _replace_var(text, var, new):
    return re.sub(r'(?<![\w.>])' + var + r'\b', new, text)


def _indent(text, at):
    line = text.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', text[line:])[0]


def _records(body, counter):
    """The record expressions `E` read as `E[counter]` in the body, first seen first."""
    found = []
    for m in re.finditer(r'((?:' + _IDENT + r')(?:\s*(?:->|\.)\s*' + _IDENT + r')*)\s*\[\s*' + counter + r'\s*\]', body):
        if re.search(r'\b' + counter + r'\b', m[1]) or m[1] in found:
            continue
        found.append(m[1])
    return found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    results = []
    floats = set(re.findall(r'\bextern\s+(?:f32|float)\s+(' + _IDENT + r')\s*;', clean))
    for loop_start, loop_end, brace, counter, bound in _for_loops(clean, opening + 1, end - 1):
        body = source[brace + 1:loop_end - 1]
        if _ESCAPE.search(clean[brace + 1:loop_end - 1]) or re.search(r'\b' + counter + r'\s*(?:[-+*/%&|^]?=(?!=)|\+\+|--)',
                                                                       clean[brace + 1:loop_end - 1]):
            continue
        for start, stop, var in _statement_before(clean, opening, loop_start, counter):
            if re.search(r'\b' + counter + r'\b', clean[start:loop_start]):
                continue  # the counter is read between the statement and its loop
            indent = _indent(source, start)
            statement = source[start:stop]
            # 1: through the loop counter
            text = source[:start] + f'{counter} = {var};\n{indent}' + _replace_var(statement, var, counter) + source[stop:]
            results.append((FAMILIES[0], text))
            records = _records(clean[brace + 1:loop_end - 1], counter)
            if not records:
                continue
            offset = _fresh(clean, 'off')
            inner = _indent(source, brace + 1 + len(body) - len(body.lstrip())) if body.strip() else indent + '    '
            for record in records:
                pattern = re.compile(re.escape(record).replace(r'\ ', r'\s*') + r'\s*\[\s*' + counter + r'\s*\]\s*(\.)?')

                def view(m, record=record, offset=offset):
                    cast = f'((__typeof__({record}))({offset} + (s32){record}))'
                    return cast + '->' if m[1] else f'(*{cast})'
                new_body = pattern.sub(view, body)
                for hoist in (True, False):
                    used = [f for f in sorted(floats) if re.search(r'\b' + f + r'\b', new_body)] if hoist else []
                    if hoist and not used:
                        continue
                    locals_, head, loop_body = [], [], new_body
                    for k, sym in enumerate(used):
                        local = _fresh(clean, f'k{k}')
                        locals_.append(f'f32 {local};')
                        head.append(f'{indent}    {local} = {sym};\n')
                        loop_body = re.sub(r'\b' + sym + r'\b', local, loop_body)
                    loop = (f'{counter} = 0;\n{indent}if ({counter} < {bound}) {{\n' + ''.join(head)
                            + f'{indent}    {offset} = 0;\n{indent}    do {{' + loop_body.rstrip() + '\n'
                            + f'{inner}{counter}++;\n{inner}{offset} += sizeof(*{record});\n'
                            + f'{indent}    }} while ({counter} < {bound});\n{indent}}}')
                    text = (source[:start] + f'{offset} = {var};\n{indent}' + _replace_var(statement, var, offset)
                            + source[stop:loop_start] + loop + source[loop_end:])
                    decls = '\n    '.join([f's32 {offset};'] + locals_)
                    text = text[:opening + 1] + '\n    ' + decls + text[opening + 1:]
                    results.append((FAMILIES[1] if hoist else FAMILIES[2], text))
    seen, unique = set(), []
    for family, text in results:
        if text != source and text not in seen:
            seen.add(text)
            unique.append((family, text))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
