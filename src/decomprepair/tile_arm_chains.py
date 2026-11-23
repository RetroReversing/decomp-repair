"""A table-lookup function with one arm per kind of cell, each arm computing `row * K2 + index * K1 + table` as a pointer,
written the way the compiler's allocator and cross-jumper want it (KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`).

m2c writes every arm as `p = ((i & 0xFF) * K1) + ((row * K2) + TABLE);`. A tile/collision lookup with ten of them (five
arms over a row-selected bank, five over one table) stood at 6175 and needed seven edits, none of which the permuter could
find one at a time, to reach 0. Each edit changes a different decision of the compiler; all are readings of
gcc-2.7.2's passes that the judge agreed with, labelled hypotheses:

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
5. `shared_return_split` (`goto L;` to `L: return *p << 7;`: each arm returns on its own and the arm that fell into the label
   gets a pointer of its own: a pseudo set in several arms is a global one, which the allocator colours after the
   quantities of each arm and so swaps the arm's registers; the same edit makes reorg.c annul the delay slot of the
   `return 0` test as the target has it), `label_run_copy` (a label's run copied in place of each `goto` to it, the arms'
   tails then merged back by jump.c's cross-jumping after allocation, which is what leaves the arms' chains separate)
   and `dead_local_reuse` (a local tested by an `if` whose arm leaves, and the next local first assigned after it:
   the later one takes the dead one's name, so its value is in the dead one's register) are the remaining steps.
6. `tile_arm_chains` is `bank_index_first`, `byte_entry_copy`, `dead_local_reuse` and `zero_arm_inversion` at once, since
   the arms only match together; `bank_arm_scope` and `table_arm_scope` then try the one-shot scopes arm by arm (the arms
   did not all want the same: some bank arms with the scope and some without, one table arm with the small term's add
   in a scope, one with the index value in one, one with the index read before the table's address and no scope).
   On the draft (KMC GCC 2.7.2) the combined child alone went 6175 -> 1685 and the per-arm steps below 1700; the whole
   route as the steps were found by hand, with the judge between each, was 6175 -> 2005 (arms) -> 1140 (the dead
   parameter's name reused) -> 905 (byte copy) -> 670 -> 295 (tails copied into the arms and a local per arm, with the
   later `local_web_split` and weight steps) -> 260 (loads before the shift) -> 60 -> 0 (the last arm's return not
   shared with its sibling).

Every child compiles to a program with the same behaviour as its source: the rewrites move statements and spell the same
arithmetic differently, they invent no value."""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILIES = ('bank_index_first', 'bank_arm_scope', 'table_arm_scope', 'byte_entry_copy', 'load_shift_split', 'zero_arm_inversion',
            'shared_return_split', 'label_run_copy', 'dead_local_reuse', 'tile_arm_chains')
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
    """One table arm at a time, four spellings of the same arithmetic with a different one-shot scope: the small term's
    add in a scope of its own (the index chain outranks the index value), the index value in a scope, the index value in
    a scope before the table's address is taken, and the index value read before the table's address with no scope."""
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
        forms.append(f'{{ u32 bb; u8 *bp; bb = {idx}; bp = {sym}; {lhs} = bp + bb * {k1}{tail}; }}')
        for text in forms:
            result.append(source[:hit.start()] + text + source[hit.end():])
    return result


def _declared_type(clean, name):
    hit = re.search(rf'^[ \t]*((?:(?:unsigned|signed|struct|const)\s+)?[A-Za-z_]\w*(?:\s*\*)*)\s*\**\s*\b{name}\b\s*;', clean, re.M)
    return hit and (hit.group(0).split(name)[0].strip(), hit.end(), hit.start())


