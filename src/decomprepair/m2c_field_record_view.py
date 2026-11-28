"""m2c's `M2C_FIELD(p, T *, K)` accesses written as members of a record type for `p`.

m2c prints every field it has no type for as `M2C_FIELD(arg0, s32 *, 0x88)`, a cast and an add. The game declared a
struct, and the compiler treats the two differently: a member access is a structure reference, which the scheduler and
cse can tell apart from a store through another pointer. A stuck N64 function matched only once its raw casts became
members (see byte_pointer_record_view, which reads hand-written casts; this reads m2c's own macro). Measured on 80
fresh m2c drafts of matched functions of an SN64 GCC 2.8.1 game, judged beside the plain draft: 21 scored lower with
records (3 of them exact), 2 higher, 57 the same, and none stopped compiling. Candidates to judge, never a replacement.

Children: every pointer retyped, then each pointer on its own when there are several. A base is retyped only when it is
a plain name, each offset is read with one type, no two members overlap and every offset is a multiple of its member's
size. Pointer members are `void *`. Only the function's own accesses are rewritten.

A global read as `M2C_FIELD(&D_x, T *, K)` is a base too: m2c declares it `extern M2C_UNK D_x;`, and the game declared
a struct there. Its declaration becomes `extern Rec D_x;` and each access `D_x.mK`. GCC (SN 2.8.1 here) then forms the
address once and stores the offset 0 member through the symbol, which no spelling of the casts does: a 22-instruction
N64 initialiser of such a record stood at 985 as its draft and was exact with this edit alone. Only a symbol the source
itself declares as a plain scalar `extern` (not one the project header names) whose every other use is understood: a
bare `D_x` is the member at offset 0, of the declared type, and `&D_x` may not be stepped without a cast.

A global m2c declares as a byte array, `extern u8 D_x[];`, and reads as `M2C_FIELD(D_x, T *, K)` is declared as the
record too (not just cast to it), and an element read through the same symbol, `M2C_FIELD(((i) * 4) + D_x, s32 *, 0x10)`
with the stride the size of the type, becomes the array member `D_x.m10[i]`. Only when every use of the symbol is one of
these two. An 18-instruction N64 stack pop of such a record (SN GCC 2.8.1 profile) went from 2030 to 310 with this
child and matched after two more steps (`narrow_widening`, `guard_temp_sink`).

The element's byte offset may be held in a local first, `i = X * 4; ... M2C_FIELD((i + D_x), s32 *, 0x10)`. When the
local is a plain 32-bit integer set once, as a product by the element's size, and read only as such a base, it holds the
index instead: `i = X;` and `D_x.m10[i]`. An 11-instruction N64 stack push (SN 2.8.1 profile) stood at 1110 as its draft;
this child scores 100 and `mask_local_retype` on it is exact.
"""
import re

from .pattern_repairs import close

FAMILY = 'm2c_field_record_view'
FAMILIES = (FAMILY,)
SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 's64': 8, 'u64': 8, 'f64': 8,
         'M2C_UNK': 4, 'M2C_UNK8': 1, 'M2C_UNK16': 2, 'M2C_UNK32': 4}
POINTER = 4  # the targets m2c drafts for here have 32-bit pointers
FIELD = re.compile(r'\bM2C_FIELD\(\s*((?:&\s*)?[A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*(\*+)\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\)')
MAX_BASES = 8


def _definition(source, name):
    """Where the function's definition starts (its line), or None."""
    found = re.search(r'^[^\n#;]*\b' + re.escape(name) + r'\s*\([^;{}]*\)\s*\{', source, re.M)
    return found.start() if found else None


def _key(base):
    return base.replace(' ', '')


