"""A small-data global the target splits, declared as an incomplete array and read into a once-set local.

GCC keeps a global at most `-G N` bytes in small data and reads it through one assembler macro (`lw $r, G` is
`lui; lw`), so the `lui` is never an instruction of its own that the scheduler can place. A symbol that is not small
data (an array of unknown size is not) is split by the compiler into `lui %hi(G)` and an access through `%lo(G)`, two
instructions it schedules apart. The target of one small N64 function (SN GCC 2.8.1, `-G8 -mips2 -O2`: a constructor
that stores nine fields of a fresh object and one global) had the global's `lui` above an unrelated store and the `lw`
several instructions later. The m2c draft declared `extern s16 G;` and read it `*(s32 *)&G`, which the compiler glues
into one macro (80 at best). Declaring `extern s32 G[];` and reading `G[0]` alone scored 410, because the two halves
then sink to the use; reading it into a once-set local right after an earlier store (`g = G[0];` after the object's
first store, `g` stored at the field) gave 0, and only one of the eight positions of that statement did.
`int_global_array_read` has the array spelling for a plain read (and no local); the draft's cast read `*(T *)&G` was
not one it accepts. This family adds what the match needed (the array retype for the cast reads, and the local at each
neighbouring statement position).
(Hypothesis: the explanation of the scheduling is read off the targets, not from the compiler's source.)

A proposal takes a global that the source (not the header) declares as `extern T G;` with a scalar `T` of at most the
profile's `-G` size in bytes (the flags must name one), that the function only reads (plain, or as `*(T2 *)&G`), that no
other function in the file names, and whose address the target builds in a register other than `$at` with the `lui`
separated from the first `%lo(G)` use by at least one instruction (`int_global_array_read.early_address`). Children, per
global:
- `extern E G[];` with every read written `G[0]` (`E` is `T`, or the cast's type when every read is a cast to one other
  type, as the target's load width said);
- when the global is read once, in a plain statement of the function body, that child with the read held in a local,
  `E temp_G;`, set once as `temp_G = G[0];` before that statement and before each of the up to five statements before it
  that may be passed (no call, no label or control statement, not a declaration), and used where the read was.
At most MAX_GLOBALS globals and MAX_CHILDREN children. The caller pairs these with the profile that is being judged;
this module reads text only and never compiles or judges."""
import re

from .csource import _blank
from .extern_size_widen import size_of, threshold
from .float_literal_global import _reads
from .int_global_array_read import early_address
from .integer_repair_support import IDENT, View, edit, view

FAMILY = 'small_data_global_local'
FAMILIES = (FAMILY,)

MAX_GLOBALS = 2
MAX_CHILDREN = 8
POSITIONS = 6  # the read's own statement and the five before it
_TYPE = r'(?:[su](?:8|16|32)|(?:unsigned|signed)\s+(?:char|short|int|long)|unsigned|signed|char|short|int|long)'
_DECLARATION = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)extern[ \t]+(?P<type>{_TYPE}|{IDENT}[ \t]*\*)[ \t]*(?P<name>{IDENT})[ \t]*;')
_CONTROL = re.compile(r'(?:if|else|while|for|do|switch|goto|break|continue|case|default)\b')
_DECL = re.compile(r'(?:(?:const|volatile|register|unsigned|signed|struct)\s+)*[A-Za-z_]\w*[\s*]+[A-Za-z_]\w*'
                   r'(?:\[[^\]]*\])?\s*(?:=[^;]*)?;')


def _norm(kind):
    return re.sub(r'\s*\*$', ' *', re.sub(r'\s+', ' ', kind.strip()))


def _casts(part, symbol):
    """[(start, end, type)] of `*(T *)&G` in the function: a scalar read of the global through a cast."""
    pattern = re.compile(rf'\*\s*\(\s*(?P<type>{_TYPE}|{IDENT}\s*\*)\s*\*\s*\)\s*&\s*{re.escape(symbol)}\b')
    return [(hit.start(), hit.end(), _norm(hit['type'])) for hit in pattern.finditer(part.clean, part.opening, part.end)]


def _statements(clean, low, high):
    """[(start, end)] of the top-level statements of the text clean[low:high]: simple ones end at `;`, a block at its
    closing brace (unless `else` follows)."""
    out, depth, paren, start, index = [], 0, 0, None, low
    while index < high:
        char = clean[index]
        if start is None:
            if char.isspace():
                index += 1
                continue
            start = index
        if char == '(':
            paren += 1
        elif char == ')':
            paren -= 1
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and not re.match(r'\s*else\b', clean[index + 1:high]):
                out.append((start, index + 1))
                start = None
        elif char == ';' and depth == 0 and paren <= 0:
            out.append((start, index + 1))
            start = None
        index += 1
    return out


