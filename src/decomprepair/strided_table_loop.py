"""A loop that walks several tables with explicit induction variables (an input-poll loop over four controllers).

m2c names each table through a pointer type, so a counter that advances by a byte offset reads as an element index
(`(&half_table) + offset`), repeats the cursor's step on every path that leaves the loop body (`goto block_N`), names
a word where the target touches a halfword, and leaves memory accesses the scheduler is free to reorder. GCC 2.7.2
with `-fno-strength-reduce` shows the target's shape instead: `lui $at,%hi(table); addu $at,$at,$offset` for every
access, one pointer step at the loop tail, and loads kept behind the stores before them. Each family below is one
step of the chain that took such a function from 4,435 to exact (`probes` offers the profile and the first three
spellings as one joint child, since the profile alone changes nothing while the source still indexes by element):

- `narrow_symbol_width`: a word-sized extern the target only reads or writes as a halfword or byte.
- `byte_offset_table_index`: `(&SYM) + v` where the target adds the counter to the symbol with no shift, spelled as a
  byte offset (`(T *)((s8 *)&SYM + v)`). Direct pointer arithmetic and a helper returning `&SYM + arg` are both read.
- `record_field_table_access`: byte-offset accesses of neighbouring symbols through one counter, spelled as fields of
  one record (`((Rec *)((s8 *)&BASE + v))->f4`), for every symbol, without the first and last, and starting at the
  declared neighbour below. A struct member reference is MEM_IN_STRUCT_P to GCC 2.x, which keeps the loads behind
  the stores before them (a plain pointer dereference is hoisted by the first scheduler, and cse reuses a load a
  store between two reads should have forced again).
- `loop_join_increment`: every path of a do-while body ends in `goto block_N` or its own `p += K;`, and the label's
  block only steps the same pointer. The goto-free form: the arms drop their copy, a `goto` out of a `do {} while (0)`
  becomes the if's other arm, and the step is written once before the loop's own increments.
- `halfword_sign_test`: `x & 0x8000` as `(s16) x < 0` where the target shifts left 16 and branches on the sign.
- `repeated_load_expression`: `t = *p; r = (a ^ t) & t;` with the load written at each use.
- `call_result_direct`: `v = f(); global = v;` where `v` is also a loop counter, stored directly.
- `loop_base_pointer`: a table read at byte offsets of the counter through a local set before the loop (the target
  builds the address once into a saved register), added in the order the target adds it.
- `loop_init_order`: the assignments before the loop in the order the target initializes their registers.

The caller measures every child; the families only propose.
"""
from __future__ import annotations

import itertools
import re

from .csource import _blank, find

ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|\d+)'
SIZES = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4, 'u64': 8, 's64': 8, 'f64': 8}
TYPES = '|'.join(SIZES)
OFFSET = 'byte_offset_table_index'
FIELDS = 'record_field_table_access'
JOIN = 'loop_join_increment'


def _target(asm):
    return re.sub(r'/\*[^\n]*?\*/', '', asm)


def _externs(clean):
    return {m['name']: (m['type'], m['array'] is not None) for m in re.finditer(
        rf'\bextern\s+(?P<type>{TYPES})\s+(?P<name>{ID})\s*(?P<array>\[[^\]]*\])?\s*;', clean)}


def _aliases(clean):
    """Helpers m2c or a repair wrote as `static T *f(long a) { return (&SYM) + a; }`: name -> symbol."""
    return {m['fn']: m['sym'] for m in re.finditer(
        rf'(?:\binline\s+|\bstatic\s+)+(?:{TYPES})\s*\*\s*(?P<fn>{ID})\s*\(\s*(?:long|s32|int)\s+(?P<arg>{ID})\s*\)\s*'
        rf'\{{\s*return\s*\(\s*&\s*(?P<sym>{ID})\s*\)\s*\+\s*(?P=arg)\s*;\s*\}}', clean)}


def _steps(clean):
    """Counters the function advances by a constant: name -> the steps."""
    out = {}
    for m in re.finditer(rf'\b(?P<v>{ID})\s*\+=\s*(?P<k>{NUM})\s*;', clean):
        out.setdefault(m['v'], set()).add(int(m['k'], 0))
    return out


