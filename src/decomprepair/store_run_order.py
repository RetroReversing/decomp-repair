"""Independent stores through one base pointer, written in another order, and a constant stored twice kept in a local.

Matched on three N64 object constructors (`-G0 -mips3 -O2 -mfp64`, a record from an allocation call, then a run of
field stores) that stood at 80 each and reached 0 by statement order alone: `p->0x64 = 0xC8;` written above the
`p->0x98 = &handler;` that m2c puts first, and, in a third constructor, the last two statements of a five-statement run
swapped. The scheduler orders independent insns by priority and, among equal ones, by the order the statements came, and
the allocator numbers pseudos by first use, so the order of a run of independent stores decides which constant is loaded
into which register and whether it comes before the `lui/addiu` of an address. Nothing offered it: `statement_slide`
reads only `M2C_FIELD` cells whose type has no pointer (a store of `M2C_UNK **`, the spelling of every code address
m2c stores, made its statement "not a cell" and so a barrier), `independent_statement_swap` and `adjacent_cast_store_swap`
refuse a statement that holds an `&` or a second base, `offset_store_order` wants distinct offsets in one order and
`member_store_hoist` only `->` members.

What this reads, for the function's runs of simple statements (a call, a branch, a label or a declaration ends a run):

    `base[off] = value;`, in every spelling of one cell the agents and m2c write: `M2C_FIELD(base, type *, off)`,
    `*(T *)((char *)base + off)`, `((Rec *) ((char *) base + off))->v` (a one-member record around the type),
    `base->member`, `base[3]`
    `local = value;`, `local op= value;`      a plain local (declared, never address-taken, not `volatile`)

where a value is made of literals, locals and parameters, `&symbol`, casts, operators (a division only by a
literal) and reads of cells (`local = base[0x94] / 3;`). A statement that reads a bare global, calls, dereferences
an unknown pointer or uses `volatile` is a barrier like a call. Two statements commute when no local is written by one and touched by the other and no cell
of one overlaps a cell of the other: two cells of one base are told apart by their byte ranges (the type's width), two
members by name, two indices by value; cells of different bases, or of one base in two spellings, are never told apart.

Children (`store_run_order`), each only when it differs from the source and every statement it passes commutes with the
moved one, in this order: each adjacent swap, then each statement moved to the front of its run, then each moved to the
back, those that involve a store of a constant or of an address first (the values the compiler has to build in a register),
bounded to `LIMIT` children.

`store_run_constant_local` (`k = C;` once used twice): a literal stored through cells of one type at two or more places,
as in `p->0 = 0x117;` before and after a call, becomes a local assigned once (`k = 0x117;`, right before the first store
or at the front of its run) and read at each store. That pins one `li` for the repeated constant. It is offered only for
integer cell types and a value other than 0.

Hypotheses from three matches, not from the compiler source; the judge decides every child."""
import re

from .integer_repair_support import IDENT, edit, view
from .statement_slide import _runs

FAMILY = 'store_run_order'
FAMILY_CONSTANT = 'store_run_constant_local'
FAMILIES = (FAMILY, FAMILY_CONSTANT)
LIMIT = 24
CONSTANT_LIMIT = 4
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'

_WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 'M2C_UNK8': 1, 's16': 2, 'u16': 2, 'short': 2, 'M2C_UNK16': 2,
          's32': 4, 'u32': 4, 'f32': 4, 'int': 4, 'float': 4, 'long': 4, 'unsigned': 4, 'M2C_UNK': 4, 'M2C_UNK32': 4,
          's64': 8, 'u64': 8, 'f64': 8, 'double': 8}
_INTEGER = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'char', 'short', 'long'}
_TYPE_WORDS = set(_WIDTH) | {'signed', 'void', 'const', 'volatile', 'struct', 'union', 'size_t'}
_NOT_DECLARATIONS = {'return', 'goto', 'case', 'else', 'extern', 'typedef', 'break', 'continue', 'default'}
_TOKEN = re.compile(rf'\s*(?:(?P<num>0[xX][0-9a-fA-F]+[uUlL]*|\d+\.\d*[fF]?|\.\d+[fF]?|\d+[uUlL]*)|(?P<id>{IDENT})'
                    r'|(?P<op><<=|>>=|->|<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|[-+*/%&|^]=|[-+*/%&|^~!<>=?:,.()\[\]]))')
