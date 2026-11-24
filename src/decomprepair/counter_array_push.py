"""A store into a global array at a global count, then the count advanced: the store through the old count, the array's pointer first.

The shape (KMC-era SN64 GCC, `-G0 -mips2 -O2 -fno-schedule-insns`; a 15-instruction N64 function that pushes a value
onto a bounded stack kept in a global array and clamps the count; 15 -> 0): the draft and the saved bests write

    P = <array> + COUNT * 4;      /* or  bp - (-(COUNT * 4))  with  bp = <array>;  */
    Q = COUNT + 1;
    COUNT = Q;
    *P = value;
    if (Q >= LIMIT) { COUNT = LIMIT - 1; }

and the compiler holds the sum `Q` across the store, loads the array's `lui` after the count's, and puts the base in
the wrong register: three register rows, which no spelling of these statements moves (the best chain over the library
stalled at 10 on a scaffolded copy of them). The target is what a developer writes by hand:

    table = (s32 *) ARRAY;       /* the first statement, before the count is read */
    slot = COUNT;
    table[slot] = value;
    COUNT = slot + 1;
    if (slot + 1 >= LIMIT) { COUNT = LIMIT - 1; }

Two edits made it, and neither alone does (measured, each 60 where the saved best stood at 15): the store written
through the old count, ahead of the count's own store, with the test recomputing `slot + 1` instead of holding it in a
temporary (the base lands in `$a1` and the address sum has the index first, but the count's `lui` is ahead of the
array's); and the array's address held in a pointer local assigned as the FIRST statement, ahead of the global count's
load (60 -> 0). Controls that stay at 60 or worse: the base assigned after the count load, the count store before the
indexed store (240), the increment in a local of its own, `COUNT++` folded into the index, and `&((s32 *) base)[COUNT]`.
Why the first statement matters (the order the first scheduler or the register allocator sees the two `lui`s) is a
hypothesis that the measurement agrees with; the judge decides each child.

`variants` reads, in one straight-line stretch, the statements `P = ADDRESS;`, `Q = COUNT + K;`, `COUNT = Q;` and
`*P = value;` (the first, then the other three in the order that keeps `Q` before its store), where `ADDRESS` is an
array symbol plus `COUNT * S` in any of m2c's spellings (`(COUNT * 4) + array`, `array + (COUNT << 2)`, `bp - (-(COUNT * 4))`
with `bp = array;` a statement above, `&array + ...`), `S` is the size of the element type `P` points to, and the array
symbol's own element is a byte (or `bp` is a byte pointer), so the offset is in bytes. The children:

- `counter_array_push`: both edits together (the combined child, so a greedy search reaches the match);
- `counter_array_push_order`: the in-place store order and the recomputed test, the array's pointer assigned where the
  address sum was;
- `counter_array_base_first`: only the pointer's assignment moved to the first statement (when the base is a local
  assigned from the array symbol a few statements above).

Faithful and bounded: `COUNT` is a plain 32-bit global (not volatile) and so is the value stored (a number, a
parameter or an unassigned local); `P` and `Q` have no other use but the later reads of `Q`, which become `slot + K`
(`Q` is not written after the store); nothing else sits between the four statements; no label between them. The array
and the count are distinct symbols, so storing before the count changes nothing a reader can see.
"""
import re

from .increment_old_value_copy import _assignment, _closes_at_end, _increment, _segments
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'counter_array_push'
ORDER = 'counter_array_push_order'
BASE_FIRST = 'counter_array_base_first'
FAMILIES = (FAMILY, ORDER, BASE_FIRST)
WIDE = r'(?:s32|u32|int|unsigned\s+int|unsigned|signed\s+int)'
BYTE = r'(?:u8|s8|char|unsigned\s+char|signed\s+char|void)'
SIZES = {'s32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4, 's16': 2, 'u16': 2, 'short': 2, 's8': 1, 'u8': 1, 'char': 1,
         's64': 8, 'u64': 8, 'f64': 8, 'double': 8}