def _unscaled_sum(target, sym, steps):
    """True where the target adds a stepped register to the symbol's address unscaled: `lui r,%hi(S); addu r,r,$s`, or
    the address built once (`lui`/`addiu`) and added to the stepped register."""
    for k in steps:
        step = rf'(?:{k}|0[xX]{k:x})'
        for m in re.finditer(rf'\blui\s+(\$\w+),\s*%hi\({sym}\)\s*\n\s*addu\s+\1,\s*\1,\s*(\$s\d+)\s*\n', target):
            if re.search(rf'\baddiu\s+{re.escape(m[2])},\s*{re.escape(m[2])},\s*{step}\b', target):
                return True
        for m in re.finditer(rf'\blui\s+(\$\w+),\s*%hi\({sym}\)\s*\n\s*addiu\s+\1,\s*\1,\s*%lo\({sym}\)', target):
            base = re.escape(m[1])
            for add in re.finditer(rf'\baddu\s+\$\w+,\s*({base}|\$s\d+),\s*({base}|\$s\d+)\s*\n', target):
                other = add[2] if add[1] == m[1] else add[1]
                if other != m[1] and re.search(rf'\baddiu\s+{re.escape(other)},\s*{re.escape(other)},\s*{step}\b', target):
                    return True
    return False


def byte_offset_variants(source, name, arch, asm):
    """Spell `(&SYM) + v` as a byte offset where the target adds the counter to the symbol unscaled."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    externs, aliases, steps = _externs(clean), _aliases(clean), _steps(body)
    target = _target(asm)
    edits = []
    for sym, (kind, is_array) in externs.items():
        if SIZES[kind] < 2:
            continue
        for v, ks in steps.items():
            index = rf'(?P<w>\(\s*)?(?:\(\s*(?:s32|u32|int|long)\s*\)\s*)?{v}\b(?(w)\s*\))'
            forms = [rf'\(\s*&\s*{sym}\s*\)\s*\+\s*{index}', rf'(?<![\w)\]])\b{v}\s*\+\s*\(\s*&\s*{sym}\s*\)']
            if is_array:
                forms += [rf'(?<![\w&]){sym}\s*\+\s*{index}', rf'(?<![\w)\]])\b{v}\s*\+\s*{sym}\b']
            forms += [rf'\b{fn}\s*\(\s*{v}\s*\)' for fn, target_sym in aliases.items() if target_sym == sym]
            hits = [m for form in forms for m in re.finditer(form, body)]
            if hits and _unscaled_sum(target, sym, ks):
                replacement = f'(({kind} *) (((s8 *) (&{sym})) + {v}))'
                edits += [(span[0] + m.start(), span[0] + m.end(), replacement) for m in hits]
    if not edits:
        return []
    edits.sort()
    for (a, b, _), (c, d, _) in zip(edits, edits[1:]):
        if c < b:
            return []
    child = source
    for a, b, text in reversed(edits):
        child = child[:a] + text + child[b:]
    return [(OFFSET, child)]


# ---------------------------------------------------------------------------------------------------------------

_CORE = (rf'\(\s*(?P<t>{TYPES})\s*\*\s*\)\s*\(\s*\(\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*\(\s*&\s*(?P<sym>{ID})\s*\)'
         rf'\s*\)\s*\+\s*(?P<v>{ID})\s*\)')
_RAW = re.compile(rf'\*\s*(?P<open>(?:\(\s*)*){_CORE}(?P<close>(?:\s*\))*)')


_BYTE = re.compile(rf'\*\s*(?P<open>(?:\(\s*)*)(?:\(\s*&\s*(?P<s1>{ID})\s*\)|(?P<s2>{ID}))\s*\+\s*(?P<v>{ID})'
                   rf'(?P<close>(?:\s*\))*)')


def _balanced(m, opened_group='open', closed_group='close'):
    """End of a match whose leading parentheses are all closed inside it, or None."""
    opened = m[opened_group].count('(')
    closers = list(re.finditer(r'\)', m[closed_group]))
    if opened > len(closers):
        return None
    return m.start(closed_group) + (closers[opened - 1].end() if opened else 0)


def _derefs(body, externs):
    """(start, end, type, symbol, counter) of each `*(T *)((s8 *)&SYM + v)` and each byte table read `*(SYM + v)`."""
    found = []
    for m in _RAW.finditer(body):
        if (end := _balanced(m)) is not None:
            found.append((m.start(), end, m['t'], m['sym'], m['v']))
    for m in _BYTE.finditer(body):
        sym = m['s1'] or m['s2']
        if sym in externs and SIZES[externs[sym][0]] == 1 and (end := _balanced(m)) is not None:
            found.append((m.start(), end, externs[sym][0], sym, m['v']))
    return sorted(found)


def _address(sym):
    m = re.search(r'([0-9A-Fa-f]{8})$', sym)
    return int(m[1], 16) if m else None


def _load_type(target, sym, kind):
    """The width and sign the target loads the symbol with, where it loads it (the declaration may disagree)."""
    seen = {m[1] for m in re.finditer(rf'\b(lbu|lb|lhu|lh)\s+\$\w+,\s*%lo\({sym}\)', target)}
    mapped = {'lbu': 'u8', 'lb': 's8', 'lhu': 'u16', 'lh': 's16'}
    return mapped[next(iter(seen))] if len(seen) == 1 else kind


def _neighbours(clean, groups):
    """For each counter, the declared symbol just below its lowest one (within 0x10), when there is one."""
    declared = {sym: _address(sym) for sym in _externs(clean) if _address(sym) is not None}
    found = {}
    for v, symbols in groups.items():
        low = min(address for address, _ in symbols.values())
        close = [(address, sym) for sym, address in declared.items() if low - 0x10 <= address < low and sym not in symbols]
        if close:
            found[v] = max(close)
    return found


def _record_groups(source, name, asm):
    """[(counter, {symbol: (address, type)}, hits)] for each counter that indexes neighbouring symbols."""
    span = find(source, name)
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    target = _target(asm)
    hits = _derefs(body, _externs(clean))
    groups = {}
    for _, _, kind, sym, v in hits:
        if (address := _address(sym)) is not None:
            groups.setdefault(v, {}).setdefault(sym, (address, _load_type(target, sym, kind)))
    return span, hits, target, _neighbours(clean, groups), {
        v: symbols for v, symbols in groups.items()
        if len(symbols) >= 2 and max(a for a, _ in symbols.values()) - min(a for a, _ in symbols.values()) <= 0x20
        and all(re.search(rf'%lo\({sym}\)', target) for sym in symbols)}


def _record_child(source, span, hits, groups, chosen):
    typedefs, edits = '', []
    for v, symbols in groups.items():
        names, below = chosen[v]
        symbols = {sym: item for sym, item in symbols.items() if sym in names}
        base = min(address for address, _ in symbols.values())
        base_name = None
        if below:  # the declared neighbour just under the first field: the record starts there
            base, base_name = below
        fields = {}
        for address, kind in sorted(symbols.values()):
            if (address - base) % SIZES[kind] or fields.setdefault(address - base, kind) != kind:
                return None
        record, fields_c, at = f'DecompRecord{base:08X}', '', 0
        if record in source:
            return None
        base_symbol = base_name or next(sym for sym, (address, _) in symbols.items() if address == base)
        for offset in sorted(fields):
            if offset > at:
                fields_c += f' u8 pad{at:x}[{offset - at}];'
            fields_c += f' {fields[offset]} f{offset:x};'
            at = offset + SIZES[fields[offset]]
        typedefs += f'typedef struct {{{fields_c} }} {record};\n'
        for a, b, kind, sym, counter in hits:
            if counter == v and sym in symbols:
                offset = symbols[sym][0] - base
                edits.append((span[0] + a, span[0] + b,
                              f'((({record} *) (((s8 *) (&{base_symbol})) + {v}))->f{offset:x})'))
    child = source
    for a, b, text in sorted(edits, reverse=True):
        child = child[:a] + text + child[b:]
    return child[:span[0]] + typedefs + child[span[0]:]


def record_field_variants(source, name, arch, asm):
    """Byte-offset accesses of neighbouring symbols through one counter, written as fields of one record: every
    symbol, and without the lowest and highest ones (a symbol the loop also reaches as a plain halfword or compare
    stays a plain access)."""
    if arch != 'mips' or not find(source, name):
        return []
    span, hits, target, neighbours, groups = _record_groups(source, name, asm)
    if not groups:
        return []
    options = {}
    for v, symbols in groups.items():
        ordered = sorted(symbols, key=lambda sym: symbols[sym][0])
        subsets = [ordered]
        for trimmed in (ordered[1:], ordered[1:-1]):
            if len(trimmed) >= 2 and trimmed not in subsets:
                subsets.append(trimmed)
        options[v] = [(subset, None) for subset in subsets]
        if v in neighbours:
            address, symbol = neighbours[v]
            options[v] += [(subset, (address, symbol)) for subset in subsets]
    out, seen = [], set()
    counters = list(options)
    for picks in itertools.product(*(range(len(options[v])) for v in counters)):
        chosen = {v: options[v][pick] for v, pick in zip(counters, picks)}
        if (child := _record_child(source, span, hits, groups, chosen)) and child not in seen:
            seen.add(child)
            out.append((FIELDS, child))
        if len(out) >= 16:
            break
    return out


# ---------------------------------------------------------------------------------------------------------------


class _Bail(Exception):
    pass


def _python_close(clean, i):
    """Index just past the brace block opening at clean[i]."""
    depth = 0
    for k in range(i, len(clean)):
        depth += (clean[k] == '{') - (clean[k] == '}')
        if depth == 0:
            return k + 1
    raise _Bail


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(clean, i):
        found = _scan.close_every(clean, i, '{', '}', True, None)
        if found is NotImplemented:
            return _python_close(clean, i)
        if found is None:
            raise _Bail
        return found


def _python_paren(clean, i):
    depth = 0
    for k in range(i, len(clean)):
        depth += (clean[k] == '(') - (clean[k] == ')')
        if depth == 0:
            return k + 1
    raise _Bail


_paren = _python_paren
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _paren(clean, i):
        found = _scan.close_every(clean, i, '(', ')', True, None)
        if found is NotImplemented:
            return _python_paren(clean, i)
        if found is None:
            raise _Bail
        return found


class _Parser:
    """Statements of an m2c body: braced ifs, `do {} while (0);`, labels, gotos; anything else is kept verbatim."""

    def __init__(self, source, clean):
        self.source, self.clean = source, clean

    def block(self, i):
        """(nodes, index after the closing brace) for the block whose '{' is at i."""
        end = _close(self.clean, i)
        nodes, at = self.statements(i + 1, end - 1)
        return nodes, end

    def statements(self, at, end):
        nodes = []
        clean = self.clean
        while True:
            m = re.compile(r'\s*').match(clean, at)
            at = m.end()
            if at >= end:
                return nodes, at
            rest = clean[at:end]
            if keyword := re.match(r'if\s*\(', rest):
                cond_end = _paren(clean, at + keyword.end() - 1)
                cond = self.source[at + keyword.end() - 1:cond_end]
                at = self.skip(cond_end)
                if clean[at] != '{':
                    raise _Bail
                then, at = self.block(at)
                other = None
                follow = re.compile(r'\s*else\b\s*').match(clean, at)
                if follow:
                    at = follow.end()
                    if clean[at] == '{':
                        other, at = self.block(at)
                    elif re.match(r'if\s*\(', clean[at:]):
                        chained, at = self.statements_one(at, end)
                        other = [chained]
                    else:
                        raise _Bail
                nodes.append(('if', cond, then, other))
            elif re.match(r'do\b\s*\{', rest):
                at = self.skip(at + 2)
                body, at = self.block(at)
                tail = re.compile(r'\s*while\s*\(([^()]*)\)\s*;').match(clean, at)
                if not tail:
                    raise _Bail
                at = tail.end()
                nodes.append(('do0', body) if tail[1].strip() == '0' else ('raw', self.source[m.end():at]))
            elif goto := re.match(rf'goto\s+({ID})\s*;', rest):
                nodes.append(('goto', goto[1]))
                at += goto.end()
            elif label := re.match(rf'(?!case\b|default\b)({ID})\s*:(?!:)', rest):
                nodes.append(('label', label[1]))
                at += label.end()
            elif re.match(r'(?:for|while|switch)\s*\(', rest) or rest[0] == '{':
                at = self.opaque(at, end)
                nodes.append(('raw', self.source[m.end():at]))
            else:
                stop = self.simple_end(at, end)
                nodes.append(('simple', self.source[at:stop].strip()))
                at = stop

    def statements_one(self, at, end):
        sub_nodes, stop = self.statements_until_one(at, end)
        return sub_nodes, stop

    def statements_until_one(self, at, end):
        keyword = re.match(r'if\s*\(', self.clean[at:end])
        cond_end = _paren(self.clean, at + keyword.end() - 1)
        cond = self.source[at + keyword.end() - 1:cond_end]
        at = self.skip(cond_end)
        if self.clean[at] != '{':
            raise _Bail
        then, at = self.block(at)
        other = None
        follow = re.compile(r'\s*else\b\s*').match(self.clean, at)
        if follow:
            at = follow.end()
            if self.clean[at] == '{':
                other, at = self.block(at)
            else:
                raise _Bail
        return ('if', cond, then, other), at

    def skip(self, at):
        return re.compile(r'\s*').match(self.clean, at).end()

    def opaque(self, at, end):
        head = re.compile(r'(?:for|while|switch)\s*\(').match(self.clean, at)
        if head:
            at = self.skip(_paren(self.clean, at + head.end() - 1))
        if self.clean[at] != '{':
            raise _Bail
        return _close(self.clean, at)

    def simple_end(self, at, end):
        depth = 0
        for k in range(at, end):
            depth += self.clean[k] in '({[' 
            depth -= self.clean[k] in ')}]'
            if self.clean[k] == ';' and depth <= 0:
                return k + 1
        raise _Bail


def _mentions(node, pattern):
    kind = node[0]
    if kind in ('simple', 'raw'):
        return bool(re.search(pattern, node[1]))
    if kind == 'goto':
        return bool(re.search(pattern, node[1]))
    if kind == 'label':
        return bool(re.search(pattern, node[1]))
    if kind == 'do0':
        return any(_mentions(n, pattern) for n in node[1])
    return bool(re.search(pattern, node[1])) or any(
        _mentions(n, pattern) for branch in node[2:] if branch for n in branch)


def _tailed(nodes, label, step):
    """The nodes with their leave-the-body copies removed, or None when a path would change meaning."""
    out = list(nodes)
    for index, node in enumerate(out):
        if node[0] == 'do0':
            before, rest = out[:index], out[index + 1:]
            body = list(node[1])
            if not body or body[-1][0] != 'if' or body[-1][3] is not None or any(
                    _mentions(n, rf'\b{label}\b') for n in body[:-1]):
                return None
            guard = body[-1]
            arm = _tailed(guard[2], label, step)
            other = _tailed(rest, label, step)
            if arm is None or other is None or not rest:
                return None
            return before + body[:-1] + [('if', guard[1], arm, other)]
        if node[0] == 'goto' and node[1] == label and index != len(out) - 1:
            return None
    if not out:
        return None
    last = out[-1]
    if last[0] == 'goto' and last[1] == label:
        return out[:-1] if not any(_mentions(n, rf'\b{label}\b') for n in out[:-1]) else None
    if last == ('simple', step):
        return out[:-1] if not any(_mentions(n, rf'\b{label}\b') for n in out[:-1]) else None
    if last[0] == 'if' and last[3] is not None:
        arm, other = _tailed(last[2], label, step), _tailed(last[3], label, step)
        if arm is None or other is None and last[3]:
            return None
        if any(_mentions(n, rf'\b{label}\b') for n in out[:-1]):
            return None
        return out[:-1] + [('if', last[1], arm, other)]
    return None


def _print(nodes, indent):
    pad = ' ' * indent
    lines = []
    for node in nodes:
        kind = node[0]
        if kind in ('simple', 'raw'):
            lines += [pad + line.strip() if n == 0 else pad + line.rstrip() for n, line in enumerate(node[1].split('\n'))]
        elif kind == 'if':
            then, other = node[2], node[3]
            cond = node[1]
            if not then and other:
                cond, then, other = f'(!({cond[1:-1]}))', other, None
            lines += [f'{pad}if {cond}', pad + '{', *_print(then, indent + 2), pad + '}']
            if other:
                lines += [pad + 'else', pad + '{', *_print(other, indent + 2), pad + '}']
        elif kind == 'do0':
            lines += [pad + 'do', pad + '{', *_print(node[1], indent + 2), pad + '}', pad + 'while (0);']
        else:
            raise _Bail
    return lines


def join_increment_variants(source, name, arch, asm):
    """A do-while body whose every path steps a pointer (`goto block_N`, or its own copy): written once at the tail."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    parser = _Parser(source, clean)
    for loop in re.finditer(r'\bdo\s*\{', clean[span[0]:span[1]]):
        brace = span[0] + loop.end() - 1
        try:
            body, after = parser.block(brace)
            tail = re.compile(r'\s*while\s*\((?!\s*0\s*\))[^;]*\)\s*;').match(clean, after)
            if not tail:
                continue
            owner = next((i for i, node in enumerate(body) if node[0] == 'if' and node[3] and len(node[3]) == 2
                          and node[3][0][0] == 'label' and re.fullmatch(rf'{ID}\s*\+=\s*{NUM}\s*;', node[3][1][1])), None)
            if owner is None:
                continue
            label, step = body[owner][3][0][1], body[owner][3][1][1]
            then = _tailed(body[owner][2], label, step)
            rest = body[owner + 1:]
            if (then is None or any(_mentions(n, rf'\b{label}\b|\bgoto\b') for n in then)
                    or any(_mentions(n, rf'\b{label}\b|\bgoto\b|\bcontinue\b') for n in body[:owner] + rest)
                    or not rest or any(n[0] != 'simple' for n in rest)):
                continue
            guard = body[owner]
            indent = len(source[source.rfind('\n', 0, brace) + 1:brace]) - len(source[source.rfind('\n', 0, brace) + 1:brace].lstrip()) + 2
            nodes = body[:owner] + [('if', guard[1], then, None)] + [('simple', step)] + rest
            text = '\n'.join(_print(nodes, indent)) + '\n'
            start = brace + 1
            # the line break after `{` stays; the closing brace keeps its own line
            closing = after - 1
            child = source[:start] + '\n' + text + source[closing - (closing - source.rfind('\n', 0, closing) - 1):]
            return [(JOIN, child)]
        except _Bail:
            continue
    return []