_BINARY = {'||': 1, '&&': 2, '|': 3, '^': 4, '&': 5, '==': 6, '!=': 6, '<': 7, '>': 7, '<=': 7, '>=': 7,
           '<<': 8, '>>': 8, '+': 9, '-': 9, '*': 10, '/': 10, '%': 10}
_ASSIGN = {'=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='}
_FIELD = re.compile(rf'M2C_FIELD\(\s*({IDENT})\s*,\s*([^,()]+?)\s*,\s*({NUMBER})\s*\)')


class _Bad(Exception):
    pass


def _tokens(text):
    out, pos = [], 0
    text = _FIELD.sub(lambda m: f'*({m[2]})((char *){m[1]} + {m[3]})', text)
    while text[pos:].strip():
        hit = _TOKEN.match(text, pos)
        if not hit:
            raise _Bad
        out.append((hit.lastgroup, hit.group(hit.lastgroup)))
        pos = hit.end()
    return out


class _Parser:
    """The C expression subset the stores are written in, as nested tuples; anything else raises `_Bad`."""

    def __init__(self, text):
        self.toks = _tokens(text)
        self.at = 0

    def peek(self, ahead=0):
        index = self.at + ahead
        return self.toks[index][1] if index < len(self.toks) else None

    def take(self, expected=None):
        if self.at >= len(self.toks) or (expected is not None and self.toks[self.at][1] != expected):
            raise _Bad
        self.at += 1
        return self.toks[self.at - 1]

    def parse(self):
        node = self.assign()
        if self.at != len(self.toks):
            raise _Bad
        return node

    def assign(self):
        left = self.ternary()
        if self.peek() in _ASSIGN:
            op = self.take()[1]
            return ('assign', op, left, self.assign())
        return left

    def ternary(self):
        cond = self.binary(1)
        if self.peek() == '?':
            self.take()
            one = self.assign()
            self.take(':')
            return ('tern', cond, one, self.ternary())
        return cond

    def binary(self, least):
        left = self.unary()
        while self.peek() in _BINARY and _BINARY[self.peek()] >= least:
            op = self.take()[1]
            left = ('bin', op, left, self.binary(_BINARY[op] + 1))
        return left

    def cast_type(self):
        """The text of a parenthesised type at the cursor, or None when the parenthesis is an expression."""
        if self.peek() != '(':
            return None
        index, words = self.at + 1, []
        while index < len(self.toks) and (self.toks[index][0] == 'id' or self.toks[index][1] == '*'):
            words.append(self.toks[index][1])
            index += 1
        if not words or index >= len(self.toks) or self.toks[index][1] != ')':
            return None
        names = [w for w in words if w != '*']
        if words[-1] == '*' and names or (names and all(w in _TYPE_WORDS for w in names)):
            self.at = index + 1
            return ' '.join(words)
        return None

    def unary(self):
        tok = self.peek()
        if tok in ('-', '+', '~', '!'):
            self.take()
            return ('un', tok, self.unary())
        if tok == '*':
            self.take()
            return ('deref', self.unary())
        if tok == '&':
            self.take()
            return ('addr', self.unary())
        if tok in ('++', '--'):
            raise _Bad
        kind = self.cast_type()
        if kind is not None:
            return ('cast', kind, self.unary())
        return self.postfix(self.primary())

    def primary(self):
        kind, text = self.take()
        if kind == 'num':
            return ('num', text)
        if kind == 'id':
            return ('name', text)
        if text == '(':
            node = self.assign()
            self.take(')')
            return node
        raise _Bad

    def postfix(self, node):
        while True:
            tok = self.peek()
            if tok == '->':
                self.take()
                node = ('arrow', node, self.take()[1])
            elif tok == '[':
                self.take()
                node = ('index', node, self.assign())
                self.take(']')
            elif tok == '(' and node[0] == 'name':
                self.take()
                args = []
                while self.peek() != ')':
                    args.append(self.assign())
                    if self.peek() == ',':
                        self.take()
                self.take(')')
                node = ('call', node, args)
            elif tok in ('.', '++', '--', '('):
                raise _Bad
            else:
                return node