def _calls(text, macros):
    for hit in re.finditer(rf'({IDENT})\s*\(', text):
        if hit[1] != 'sizeof' and hit[1] not in macros:
            return True
    return bool(re.search(r'\(\s*\*\s*\w+\s*\)\s*\(', text))


def _plan(source, part, symbol, hit, element, reads, macros):
    """The array child and the local children of one global: [source]."""
    indent = hit['indent']
    declaration = (hit.start(), hit.end(), f'{indent}extern {element} {symbol}[];')

    def text(read):
        kind = read[2]
        return f'{symbol}[0]' if kind in (None, element) else f'*({kind} *) {symbol}'

    out = [edit(source, [declaration] + [(a, b, text((a, b, kind))) for a, b, kind in reads])]
    if len(reads) != 1:
        return out
    a, b, kind = reads[0]
    statements = _statements(part.clean, part.opening + 1, part.end - 1)
    at = next((n for n, (s, e) in enumerate(statements) if s <= a < e), None)
    if at is None:
        return out
    clean = part.clean
    statement = clean[statements[at][0]:statements[at][1]]
    if clean[part.opening + 1:statements[at][0]].count('{') != clean[part.opening + 1:statements[at][0]].count('}') \
            or re.match(r'\s*(?:\w+\s*:(?!:)|(?:if|else|while|for|do|switch|goto|break|continue|case|default)\b)', statement) \
            or '{' in statement:
        return out
    local = f'temp_{symbol}'
    if local in set(re.findall(IDENT, source)):
        return out
    first = next((n for n, (s, e) in enumerate(statements) if not _DECL.fullmatch(clean[s:e].strip())), at)
    anchor = statements[first - 1][1] if first else part.opening + 1
    declare = (anchor, anchor, f'\n    {element} {local};')
    low = at
    while low > first and at - low < POSITIONS - 1:
        before = clean[statements[low - 1][0]:statements[low - 1][1]]
        if '{' in before or _CONTROL.match(before) or re.match(r'\w+\s*:(?!:)', before) or _calls(before, macros):
            break
        low -= 1
    for position in range(at, low - 1, -1):
        s = statements[position][0]
        line = source.rfind('\n', 0, s) + 1
        gap = source[line:s]
        pad = gap if not gap.strip() else '    '
        insert = (s, s, f'{local} = {text(reads[0])};\n{pad}')
        out.append(edit(source, [declaration, declare, insert, (a, b, local)]))
    return out


def variants(source, name, header='', asm='', flags=()):
    """Proposals: each small global the target's `lui` separates from its load, retyped as an incomplete array, and
    that with the read held in a local set at each neighbouring statement position."""
    limit = threshold(flags)
    if not asm or not limit:
        return []
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    used = set(re.findall(IDENT, source[part.opening:part.end]))
    macros = set(re.findall(rf'(?m)^[ \t]*#[ \t]*define[ \t]+({IDENT})\(', f'{header}\n{source}'))
    found = []
    for hit in _DECLARATION.finditer(outside):
        symbol, kind = hit['name'], _norm(hit['type'])
        if len(found) >= MAX_GLOBALS:
            break
        size = size_of(kind)
        if hit.start() >= part.opening or symbol not in used or symbol == name or size is None or size > limit:
            continue
        if re.search(rf'\b{re.escape(symbol)}\b', header or '') or not early_address(symbol, asm):
            continue
        casts = _casts(part, symbol)
        masked = ''.join(' ' if any(a <= i < b for a, b, _ in casts) else c for i, c in enumerate(part.clean)) \
            if casts else part.clean
        plain = _reads(View(part.source, masked, part.opening, part.end), symbol) if (
            re.search(rf'(?<![\w.]){re.escape(symbol)}\b', masked[part.opening:part.end])) else []
        if plain is None or not (plain or casts):
            continue
        if re.search(rf'&\s*{re.escape(symbol)}\b', masked[part.opening:part.end]):
            continue  # an address that is not a cast read
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue
        kinds = {kind for _, _, kind in casts}
        element = next(iter(kinds)) if not plain and len(kinds) == 1 and size_of(next(iter(kinds))) else kind
        reads = sorted([(a, b, None) for a, b in plain] + casts)
        found.append(_plan(source, part, symbol, hit, element, reads, macros))
    out = []
    for rank in range(max((len(one) for one in found), default=0)):  # one child of each global in turn
        out += [(FAMILY, one[rank]) for one in found if rank < len(one)]
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'flags'),
          'order': 63, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