# ---------------------------------------------------------------------------------------------------------------

SIGN_TEST = 'halfword_sign_test'
REPEATED_LOAD = 'repeated_load_expression'


def sign_test_variants(source, name, arch, asm):
    """`if (x & 0x8000)` on a halfword value, written as the sign test the target's `sll 16; bgez` is."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    target = _target(asm)
    if not re.search(r'\bsll\s+(\$\w+),\s*\$\w+,\s*(?:0x10|16)\s*\n\s*(?:bgez|bltz)\s+\1\b', target):
        return []
    clean = _blank(source)
    pattern = re.compile(rf'\bif\s*\(\s*\(?\s*(?P<x>{ID})\s*&\s*(?:0x8000|32768)\s*\)?\s*\)')
    hit = pattern.search(clean, *span)
    if not hit:
        return []
    return [(SIGN_TEST, source[:hit.start()] + f'if ((s16) {hit["x"]} < 0)' + source[hit.end():])]


def repeated_load_variants(source, name, arch, asm=''):
    """`t = *p; r = (a ^ t) & t;` with `t` used nowhere else: the load written at each use (cse then keeps one load
    where nothing stores between them, and reloads where a store does)."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    pattern = re.compile(rf'(?P<t>{ID})\s*=\s*(?P<cast>\((?:u8|s8|u16|s16|u32|s32)\)\s*)?'
                         rf'\((?P<load>[^;{{}}=]*(?:\*|->)[^;{{}}=]*)\)\s*;\s*(?P<use>[^;{{}}]*;)')
    call = re.compile(r'\b(?!u8\b|s8\b|u16\b|s16\b|u32\b|s32\b)\w+\s*\(')
    for hit in pattern.finditer(clean, *span):
        t = hit['t']
        uses = list(re.finditer(rf'\b{t}\b', hit['use']))
        if call.search(hit['load']) or hit['load'].count('(') != hit['load'].count(')'):
            continue
        if len(uses) < 2 or re.search(rf'\b{t}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\+\+\s*{t}\b|\b{t}\s*\+\+|'
                                      rf'(?:^|[(,=!&|^+\-*/<>?:])\s*&\s*{t}\b', hit['use']):
            continue
        later = re.search(rf'\b{t}\b', clean[hit.end():span[1]])
        if later and not re.compile(rf'{t}\s*=(?!=)').match(clean, hit.end() + later.start()):
            continue
        load = f'({hit["load"]})' if not hit['cast'] else f'({hit["cast"].strip()} ({hit["load"]}))'
        use_start = hit.start('use')
        new_use = re.sub(rf'\b{t}\b', load.replace('\\', '\\\\'), source[use_start:hit.end('use')])
        return [(REPEATED_LOAD, source[:hit.start()] + new_use + source[hit.end('use'):])]
    return []


