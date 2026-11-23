"""m2c's mask-and-shift update of a packed field, written as a bit-field update (`p->state |= 0x10;`).

A struct of bit-fields is how the game wrote `p->state |= 0x10;`, and m2c, which cannot see the bit-field, prints the
update of the word as arithmetic on the whole word:

    temp = *(u32 *)(p + 0x58);
    *(u32 *)(p + 0x58) = (temp & 0xFFFF0003) | ((((temp >> 2) & 0x3FFF) | 0x10) * 4);

or the same with the two halves in locals (`a = temp & M; b = ((temp >> S) & W) | K; ... = a | (b << S)`), or, for a
field that reaches the top bit of the word, `(temp & 0x7FFFFF) | (((temp >> 0x17) | K) << 0x17)`. A bit-field update
compiles to the same load, mask, or and store, with the registers and the order the target's compiler gave it; the
arithmetic spelling gave GCC 2.7.2 (KMC, N64) other registers: on a 603-instruction state machine whose cases each
updated two fields of two words, writing each update as `p->state |= K;` took the case arms from register-swapped to
the target's bytes, and an arm that once had a mask and shift of its own ended up allocating the way its neighbours did
(GCC's block-local allocator, local-alloc.c, sorts a block of exactly three quantities with an exchange that compares
quantity numbers, not positions, so the spelling decides which quantity gets `$v0`).

A proposal needs the update's shape to be exactly a field set (`field |= K` with a literal K that fits the field), so the
program is the same one. The bit-fields are read big-endian (the first field takes the most significant bits), as every
MIPS game this library has been used on that ran on the N64 does; a little-endian game gets proposals that do not match
and cost one compile each. All the updates of one word are written as one typedef
`typedef struct { char pad[0x58]; unsigned int f16 : 14; ... } __repair_bits_58;` with unnamed bit-fields for the bits no
update touches; a word whose updates overlap without being the same field is left alone.

Labelled `field_rmw_bitfield`: every update of one word at once, for each word; every update of every word. The load of the
word and the locals only the update used are removed when nothing reads them afterwards.
"""
import re

from .csource import _blank, find

FAMILY = 'field_rmw_bitfield'
FAMILIES = (FAMILY,)
LIMIT = 8

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?[lL]?'
_CASTS = r'(?:unsigned\s+int|unsigned\s+long|unsigned|signed|int|long|u32|s32|u_int|s_int)'
_ACCESS = re.compile(
    rf'\*\(\(\s*(?:u32|s32|unsigned int|unsigned|int|long)\s*\*\s*\)\s*\(\(\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<base>{_ID})\s*\)\s*\+\s*(?P<off>{_NUM})\s*\)\)'
    rf'|\*\(\s*(?:u32|s32|unsigned int|unsigned|int|long)\s*\*\s*\)\s*\(\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<cbase>{_ID})\s*\+\s*(?P<coff>{_NUM})\s*\)')
_SKIP = re.compile(r'\s*(?:if|else|while|for|do|switch|case|default|return|goto|break|continue|typedef)\b')


# --- a tiny expression reader: identifiers, numbers, casts, | & << >> * + ---------------------------------------------

def _tokens(text):
    return re.findall(rf'{_ID}|{_NUM}|<<|>>|[()|&*+~^-]', text)


class _Parse:
    def __init__(self, text):
        self.tokens = _tokens(text)
        self.at = 0
        self.ok = True

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.at += 1
        return token

    def expression(self):
        return self.binary(0)

    LEVELS = (('|',), ('&',), ('<<', '>>'), ('+', '-'), ('*',))

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek() in self.LEVELS[level]:
            op = self.take()
            left = (op, left, self.binary(level + 1))
        return left

    def unary(self):
        token = self.peek()
        if token == '(':
            save = self.at
            self.take()
            # a cast: ( type words ) operand
            words = []
            while self.peek() and re.fullmatch(_ID, self.peek()) and self.peek() in (
                    'unsigned', 'signed', 'int', 'long', 'u32', 's32', 'u_int', 's_int', 'short', 'char'):
                words.append(self.take())
            if words and self.peek() == ')' and ' '.join(words) in (
                    'unsigned', 'int', 'long', 'u32', 's32', 'unsigned int', 'signed int', 'unsigned long', 'u_int', 's_int'):
                self.take()
                return self.unary()
            self.at = save + 1
            inner = self.expression()
            if self.take() != ')':
                self.ok = False
            return inner
        if token and re.fullmatch(_NUM, token):
            self.take()
            return ('num', int(token.rstrip('uUlL'), 0))
        if token and re.fullmatch(_ID, token):
            self.take()
            return ('id', token)
        self.ok = False
        return ('bad',)