CAST = re.compile(rf'\(\s*(?:const\s+)?(?:(?:unsigned|signed)\s+)?{IDENT}\s*\**\s*\)\s*')
SCALED = rf'\(?(?P<g>{IDENT})(?:\*(?P<m>\d+)|<<(?P<k>\d+))\)?'
FORMS = [re.compile(pattern) for pattern in (
    rf'{SCALED}\+(?P<amp>&?)(?P<b>{IDENT})',
    rf'(?P<amp>&?)(?P<b>{IDENT})\+{SCALED}',
    rf'(?P<amp>&?)(?P<b>{IDENT})-\(-{SCALED}\)',
)]
DECLARATION = re.compile(rf'(?:(?:static|const|unsigned|signed|extern)\s+)*(?:[su](?:8|16|32|64)|f(?:32|64)|int|char|short|float|double)\s*\**\s*{IDENT}\s*(?:=[^=].*)?', re.S)


def _naked(text):
    """`text` without casts, spaces and the parentheses that wrap all of it."""
    text = text.strip()
    previous = None
    while previous != text:
        previous = text
        text = CAST.sub('', text).strip()
        while text.startswith('(') and _closes_at_end(text):
            text = text[1:-1].strip()
    return re.sub(r'\s+', '', text)


def _address(right):
    """(array or base name, '&' or '', count name, scale) of an array plus a scaled count, else None."""
    text = _naked(right)
    for form in FORMS:
        hit = form.fullmatch(text)
        if hit:
            scale = int(hit['m']) if hit['m'] else 1 << int(hit['k'])
            return hit['b'], hit['amp'], hit['g'], scale
    return None


def _declared(clean, opening, end):
    """Declaration segments at the top of the body and the first statement's index, from `_segments`."""
    segments = _segments(clean, opening + 1, end - 1)
    for index, (begin, stop, mark) in enumerate(segments):
        text = clean[begin:stop].strip()
        if mark != ';' or not DECLARATION.fullmatch(text):
            return segments, index
    return segments, len(segments)


def _type_of(text, name):
    hit = re.search(rf'(?m)^[ \t]*(?:extern[ \t]+)?((?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]+{re.escape(name)}[ \t]*(\[[^\]]*\])?[ \t]*;', text)
    return (hit[1], bool(hit[2])) if hit else (None, False)


