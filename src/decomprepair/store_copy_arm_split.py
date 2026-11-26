"""An indexed byte store written as a pointer copy plus an index add in the two identical arms of a guard, the base copy
GCC 2.7.2 keeps as a `move`.

Found by matching a KMC N64 string-decode function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 230 -> 0) whose loop
stores each decoded byte twice, `buf[i] -= 1` through the first address and then `buf[i + 1] = c`. The target's second
store is `move $v0,$a0; addu $v0,$v0,$a2; ... sb $v1,($v0)`: the base pointer copied into a register of its own and the
index added to the copy. Every spelling of the store that a compiler folds (`buf[i]`, `*(buf + i)`, `q = buf; q += i;
*q = c;`, casts, inline helpers, 400 of them tried) came out as one `addu $v0,$a0,$a2`.

Why (the cc1 dumps and combine.c / flow.c, read in the source): cse leaves `q = buf` alone and combine folds a copy into
the add that uses it only when the two insns are in one basic block (flow.c builds a LOG_LINK from a use to the set that
feeds it only inside a block, and `can_combine_p` refuses to move a source across a set). Cross-jumping runs after
register allocation (jump2), so two identical arms are still two blocks at combine time and merge afterwards. With the
add written in both arms of an `if (g) { q += i; } else { q += i; }` the copy sits in the block before the guard and the
add in the blocks after it: combine cannot fold them, and jump2 then merges the arms and drops the branch (which tests a
register that is already live), leaving `move; addu` straight-line. Those are hypotheses read from the dumps and the
source of the passes, not a confirmed trace of the original.

Three edits that are no better alone make the function match, so `store_copy_arm_split` offers them as one child:

1. the store itself, as the copy plus the guarded add (230 -> 30 alone: the registers of the buffer pointer and of the
   string pointer are exchanged);
2. the earlier statement that forms the same address (`t = buf + i;`) in one `do { } while (0)` scope, and the copy in
   one or two: flow.c counts a reference once more for every loop round it, so the buffer pointer's priority
   (refs * log2 refs / live length, global.c) passes the string pointer's;
3. the scope that held both the store through that address and the next byte's load, split so the load is outside it
   (the load inside it kept the string pointer's references one loop deeper than the buffer's).

`store_copy_arm_split_plain` offers step 1 alone. The wrappers are scaffolding no developer wrote and so is the guard;
polishing removes them once the match is recorded. The guard is a local or parameter the loop already reads (its compare
is free: the branch disappears with the arms); `D_` globals are not used, they would add a load.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'store_copy_arm_split'
PLAIN = 'store_copy_arm_split_plain'
FAMILIES = (FAMILY, PLAIN)
POINTER = 'q_as'
GUARDS = 4
LIMIT = 40
_CAST = r'(?:\(\s*(?:unsigned\s+char|u8)\s*\)\s*)?'
_SCALAR = re.compile(r'\b(?:float|double|f32|f64|volatile)\b')
_DECLARATION = re.compile(rf'^[ \t]*(?P<type>(?:(?:unsigned|signed|const|struct|union)\s+)*{IDENT})(?P<gap>[ \t]*\*+[ \t]*|[ \t]+)'
                          rf'(?P<name>{IDENT})(?P<array>\s*\[\s*\w+\s*\])?\s*;[ \t]*$')
_STORE = re.compile(rf'(?<![\w\]\)])(?P<p>{IDENT})\s*\[\s*{_CAST}(?P<i>{IDENT})\s*\]\s*=\s*(?P<v>{IDENT})\s*;')
_FENCE = re.compile(r'do\s*\{(?P<body>[^{}]*)\}\s*while\s*\(\s*0\s*\)\s*;')


def _wrap(text, depth):
    return 'do { ' * depth + text.strip() + ' } while (0);' * depth


def _declarations(part):
    """({name: (type, kind)}, offset past the leading declarations): kind is 'ptr', 'array' or 'scalar'."""
    found, at, last = {}, part.opening + 1, None
    for line in part.clean[part.opening + 1:part.end].split('\n'):
        stop = at + len(line)
        match = _DECLARATION.match(line)
        if not match:
            if line.strip():
                break
        else:
            kind = 'array' if match['array'] else 'ptr' if '*' in match['gap'] else 'scalar'
            found[match['name']] = (match['type'], kind)
            last = stop + 1
        at = stop + 1
    return found, last


def _parameters(part):
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head and ')' in head else ''
    found = {}
    for piece in signature.split(','):
        match = re.match(rf'\s*(?P<type>(?:(?:unsigned|signed|const|struct|union)\s+)*{IDENT})(?P<gap>[\s*]+)(?P<name>{IDENT})\s*$', piece)
        if match:
            found[match['name']] = (match['type'], 'ptr' if '*' in match['gap'] else 'scalar')
    return found


def _loops(clean, part):
    """The brace spans (start of `{`, end past `}`) of the do, for and while loop bodies in the function."""
    spans = []
    for hit in re.finditer(r'\bdo\s*\{|\b(?:for|while)\s*\(', clean[part.opening:part.end]):
        at = part.opening + hit.end() - 1
        if clean[at] == '(':
            stop = close(clean, at, '(', ')')
            if not stop:
                continue
            tail = re.match(r'\s*\{', clean[stop:])
            if not tail:
                continue
            at = stop + tail.end() - 1
        end = close(clean, at, '{', '}')
        if end:
            spans.append((at, end))
    return spans


def _guards(clean, part, span, names, avoid):
    """Locals and parameters the loop does not assign, longest-lived first (their mentions span the most source, so the
    allocator ranks them last and the extra read in the guard cannot lift one above the pointers under contest)."""
    text = clean[span[0]:span[1]]
    found = []
    for n in names:
        if n in avoid:
            continue
        if re.search(rf'(?<![\w.>]){re.escape(n)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(n)}\b|\b{re.escape(n)}\s*(?:\+\+|--)', text):
            continue
        mentions = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(n)}\b', clean[part.opening:part.end])]
        if len(mentions) >= 2:
            found.append((mentions[0] - mentions[-1], n))
    return [n for _, n in sorted(found)][:GUARDS]


def _address(clean, span, store, pointer, index, names):
    """The statement before `store` in the loop that forms the same address, `t = P + I;`: (start, end) or None."""
    text = clean[span[0]:store]
    hits = list(re.finditer(rf'(?<![\w.>])(?P<t>{IDENT})\s*=\s*{re.escape(pointer)}\s*\+\s*{re.escape(index)}\s*;', text))
    if not hits or hits[-1]['t'] not in names:
        return None
    return span[0] + hits[-1].start(), span[0] + hits[-1].end()


def _split_fence(source, clean, span, before):
    """A scope of two or more statements ahead of `before`, as its first statement scoped and the rest plain."""
    found = None
    for hit in _FENCE.finditer(clean, span[0], before):
        statements = [s.strip() for s in clean[hit.start('body'):hit.end('body')].split(';') if s.strip()]
        if len(statements) >= 2:
            found = (hit, statements)
    if not found:
        return None
    hit, statements = found
    text = ' '.join([_wrap(statements[0] + ';', 1)] + [s + ';' for s in statements[1:]])
    return hit.start(), hit.end(), text


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(rf'\b{POINTER}\b', clean):
        return []
    locals_, where = _declarations(part)
    if where is None:
        return []
    known = {**_parameters(part), **locals_}
    scalars = [n for n, (kind, shape) in known.items() if shape != 'array' and not _SCALAR.search(kind)]
    result = []
    for span in _loops(clean, part):
        for hit in _STORE.finditer(clean, span[0], span[1]):
            pointer, index, value = hit['p'], hit['i'], hit['v']
            if pointer not in locals_ or locals_[pointer][1] not in ('ptr', 'array') or _SCALAR.search(locals_[pointer][0]):
                continue
            if (index not in known or known[index][1] != 'scalar' or _SCALAR.search(known[index][0])
                    or value not in known or known[value][1] != 'scalar' or _SCALAR.search(known[value][0])):
                continue
            if clean[:hit.start()].rstrip()[-1:] not in ';{}':
                continue
            indent = source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]
            indent = indent if not indent.strip() else ''
            element = locals_[pointer][0]
            address = _address(clean, span, hit.start(), pointer, index, locals_)
            split = _split_fence(source, clean, span, hit.start())
            for guard in _guards(clean, part, span, scalars, {pointer, index, value}):
                arms = f'if ({guard}) {{ {POINTER} += {index}; }} else {{ {POINTER} += {index}; }}'
                for copy_depth in (0, 1, 2):
                    store = (f'{_wrap(f"{POINTER} = {pointer};", copy_depth)}\n'
                             f'{indent}{arms}\n{indent}*{POINTER} = {value};')
                    base = [(hit.start(), hit.end(), store), (where, where, f'  {element} *{POINTER};\n')]
                    if copy_depth == 0:
                        result.append((PLAIN, edit(source, base)))
                        continue
                    for first_depth in (1, 2):
                        for splitting in ([False, True] if split else [False]):
                            edits = list(base)
                            if address:
                                edits.append((address[0], address[1], _wrap(source[address[0]:address[1]], first_depth)))
                            elif first_depth > 1:
                                continue
                            if splitting:
                                edits.append(split)
                            if address or splitting:
                                result.append((FAMILY, edit(source, edits)))
    ordered, seen = [], set()
    for family, text in sorted(result, key=lambda item: (item[0] != PLAIN, len(item[1]))):
        if text not in seen:
            seen.add(text)
            ordered.append((family, text))
    plain = [item for item in ordered if item[0] == PLAIN][:GUARDS]
    return (plain + [item for item in ordered if item[0] == FAMILY])[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