def _parse(text):
    parser = _Parse(text)
    tree = parser.expression()
    return tree if parser.ok and parser.at == len(parser.tokens) else None


def _mul_to_shift(node):
    """`x * 4` is `x << 2`."""
    if node[0] == '*' and node[2][0] == 'num' and node[2][1] > 0 and node[2][1] & (node[2][1] - 1) == 0:
        return ('<<', node[1], ('num', node[2][1].bit_length() - 1))
    return node


def _unpack_or(node):
    """The two operands of an `|` node."""
    return node[1], node[2]


def _field(node, word):
    """`(((word >> S) & W) | K)` or `((word >> S) | K)` as (S, W or None, K), else None."""
    if node[0] != '|':
        return None
    for shifted, constant in ((node[1], node[2]), (node[2], node[1])):
        if constant[0] != 'num':
            continue
        width = None
        if shifted[0] == '&' and shifted[2][0] == 'num':
            shifted, width = shifted[1], shifted[2][1]
        if shifted[0] == '>>' and shifted[1] == ('id', word) and shifted[2][0] == 'num':
            return shifted[2][1], width, constant[1]
    return None


def _decode(tree, word, locals_):
    """(S, width, K) when `tree` stores `word` with the field at bit S or-ed with K, else None."""
    def resolve(node):
        if node[0] == 'id' and node[1] in locals_:
            return resolve(locals_[node[1]])
        if node[0] in ('|', '&', '<<', '>>', '*', '+', '-'):
            return (node[0], resolve(node[1]), resolve(node[2]))
        return node
    tree = resolve(tree)
    if tree[0] != '|':
        return None
    for kept, put in ((tree[1], tree[2]), (tree[2], tree[1])):
        if kept[0] != '&' or kept[1] != ('id', word) and kept[2] != ('id', word):
            continue
        mask = kept[2] if kept[1] == ('id', word) else kept[1]
        if mask[0] != 'num':
            continue
        put = _mul_to_shift(put)
        if put[0] != '<<' or put[2][0] != 'num':
            continue
        found = _field(put[1], word)
        if not found:
            continue
        shift, width, constant = found
        if width is None:
            bits = 32 - shift
        elif width & (width + 1) == 0 and width:
            bits = width.bit_length()
        else:
            continue
        if bits <= 0 or shift + bits > 32 or constant <= 0 or constant >> bits:
            continue
        if (mask[1] & 0xFFFFFFFF) != (~(((1 << bits) - 1) << shift) & 0xFFFFFFFF):
            continue
        return shift, bits, constant
    return None


# --- the function ------------------------------------------------------------------------------------------------

def _statements(clean, opening, closing):
    out, start, depth = [], opening + 1, 0
    for at in range(opening + 1, closing):
        ch = clean[at]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch in '{}:':
            out.append(None)
            start = at + 1
        elif depth == 0 and ch == ';':
            text = clean[start:at]
            if text.strip():
                lead = len(text) - len(text.lstrip())
                out.append((start + lead, at + 1, text.lstrip()))
            start = at + 1
    return out


def _walk(statements, top, base, offset):
    """Walk back from statement `top` through simple statements to the load of the word at `base + offset`:
    (index of the load, its variable, [indices between]) or None."""
    middle = []
    for back in range(top, max(top - 9, -1), -1):
        earlier = statements[back]
        if earlier is None:
            return None
        m = re.match(rf'\s*(?P<var>{_ID})\s*=\s*(?:\(\s*{_CASTS}\s*\)\s*)?(?P<load>\(?\s*\*.+)\Z', earlier[2], re.S)
        text = m['load'].strip() if m else ''
        while text.startswith('(') and text.endswith(')') and _ACCESS.fullmatch(text[1:-1].strip()):
            text = text[1:-1].strip()
        access = _ACCESS.fullmatch(text) if m else None
        if m and access and (access['base'] or access['cbase']) == base \
                and int(access['off'] or access['coff'], 0) == offset:
            return back, m['var'], middle
        if re.search(r'\w\s*\(|\*\s*\(\(|\+\+|--', earlier[2]) and not re.match(rf'\s*{_ID}\s*=', earlier[2]):
            return None
        if _ACCESS.search(earlier[2]) and re.match(r'\s*\*', earlier[2]):
            return None  # another store in between: keep the program's order
        middle.append(back)
    return None


