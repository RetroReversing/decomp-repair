"""A table element indexed again in each of a run of statements, read through one pointer local.

m2c and a hand-written first draft spell each read with the whole index (`dx = T[S[i].idx].x - o->x;
dy = T[S[i].idx].y - o->y; ...`). Under KMC GCC 2.7.2 at `-O1` the compiler then rebuilds the address (or folds the
member's offset into each `lui`) in every statement, where the target built it once and loads `0x18`, `0x1C`, `0x20` off
one register: the original took the element's address first. A 468-instruction N64 homing update went 1235 -> 130 with
that one pointer. `element_pointer_direct_index` is the other direction.

`variants` looks for the same `NAME[index].` text in two or more consecutive lines of one block, `NAME` an array the
source or header declares `extern T NAME[];`, and offers the run in braces with `T *element = &NAME[index];` first,
and the same with the pointer declared at the function's head. The index must keep its value across the run: no calls,
`++` or `--`, and every line is a plain assignment `name = ...;` to a name the index does not use; when the index is
only constants and the function's own locals, a store through a member may also be in the run. The judge decides."""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view

FAMILY = 'repeated_element_pointer'
FAMILIES = (FAMILY,)
LIMIT = 8
POINTER = 'element'
ELEMENT = re.compile(rf'(?<![\w.>])(?P<array>{IDENT})\s*\[')
PLAIN = re.compile(rf'^\s*(?P<target>{IDENT})\s*(?:[-+*/|&^]|<<|>>)?=(?!=)[^;]*;\s*$')
STATEMENT = re.compile(r'^\s*[^;{}]*=(?!=)[^;{}]*;\s*$')
UNSAFE = re.compile(rf'\+\+|--|\b(?!(?:sizeof|return)\b){IDENT}\s*\(')


def _element_type(text, array):
    hit = re.search(rf'\bextern\s+((?:(?:unsigned|signed|struct|const)\s+)*{IDENT}(?:\s*\*)*)\s*\b{re.escape(array)}'
                    r'\s*\[[^\][]*\]\s*;', text)
    return ' '.join(hit[1].split()) if hit else None


def _closing(line, opening):
    depth = 0
    for at in re.finditer(r'[\[\]]', line[opening:]):
        depth += 1 if at[0] == '[' else -1
        if not depth:
            return opening + at.start()
    return None


def _elements(line):
    """The `NAME[index]` texts of a line that a member is read from, outermost ones included."""
    for hit in ELEMENT.finditer(line):
        end = _closing(line, hit.end() - 1)
        if end is not None and re.match(r'\s*\.', line[end + 1:]):
            yield hit['array'], line[hit.start():end + 1]


def _locals(part, header_names):
    return {m[1] for m in re.finditer(rf'\b{IDENT}[ \t*]+({IDENT})\s*(?=[;,=)])', part.source[:part.end])
            if m[1] not in header_names and not _address_taken(part.body, m[1])}


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b|^\s*#', part.body, re.M):
        return []
    context = header + '\n' + source
    if re.search(rf'\b{POINTER}\b', part.body):
        return []
    lines = part.clean[:part.end].splitlines(keepends=True)
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    globals_ = set(re.findall(rf'\bextern\b[^;(]*?\b({IDENT})\s*(?:\[[^;]*)?;', context))
    owned = _locals(part, globals_)
    first = next((i for i, s in enumerate(starts) if s > part.opening), len(lines))
    out, done, i = [], set(), first
    while i < len(lines):
        for array, text in list(_elements(lines[i])):
            if (i, text) in done:
                continue
            kind = _element_type(context, array)
            if not kind:
                continue
            index = text[text.index('[') + 1:-1]
            names = set(re.findall(rf'(?<![\w.>])({IDENT})', index))
            private = names <= owned and not re.search(r'->|[.\[*]', index)
            end = i
            while end < len(lines) and text in lines[end]:
                line = lines[end]
                plain = PLAIN.match(line)
                # a store through a member cannot change an index made of constants and the function's own locals
                member_store = private and STATEMENT.match(line) and re.match(r'\s*[^=]*(?:->|\.)\w+\s*[-+*/|&^]?=', line)
                if UNSAFE.search(line) or not (plain and plain['target'] not in names or member_store):
                    break
                done.add((end, text))
                end += 1
            if end - i < 2 or UNSAFE.search(index):
                continue
            begin, stop = starts[i], starts[end - 1] + len(lines[end - 1])
            indent = re.match(r'[ \t]*', source[begin:])[0]
            run = source[begin:stop].replace(text, '(*element)')
            run = run.replace('(*element).', 'element->')
            body = ''.join(f'    {line}' for line in run.splitlines(keepends=True))
            out.append((FAMILY, edit(source, [(begin, stop, f'{indent}{{\n{indent}    {kind} *{POINTER} = &{text};\n\n'
                                                           f'{body}{indent}}}\n')])))
            head = source.index('\n', part.opening) + 1
            out.append((FAMILY, edit(source, [(head, head, f'    {kind} *{POINTER};\n'),
                                              (begin, stop, f'{indent}{POINTER} = &{text};\n{run}')])))
            if len(out) >= LIMIT:
                return out
        i += 1
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 900}
