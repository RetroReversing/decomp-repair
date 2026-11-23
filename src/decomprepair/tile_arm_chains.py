"""A table-lookup function with one arm per kind of cell, each arm computing `row * K2 + index * K1 + table` as a pointer,
written the way the compiler's allocator and cross-jumper want it (KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`).

m2c writes every arm as `p = ((i & 0xFF) * K1) + ((row * K2) + TABLE);`. A tile/collision lookup with ten of them (five
arms over a row-selected bank, five over one table) stood at 6175 and needed seven edits, none of which the permuter could
find one at a time, to reach 60 (the last two rows are an instruction order GCC's scheduler picks). Each edit changes a
different decision of the compiler; all are readings of gcc-2.7.2's passes that the judge agreed with, labelled
hypotheses:

1. `bank_index_first`: the bank's address in a local, the row product in a one-shot scope of its own, and the index term
   added as the *first* operand (`p = (u8 *)(i * K1) + (s32)bank;`).
   - local-alloc.c (`qty_compare`) gives the registers of a basic block to its quantities in order of
     `floor_log2(refs) * refs * size / life` and each takes the lowest free one, so the product chain of `row` (two
     operands wide: the row and the symbol's address) and the chain of the index compete for `$v0`; a `do { } while (0);`
     around the row product doubles its references (flow.c adds the loop depth) and it wins, which is what the target
     has in the arms that continue past the add (`$v0` = bank, `$v1` = index term);
   - local-alloc ties the sum's output to its *first* operand (`combine_regs` over the insn's operands in order), and
     expr.c expands pointer + integer with the pointer first; `(u8 *)(i * K1) + (s32)bank` makes the index term the
     pointer operand, so the sum lands in the index term's register as the target does.
   The arms with only a table (`p = (i * K1) + TABLE`) get the table's address in a local first (jump.c's cross-jumping
   compares insns by register, so what the address's register is decides which arms it merges); the arm that adds a small
   term after the product also gets the add in a one-shot scope, which is the same priority edit for the index chain.
2. `byte_entry_copy`: an `s32` parameter that is masked `& 0xFF` into locals and used unmasked elsewhere, read through a
   `u8` copy of itself for the masks (the copy is a QImode move cse does not propagate, so the target's `move v1,a3;
   andi t0,v1,0xff` appears).
3. `load_shift_split`: `b = *(p + 1); a = *(p + 0) << 7;` as `a = *(p + 0); b = *(p + 1); a = a << 7;` (both loads
   before the shift, so the scheduler keeps the load order and `b` does not conflict with the pointer).
4. `zero_arm_inversion`: `if (C) { return 0; } rest; return x;` at the end of a function as `if (!C) { rest; return x; }
   return 0;`, which makes reorg.c annul the delay slot that holds `li $v0,0` (`bnel`) as the target does.
5. `tile_arm_chains` is the first four at once, since the arms only match together; `bank_arm_scope` and
   `table_arm_scope` then try the one-shot scopes arm by arm (the arms did not all want the same: two bank arms with the
   scope and one without, one table arm with the small term's add in a scope, one with the index value in one). On the
   draft (KMC GCC 2.7.2) the combined child alone went 6175 -> 1875 and the per-arm steps 1875 -> 1680; the rest of the
   measured route to 60 (the arms' shared tail copied into each arm, a local per arm, the dead parameter's name reused
   for a later arm's value, the loads before the shift) is `goto_run_copy`, `arm_variable_share` and these families'
   other children. A hand run of those steps with the judge between each took the draft 6175 -> 2005 -> 1140 -> 905 ->
   670 -> 295 -> 260 -> 60, the last two rows a scheduler order.

Every child compiles to a program with the same behaviour as its source: the rewrites move statements and spell the same
arithmetic differently, they invent no value."""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILIES = ('bank_index_first', 'bank_arm_scope', 'table_arm_scope', 'byte_entry_copy', 'load_shift_split', 'zero_arm_inversion',
            'tile_arm_chains')
LIMIT = 40