def _arm(statements, value, walked):
    """(shift, bits, constant, [statement indices to drop]) when the statements back to the load set one field."""
    load, var, middle = walked
    locals_ = {}
    for back in sorted(middle):
        m = re.match(rf'\s*({_ID})\s*=\s*(.+)\Z', statements[back][2], re.S)
        tree = _parse(m[2]) if m else None
        if tree:
            locals_[m[1]] = tree
    tree = _parse(value)
    decoded = _decode(tree, var, locals_) if tree else None
    if not decoded:
        return None
    used, todo = set(), set(re.findall(_ID, value))
    while todo:
        local = todo.pop()
        if local in locals_ and local not in used:
            used.add(local)
            todo |= set(re.findall(_ID, next(statements[k][2] for k in middle
                                              if re.match(rf'\s*{local}\s*=', statements[k][2]))))
    defs = [k for k in sorted(middle) if re.match(rf'\s*({_ID})\s*=', statements[k][2])
            and re.match(rf'\s*({_ID})', statements[k][2])[1] in used]
    return (*decoded, [load, *defs])


def _store(text):
    """(base, offset, value) of a store `*ACC = value;` to a word, else None."""
    m = re.match(r'\s*(?P<access>.+?)\s*=\s*(?P<value>[^=].*)\Z', text, re.S)
    target = _ACCESS.fullmatch(m['access'].strip()) if m and not _SKIP.match(text) else None
    if not target:
        return None
    offset = int(target['off'] or target['coff'], 0)
    return (target['base'] or target['cbase']), offset, m['value'] if offset % 4 == 0 else None


def _updates(clean, opening, closing):
    """Items for every update recognised, and the statement list.

    An item is {offset, base, fields: [(shift, bits)], edits: [(statement index, text or None)], drop: [indices],
    replaced: [(start, end)]}: `edits` replace a statement, `drop` are the loads and locals that go when unread."""
    statements = _statements(clean, opening, closing)
    items = []
    for index, item in enumerate(statements):
        if item is None:
            continue
        parts = _store(item[2])
        if not parts or parts[2] is None:
            continue
        base, offset, value = parts
        walked = _walk(statements, index - 1, base, offset)
        arm = _arm(statements, value, walked) if walked else None
        if arm:
            shift, bits, constant, drop = arm
            items.append({'offset': offset, 'base': base, 'fields': [(shift, bits)],
                          'edits': [(index, shift, constant, '')], 'drop': drop, 'replaced': [item[:2]]})
    # a join: `label: *(p + off) = f(locals); goto next;`, reached by gotos and by falling into it, each arm setting the locals
    for m in re.finditer(rf'(?m)^[ \t]*({_ID})[ \t]*:(?!:)', clean[opening:closing]):
        label = m[1]
        position, after = opening + m.start(), opening + m.end()
        index = next((k for k, s in enumerate(statements) if s and s[0] >= after), None)
        if index is None or index + 1 >= len(statements) or statements[index + 1] is None or label == 'default':
            continue
        parts = _store(statements[index][2])
        goes = re.fullmatch(rf'goto\s+({_ID})', statements[index + 1][2].strip())
        if not parts or parts[2] is None or not goes:
            continue
        base, offset, value = parts
        ends = [(k, True) for k, s in enumerate(statements) if s and re.fullmatch(rf'goto\s+{label}', s[2].strip())]
        before = [k for k, s in enumerate(statements) if s and s[1] <= position]
        if before and all(x is None for x in statements[before[-1] + 1:index]) \
                and not re.match(r'\s*(?:goto|return|break)\b', statements[before[-1]][2]):
            ends.append((before[-1], False))
        if not ends:
            continue
        edits, drop, fields, ok = [], [], [], True
        for k, is_goto in ends:
            walked = _walk(statements, k - 1 if is_goto else k, base, offset)
            arm = _arm(statements, value, walked) if walked else None
            if not arm:
                ok = False
                break
            shift, bits, constant, dropped = arm
            edits.append((k, shift, constant, f' goto {goes[1]};', is_goto))
            drop += dropped
            fields.append((shift, bits))
        if ok:
            items.append({'offset': offset, 'base': base, 'fields': fields, 'edits': edits, 'drop': drop,
                          'replaced': [(position, statements[index + 1][1])], 'join': label})
    return items, statements