def _unreduced_symbols(asm):
    """Symbols the target addresses as `lui r,%hi(S); addu r,r,$s` with an induction register the function steps."""
    target = _target(asm)
    steps = {m[1] for m in re.finditer(r'\baddiu\s+(\$s\d+),\s*(\$s\d+),\s*(?:0x[\da-fA-F]+|\d+)\b', target)
             if m[1] == m[2]}
    found = {}
    for m in re.finditer(r'\blui\s+(\$\w+),\s*%hi\(([^()]+)\)\s*\n\s*addu\s+\1,\s*\1,\s*(\$s\d+)\b', target):
        if m[3] in steps:
            found[m[2]] = found.get(m[2], 0) + 1
    return {sym for sym, count in found.items() if count >= 2}


def probes(proj, fn, own, header=''):
    """The profile without strength reduction joined with the table-loop spellings (the profile alone changes nothing
    while the source still indexes by element: GCC reduces `&table + offset` into a pointer either way)."""
    if dict(proj).get('arch') != 'mips' or own.get('toolchain') != 'gcc-2.7.2-kmc':
        return []
    flags = own['flags'].split() if isinstance(own['flags'], str) else list(own['flags'])
    source, name, asm = fn['best_source'], fn['name'], dict(fn).get('asm') or ''
    if '-fno-strength-reduce' in flags or not source or len(_unreduced_symbols(asm)) < 2:
        return []
    out, child = [], source
    for family in (byte_offset_variants, record_field_variants, join_increment_variants):
        if made := family(child, name, 'mips', asm):
            child = made[0][1]
            out.append(child)
    return [([*flags, '-fno-strength-reduce'], child) for child in dict.fromkeys(out)]