_IDENT = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_INDEX = rf'(?:\(\s*{_IDENT}\s*&\s*{_NUM}\s*\)|{_IDENT})'
# `p = ((i & 0xFF) * K1) + ((row * K2) + TABLE) <tail>;`
_BANK = re.compile(
    rf'(?P<lhs>{_IDENT})\s*=\s*\(\s*(?P<idx>{_INDEX})\s*\*\s*(?P<k1>{_NUM})\s*\)\s*\+\s*'
    rf'\(\s*\(\s*(?P<row>{_IDENT})\s*\*\s*(?P<k2>{_NUM})\s*\)\s*\+\s*(?P<sym>{_IDENT})\s*\)(?P<tail>[^;{{}}]*);')
# `p = (i * K1) + TABLE <tail>;`
_TABLE = re.compile(
    rf'(?P<lhs>{_IDENT})\s*=\s*\(\s*(?P<idx>{_INDEX})\s*\*\s*(?P<k1>{_NUM})\s*\)\s*\+\s*'
    rf'(?P<sym>{_IDENT})(?P<tail>[^;{{}}()]*(?:\([^;{{}}]*\)[^;{{}}()]*)*);')
_DECL = re.compile(r'^[ \t]*(?:(?:u|s)(?:8|16|32|64)|f32|f64|char|short|int|long|unsigned|void)\b[^;(){}]*;[ \t]*$')
_LOAD = r'(?:M2C_FIELD\s*\(|\*\s*\(|\*\*|\*\s*[A-Za-z_])'


def _tables(source):
    """Names declared as arrays (`extern char D_80001000[];`): the symbols whose address a row/index sum adds to."""
    return set(re.findall(rf'\b{_IDENT}\s+({_IDENT})\s*\[[^\]]*\]\s*;', _blank(source)))


def _span(source, name):
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', _blank(source)[span[0]:span[1]]):
        return None
    return span


def _tail(text):
    text = text.strip()
    return f' {text}' if text else ''


def bank_index_first(source, name, scope=True):
    """Every `row * K2 + table` arm in the bank form, every `index * K1 + table` arm with the table in a local. With
    `scope` the row product sits in a one-shot scope (the priority edit); without it, only the operand order changes."""
    span = _span(source, name)
    if not span:
        return None
    clean = _blank(source)
    tables = _tables(source)
    start, end = span
    edits = []
    for hit in _BANK.finditer(clean, start, end):
        if hit['sym'] not in tables or hit['row'] == hit['lhs']:
            continue
        tail = _tail(source[hit.start('tail'):hit.end('tail')])
        idx = source[hit.start('idx'):hit.end('idx')]
        weight = f'do {{ bank = bp + {hit["row"]} * {hit["k2"]}; }} while (0);' if scope else f'bank = bp + {hit["row"]} * {hit["k2"]};'
        text = (f'{{ u8 *bp = {hit["sym"]}; u8 *bank; {weight} '
                f'{hit["lhs"]} = (u8 *)({idx} * {hit["k1"]}) + (int)bank{tail}; }}')
        edits.append((hit.start(), hit.end(), text))
    for hit in _TABLE.finditer(clean, start, end):
        if hit['sym'] not in tables or any(a <= hit.start() < b for a, b, _ in edits):
            continue
        tail = _tail(source[hit.start('tail'):hit.end('tail')])
        idx = source[hit.start('idx'):hit.end('idx')]
        text = f'{{ u8 *bp = {hit["sym"]}; {hit["lhs"]} = bp + {idx} * {hit["k1"]}{tail}; }}'
        edits.append((hit.start(), hit.end(), text))
    if not edits:
        return None
    return _splice(source, edits)


def _splice(source, edits):
    for a, b, text in sorted(edits, reverse=True):
        source = source[:a] + text + source[b:]
    return source