def shared_return_split(source, name):
    """A `goto L;` to `L: return EXPR;`, one arm assigning the variable the return reads just before the label and others
    jumping in: each jumping arm returns on its own and the arm that falls into the label gets a variable of its own,
    so no pointer is shared across the arms (a pseudo set in several arms is a global one: the allocator, not local-alloc,
    gives it a register after the quantities of each arm, which swaps the arm's registers)."""
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    result = []
    for label in re.finditer(rf'(?<![\w.>:])(?P<label>{_IDENT})\s*:(?!:)\s*return\s+(?P<expr>[^;{{}}]+);', clean[opening:end]):
        at = opening + label.start()
        text, expr = label['label'], label['expr'].strip()
        jumps = [m for m in re.finditer(rf'\bgoto\s+{text}\s*;', clean[opening:end])]
        before = clean[opening:at]
        prior = re.search(rf'(?P<v>{_IDENT})\s*=(?!=)[^;{{}}]*;\s*\}}?\s*$', before)
        if not jumps or not prior or prior['v'] not in re.findall(_IDENT, expr):
            continue
        var = prior['v']
        decl = _declared_type(clean[opening:], var)
        if not decl or f'{var}_b' in clean:
            continue
        ctype, declaration_end, declaration_start = decl
        edited = source
        edits = []
        line = clean.rfind('\n', 0, opening + prior.start('v')) + 1
        indent = re.match(r'[ \t]*', clean[line:])[0] or '    '
        edits.append((at, opening + label.end(), f'{indent}return {re.sub(rf"(?<![\w.>]){var}\b", var + "_b", expr)};'))
        assign_start = opening + prior.start('v')
        edits.append((assign_start, assign_start + len(var), f'{var}_b'))
        for jump in jumps:
            edits.append((opening + jump.start(), opening + jump.end(), f'return {expr};'))
        for a, b, replacement in sorted(edits, reverse=True):
            edited = edited[:a] + replacement + edited[b:]
        line_end = opening + declaration_end
        edited = edited[:line_end] + f'\n    {ctype} {var}_b;' + edited[line_end:]
        result.append(edited)
    return result


def label_run_copy(source, name):
    """A label's run of statements copied in place of each `goto` to it, followed by a jump to the label the run falls
    into: the arms stop sharing one block (jump.c cross-jumps the identical tails afterwards, or not, as the target has
    it)."""
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    result = []
    labels = list(re.finditer(rf'(?<![\w.>:?])(?P<label>{_IDENT})\s*:(?!:)', clean[opening:end]))
    for number, label in enumerate(labels[:-1]):
        name_ = label['label']
        if name_ in ('default', 'else'):
            continue
        run_start = opening + label.end()
        following = labels[number + 1]
        run = source[run_start:opening + following.start()].strip('\n')
        run_clean = clean[run_start:opening + following.start()]
        if not run.strip() or len(run) > 400 or re.search(r'\b(?:return|goto|for|while|do|switch|if|case)\b|[{}]', run_clean):
            continue
        jumps = [m for m in re.finditer(rf'\bgoto\s+{name_}\s*;', clean[opening:end]) if opening + m.start() < run_start - len(name_) - 1
                 or opening + m.start() > opening + following.start()]
        if not jumps:
            continue
        text = source
        for jump in reversed(jumps):
            indent = re.search(r'[ \t]*$', source[:opening + jump.start()])[0]
            body = '\n'.join(line if not line.strip() else indent + line.strip() for line in run.split('\n'))
            text = text[:opening + jump.start()] + body.lstrip() + f'\n{indent}goto {following["label"]};' + text[opening + jump.end():]
        result.append(text)
    return result


def dead_local_reuse(source, name):
    """A local `a` that a top-level `if` tests and whose arm always leaves, then a later local `b` first assigned after the
    `if`: `b` takes `a`'s name in what follows (the later value takes the dead one's register, the parameter's when `a`
    was masked out of it), and `a`, if the code after the `if` assigns it again before reading it, gets a name of its own
    for that."""
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    last = clean.rfind('}', opening, end)
    body = clean[opening:last]
    names = list(re.findall(rf'^[ \t]*(?:(?:u|s)(?:8|16|32)|int|unsigned)\s+({_IDENT})\s*;', body, re.M))
    types = dict(re.findall(rf'^[ \t]*((?:u|s)(?:8|16|32)|int|unsigned)\s+({_IDENT})\s*;', body, re.M)[i][::-1] for i in range(len(names)))
    result = []
    depth = 0
    for hit in re.finditer(r'[{}]|(?<![\w.])if\s*\(', body):
        if hit[0] == '{':
            depth += 1
        elif hit[0] == '}':
            depth -= 1
        elif depth == 1:
            at = opening + hit.start()
            paren = clean.find('(', at)
            after = close(clean, paren)
            brace = clean.find('{', after) if after else -1
            if brace < 0 or clean[after:brace].strip():
                continue
            arm_end = close(clean, brace, '{', '}')
            if arm_end is None or re.match(r'\s*else\b', clean[arm_end:last]) or not re.search(r'(?:return[^;]*|goto\s+\w+)\s*;\s*\}$', clean[brace:arm_end]):
                continue
            condition = clean[paren:after]
            rest = clean[arm_end:last]
            for a in names:
                if not re.search(rf'(?<![\w.>]){a}\b', condition):
                    continue
                first_a = re.search(rf'(?<![\w.>]){a}\b', rest)
                if first_a and not re.match(rf'{a}\s*=(?!=)', rest[first_a.start():]):
                    continue
                for b in names:
                    if b == a or re.search(rf'(?<![\w.>]){b}\b', clean[at:arm_end]):
                        continue
                    first_b = re.search(rf'(?<![\w.>]){b}\b', rest)
                    if not first_b or not re.match(rf'{b}\s*=(?!=)', rest[first_b.start():]):
                        continue
                    fresh = f'{a}_b'
                    if fresh in clean:
                        continue
                    renamed = source[arm_end:last]
                    if first_a:
                        renamed = re.sub(rf'(?<![\w.>]){a}\b', fresh, renamed)
                    renamed = re.sub(rf'(?<![\w.>]){b}\b', a, renamed)
                    text = source[:arm_end] + renamed + source[last:]
                    if first_a:
                        declaration = re.search(rf'^[ \t]*({types.get(a, "s32")})\s+{a}\s*;[ \t]*\n', text, re.M)
                        text = text[:declaration.end()] + f'{declaration.group(0).split(a)[0]}{fresh};\n' + text[declaration.end():]
                    text = re.sub(rf'^[ \t]*(?:(?:u|s)(?:8|16|32)|int|unsigned)\s+{b}\s*;[ \t]*\n', '', text, count=1, flags=re.M)
                    if text != source and text not in result:
                        result.append(text)
    return result[:LIMIT]


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