# ---------------------------------------------------------------------------------------------------------------

BASE_POINTER = 'loop_base_pointer'
INIT_ORDER = 'loop_init_order'

_SUM = re.compile(rf'\(\s*(?P<t>{TYPES})\s*\*\s*\)\s*\(\s*\(\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*'
                  rf'(?:\(\s*&\s*(?P<s1>{ID})\s*\)|&\s*(?P<s2>{ID})|\(\s*(?P<s3>{ID})\s*\)|(?P<s4>{ID}))\s*\)\s*'
                  rf'\+\s*(?P<v>{ID})\s*\)')


def loop_base_pointer_variants(source, name, arch, asm):
    """A table read at several byte offsets of the loop's counter, its base address held in a local set before the
    loop (the target builds it once into a saved register) and added the way the target adds it."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    target = _target(asm)
    steps = {m[1] for m in re.finditer(r'\baddiu\s+(\$s\d+),\s*(\$s\d+),\s*(?:0x[\da-fA-F]+|\d+)\b', target) if m[1] == m[2]}
    externs = _externs(clean)
    uses = {}
    for m in _SUM.finditer(body):
        sym = m['s1'] or m['s2'] or m['s3'] or m['s4']
        if sym in externs:
            uses.setdefault((sym, m['v'], m['t']), []).append(m)
    loop = re.search(r'\bdo\s*\{', body)
    for (sym, v, kind), hits in uses.items():
        if len(hits) < 2 or not loop or any(h.start() < loop.start() for h in hits):
            continue
        hoist = re.search(rf'\blui\s+(\$s\d+),\s*%hi\({sym}\)\s*\n\s*addiu\s+\1,\s*\1,\s*%lo\({sym}\)', target)
        if not hoist or (base := hoist[1]) in steps:
            continue
        add = next((m for m in re.finditer(r'\baddu\s+\$\w+,\s*(\$s\d+),\s*(\$s\d+)\s*\n', target)
                    if base in (m[1], m[2]) and (m[1] in steps or m[2] in steps)), None)
        if not add:
            continue
        local = f'decomp_base_{sym}'
        if local in source:
            continue
        counter_first = add[1] != base
        pointer = f'{externs[sym][0]} *'
        value = sym if externs[sym][1] else f'&{sym}'
        text = f'(({kind} *) ({v} + (u32) {local}))' if counter_first else f'(({kind} *) ((u32) {local} + {v}))'
        child = source
        for m in reversed(hits):
            child = child[:span[0] + m.start()] + text + child[span[0] + m.end():]
        at = span[0] + loop.start()
        child = child[:at] + f'{local} = {value};\n    ' + child[at:]
        brace = child.index('{', span[0])
        child = child[:brace + 1] + f'\n  {pointer}{local};' + child[brace + 1:]
        return [(BASE_POINTER, child)]
    return []


def _preloop(target):
    """The register initializations just before the first loop's label, in order: (register, kind, symbol)."""
    lines = [line.strip() for line in target.split('\n') if line.strip()]
    labels = {line[:-1]: i for i, line in enumerate(lines) if re.fullmatch(r'\.?L\w+:', line)}
    head = None
    for i, line in enumerate(lines):
        if m := re.search(r'\b(?:b\w+|j)\s+(?:[^,\s]+,\s*)*(\.?L\w+)\s*$', line):
            if labels.get(m[1], 10**9) < i:
                head = labels[m[1]]
                break
    if head is None:
        return None
    start = max((i for i in range(head) if re.match(r'jal\b', lines[i])), default=-1) + 2  # the delay slot stays
    out, i = [], start
    while i < head:
        line = lines[i]
        if m := re.fullmatch(r'(?:addu|or)\s+(\$s\d+),\s*\$zero,\s*\$zero|move\s+(\$s\d+),\s*\$zero', line):
            out.append((m[1] or m[2], 'zero', None))
        elif m := re.fullmatch(r'lui\s+(\$s\d+),\s*%hi\(([^()]+)\)', line):
            out.append((m[1], 'sym', m[2]))
            i += 1  # its addiu
        elif m := re.fullmatch(r'(?:addu|or)\s+(\$s\d+),\s*(\$s\d+),\s*\$zero|move\s+(\$s\d+),\s*(\$s\d+)', line):
            out.append((m[1] or m[3], 'copy', None))
        elif re.match(r'\.?L\w+:', line):
            pass
        else:
            return None
        i += 1
    return out