def _width(type_text, records):
    words = type_text.split()
    if '*' in words:
        return 4
    for word in reversed(words):
        if word in _WIDTH:
            return _WIDTH[word]
    record = records.get(words[-1]) if words else None
    return record[1] if record else 8


def _records(text):
    """{typedef name: (member name, member's width)} of the one-member records (`typedef struct { f32 v; } Field_f32;`)."""
    found = {}
    for members, name in re.findall(rf'typedef\s+struct\s*(?:{IDENT})?\s*\{{([^{{}}]*)\}}\s*({IDENT})\s*;', text):
        fields = [part.strip() for part in members.split(';') if part.strip()]
        if len(fields) == 1:
            hit = re.fullmatch(rf'(.*?)({IDENT})', fields[0])
            if hit:
                found[name] = (hit[2], _width(hit[1].strip(), {}), hit[1].strip())
    return found


def _address(node):
    """(base, byte offset) of `(char *) base + off`, `(T *) that`, or a bare `base`; None for anything else."""
    if node[0] == 'cast' and node[1].endswith('*'):
        return _address(node[2])
    if node[0] == 'name':
        return node[1], 0
    if node[0] == 'bin' and node[1] == '+' and node[3][0] == 'num' and node[2][0] == 'cast' and node[2][1] == 'char *':
        inner = _address(node[2][2])
        if inner and inner[1] == 0:
            return inner[0], int(node[3][1].rstrip('uUlL'), 0)
    return None


def _cell(node, records):
    """(base, family, low, high) when `node` is one memory cell of a base pointer, else None. Family `off` is a byte range,
    `member` a member name, `index` an array index."""
    if node[0] == 'deref':
        inner = node[1]
        if inner[0] == 'cast' and inner[1].endswith('*'):
            where = _address(inner[2])
            if where:
                return where[0], 'off', where[1], where[1] + _width(inner[1][:-1].strip(), records)
        if inner[0] == 'name':
            return inner[1], 'off', 0, 8
    elif node[0] == 'arrow':
        obj = node[1]
        if obj[0] == 'cast' and obj[1].endswith('*'):
            where = _address(obj[2])
            record = records.get(obj[1][:-1].strip())
            if where and record and record[0] == node[2]:
                return where[0], 'off', where[1], where[1] + record[1]
        elif obj[0] == 'name':
            return obj[1], 'member', node[2], node[2]
    elif node[0] == 'index' and node[1][0] == 'name' and node[2][0] == 'num':
        return node[1][1], 'index', int(node[2][1].rstrip('uUlL'), 0), 0
    return None


def _clash(one, two):
    if one[0] == 'v' or two[0] == 'v':
        return one == two
    if one[1] != two[1]:
        return True  # different bases may be one object; one base in two spellings is not told apart
    if one[2] != two[2]:
        return True
    if one[2] == 'off':
        return one[3] < two[4] and two[3] < one[4]
    return one[3] == two[3]


class Effects:
    def __init__(self, kind, writes, reads, store=None, value=None):
        self.kind, self.writes, self.reads, self.store, self.value = kind, writes, reads, store, value

    def commutes(self, other):
        return not (any(_clash(w, k) for w in self.writes for k in other.writes | other.reads)
                    or any(_clash(w, k) for w in other.writes for k in self.reads))


def _key(cell):
    return ('c',) + cell


