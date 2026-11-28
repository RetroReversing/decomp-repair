"""Symbols m2c left untyped, indexed by hand, declared as arrays of the element their stride gives.

m2c adds its byte offsets to the address of a symbol it could not type, which it declares as one word:

    extern M2C_UNK gScores;                        extern s32 gScores[];
    extern M2C_UNK D_80000010;                     extern u8 D_80000010[];
    *((player * 4) + &gScores) = 6;       ->       gScores[player] = 6;
    temp = (player * 4) + &gScores;                temp = &gScores[player];
    *temp += 0x3E8;                                *temp += 0x3E8;
    *(player + &D_80000010) = 0;                   D_80000010[player] = 0;
    var = &D_80000010; *(player + var) = 1;        u8 *var; var = D_80000010; *(player + var) = 1;

C scales those sums by the word again (`sll 4` where the target has `sll 2`), and a byte table is stored with `sw`.
The multiplier of the index says the element: 4 is a word array, 2 a halfword array, none a byte array. The sites only
pay off together (a per-site rewrite is `pointer_byte_step`, at most six sites, dereferences only), so one child
retypes every symbol at once. On a 229-instruction SN GCC 2.8.1 N64 pickup update the machine draft had eleven word
and byte sites of five symbols; the child below took it from 4965 to the rows a typed rewrite then closed.

Two symbols a pointer local picks between before one shared store (`p = &A; L: *(i + p) = 1;` and `p = &B; goto L;`)
are first written out on each path.

A symbol is retyped only when every use of it in the function is one of these shapes with one stride, declared
`extern M2C_UNK X;`, `extern s32 X;` or (after `m2cfix`) `extern char X[];`. The second child spells the narrow
elements signed. A compiler's choice, so the exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stride_typed_symbol_arrays'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
ELEMENTS = ({1: 'u8', 2: 'u16', 4: 's32'}, {1: 's8', 2: 's16', 4: 's32'})
_DECL = re.compile(r'(?m)^[ \t]*extern\s+(?:(?:M2C_UNK|M2C_UNK32|s32)\s+(?P<word>' + IDENT + r')|char\s+(?P<chars>'
                   + IDENT + r')\s*\[\s*\])\s*;')


def _left_operand(text, plus):
    """Start of the one operand that ends before the `+` at `plus`: `(...)`, a name, or a call; None otherwise."""
    end = len(text[:plus].rstrip())
    at = end
    if text[at - 1:at] == ')':
        depth = 0
        while at:
            at -= 1
            depth += {')': 1, '(': -1}.get(text[at], 0)
            if not depth:
                break
        if depth:
            return None
    while at and (text[at - 1].isalnum() or text[at - 1] == '_'):
        at -= 1
    if at == end:
        return None
    before = text[:at].rstrip()
    # the operand must be the whole left side of the sum
    return (at, end) if not before or before[-1] in '(=,;{}' else None


def _scaled(operand):
    """(index, stride) for `(E * K)`, else the operand itself at stride 1."""
    if operand.startswith('(') and close(operand, 0, '(', ')') == len(operand):
        product = re.fullmatch(r'\((?P<i>.+?)\s*\*\s*(?P<k>0x[0-9a-fA-F]+|\d+)\s*\)', operand, re.S)
        if product and close(operand, 0, '(', ')') == len(operand):
            depth = 0
            for char in product['i']:
                depth += {'(': 1, ')': -1}.get(char, 0)
                if depth < 0:
                    return None
            return product['i'], int(product['k'], 0)
        return operand[1:-1], 1
    return operand, 1


def _site(source, clean, start, end, symbol, addressed):
    """(start, end, index) of the sum or bare address using `symbol` at clean[start:end]; None for another shape."""
    before = clean[:start].rstrip()
    if addressed:
        if not before.endswith('&') or before.endswith('&&'):
            return None
        start = len(before) - 1
        before = clean[:start].rstrip()
    after = clean[end:].lstrip()[:1]
    if before.endswith('+'):
        left = _left_operand(clean, len(before) - 1)
        if not left or after not in (')', ';', ','):
            return None
        scaled = _scaled(source[left[0]:left[1]])
        return (left[0], end, scaled) if scaled else None
    if before.endswith('=') and not before.endswith(('==', '!=', '<=', '>=')) and after == ';':
        return (start, end, None)
    return None


def _written_out(source):
    """A store through a pointer that two paths set to different symbols before meeting at a label, written out on both:
    `p = &A; L: *(i + p) = 1; break; ... p = &B; goto L;` is `*(i + &A) = 1; break; ... *(i + &B) = 1; break;`."""
    join = re.compile(r'(?<![\w.>])(?P<p>' + IDENT + r') = (?P<amp>&?)(?P<a>' + IDENT + r');\s*(?P<label>' + IDENT + r'):\s*'
                      r'\*\((?P<i>[^;{}]+?) \+ (?P=p)\) = (?P<v>-?\w+);(?P<end>\s*break;)')
    for hit in list(join.finditer(source)):
        pointer, label = hit['p'], hit['label']
        amp = hit['amp']
        jumps = list(re.finditer(r'(?<![\w.>])' + pointer + r' = ' + amp + r'(?P<b>' + IDENT + r');\s*goto ' + label + ';', source))
        if len(jumps) != 1 or len(re.findall(r'\bgoto\s+' + label + r'\b', source)) != 1:
            continue
        jump = jumps[0]
        if not all(re.search(r'(?m)^extern\b[^;=(]*\b' + symbol + r'\b', source) for symbol in (hit['a'], jump['b'])):
            continue
        store = lambda symbol, hit=hit: f"*({hit['i']} + {hit['amp']}{symbol}) = {hit['v']};"
        edits = [(hit.start(), hit.end(), store(hit['a']) + hit['end']),
                 (jump.start(), jump.end(), store(jump['b']) + ' break;')]
        for start, end, text in sorted(edits, reverse=True):
            source = source[:start] + text + source[end:]
        if len(re.findall(r'\b' + pointer + r'\b', source)) == 1:
            source = re.sub(r'(?m)^[ \t]*' + IDENT + r'\s*\*\s*' + pointer + r';[ \t]*\n', '', source)
        return _written_out(source)
    return source


def _rewrite(source, name, elements):
    source = _written_out(source)
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    edits, retyped, pointers = [], 0, {}
    for decl in _DECL.finditer(clean[:span[0]]):
        symbol = decl['word'] or decl['chars']
        uses = list(re.finditer(r'(?<![\w.])(?<!->)' + symbol + r'\b', clean[opening:span[1]]))
        sites = [_site(source, clean, opening + u.start(), opening + u.end(), symbol, bool(decl['word'])) for u in uses]
        if not sites or any(site is None for site in sites):
            continue
        strides = {site[2][1] for site in sites if site[2]}
        if not strides:  # only `var = &X;`: bytes, when the function then reads or writes `*(offset + var)`
            locals_ = [re.search(r'(' + IDENT + r')\s*=\s*$', clean[:site[0]]) for site in sites]
            if all(local and re.search(r'\*\s*\([^;{}]*\+\s*' + local[1] + r'\s*\)', clean[opening:span[1]]) for local in locals_):
                strides = {1}
        if len(strides) != 1 or next(iter(strides)) not in elements:
            continue
        stride = next(iter(strides))
        element = elements[stride]
        for start, end, scaled in sites:
            if scaled is None:  # `var = &X;`: the array is the address, and `var` steps its elements
                target = re.search(r'(' + IDENT + r')\s*=\s*$', clean[:start])
                if not target:
                    break
                pointers.setdefault(target[1], set()).add(element)
                edits.append((start, end, symbol))
                continue
            index, _ = scaled
            opened = clean[:start].rstrip()
            closed = len(clean) - len(clean[end:].lstrip())
            deref = opened.endswith('(') and clean[closed:closed + 1] == ')' and opened[:-1].rstrip().endswith('*') \
                and re.search(r'(?:[=(,;{}+\-/&|?:<>!]|\*\s*\*)\s*$|^\s*$', opened[:-1].rstrip()[:-1])
            if deref:
                edits.append((len(opened[:-1].rstrip()) - 1, closed + 1, f'{symbol}[{index}]'))
            else:
                edits.append((start, end, f'&{symbol}[{index}]'))
        else:
            edits.append((decl.start(), decl.end(), f'extern {element} {symbol}[];'))
            retyped += 1
            continue
        return None
    for local, kinds in pointers.items():
        declared = re.search(r'(?m)^[ \t]*(?P<t>' + IDENT + r')(?P<s>\s*\*\s*)' + local + r'\s*;', clean[opening:span[1]])
        taken = len(re.findall(r'(?<![=!<>])\b' + local + r'\s*=(?!=)', clean[opening:span[1]]))
        retargeted = sum(1 for _, _, text in edits if re.fullmatch(IDENT, text))
        if not declared or len(kinds) != 1 or taken > retargeted:
            return None
        edits.append((opening + declared.start('t'), opening + declared.end('t'), next(iter(kinds))))
    if not retyped:
        return None
    edits.sort()
    if any(first[1] > second[0] for first, second in zip(edits, edits[1:])):
        return None
    for start, end, text in reversed(edits):
        source = source[:start] + text + source[end:]
    return _folded(source, name, elements)


def _folded(source, name, elements):
    """The reads and updates the new arrays spell directly: `M2C_FIELD((&B[i]), u8 *, 2)` is `B[i + 2]`, and a pointer
    taken for one update, `t = &W[i]; *t += 0x3E8;`, is `W[i] += 0x3E8;`."""
    for symbol in re.findall(r'(?m)^extern ' + elements[1] + r' (' + IDENT + r')\[\];', source):
        element = elements[1]
        source = re.sub(r'M2C_FIELD\(\(&' + symbol + r'\[(\w+)\]\), ' + element + r' \*, (\d+|0x[0-9a-fA-F]+)\)',
                        lambda m, symbol=symbol: f'{symbol}[{m[1]} + {m[2]}]', source)
        source = re.sub(r'\*\(' + element + r' \*\)\(&(' + symbol + r'\[\w+\])\)', r'\1', source)
    clean = _blank(source)
    pattern = re.compile(r'(?<![\w.>])(?P<t>' + IDENT + r') = &(?P<e>' + IDENT + r'\[[^;\[\]]+\]);\s*\*(?P=t) '
                         r'(?P<op>[-+&|^]=) (?P<v>-?\w+);')
    for hit in reversed(list(pattern.finditer(clean))):
        # the pointer must have no other use: its declaration, this assignment and this update
        if len(re.findall(r'\b' + hit['t'] + r'\b', clean)) != 3:
            continue
        element = source[hit.start('e'):hit.end('e')]
        source = source[:hit.start()] + f"{element} {hit['op']} {hit['v']};" + source[hit.end():]
    return source


def variants(source, name):
    result = []
    for elements in ELEMENTS:
        child = _rewrite(source, name, elements)
        if child and (FAMILY, child) not in result:
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
