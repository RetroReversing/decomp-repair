"""A store whose element address is a global array's base plus a scaled index, and whose value is a call: the call first, the base in a pointer of its own, then the sum.

The shape (KMC-era SN64 GCC, `-G0 -mips3 -O2`; a 20-instruction N64 function that fills the first and last word of a
16-byte slot of a global table and returns 1; 60 -> 0): m2c wrote, and a search left,

    M2C_FIELD((slot = (index * 0x10) + TABLE), s32 *, 0) = helper(arg1);       /* or  slot = ...;  and the store after */
    M2C_FIELD(slot, s32 *, 0xC) = arg2;

and the compiler computes the shifted index (`sll`) before the table's `lui`/`addiu`, where the target has the table's
address first and the shift after it, both after the call. The saved best (60) was the scaffolded spelling above; the
draft (925) wrote the address before the call, which spills `arg0` differently, and no single edit of either helped:
`symbol_address_local` holds the table in a pointer but sets it ahead of the whole statement (so ahead of the call),
and moving the call alone leaves the sum in one expression. The developer's C:

    value = helper(arg1);
    base = TABLE;
    slot = base + index * 0x10;
    M2C_FIELD(slot, s32 *, 0) = value;
    M2C_FIELD(slot, s32 *, 0xC) = arg2;

Measured on that function (each from the saved best, judged by the app's judge): the call hoisted alone 60; the base
in a pointer ahead of the statement 656; the base and the sum in separate statements ahead of the call 925; the call,
then the base, then the sum 0. Why the base's own statement matters is a hypothesis (the first scheduler sees the
`lui`/`addiu` and the `sll` as independent instructions and starts the one that was written first); the judge
decides each child.

`variants` reads a store `LEFT = RIGHT;` as one statement in two spellings:

- the address is assigned inside the left side, `M2C_FIELD((P = ADDRESS), TYPE *, OFFSET) = RIGHT;` or
  `*(P = ADDRESS) = RIGHT;`;
- the address is the statement before, `P = ADDRESS;` and then `M2C_FIELD(P, TYPE *, OFFSET) = RIGHT;`, `*P = RIGHT;`
  or `P[K] = RIGHT;`.

`ADDRESS` is a global array's name (`TABLE`) or the address of a global scalar (`&TABLE`) plus an integer expression of
parameters, locals and numbers (`(arg0 * 0x10) + TABLE`, `TABLE + (index << 2)`); `RIGHT` makes a call. The children:

- `address_after_call`: `value = RIGHT; base = TABLE; P = base + INDEX; STORE(value)`: the order of the developer's C;
- `address_base_before_call`: `base = TABLE; value = RIGHT; P = base + INDEX; STORE(value)`: the same with the base held
  across the call (a saved register), for the compilers that wanted that.

Faithful and bounded: the address reads only the table's own link-time address and locals and parameters that nothing
takes the address of and the call does not write, so computing it after the call is the same program (C leaves the
order of the two operands of an assignment open; in the statement-before spelling the call cannot read `P`, the one
thing that moves); the table is declared `extern TYPE NAME[...];` (or `extern TYPE NAME;` for `&NAME`) and the
pointer local keeps that element type, so the sum scales as it did; the stored type is a scalar (the type the access
names, or the element type of `P`'s declaration); the statement stands alone (not the body of an unbraced `if`,
`else` or loop, no label before it); no `asm`, `volatile` or `goto` in the function."""
import re

from .increment_old_value_copy import _assignment, _segments, _writes
from .integer_repair_support import IDENT, _address_taken, edit, view