def _clean_ref(text, name):
    return rf'(?<![\w.>])(?<!->){re.escape(name)}\b'


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body):
        return []
    clean = part.clean
    segments, first = _declared(clean, part.opening, part.end)
    initial = {}  # local name -> its initialiser
    declared = {}  # local name -> (type text, pointer?) from the declaration lines
    for begin, stop, _ in segments[:first]:
        hit = re.fullmatch(rf'(?:(?:static|const)\s+)*((?:unsigned\s+|signed\s+)?[A-Za-z_]\w*)\s*(\**)\s*({IDENT})\s*(?:=\s*([^=].*))?', clean[begin:stop].strip(), re.S)
        if hit:
            declared[hit[3]] = (hit[1], hit[2])
            if hit[4]:
                initial[hit[3]] = hit[4].strip()
    params = {}
    head = re.search(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*{{', clean[:part.opening + 1])
    for argument in (head[1].split(',') if head else []):
        word = re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', argument.strip())
        if word:
            params[word[1]] = argument
    context = source + '\n' + header
    results = []
    for index in range(first, len(segments)):
        begin, stop, mark = segments[index]
        text = clean[begin:stop].strip()
        assigned = _assignment(text) if mark == ';' else None
        if not assigned or not re.fullmatch(IDENT, assigned[0]) or assigned[0] not in declared:
            continue
        pointer, right = assigned
        found = _address(right)
        if not found:
            continue
        results += _site(source, part, segments, first, index, pointer, found, declared, initial, params, context)
    seen, out = set(), []
    for family, text in results:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out


def _site(source, part, segments, first, index, pointer, found, declared, initial, params, context):
    clean = part.clean
    base, amp, count, scale = found
    kind, stars = declared[pointer]
    if stars != '*' or SIZES.get(re.sub(r'\s+', ' ', kind)) != scale:
        return []
    element = re.sub(r'\s+', ' ', kind)
    ctype, _ = _type_of(context, count)
    if count in declared or count in params or not ctype or not re.fullmatch(WIDE, ctype):
        return []
    # The four statements: the address, then `Q = COUNT + K;`, `COUNT = Q;`, `*P = value;` within AHEAD segments.
    later = [(i, segments[i]) for i in range(index + 1, min(index + 1 + 3, len(segments)))]
    if len(later) != 3 or any(mark != ';' for _, (_, _, mark) in later):
        return []
    sum_at = store_at = write_at = None
    for i, (begin, stop, _) in later:
        statement = clean[begin:stop].strip()
        assigned = _assignment(statement)
        if not assigned:
            return []
        left, right = assigned
        if re.fullmatch(IDENT, left) and left in declared and sum_at is None and _increment(right, count):
            sum_at, total, step = i, left, _increment(right, count)
        elif left == count and re.fullmatch(IDENT, right.strip()) and write_at is None:
            write_at, written = i, right.strip()
        elif re.fullmatch(rf'\*\s*{re.escape(pointer)}|{re.escape(pointer)}\s*\[\s*0\s*\]', left) and store_at is None:
            store_at, value = i, right.strip()
        else:
            return []
    if None in (sum_at, store_at, write_at) or written != total or write_at < sum_at:
        return []
    qtype, qstars = declared[total]
    if qstars or not re.fullmatch(WIDE, qtype):
        return []
    sign, constant = step
    last = segments[index + 3][1]
    body_end = part.end - 1
    # The value stored is a number or an unassigned parameter or local that is none of the names involved.
    if not (re.fullmatch(NUMBER, value) or (re.fullmatch(IDENT, value) and value not in (pointer, total, count, base)
                                            and (value in params or (value in declared and not declared[value][1])))):
        return []
    if re.search(rf'(?<![\w.>]){re.escape(value)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[segments[first][0]:body_end]) \
            and re.fullmatch(IDENT, value) and value in declared:
        return []
    after = clean[last + 1:body_end]
    if re.search(rf'(?<![\w.>]){re.escape(total)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.>])(?:\+\+|--)\s*{re.escape(total)}|(?<![\w.>]){re.escape(total)}\s*(?:\+\+|--)|&\s*{re.escape(total)}\b', after):
        return []
    if re.search(rf'(?m)^[ \t]*(?!(?:case|default)\b){IDENT}[ \t]*:(?!:)', clean[segments[index][0]:last]):
        return []
    if re.search(_clean_ref(clean, total), clean[segments[first][0]:segments[index][0]]):
        return []  # the sum's local is also used above
    # P is used only by its address and its store.
    inside = clean[segments[first][0]:body_end]
    if len(re.findall(_clean_ref(inside, pointer), inside)) != 2:
        return []
    # The array: a symbol read directly (a byte array), or a byte pointer local assigned from one just above.
    root, spelled, assign_at = base, amp, None
    if base in declared:
        btype, bstars = declared[base]
        if bstars != '*' or not re.fullmatch(BYTE, btype.strip()):
            return []
        assign_at = None
        for back in range(index - 1, first - 1, -1):
            start, end, mark = segments[back]
            hit = re.fullmatch(rf'{re.escape(base)}\s*=\s*(?P<amp>&?)\s*(?:\(\s*[\w\s]*\*\s*\)\s*)?(?P<sym>{IDENT})', clean[start:end].strip()) if mark == ';' else None
            if hit:
                if hit['sym'] in declared or hit['sym'] in params:
                    return []
                root, spelled, assign_at = hit['sym'], hit['amp'], back
                break
            if re.search(_clean_ref(clean[start:end], base), clean[start:end]):
                return []
        if assign_at is None and base in initial:
            hit = re.fullmatch(rf'(?P<amp>&?)\s*(?:\(\s*[\w\s]*\*\s*\)\s*)?(?P<sym>{IDENT})', initial[base])
            if not hit or hit['sym'] in declared or hit['sym'] in params:
                return []
            root, spelled = hit['sym'], hit['amp']
            assign_at = -1  # the declaration's own initialiser
        if assign_at is None:
            return []
    elif base in params:
        return []
    else:
        etype, array = _type_of(context, base)
        if not etype or not (re.fullmatch(BYTE, etype) or (etype == 'M2C_UNK' and amp)) or (not array and not amp):
            return []
    if root == count or root in declared:
        return []
    # What else reads the base local (the statement above is dropped only when nothing else does).
    base_refs = len(re.findall(_clean_ref(inside, base), inside)) if base in declared else 0
    droppable = base in declared and base_refs == (1 if assign_at == -1 else 2)  # its assignment and the address sum
    table = _fresh(source, 'table')
    slot = _fresh(source, 'slot')
    hoist = f'{table} = ({element} *){spelled}{root};'
    count_sum = f'{slot} {sign} {constant}'
    # Later reads of the sum become `slot + K` (parenthesised unless they stand alone as an operand of a comparison).
    flips = []
    for hit in re.finditer(_clean_ref(after, total), after):
        at, stop = last + 1 + hit.start(), last + 1 + hit.end()
        bare = (re.search(r'(?:[(=,]|>=|<=|==|!=|<|>|&&|\|\||\breturn)\s*$', clean[max(0, at - 8):at])
                and re.match(r'\s*(?:[),;]|>=|<=|==|!=|<|>|&&|\|\|)', clean[stop:stop + 4]))
        flips.append((at, stop, count_sum if bare else f'({count_sum})'))
    removals = _declaration_spans(clean, segments, first, [pointer, total] + ([base] if droppable else []))
    lead = _indent(clean, segments[first][0])
    declare = (part.opening + 1, part.opening + 1, f'\n{lead}{element} *{table};\n{lead}{ctype} {slot};')
    dropped = _statement(clean, segments[assign_at]) if droppable and assign_at >= 0 else None
    first_at = segments[first]
    block = (_statement(clean, segments[index])[0], _statement(clean, segments[index + 3])[1])
    indent = _indent(clean, segments[index][0])

    def lines(*texts):
        return ''.join(f'{indent}{text}\n' for text in texts)

    body = (slot + ' = ' + count + ';', f'{table}[{slot}] = {value};', f'{count} = {count_sum};')
    out = []
    # Combined: the pointer is the first statement (the dropped base assignment, when it was the first, is that statement).
    before = _statement(clean, first_at)[0]
    if assign_at == -1:
        head = [(before, before, f'{_indent(clean, first_at[0])}{hoist}\n')]
    elif droppable and assign_at == first:
        head = [(dropped[0], dropped[1], f'{_indent(clean, first_at[0])}{hoist}\n')]
    else:
        head = [(before, before, f'{_indent(clean, first_at[0])}{hoist}\n')] + ([(dropped[0], dropped[1], '')] if droppable else [])
    out.append((FAMILY, edit(source, [declare, *head, (*block, lines(*body)), *flips, *removals])))
    # Order only: the pointer is assigned where the address sum was.
    keep = [(dropped[0], dropped[1], '')] if dropped else []
    out.append((ORDER, edit(source, [declare, *keep, (*block, lines(hoist, *body)), *flips, *removals])))
    if base in declared and assign_at is not None and assign_at not in (-1, first):
        text = clean[segments[assign_at][0]:segments[assign_at][1]].strip()
        moved = [(*dropped, ''), (before, before, f'{_indent(clean, first_at[0])}{text};\n')]
        out.append((BASE_FIRST, edit(source, moved)))
    return out


def _statement(clean, segment):
    """(start, end) of a statement's own lines: from the start of its line and past its newline when only blanks flank it."""
    begin, stop, _ = segment
    line = clean.rfind('\n', 0, begin) + 1
    start = line if not clean[line:begin].strip() else begin
    tail = re.match(r'[ \t]*\n', clean[stop + 1:])
    return start, stop + 1 + (tail.end() if tail else 0)


def _indent(clean, at):
    line = clean.rfind('\n', 0, at) + 1
    lead = clean[line:at]
    return lead if not lead.strip() else '    '


def _fresh(source, base):
    name, number = base, 1
    while re.search(rf'\b{name}\b', source):
        number += 1
        name = f'{base}{number}'
    return name


def _declaration_spans(clean, segments, first, names):
    """Spans of the declaration lines of `names` (each declared alone) at the top of the body."""
    spans = []
    for segment in segments[:first]:
        text = clean[segment[0]:segment[1]].strip()
        if any(re.fullmatch(rf'(?:\w+\s+)*\w+\s*\**\s*{re.escape(name)}(?:\s*=[^=].*)?', text, re.S) for name in names):
            spans.append((*_statement(clean, segment), ''))
    return spans


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 70}  # the registry: no caller wiring (registry.py)