def _layout(fields):
    """[(shift, width)] sorted, or None when two different fields overlap."""
    fields = sorted(set(fields), reverse=True)
    last = 32
    for shift, width in fields:
        if shift + width > last:
            return None
        last = shift
    return fields


def _typedef(offset, fields):
    members, top = [], 32
    for shift, width in fields:
        if shift + width < top:
            members.append(f'unsigned int : {top - shift - width};')
        members.append(f'unsigned int f{shift} : {width};')
        top = shift
    if top > 0:
        members.append(f'unsigned int : {top};')
    return f'typedef struct {{ char pad[0x{offset:X}]; {" ".join(members)} }} __repair_bits_{offset:X};\n'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    items, statements = _updates(clean, opening, closing)
    if not items:
        return []
    words = {}
    for item in items:
        words.setdefault(item['offset'], []).append(item)

    def build(offsets):
        edits, declarations, replaced, candidates = [], [], [], []
        for offset in offsets:
            chosen = words[offset]
            layout = _layout([field for item in chosen for field in item['fields']])
            if not layout or re.search(rf'__repair_bits_{offset:X}\b', clean):
                continue
            declarations.append(_typedef(offset, layout))
            for item in chosen:
                kind = f'((__repair_bits_{offset:X} *) {item["base"]})->f'
                for edit in item['edits']:
                    k, shift, constant = edit[:3]
                    update = f'{kind}{shift} |= 0x{constant:X};'
                    start, end, _ = statements[k]
                    if len(edit) == 4:       # a plain update: the store itself
                        edits.append((start, end, update))
                    elif edit[4]:            # a join's goto
                        edits.append((start, end, update + edit[3]))
                    else:                    # the arm that falls into the join label
                        edits.append((end, end, '\n' + re.search(r'([ \t]*)$', source[:start])[1] + update + edit[3]))
                replaced += item['replaced']
                candidates += item['drop']
                if 'join' in item:
                    edits.append((item['replaced'][0][0], item['replaced'][0][1], ''))
        if not edits:
            return None
        # a load or a local goes when nothing else reads it
        spans = replaced + [statements[k][:2] for k in set(candidates)]
        spans += [item[:2] for item in statements if item and re.fullmatch(
            rf'\s*(?:(?:unsigned|signed|register|volatile|const)\s+)*{_ID}(?:\s*\*+\s*|\s+){_ID}\s*', item[2])]
        names = {}
        for k in set(candidates):
            names.setdefault(re.match(rf'\s*({_ID})', statements[k][2])[1], []).append(k)
        for local, owners in names.items():
            reads = [m for m in re.finditer(rf'\b{local}\b(?!\s*=(?!=))', clean[opening:closing])
                     if not any(a <= opening + m.start() < b for a, b in spans)]
            if reads:
                continue
            for k in owners:
                first, last = statements[k][0], statements[k][1]
                while first > 0 and source[first - 1] in ' \t':
                    first -= 1
                if first > 0 and source[first - 1] == '\n' and source[last:last + 1] == '\n':
                    last += 1
                edits.append((first, last, ''))
        new = source
        for start, end, replacement in sorted(set(edits), reverse=True):
            new = new[:start] + replacement + new[end:]
        return new[:span[0]] + ''.join(declarations) + new[span[0]:]

    groups = [[offset] for offset in sorted(words)]
    if len(groups) > 1:
        groups.append(sorted(words))
    out, seen = [], set()
    for group in groups:
        new = build(group)
        if new and new != source and new not in seen:
            seen.add(new)
            out.append((FAMILY, new))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