def _read(node, names, records, cells, locals_):
    """Add the locals and cells a pure value reads; False when it is not pure (a call, a global read, an unknown pointer)."""
    kind = node[0]
    if kind == 'num':
        return True
    if kind == 'name':
        if node[1] in names:
            locals_.add(('v', node[1]))
            return True
        return False
    if kind == 'cast':
        return not node[1].endswith('volatile') and _read(node[2], names, records, cells, locals_)
    if kind == 'un':
        return _read(node[2], names, records, cells, locals_)
    if kind == 'addr':
        return node[1][0] == 'name' and node[1][1] not in names
    if kind == 'bin':
        if node[1] in ('/', '%') and node[3][0] != 'num':
            return False
        return _read(node[2], names, records, cells, locals_) and _read(node[3], names, records, cells, locals_)
    if kind == 'tern':
        return all(_read(part, names, records, cells, locals_) for part in node[1:])
    cell = _cell(node, records)
    if cell:
        cells.add(_key(cell))
        locals_.add(('v', cell[0]))
        return True
    return False


def _effects(text, names, records):
    try:
        tree = _Parser(text.strip().rstrip(';')).parse()
    except _Bad:
        return None
    if tree[0] != 'assign':
        return None
    _, op, left, right = tree
    reads, locals_ = set(), set()
    if not _read(right, names, records, reads, locals_):
        return None
    if left[0] == 'name' and left[1] in names:
        target = ('v', left[1])
        kind, writes, store = 'local', {target}, None
        if op != '=':
            locals_.add(target)
    else:
        cell = _cell(left, records)
        if not cell:
            return None
        target = _key(cell)
        kind, writes, store = 'store', {target}, cell
        locals_.add(('v', cell[0]))
        if op != '=':
            reads.add(target)
    value = None
    if op == '=' and right[0] in ('num', 'un') and (right[0] == 'num' or right[2][0] == 'num'):
        value = ('constant', right)
    elif op == '=' and right[0] == 'addr' or (right[0] == 'cast' and right[2][0] == 'addr'):
        value = ('address', right)
    return Effects(kind, writes, reads | locals_, store, value)


def _names(part, source):
    """The locals and parameters a statement may assign or read as plain names (not address-taken)."""
    head = source[:part.opening]
    signature = head[head.rfind('(', 0, part.opening):part.opening] if '(' in head else ''
    names = set(re.findall(rf'(?:^|[(,])\s*(?:(?:const|unsigned|signed|struct)\s+)*{IDENT}(?:\s+{IDENT})*[\s*]+({IDENT})\s*(?=[,)\[])',
                           signature))
    body = part.clean[part.opening:part.end]
    for hit in re.finditer(rf'(?m)^[ \t]*(?:(?:register|unsigned|signed|struct)[ \t]+)*({IDENT})[ \t]*[\s*]*[ \t*]({IDENT})[ \t]*;', body):
        if hit[1] not in _NOT_DECLARATIONS and hit[2] not in _NOT_DECLARATIONS:
            names.add(hit[2])
    return {name for name in names if not re.search(rf'&\s*{re.escape(name)}\b', body)}


def _segments(source, part, names, records):
    """[[(start, end, effects)]]: runs of two or more consecutive statements the model understands."""
    found = []
    stop = part.clean.rindex('}', part.opening, part.end)
    for run in _runs(part.clean, part.opening + 1, stop, minimum=1):
        group = []
        for start, end in run:
            effects = _effects(source[start:end], names, records)
            if effects is None:
                if len(group) >= 2:
                    found.append(group)
                group = []
            else:
                group.append((start, end, effects))
        if len(group) >= 2:
            found.append(group)
    return found


def _rebuild(source, group, order):
    spans = [(s, e) for s, e, _ in group]
    child = source[:spans[0][0]]
    for slot, index in enumerate(order):
        gap = source[spans[slot - 1][1]:spans[slot][0]] if slot else ''
        child += gap + source[spans[index][0]:spans[index][1]]
    return child + source[spans[-1][1]:]


def _moves(source, group):
    """[(rank, order)] of every adjacent swap, move to the front and move to the back that commutes with what it passes."""
    count = len(group)
    effects = [item[2] for item in group]
    found, seen = [], set()

    def move(index, target, kind):
        step = 1 if target > index else -1
        between = range(index + step, target + step, step)
        if not all(effects[index].commutes(effects[k]) for k in between):
            return
        order = list(range(count))
        order.insert(target, order.pop(index))
        if tuple(order) in seen:
            return
        seen.add(tuple(order))
        wanted = any(effects[k].value for k in (index, *between))
        found.append((kind * 2 + (0 if wanted else 1), abs(target - index), tuple(order)))

    for index in range(count - 1):
        move(index, index + 1, 0)
    for index in range(2, count):
        move(index, 0, 1)
    for index in range(count - 2):
        move(index, count - 1, 2)
    return found