# the shapes `bank_index_first` writes: one block per arm
_BANK_BLOCK = re.compile(
    rf'\{{ u8 \*bp = (?P<sym>{_IDENT}); u8 \*bank; (?P<weight>do \{{ bank = bp \+ (?P<row>{_IDENT}) \* (?P<k2>{_NUM}); \}} while \(0\);|'
    rf'bank = bp \+ (?P<row2>{_IDENT}) \* (?P<k22>{_NUM});) (?P<rest>{_IDENT} = \(u8 \*\)\([^;]*\) \+ \(int\)bank[^;]*;) \}}')
_TABLE_BLOCK = re.compile(
    rf'\{{ u8 \*bp = (?P<sym>{_IDENT}); (?P<lhs>{_IDENT}) = bp \+ (?P<idx>{_INDEX}) \* (?P<k1>{_NUM})(?P<tail>[^;{{}}]*); \}}')


def bank_arm_scope(source, name):
    """One arm at a time: the row product's one-shot scope taken off an arm that has it, or put on one that has not."""
    span = _span(source, name)
    if not span:
        return []
    result = []
    for hit in _BANK_BLOCK.finditer(source, span[0], span[1]):
        row, k2 = (hit['row'], hit['k2']) if hit['row'] else (hit['row2'], hit['k22'])
        scoped = bool(hit['row'])
        weight = f'bank = bp + {row} * {k2};' if scoped else f'do {{ bank = bp + {row} * {k2}; }} while (0);'
        text = f'{{ u8 *bp = {hit["sym"]}; u8 *bank; {weight} {hit["rest"]} }}'
        result.append(source[:hit.start()] + text + source[hit.end():])
    return result


def table_arm_scope(source, name):
    """One table arm at a time, three spellings of the same arithmetic with a different one-shot scope: the small term's
    add in a scope of its own (the index chain outranks the index value), the index value in a scope, and the index value
    in a scope before the table's address is taken."""
    span = _span(source, name)
    if not span:
        return []
    result = []
    for hit in _TABLE_BLOCK.finditer(source, span[0], span[1]):
        sym, lhs, idx, k1, tail = (hit[g] for g in ('sym', 'lhs', 'idx', 'k1', 'tail'))
        forms = []
        if tail.strip():
            forms.append(f'{{ u8 *bp = {sym}; u8 *sm; sm = bp + {idx} * {k1}; do {{ {lhs} = sm{tail}; }} while (0); }}')
        forms.append(f'{{ u8 *bp = {sym}; u32 bb; do {{ bb = {idx}; }} while (0); {lhs} = bp + bb * {k1}{tail}; }}')
        forms.append(f'{{ u32 bb; u8 *bp; do {{ bb = {idx}; }} while (0); bp = {sym}; {lhs} = bp + bb * {k1}{tail}; }}')
        for text in forms:
            result.append(source[:hit.start()] + text + source[hit.end():])
    return result