def _layouts(body, extra=()):
    """{base: {offset: (member type, size)}} for the bases that can be records. `extra`: (base, offset, type) of
    accesses written another way (a global's bare name)."""
    seen, refused = {}, set()
    accesses = [(_key(m[1]), int(m[4], 0), m[2], m[3]) for m in FIELD.finditer(body)]
    accesses += [(base, offset, typ, '*') for base, offset, typ in extra]
    for base, offset, typ, stars in accesses:
        member, size = ('void *', POINTER) if len(stars) > 1 else (typ, SIZES.get(typ))
        fields = seen.setdefault(base, {})
        if size is None or offset < 0 or offset % size or fields.setdefault(offset, (member, size)) != (member, size):
            refused.add(base)
    out = {}
    for base, fields in seen.items():
        ordered = sorted(fields.items())
        if base not in refused and all(at + size <= later for (at, (_, size)), (later, _) in zip(ordered, ordered[1:])):
            out[base] = dict(ordered)
    return out


def _byte_array(symbol):
    return re.compile(r'^[ \t]*extern[ \t]+(?:u8|s8)[ \t]+' + re.escape(symbol) + r'\[\][ \t]*;[ \t]*\n', re.M)


def _unwrap(text):
    """`text` without parentheses around the whole of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _element(base, symbol):
    """(index, stride) when `base` is `((index) * stride) + symbol`, either way round, else None."""
    text, word = _unwrap(base), re.escape(symbol)
    found = re.fullmatch(r'(?P<product>\(.*\))\s*\+\s*' + word, text) or re.fullmatch(word + r'\s*\+\s*(?P<product>\(.*\))', text)
    if not found:
        return None
    product = _unwrap(found['product'])
    scaled = re.fullmatch(r'(?P<index>.+?)\s*\*\s*(?P<stride>0x[0-9A-Fa-f]+|\d+)', product)
    if not scaled:
        return None
    index = scaled['index'].strip()
    if not (re.fullmatch(r'[A-Za-z_]\w*', index) or (index.startswith('(') and close(index, 0) == len(index))):
        return None
    return _unwrap(index), int(scaled['stride'], 0)


def _held_offset(base, symbol):
    """The name when `base` is `name + symbol`, either way round, else None."""
    text, word = _unwrap(base), re.escape(symbol)
    found = re.fullmatch(r'([A-Za-z_]\w*)\s*\+\s*' + word, text) or re.fullmatch(word + r'\s*\+\s*([A-Za-z_]\w*)', text)
    return found[1] if found else None


def _scaled_local(body, local, size, uses):
    """The spans to delete so that `local = index * size;` holds the index itself (the scale and the parentheses around
    the whole index), when `local` is a 32-bit integer declared here, set only by that statement and otherwise read only
    in its `uses` element bases."""
    word = r'\b' + re.escape(local) + r'\b'
    declared = re.findall(r'^[ \t]*(?:s32|u32|int)[ \t]+' + re.escape(local) + r'[ \t]*;', body, re.M)
    sets = list(re.finditer(r'^[ \t]*' + re.escape(local) + r'[ \t]*=(?!=)[ \t]*([^;\n]+);', body, re.M))
    if len(declared) != 1 or len(sets) != 1 or len(re.findall(word, body)) != uses + 2:
        return None
    value = sets[0][1].rstrip()
    product = re.fullmatch(r'(.+?)(\s*(\*|<<)\s*(0x[0-9A-Fa-f]+|\d+))', value)
    if not product:
        return None
    index, by = product[1].strip(), int(product[4], 0)
    scale = by if product[3] == '*' else 1 << min(by, 8)
    whole = re.fullmatch(r'[A-Za-z_]\w*', index) or (index.startswith('(') and close(index, 0) == len(index))
    if not whole or scale != size or re.search(word, index):
        return None
    start = sets[0].start(1)
    end = start + len(value)
    scale_at = end - len(product[2])
    if not index.startswith('('):
        return [(scale_at, end)]
    return [(start, start + 1), (start + len(index) - 1, end)]


def _byte_accesses(body, symbol):
    """([(start, end, offset, member type, size, index or None)], [spans to delete from held offsets]) when every use
    of the byte array `symbol` in `body` is the base of an `M2C_FIELD`, alone or stepped by an index, else None."""
    out, at, held = [], 0, {}
    word = re.compile(r'\b' + re.escape(symbol) + r'\b')
    for macro in re.finditer(r'\bM2C_FIELD\(', body):
        if macro.start() < at:
            continue
        end = close(body, macro.end() - 1)
        if end is None:
            return None
        inner = body[macro.end():end - 1]
        if not word.search(inner):
            continue
        parts = re.fullmatch(r'(?s)(.*),\s*([A-Za-z_]\w*)\s*(\*+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*', inner)
        if not parts:
            return None
        base, typ, stars, offset = parts[1], parts[2], parts[3], int(parts[4], 0)
        member, size = ('void *', POINTER) if len(stars) > 1 else (typ, SIZES.get(typ))
        if size is None or offset % size:
            return None
        index = None
        if _unwrap(base) != symbol:
            element = _element(base, symbol)
            local = None if element else _held_offset(base, symbol)
            if local:
                held.setdefault(local, []).append(size)
                index = local
            elif not element or element[1] != size or word.search(element[0]) or 'M2C_FIELD' in element[0]:
                return None
            else:
                index = element[0]
        out.append((macro.start(), end, offset, member, size, index))
        at = end
    covered = sum(len(word.findall(body[a:b])) for a, b, *_ in out)
    if not out or covered != len(word.findall(body)):
        return None
    scales = [_scaled_local(body, local, sizes[0], len(sizes)) if len(set(sizes)) == 1 else None
              for local, sizes in held.items()]
    return (out, [span for spans in scales for span in spans]) if all(scales) else None


def _byte_record(source, name, start, symbol, header):
    """The child that declares the byte array `symbol` as a record, or None."""
    head, body = source[:start], source[start:]
    word, tag = r'\b' + re.escape(symbol) + r'\b', f'Rec_{name}_{symbol}'
    if (len(_byte_array(symbol).findall(head)) != 1 or len(re.findall(word, head)) != 1
            or re.search(word, header) or re.search(r'\b' + re.escape(tag) + r'\b', source)):
        return None
    found = _byte_accesses(body, symbol)
    if not found:
        return None
    accesses, scales = found
    members, arrays = {}, set()
    for _, _, offset, member, size, index in accesses:
        if members.setdefault(offset, (member, size)) != (member, size):
            return None
        if index is not None:
            arrays.add(offset)
    ordered = sorted(members.items())
    if any(at + size > later for (at, (_, size)), (later, _) in zip(ordered, ordered[1:])):
        return None
    lines, at = [], 0
    for position, (offset, (member, size)) in enumerate(ordered):
        if offset > at:
            lines.append(f'    char pad{at:X}[0x{offset - at:X}];')
        space = '' if member.endswith('*') else ' '
        count = 0
        if offset in arrays:
            later = ordered[position + 1][0] if position + 1 < len(ordered) else offset + size
            count = (later - offset) // size
        lines.append(f'    {member}{space}m{offset:X}{f"[{count}]" if count else ""};')
        at = offset + size * max(count, 1)
    edits = [(a, b, '') for a, b in scales]
    for a, b, offset, _, _, index in accesses:
        element = f'[{index}]' if index is not None else '[0]' if offset in arrays else ''
        edits.append((a, b, f'{symbol}.m{offset:X}{element}'))
    for a, b, text in sorted(edits, reverse=True):
        body = body[:a] + text + body[b:]
    record = 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\nextern {tag} {symbol};\n'
    return _byte_array(symbol).sub('', head) + record + '\n' + body


def _declaration(symbol):
    return re.compile(r'^[ \t]*extern[ \t]+([A-Za-z_]\w*)[ \t]+' + re.escape(symbol) + r'[ \t]*;[ \t]*\n', re.M)


def _global(source, start, symbol, header):
    """(declared type, spans of the bare uses in the function's text) when `symbol` can become a record, else None."""
    word = r'\b' + re.escape(symbol) + r'\b'
    found = _declaration(symbol).findall(source[:start])
    if len(found) != 1 or re.search(word, header):
        return None
    if len(re.findall(word, source[:start])) != 1:
        return None
    body = source[start:]
    bare = []
    for use in re.finditer(word, body):
        before, after = body[:use.start()].rstrip(), body[use.end():].lstrip()
        if before.endswith(('.', '->')):
            return None  # a member of that name somewhere else
        if before.endswith('&') and not before.endswith('&&'):
            lead = before[:-1].rstrip()
            if lead.endswith('M2C_FIELD('):
                continue
            cast = re.search(r'\(\s*[A-Za-z_]\w*[\s*]*\*\s*\)$', lead)
            if not cast and (re.match(r'[-+\[]', after) or re.search(r'[-+]$', lead)):
                return None  # arithmetic on the address would step by the record's size
            continue
        bare.append(use.span())
    return found[0], bare


def _record(tag, fields):
    lines, at = [], 0
    for offset, (member, size) in fields.items():
        if offset > at:
            lines.append(f'    char pad{at:X}[0x{offset - at:X}];')
        space = '' if member.endswith('*') else ' '
        lines.append(f'    {member}{space}m{offset:X};')
        at = offset + size
    return 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\n'


def _members(body, base, tag):
    if base.startswith('&'):
        return FIELD.sub(lambda m: f'{base[1:]}.m{int(m[4], 0):X}' if _key(m[1]) == base else m[0], body)
    return FIELD.sub(lambda m: f'((({tag} *) {base})->m{int(m[4], 0):X})' if m[1] == base else m[0], body)


def _child(source, name, start, bases, bare):
    head, body = source[:start], source[start:]
    records = []
    # the bare uses are spans of the untouched body: rewrite them before anything moves them
    spans = sorted((a, b, base[1:]) for base in bases if base in bare for a, b in bare[base])
    for a, b, symbol in reversed(spans):
        body = body[:a] + symbol + '.m0' + body[b:]
    for base, fields in bases.items():
        symbol = base.lstrip('&')
        tag = f'Rec_{name}_{symbol}'
        if re.search(r'\b' + re.escape(tag) + r'\b', source):
            return None
        record = _record(tag, fields)
        if base.startswith('&'):
            head = _declaration(symbol).sub('', head)
            record += f'extern {tag} {symbol};\n'
        records.append(record)
        body = _members(body, base, tag)
    return head + ''.join(records) + '\n' + body


def variants(source, name, header=''):
    start = _definition(source, name)
    if start is None or 'M2C_FIELD(' not in source[start:]:
        return []
    body = source[start:]
    arrays = list(dict.fromkeys(re.findall(r'^[ \t]*extern[ \t]+(?:u8|s8)[ \t]+([A-Za-z_]\w*)\[\]', source[:start], re.M)))[:MAX_BASES]
    records = [child for child in (_byte_record(source, name, start, symbol, header) for symbol in arrays) if child]
    globals_, extra, bare = {}, [], {}
    for base in dict.fromkeys(_key(m[1]) for m in FIELD.finditer(body)):
        if not base.startswith('&'):
            continue
        found = _global(source, start, base[1:], header)
        globals_[base] = found
        if found and found[1]:
            bare[base] = found[1]
            extra.append((base, 0, found[0]))
    layouts = {base: fields for base, fields in _layouts(body, extra).items()
               if not base.startswith('&') or globals_[base]}
    if not layouts:
        return [(FAMILY, child) for child in records]
    choices = [layouts]
    if len(layouts) > 1:
        choices += [{base: fields} for base, fields in list(layouts.items())[:MAX_BASES]]
    children = (_child(source, name, start, bases, bare) for bases in choices)
    return [(FAMILY, child) for child in [*records, *children] if child and child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring
