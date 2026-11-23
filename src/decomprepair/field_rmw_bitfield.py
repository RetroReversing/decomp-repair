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


def _updates(source, clean, opening, closing):
    """[(load_stmt, store_stmt, middle, base, offset, shift, width, constant)] for each recognised update."""
    statements = _statements(clean, opening, closing)
    found = []
    for index, item in enumerate(statements):
        if item is None:
            continue
        start, end, text = item
        store = re.match(r'\s*(?P<access>.+?)\s*=\s*(?P<value>[^=].*)\Z', text, re.S)
        if not store:
            continue
        target = _ACCESS.fullmatch(store['access'].strip())
        if not target or _SKIP.match(text):
            continue
        base = target['base'] or target['cbase']
        offset = int(target['off'] or target['coff'], 0)
        if offset % 4:
            continue
        # walk back through simple statements (no labels or braces) to the load of the same word
        middle, load = [], None
        for back in range(index - 1, max(index - 9, -1), -1):
            earlier = statements[back]
            if earlier is None:
                break
            m = re.match(rf'\s*(?P<var>{_ID})\s*=\s*(?:\(\s*{_CASTS}\s*\)\s*)?(?P<load>\*.+)\Z', earlier[2], re.S)
            access = _ACCESS.fullmatch(m['load'].strip()) if m else None
            if m and access and (access['base'] or access['cbase']) == base \
                    and int(access['off'] or access['coff'], 0) == offset:
                load = (back, m['var'])
                break
            if re.search(r'\w\s*\(|\*\s*\(\(|\+\+|--', earlier[2]) and not re.match(rf'\s*{_ID}\s*=', earlier[2]):
                break
            if _ACCESS.search(earlier[2]) and re.match(r'\s*\*', earlier[2]):
                break  # another store in between: keep the program's order
            middle.append(back)
        if not load:
            continue
        locals_ = {}
        for back in sorted(middle):
            m = re.match(rf'\s*({_ID})\s*=\s*(.+)\Z', statements[back][2], re.S)
            if m:
                tree = _parse(m[2])
                if tree:
                    locals_[m[1]] = tree
        tree = _parse(store['value'])
        if not tree:
            continue
        decoded = _decode(tree, load[1], locals_)
        if decoded:
            used, todo = set(), set(re.findall(_ID, store['value']))
            while todo:
                local = todo.pop()
                if local in locals_ and local not in used:
                    used.add(local)
                    todo |= set(re.findall(_ID, next(statements[k][2] for k in middle
                                                      if re.match(rf'\s*{local}\s*=', statements[k][2]))))
            defs = [k for k in sorted(middle) if re.match(rf'\s*({_ID})\s*=', statements[k][2])
                    and re.match(rf'\s*({_ID})', statements[k][2])[1] in used]
            found.append((load[0], index, defs, base, offset, *decoded))
    return found, statements


def _layout(updates_for_word):
    """[(shift, width)] sorted, or None when two different fields overlap."""
    fields = sorted({(shift, width) for shift, width in updates_for_word}, reverse=True)
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
    found, statements = _updates(source, clean, opening, closing)
    if not found:
        return []
    words = {}
    for item in found:
        words.setdefault(item[4], []).append(item)

    def build(offsets):
        edits, declarations, used = [], [], set()
        for offset in offsets:
            items = words[offset]
            layout = _layout([(i[5], i[6]) for i in items])
            if not layout or re.search(rf'__repair_bits_{offset:X}\b', clean):
                continue
            declarations.append(_typedef(offset, layout))
            for load, store, middle, base, _, shift, width, constant in items:
                start, end, text = statements[store]
                edits.append((start, end, f'((__repair_bits_{offset:X} *) {base})->f{shift} |= 0x{constant:X};'))
                used.add(offset)
                # drop the load and the locals only this update read, when nothing else reads them
                later = clean[end:closing]
                gone = [load, *middle]
                for k in gone:
                    local = re.match(rf'\s*({_ID})', statements[k][2])[1]
                    others = ''.join(statements[j][2] for j in range(load, store)
                                     if statements[j] is not None and j not in gone)
                    reads = rf'\b{local}\b(?!\s*=(?!=))'
                    if not re.search(reads, later) and not re.search(reads, others):
                        first, last = statements[k][0], statements[k][1]
                        while first > 0 and source[first - 1] in ' \t':
                            first -= 1
                        if first > 0 and source[first - 1] == '\n' and source[last:last + 1] == '\n':
                            last += 1
                        edits.append((first, last, ''))
        if not used or not edits:
            return None
        new = source
        for start, end, replacement in sorted(set(edits), reverse=True):
            new = new[:start] + replacement + new[end:]
        at = span[0]
        return new[:at] + ''.join(declarations) + new[at:]

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