AFTER = 'address_after_call'
BEFORE = 'address_base_before_call'
FAMILIES = (AFTER, BEFORE)
SCALAR = (r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long|float|double)|[su](?:8|16|32|64)|f(?:32|64)')
INTEGER = re.compile(r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|[su](?:8|16|32)')
KEYWORD = re.compile(r'\s*(?:if|else|for|while|do|switch|return|goto|case|default|break|continue)\b|\s*' + IDENT + r'\s*:(?!:)')
STORE = [
    # (the left side with the address assigned inside it, with a group `p` for the pointer and `a` for the address)
    re.compile(rf'M2C_FIELD\(\s*\(\s*(?P<p>{IDENT})\s*=\s*(?P<a>.+?)\s*\)\s*,\s*(?P<t>{SCALAR})\s*\*\s*,\s*(?P<o>[^,()]+?)\s*\)', re.S),
    re.compile(rf'\*\s*\(\s*(?P<p>{IDENT})\s*=\s*(?P<a>.+?)\s*\)', re.S),
]
AFTER_STORE = [
    # (the left side that reads the pointer, as the statement after `P = ADDRESS;`)
    re.compile(rf'M2C_FIELD\(\s*(?P<p>{IDENT})\s*,\s*(?P<t>{SCALAR})\s*\*\s*,\s*(?P<o>[^,()]+?)\s*\)'),
    re.compile(rf'\*\s*(?P<p>{IDENT})'),
    re.compile(rf'(?P<p>{IDENT})\s*\[\s*(?P<k>{r"[^\]]+"})\s*\]'),
]
SUM = re.compile(r'[\w\s*+\-<>()&]+')


def _split_sum(address):
    """(symbol text, ampersand, index text, symbol first) of `SYMBOL + INDEX` / `INDEX + SYMBOL`, or None."""
    depth, cut = 0, None
    for at, char in enumerate(address):
        depth += (char == '(') - (char == ')')
        if char == '+' and depth == 0:
            if cut is not None:
                return None
            cut = at
    if cut is None:
        return None
    left, right = address[:cut].strip(), address[cut + 1:].strip()
    for symbol, index, first in ((left, right, True), (right, left, False)):
        hit = re.fullmatch(rf'(?P<amp>&?)\s*(?P<s>{IDENT})', symbol)
        if hit and not re.search(rf'(?<![\w.>])(?:{IDENT})\s*\(', index) and SUM.fullmatch(index):
            return hit['s'], hit['amp'], index, first
    return None


def _globals(text, name):
    """(element type, is an array) of `extern TYPE name[...];` / `extern TYPE name;` in `text`, or None."""
    hit = re.search(rf'(?m)^[ \t]*extern[ \t]+((?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]+{re.escape(name)}[ \t]*(\[[^\]]*\])?[ \t]*;', text)
    return (re.sub(r'\s+', ' ', hit[1]), bool(hit[2])) if hit else None


def _fresh(source, base):
    name, number = base, 1
    while re.search(rf'\b{name}\b', source):
        number += 1
        name = f'{base}{number}'
    return name


def _indent(clean, at):
    line = clean.rfind('\n', 0, at) + 1
    lead = clean[line:at]
    return lead if not lead.strip() else '    '


def _lines(clean, begin, stop):
    """(start, end) of a statement's lines when only blanks flank it, else of the statement itself."""
    line = clean.rfind('\n', 0, begin) + 1
    start = line if not clean[line:begin].strip() else begin
    tail = re.match(r'[ \t]*\n', clean[stop + 1:])
    return start, stop + 1 + (tail.end() if tail else 0)


def _real_call(text):
    return any(name not in ('sizeof',) and not name.startswith('M2C_') for name in re.findall(rf'(?<![\w.>])({IDENT})\s*\(', text))


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body):
        return []
    clean = part.clean
    segments = _segments(clean, part.opening + 1, part.end - 1)
    declared, params = {}, {}
    head = re.search(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*{{', clean[:part.opening + 1])
    for argument in (head[1].split(',') if head else []):
        word = re.fullmatch(rf'\s*((?:(?:unsigned|signed|const)\s+)*{IDENT})\s*(\**)\s*({IDENT})\s*', argument)
        if word:
            params[word[3]] = (word[1], word[2])
    first = 0
    for begin, stop, mark in segments:
        hit = re.fullmatch(rf'((?:(?:static|const|unsigned|signed)\s+)*{IDENT})\s*(\**)\s*({IDENT})', clean[begin:stop].strip()) if mark == ';' else None
        if not hit or KEYWORD.match(clean[begin:stop]):
            break
        declared[hit[3]] = (hit[1], hit[2])
        first += 1
    context = source + '\n' + header
    body = clean[part.opening + 1:part.end - 1]
    results = []
    for index in range(first, len(segments)):
        begin, stop, mark = segments[index]
        text = clean[begin:stop]
        if mark != ';' or KEYWORD.match(text):
            continue
        assigned = _assignment(text.strip())
        if not assigned:
            continue
        left, right = assigned
        site = _inside(left) or _before(clean, segments, index, first, left, declared)
        if site:
            results += _rewrite(source, part, segments, index, site, right, declared, params, context, body)
    seen, out = set(), []
    for family, text in results:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out


def _inside(left):
    """The store with its address assigned inside the left side: (pointer, address, type or None, access text(P), 0)."""
    for number, pattern in enumerate(STORE):
        hit = pattern.fullmatch(left)
        if hit:
            if number == 0:
                access = f'M2C_FIELD({{p}}, {hit["t"]} *, {hit["o"]})'
            else:
                access = '*{p}'
            return hit['p'], hit['a'], (hit['t'] if number == 0 else None), access, None
    return None


def _before(clean, segments, index, first, left, declared):
    """The store reading a pointer that the statement before assigned: same tuple, plus the index of that statement."""
    if index - 1 < first:
        return None
    begin, stop, mark = segments[index - 1]
    previous = clean[begin:stop].strip()
    assigned = _assignment(previous) if mark == ';' and not KEYWORD.match(previous) else None
    if not assigned or not re.fullmatch(IDENT, assigned[0]):
        return None
    pointer, address = assigned
    for number, pattern in enumerate(AFTER_STORE):
        hit = pattern.fullmatch(left)
        if hit and hit['p'] == pointer:
            if number == 0:
                access = f'M2C_FIELD({{p}}, {hit["t"]} *, {hit["o"]})'
            elif number == 1:
                access = '*{p}'
            else:
                access = '{p}[' + hit['k'] + ']'
            return pointer, address, (hit['t'] if number == 0 else None), access, index - 1
    return None


def _rewrite(source, part, segments, index, site, right, declared, params, context, body):
    clean = part.clean
    pointer, address, kind, access, previous = site
    if pointer not in declared or declared[pointer][1] != '*':
        return []
    split = _split_sum(re.sub(r'\s+', ' ', address).strip())
    if not split or not _real_call(right):
        return []
    symbol, amp, offset, symbol_first = split
    if symbol in declared or symbol in params or symbol == pointer:
        return []
    found = _globals(context, symbol)
    if not found or bool(found[1]) == bool(amp):
        return []  # an array is named as itself, a scalar by its address
    element = found[0]
    if kind is None:
        kind = re.sub(r'\s+', ' ', declared[pointer][0])
        if not re.fullmatch(SCALAR, kind):
            return []
    # The index reads integer locals and parameters only, and nothing the call writes or takes the address of.
    names = set(re.findall(rf'(?<![\w.]){IDENT}', offset))
    for each in names:
        known = declared.get(each) or params.get(each)
        if not known or known[1] or not INTEGER.fullmatch(re.sub(r'\s+', ' ', known[0]).replace('const ', '')):
            return []
        if _address_taken(body, each) or _writes(right, each):
            return []
    if re.search(rf'(?<![\w.>]){re.escape(pointer)}\b', right):
        return []
    store_begin, store_stop, _ = segments[index]
    value = _fresh(source, 'call_value')
    base = _fresh(source, 'table_base')
    sum_text = (f'{base} + {offset}' if symbol_first else f'{offset} + {base}')
    indent = _indent(clean, segments[previous if previous is not None else index][0])
    store = access.replace('{p}', pointer) + f' = {value};'
    start = _lines(clean, *segments[previous if previous is not None else index][:2])[0]
    end = _lines(clean, store_begin, store_stop)[1]
    right_text = right.strip()
    base_set = f'{base} = {amp}{symbol};'
    declare = (part.opening + 1, part.opening + 1,
               f'\n{indent}{kind} {value};\n{indent}{element} *{base};')
    out = []
    for family, order in ((AFTER, (f'{value} = {right_text};', base_set)), (BEFORE, (base_set, f'{value} = {right_text};'))):
        block = ''.join(f'{indent}{line}\n' for line in (*order, f'{pointer} = {sum_text};', store))
        if start == store_begin or (previous is not None and start == segments[previous][0]):
            block = block[len(indent):]  # (the statement shares its line with a brace: its first line starts where it did)
        out.append((family, edit(source, [declare, (start, end, block)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 72}  # the registry: no caller wiring (registry.py)