def load_shift_pairs(source, name):
    """The `b = LOAD1; a = LOAD0 << S;` pairs of the function: (start, end, a, b, load0, load1, shift, indent)."""
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    pair = re.compile(rf'(?P<b>{_IDENT})\s*=\s*(?P<l1>{_LOAD}[^;]*);\s*(?P<a>{_IDENT})\s*=\s*(?P<l0>{_LOAD}[^;]*?)\s*<<\s*(?P<s>\d+)\s*;')
    found = []
    for hit in pair.finditer(clean, start, end):
        if hit['a'] == hit['b'] or re.search(rf'(?<![\w.>])(?:{hit["a"]}|{hit["b"]})\b', hit['l1'] + ' ' + hit['l0']):
            continue
        base = lambda text: re.sub(r'\s+', '', re.sub(r'[+-]\s*0[xX]?[0-9A-Fa-f]*\s*\)?$', '', text.split(',')[0]))
        if base(hit['l1']) != base(hit['l0']):
            continue
        a, b, l0, l1 = (source[hit.start(g):hit.end(g)] for g in ('a', 'b', 'l0', 'l1'))
        found.append((hit.start(), hit.end(), a, b, l0, l1, hit['s'], re.search(r'[ \t]*$', source[:hit.start()])[0]))
    return found


def load_shift_split(source, name, only=None):
    """`b = LOAD1; a = LOAD0 << S;` as `a = LOAD0; b = LOAD1; a = a << S;` (every pair, or the `only`th)."""
    edits = []
    for number, (a0, b0, a, b, l0, l1, shift, indent) in enumerate(load_shift_pairs(source, name)):
        if only is None or only == number:
            edits.append((a0, b0, f'{a} = {l0};\n{indent}{b} = {l1};\n{indent}{a} = {a} << {shift};'))
    return _splice(source, edits) if edits else None


def load_shift_swap(source, name, only):
    """The pair's two statements in the other order: `a = LOAD0 << S; b = LOAD1;`."""
    pairs = load_shift_pairs(source, name)
    if only >= len(pairs):
        return None
    a0, b0, a, b, l0, l1, shift, indent = pairs[only]
    return _splice(source, [(a0, b0, f'{a} = {l0} << {shift};\n{indent}{b} = {l1};')])


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
    for text in shared_return_split(source, name):
        add('shared_return_split', text)
    for text in label_run_copy(source, name):
        add('label_run_copy', text)
    for text in dead_local_reuse(source, name):
        add('dead_local_reuse', text)
    add('byte_entry_copy', byte_entry_copy(source, name))
    add('load_shift_split', load_shift_split(source, name))
    for number in range(min(len(load_shift_pairs(source, name)), 6)):
        add('load_shift_split', load_shift_split(source, name, number))
        add('load_shift_split', load_shift_swap(source, name, number))
    add('zero_arm_inversion', zero_arm_inversion(source, name))
    # the combination: the arms only match together
    text = source
    for step in (lambda t: bank_index_first(t, name, True), lambda t: byte_entry_copy(t, name),
                 lambda t: (dead_local_reuse(t, name) or [None])[0], lambda t: zero_arm_inversion(t, name)):
        text = step(text) or text
    add('tile_arm_chains', text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}  # the registry: no caller wiring (registry.py)