def loop_init_order_variants(source, name, arch, asm):
    """The assignments before a do-while written in the order the target initializes their registers: the counter's
    zero first, a symbol's address where the target builds it, a value the call before the loop already held as a copy
    of that register, the other counters' zeros by descending step."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    order = _preloop(_target(asm))
    loop = re.search(r'\bdo\s*\{', clean[span[0]:span[1]])
    if not order or not loop or len(order) < 3:
        return []
    at = span[0] + loop.start()
    block = re.search(rf'(?:\s*{ID}\s*=\s*(?:0|&?{ID})\s*;)+\s*$', clean[span[0]:at])
    if not block:
        return []
    start = span[0] + block.start()
    stmts = list(re.finditer(rf'(?P<v>{ID})\s*=\s*(?P<e>0|&?{ID})\s*;', clean[start:at]))
    if len(stmts) != len(order):
        return []
    counter = re.search(rf'\bwhile\s*\(\s*(?P<v>{ID})\s*<', clean[at:span[1]])
    steps = _steps(clean[at:span[1]])
    zeros = iter(sorted((s for s in stmts if s['e'] == '0'),
                        key=lambda s: (s['v'] != (counter['v'] if counter else None), -max(steps.get(s['v'], {0})))))
    built = {sym for _, kind, sym in order if kind == 'sym'}
    by_symbol = {s['e'].lstrip('&'): s for s in stmts if s['e'] != '0'}
    copies = iter([s for s in stmts if s['e'] != '0' and s['e'].lstrip('&') not in built])
    chosen = []
    for _, kind, sym in order:
        item = next(zeros, None) if kind == 'zero' else by_symbol.get(sym) if kind == 'sym' else next(copies, None)
        if item is None or item in chosen:
            return []
        chosen.append(item)
    indent = re.match(r'\s*', clean[start:at])[0].replace('\n', '') or '    '
    text = ''.join(f'\n{indent}{source[start + s.start():start + s.end()]}' for s in chosen) + '\n' + indent
    child = source[:start] + text + source[at:]
    return [(INIT_ORDER, child)] if child != source else []


# ---------------------------------------------------------------------------------------------------------------

NARROW = 'narrow_symbol_width'
RESULT_DIRECT = 'call_result_direct'


def _accesses(target, sym):
    """The widths the target reads or writes the symbol with: by its own `%lo`, or through the register it built
    (`lui`/`addiu`), perhaps added to an index first. A saved register keeps the address for the whole function; a
    temporary only for the next few instructions."""
    lines = [line.strip() for line in target.split('\n') if line.strip()]
    memory = re.compile(r'(lbu|lb|lhu|lh|lw|sb|sh|sw)\s+\$\w+,\s*(?:%lo\([^()]+\)|0x[\da-fA-F]+|\d+)?\((\$\w+)\)')
    seen = set()
    for i, line in enumerate(lines):
        if not (m := re.fullmatch(rf'lui\s+(\$\w+),\s*%hi\({re.escape(sym)}\)', line)):
            continue
        base = m[1]
        registers = {base}
        for follow in lines[i + 1:] if base.startswith('$s') else lines[i + 1:i + 9]:
            if add := re.fullmatch(r'addu\s+(\$\w+),\s*(\$\w+),\s*(\$\w+)', follow):
                if registers & {add[2], add[3]}:
                    registers.add(add[1])
                continue
            if (access := memory.fullmatch(follow)) and access[2] in registers:
                symbolic = re.search(r'%lo\(([^()]+)\)', follow)
                if not symbolic or symbolic[1] == sym:
                    seen.add(access[1])
                    if not base.startswith('$s'):
                        break
    return seen


def narrow_symbol_variants(source, name, arch, asm):
    """A word-sized global the target only reads or writes as a halfword or byte, declared as that width."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    target = _target(asm)
    mapped = {'lbu': 'u8', 'lb': 's8', 'lhu': 'u16', 'lh': 's16', 'sb': 'u8', 'sh': 'u16'}
    changes = {}
    for sym, (kind, _) in _externs(clean).items():
        if SIZES[kind] != 4 or kind == 'f32' or not re.search(rf'\b{sym}\b', body):
            continue
        seen = _accesses(target, sym)
        types = {mapped[op] for op in seen if op in mapped}
        if seen and not seen & {'lw', 'sw'} and len(types) == 1:
            changes[sym] = (kind, types.pop())
    if not changes:
        return []
    child = source
    for sym, (old, new) in changes.items():
        child = re.sub(rf'(\bextern\s+){old}(\s+{sym}\s*(?:\[[^\]]*\])?\s*;)', rf'\g<1>{new}\g<2>', child)
        child = re.sub(rf'\(\s*{old}\s*\*\s*\)(\s*\(\s*\(\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*\(\s*&\s*{sym}\s*\))',
                       rf'({new} *)\g<1>', child)
    return [(NARROW, child)] if child != source else []