def byte_entry_copy(source, name):
    """A parameter masked into locals (`x = p & 0xFF;`, twice or more) and used another way too, read through a `u8`
    copy for the masks."""
    span = _span(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    header = clean[start:opening]
    params = re.findall(rf'\b(?:s32|u32|int|unsigned|long)\s+({_IDENT})\s*[,)]', header)
    body = clean[opening:end]
    for param in params:
        masks = list(re.finditer(rf'(?<![\w.>])({_IDENT})\s*=\s*{param}\s*&\s*0[xX][fF][fF]\s*;', body))
        uses = len(re.findall(rf'(?<![\w.>]){param}\b', body))
        if len(masks) < 2 or uses <= len(masks) or f'{param}_byte' in clean:
            continue
        edited = source
        for hit in reversed(masks):
            a, b = opening + hit.start(), opening + hit.end()
            edited = edited[:a] + f'{hit[1]} = {param}_byte & 0xFF;' + edited[b:]
        # declarations sit on the lines after the opening brace; the copy goes after the last of them
        lines = edited[opening + 1:].split('\n')
        last = 0
        for number, line in enumerate(lines[1:], 1):
            if _DECL.match(line) or not line.strip():
                last = number if _DECL.match(line) else last
                continue
            break
        indent = re.match(r'\s*', lines[1] if len(lines) > 1 else '    ')[0] or '    '
        lines.insert(last + 1, f'{indent}{param}_byte = {param};')
        lines.insert(1, f'{indent}u8 {param}_byte;')
        return edited[:opening + 1] + '\n'.join(lines)
    return None


def load_shift_split(source, name):
    """`b = LOAD1; a = LOAD0 << S;` as `a = LOAD0; b = LOAD1; a = a << S;`."""
    span = _span(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    pair = re.compile(rf'(?P<b>{_IDENT})\s*=\s*(?P<l1>{_LOAD}[^;]*);\s*(?P<a>{_IDENT})\s*=\s*(?P<l0>{_LOAD}[^;]*?)\s*<<\s*(?P<s>\d+)\s*;')
    edits = []
    for hit in pair.finditer(clean, start, end):
        if hit['a'] == hit['b'] or re.search(rf'(?<![\w.>])(?:{hit["a"]}|{hit["b"]})\b', hit['l1'] + ' ' + hit['l0']):
            continue
        base = lambda text: re.sub(r'\s+', '', re.sub(r'[+-]\s*0[xX]?[0-9A-Fa-f]*\s*\)?$', '', text.split(',')[0]))
        if base(hit['l1']) != base(hit['l0']):
            continue
        a, b, l0, l1 = (source[hit.start(g):hit.end(g)] for g in ('a', 'b', 'l0', 'l1'))
        indent = re.search(r'[ \t]*$', source[:hit.start()])[0]
        text = f'{a} = {l0};\n{indent}{b} = {l1};\n{indent}{a} = {a} << {hit["s"]};'
        edits.append((hit.start(), hit.end(), text))
    return _splice(source, edits) if edits else None


def zero_arm_inversion(source, name):
    """`if (C) { return 0; } rest; return x;` at the end of the function, as `if (!C) { rest; return x; } return 0;`."""
    span = _span(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    depth = 0
    for hit in re.finditer(r'[{}]|(?<![\w.])if\s*\(', clean[opening:end]):
        text = hit[0]
        if text == '{':
            depth += 1
        elif text == '}':
            depth -= 1
        elif depth == 1:
            at = opening + hit.start()
            paren = clean.find('(', at)
            after = close(clean, paren)
            arm = re.match(r'\s*\{\s*return\s+0\s*;\s*\}', clean[after:end]) if after else None
            if not arm:
                continue
            rest_start = after + arm.end()
            last = clean.rfind('}', opening, end)
            rest = clean[rest_start:last] if last > rest_start else None
            if rest is None or not re.search(r'return\s+[^;]+;\s*$', rest) or re.search(r'\bfor\b|\bwhile\b|\bdo\b|\bswitch\b', rest):
                continue
            condition = source[paren + 1:after - 1]
            flipped = negate(condition)
            if not flipped:
                continue
            body = source[rest_start:last].rstrip('\n')
            return source[:at] + f'if ({flipped}) {{' + body + '\n    }\n    return 0;\n' + source[last:]
    return None


def variants(source, name):
    result = []

    def add(family, text):
        if text and text != source and all(text != other for _, other in result):
            result.append((family, text))

    add('bank_index_first', bank_index_first(source, name, True))
    add('bank_index_first', bank_index_first(source, name, False))
    for text in bank_arm_scope(source, name):
        add('bank_arm_scope', text)
    for text in table_arm_scope(source, name):
        add('table_arm_scope', text)
    add('byte_entry_copy', byte_entry_copy(source, name))
    add('load_shift_split', load_shift_split(source, name))
    add('zero_arm_inversion', zero_arm_inversion(source, name))
    # the combination: the arms only match together
    text = source
    for step in (lambda t: bank_index_first(t, name, True), lambda t: byte_entry_copy(t, name),
                 lambda t: load_shift_split(t, name), lambda t: zero_arm_inversion(t, name)):
        text = step(text) or text
    add('tile_arm_chains', text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}  # the registry: no caller wiring (registry.py)
