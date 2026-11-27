"""m2c's signed division by a constant with the sign correction written twice, back as `%` (and `/`).

GCC divides a signed value by a constant that is no power of two with `mult` by a magic number, `mfhi`, and one
subtraction of the sign (`x >> 31`). SN64 GCC 2.8.1 schedules the `sra` for the sign *before* the `mfhi`, and m2c then
reads the high word as the whole quotient while still keeping the subtraction:

    temp_ret = f();
    temp_v0 = temp_ret;
    temp_hi = temp_ret / 3;
    temp_a0 = (temp_hi - (temp_v0 >> 0x1F)) * 3;
    p->x = base + (temp_v0 - ((temp_hi - (temp_v0 >> 0x1F)) * 3));
    p->y = f(((temp_hi - (temp_v0 >> 0x1F)) * 3), temp_hi);

The target computes `base + temp_v0 % 3`. The draft is not that program (for a negative value it is one off), and it
compiles to a second `subu` and other registers. m2c also saw the quotient and the product still sitting in `$a0`/`$a1`
at the next call and passed them as arguments to a callee that takes none, which keeps both alive.

On a 61-instruction N64 function (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) the saved best scored 105. The division alone was
240, dropping the leftover arguments alone 170, and the two together 0.

Shape: `Q = X / N;` (N not a power of two, Q assigned once) and `(Q - (Y >> 0x1F))` where Y is X or a plain copy of it
(also with the quotient inline, `((X / N) - (Y >> 31))`). Children:

- the correction written once: the corrected quotient becomes `Q`, and `Y - (Q * N)` becomes `Y % N`;
- the same, and every call whose arguments are all leftovers of that division (the quotient or its product) takes
  none (only when the callee is not declared with parameters in the project header; a prototype of the function's own
  source that lists parameters becomes `(void)`);
- that second child with the assignments nobody reads any more taken out.

The judge decides each child.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close
from .stray_global_call_argument import _arguments, _blank, _prototype

FAMILY = 'doubled_division_sign'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|[0-9]+'
SIGN = r'(?:0[xX]1[fF]|31)'
CAST = r'(?:\(\s*s32\s*\)\s*)?'
QUOTIENT = re.compile(rf'(?<![\w.>])(?P<q>{IDENT})\s*=\s*(?P<x>{IDENT})\s*/\s*(?P<n>{NUMBER})\s*;')
COPY = re.compile(rf'(?m)^[ \t]*(?P<to>{IDENT})\s*=\s*(?P<of>{IDENT})\s*;')
CALL = re.compile(rf'(?<![\w.>])(?P<f>{IDENT})\s*\(')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do'}


def _assigned_once(body, name):
    return len(re.findall(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{name}\b|'
                          rf'(?<![\w.>]){name}\s*(?:\+\+|--)|&\s*{name}\b(?!\s*[.\[])', body)) == 1


def _copies(body, name):
    """`name` and the locals that hold the same value by one plain copy, either way round."""
    names = {name}
    for hit in COPY.finditer(body):
        for one, other in ((hit['to'], hit['of']), (hit['of'], hit['to'])):
            if other == name and _assigned_once(body, hit['to']):
                names.add(one)
    return names


def _alternatives(names):
    return '(?:' + '|'.join(sorted(map(re.escape, names), key=len, reverse=True)) + r')(?!\w)'


def _correct(text, quotient, dividend, copies, divisor):
    """`text` with the second sign correction gone and the remainder spelled `%`."""
    value = _alternatives(copies)
    inline = rf'\(\s*{re.escape(dividend)}\s*/\s*{divisor}\s*\)'
    held = rf'(?:{re.escape(quotient)}(?!\w)|{inline})' if quotient else inline
    shifted = rf'{CAST}\(\s*{CAST}{value}\s*>>\s*{SIGN}\s*\)'
    corrected = re.compile(rf'\(\s*(?P<held>{held})\s*-\s*{shifted}\s*\)')
    text, count = corrected.subn(lambda m: m['held'], text)
    if not count:
        return text, 0
    product = rf'(?:\(\s*(?:{held})\s*\*\s*{divisor}\s*\)|\(\s*{divisor}\s*\*\s*(?:{held})\s*\))'
    remainder = re.compile(rf'\(\s*(?P<y>{value})\s*-\s*{product}\s*\)')
    text = remainder.sub(lambda m: f"({m['y']} % {int(divisor, 0)})", text)
    bare = re.compile(rf'(?<=[=(,])(?P<lead>\s*)(?P<y>{value})\s*-\s*{product}(?=\s*[;),])')
    text = bare.sub(lambda m: f"{m['lead']}{m['y']} % {int(divisor, 0)}", text)
    return text, count


def _unwrapped(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _leftover(argument, held, divisor):
    """Whether an argument is only the quotient or its product, what a register still held."""
    text = _unwrapped(argument)
    number = int(divisor, 0)
    spelled = rf'(?:{divisor}|{number}|0x{number:X})'
    product = re.fullmatch(rf'(?P<a>.+?)\s*\*\s*{spelled}|{spelled}\s*\*\s*(?P<b>.+)', text)
    if product:
        text = _unwrapped(product['a'] or product['b'])
    return text in held


def _drop_leftovers(source, name, header_clean, held, divisor):
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    calls = {}
    for hit in CALL.finditer(clean, part.opening + 1, part.end):
        if hit['f'] in KEYWORDS:
            continue
        end = close(clean, hit.end() - 1, '(', ')')
        if end:
            calls.setdefault(hit['f'], []).append((hit.end(), end - 1, _arguments(clean, hit.end(), end - 1)))
    edits = []
    for callee, sites in calls.items():
        declared = re.search(rf'(?<![\w.>]){re.escape(callee)}\s*\(\s*(?P<first>[^)\s]*)', header_clean)
        if declared and declared['first'] not in ('', 'void'):
            continue
        drop = [(start, end, '') for start, end, spans in sites
                if spans and all(_leftover(source[a:b], held, divisor) for a, b in spans)]
        if not drop:
            continue
        edits += drop
        prototype = _prototype(clean, part.opening, callee)
        if prototype and prototype[2] and clean[prototype[0]:prototype[1]].strip() != 'void' and len(drop) == len(sites):
            edits.append((prototype[0], prototype[1], 'void'))
    return edit(source, edits) if edits else source


def _without_unread(source, name, locals_):
    """The source without the plain statements that assign a local of the division which nothing reads."""
    while True:
        part = view(source, name)
        if not part:
            return source
        for local in locals_:
            writes = list(re.finditer(rf'(?m)^[ \t]*{local}\s*=(?!=)[^;{{}}\n]*;[ \t]*\n', part.clean))
            reads = len(re.findall(rf'(?<![\w.>]){local}(?!\w)', part.body))
            declared = len(re.findall(rf'(?m)^[ \t]*(?:{IDENT}[ \t*]+)+{local}\s*;', part.body))
            own = sum(len(re.findall(rf'(?<![\w.>]){local}(?!\w)', w.group())) for w in writes)
            if writes and declared == 1 and reads == own + declared and not any('(' in w.group() and re.search(
                    rf'(?!(?:s32|u32|s16|u16|s8|u8)\b){IDENT}\s*\(', w.group()) for w in writes):
                source = edit(source, [(w.start(), w.end(), '') for w in writes])
                break
        else:
            return source


def variants(source, name, header=''):
    part = view(source, name)
    if not part or not re.search(rf'>>\s*{SIGN}\b', part.body):
        return []
    body = part.body
    sites = []
    for hit in QUOTIENT.finditer(body):
        if _assigned_once(body, hit['q']):
            sites.append((hit['q'], hit['x'], hit['n']))
    for hit in re.finditer(rf'\(\s*(?P<x>{IDENT})\s*/\s*(?P<n>{NUMBER})\s*\)\s*-\s*{CAST}\(', body):
        sites.append((None, hit['x'], hit['n']))
    text = source
    held, locals_, applied = set(), [], []
    for quotient, dividend, divisor in dict.fromkeys(sites):
        number = int(divisor, 0)
        if number < 3 or not number & (number - 1):
            continue
        current = view(text, name)
        if not current:
            return []
        inner, count = _correct(text[current.opening:current.end], quotient, dividend,
                                _copies(current.body, dividend), divisor)
        if not count:
            continue
        text = text[:current.opening] + inner + text[current.end:]
        names = {quotient} if quotient else {f'{dividend} / {divisor}'}
        # a local that holds only the product is a leftover too, and goes when nothing reads it
        products = {hit['p'] for hit in re.finditer(
            rf'(?<![\w.>])(?P<p>{IDENT})\s*=\s*\(?\s*{re.escape(quotient or "")}\s*\*\s*{divisor}\s*\)?\s*;',
            view(text, name).body)} if quotient else set()
        held |= names | products
        locals_ += sorted(products) + ([quotient] if quotient else [])
        applied.append(divisor)
    if text == source:
        return []
    out = [text]
    dropped = text
    for divisor in dict.fromkeys(applied):
        dropped = _drop_leftovers(dropped, name, _blank(header or ''), held, divisor)
    if dropped != text:
        out.append(dropped)
    trimmed = _without_unread(dropped, name, locals_)
    if trimmed != dropped:
        out.append(trimmed)
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 40,
          'archs': ('mips',)}