def call_result_direct_variants(source, name, arch, asm=''):
    """`v = f(...); global = v;` where `v` is a counter the function steps: the call's result stored directly, so the
    counter keeps one live range (m2c reused its name for each switch case's result)."""
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    counters = _steps(body)
    externs = _externs(clean)
    pattern = re.compile(rf'(?P<v>{ID})\s*=\s*(?P<call>{ID}\s*\([^;{{}}]*\))\s*;\s*(?P<g>{ID})\s*=\s*(?P=v)\s*;')
    found = [m for m in pattern.finditer(body) if m['v'] in counters and m['g'] in externs]
    edits = []
    for v in {m['v'] for m in found}:
        mine = [m for m in found if m['v'] == v]
        # from the first of them on, every mention is an assignment or the copy rewritten here: no path after a case
        # reads the counter's old value
        start = min(m.start() for m in mine)
        if all(any(m.start('g') <= start + mention.start() < m.end() for m in mine)
               or re.compile(rf'{v}\s*=(?!=)').match(body, start + mention.start())
               for mention in re.finditer(rf'\b{v}\b', body[start:])):
            edits += [(span[0] + m.start(), span[0] + m.end(), f'{m["g"]} = {m["call"]};') for m in mine]
    if not edits:
        return []
    child = source
    for a, b, text in reversed(edits):
        child = child[:a] + text + child[b:]
    return [(RESULT_DIRECT, child)]