def _order_children(source, segments):
    ranked = []
    for number, group in enumerate(segments):
        for rank, distance, order in _moves(source, group):
            ranked.append((rank, distance, number, order, group))
    result = []
    for _, _, _, order, group in sorted(ranked, key=lambda item: item[:3]):
        child = _rebuild(source, group, order)
        if child != source and child not in result:
            result.append(child)
        if len(result) >= LIMIT:
            break
    return result


def _insert_declaration(source, part, declaration):
    """`source` with `declaration` after the function's leading declarations."""
    body = part.clean
    pos = part.opening + 1
    last = pos
    for hit in re.finditer(r'[^;{}]*;', body[pos:part.end]):
        text = hit.group(0).strip()
        if not re.fullmatch(rf'(?:(?:register|unsigned|signed|struct)\s+)*{IDENT}[\s*]+{IDENT}(?:\s*=[^;]*)?;', text) or text.split()[0] in _NOT_DECLARATIONS:
            break
        last = pos + hit.end()
    indent = re.search(r'\n([ \t]*)\S', source[part.opening:]).group(1) or '    '
    return edit(source, [(last, last, f'\n{indent}{declaration}')])


def _constant_children(source, part, name, names, records):
    groups = {}
    stop = part.clean.rindex('}', part.opening, part.end)
    for run in _runs(part.clean, part.opening + 1, stop, minimum=1):
        for start, end in run:
            text = source[start:end]
            hit = re.fullmatch(rf'(?s)(.*?)(?<![=!<>+\-*/&|^%])=(?!=)\s*(?P<value>[-+]?\s*{NUMBER})\s*;\s*', text)
            effects = hit and _effects(text, names, records)
            if not effects or effects.kind != 'store':
                continue
            value = int(hit['value'].replace(' ', '').rstrip('uUlL'), 0)
            kind = _cell_type(_Parser(text.strip().rstrip(';')).parse()[2], records)
            if value and kind:
                groups.setdefault((value, kind), []).append((start, start + hit.start('value'), start + hit.end('value'), run))
    result = []
    used = set(re.findall(IDENT, part.clean))
    for (value, kind), items in sorted(groups.items(), key=lambda item: -len(item[1]))[:CONSTANT_LIMIT]:
        local = f'k_{"m" if value < 0 else ""}{abs(value):X}'
        if len(items) < 2 or local in used:
            continue
        first = items[0]
        for at in dict.fromkeys((first[0], first[3][0][0])):
            line = source.rfind('\n', 0, at) + 1
            lead = source[line:at] if not source[line:at].strip() else ''
            child = edit(source, [(v0, v1, local) for _, v0, v1, _ in items] + [(at, at, f'{local} = {value};\n{lead}')])
            moved = view(child, name)
            if moved:
                child = _insert_declaration(child, moved, f'{kind} {local};')
                if child != source and child not in result:
                    result.append(child)
    return result


def _cell_type(tree_left, records):
    """The integer type name a store's cell has, or None."""
    cell = tree_left
    if cell[0] == 'deref' and cell[1][0] == 'cast':
        kind = cell[1][1][:-1].strip()
    elif cell[0] == 'arrow' and cell[1][0] == 'cast':
        record = records.get(cell[1][1][:-1].strip())
        kind = record[2] if record else ''
    else:
        return None
    if kind in _INTEGER or kind in ('M2C_UNK', 'M2C_UNK32'):
        return 's32' if kind.startswith('M2C') else kind
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean[part.opening:part.end]):
        return []
    names = _names(part, source)
    records = _records(header + '\n' + source)
    segments = _segments(source, part, names, records)
    result = [(FAMILY, child) for child in _order_children(source, segments)]
    result += [(FAMILY_CONSTANT, child) for child in _constant_children(source, part, name, names, records)]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
