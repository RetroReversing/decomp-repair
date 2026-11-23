"""A hand-built stack frame (a struct with padding, a volatile word, a phantom array) written as the plain locals the compiler spills (GCC 2.7.2, KMC, N64).

A target that reloads a parameter before every call (`lw $a3, 0x2c($sp)`) and stores a byte parameter in the middle of its
frame (`sb $a1, 0x37($sp)`) did not have those variables in memory: the saved registers ran out and reload spilled the
two parameters. An agent that sees the slots writes the frame out by hand to get the same offsets:

    struct { s32 texture; GfxPair *start; s32 unused; volatile s32 vertexTransform; u8 padding[7]; u8 emit; } state;
    u32 savedSpace[8];
    state.vertexTransform = a3;  ...  call(..., state.vertexTransform, ...);

The frame is then right, but the loads are fixed in the program: the first scheduler sees a frame-pointer-relative `volatile`
memory read it cannot move across the outgoing argument stores (they sit on the stack pointer, a base it cannot compare),
so the reload stays behind the stores where the target's, spilled after the first scheduler, comes before them. The plain
program lets reload place the slot (`sw $a3, 0x2c($sp)`: the first spill lands exactly there, and the byte's slot at
`0x34` with the byte at `0x37`, big-endian) and the second scheduler order the reload. Measured on a 559-instruction N64
display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): 1850 -> 1106 with the parameter read directly and the
byte a plain local, and 950 once the loops were the `for` loops whose test copies leave the frame its missing 0x20 bytes
(`cursor_base_index_for`, `guarded_counter_for_loop`): every `sp` offset of the function matched without a phantom array.

`variants` takes a function that declares such a struct in its body and offers
  * `frame_struct_unwrap`: the struct reduced to its address-taken members (the ones a `&state.member` passes on), every
    other member that is read a plain local of its own type (no `volatile`), the members nothing names dropped, and a
    local array nothing reads dropped with them;
  * `frame_struct_param_fold`: the same, with a local that is set once from a parameter and never written again read as
    that parameter (the compiler's copy propagation would, and the copy is not in the game).
It declines a struct whose address is taken as a whole, one with a member that is itself an aggregate, and a name used
outside the function. The exact judge decides whether the frame still comes out the same.
"""
import re

from .csource import find

FAMILY = 'frame_struct_unwrap'
FOLD = 'frame_struct_param_fold'
FAMILIES = (FAMILY, FOLD)

_ID = r'[A-Za-z_]\w*'
_STRUCT = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:volatile[ \t]+)?struct\s*\{{(?P<fields>[^{{}}]*)\}}[ \t]*(?P<var>{_ID})[ \t]*;[ \t]*\n')
_MEMBER = re.compile(rf'\s*(?P<type>[A-Za-z_][\w \t\*]*?)[ \t\*]*(?P<name>{_ID})[ \t]*(?P<array>\[[^\]]+\])?[ \t]*$')
_SCALAR = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'char', 'short', 'unsigned', 'signed', 'long', 'volatile', 'const',
           'unsigned int', 'unsigned char', 'unsigned short', 'f32', 'float'}


def _members(text):
    """(type, name, array, pointer) for each member, or None for anything this cannot read plainly."""
    out = []
    for part in text.split(';'):
        if not part.strip():
            continue
        hit = _MEMBER.fullmatch(part)
        if not hit or re.search(r'\b(?:struct|union)\b|[{}()]', part):
            return None
        kind = ' '.join(part[:part.rindex(hit['name'])].split())
        out.append((kind, hit['name'], hit['array'] or '', '*' in part))
    return out or None


def _decl(kind, name):
    """`GfxPair *` + `start` is `GfxPair *start`; `s32` + `a` is `s32 a`."""
    kind = ' '.join(word for word in kind.split() if word != 'volatile')
    return f'{kind}{name}' if kind.endswith('*') else f'{kind} {name}'


def _parameters(source, name, span):
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', source[span[0]:span[1]])
    if not head:
        return {}
    start = span[0] + head.end()
    depth, at = 1, start
    while at < len(source) and depth:
        depth += {'(': 1, ')': -1}.get(source[at], 0)
        at += 1
    out = {}
    for part in re.split(r',(?![^()]*\))', source[start:at - 1]):
        hit = re.search(rf'(?P<type>[\w \t\*]*?)(?P<name>{_ID})\s*$', part.strip())
        if hit and hit['type'].strip():
            out[hit['name']] = ' '.join(hit['type'].replace('register', ' ').split())
    return out


def _assigned_once_from_parameter(text, local, parameters):
    """The parameter the local is set from (a plain `local = param;` once), when nothing else writes either of them."""
    sets = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)\s*(?P<src>{_ID})\s*;', text))
    if len(sets) != 1 or sets[0]['src'] not in parameters:
        return None
    param = sets[0]['src']
    writes = rf'(?<![\w.>])(?:{re.escape(local)}|{re.escape(param)})\s*(?:=(?!=)|[-+*/|&^%]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*(?:{re.escape(local)}|{re.escape(param)})\b|&\s*(?:{re.escape(local)}|{re.escape(param)})\b'
    if len(re.findall(writes, text)) != 1:
        return None
    return sets[0], param


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    hit = _STRUCT.search(text)
    if not hit:
        return []
    var = hit['var']
    members = _members(hit['fields'])
    if not members:
        return []
    kinds = {field: (kind, array, pointer) for kind, field, array, pointer in members}
    rest = text[:hit.start()] + text[hit.end():]
    if re.search(rf'&\s*{re.escape(var)}\b(?!\s*\.)', rest):
        return []
    used, taken = {}, set()
    for use in re.finditer(rf'(&\s*)?\b{re.escape(var)}\s*\.\s*({_ID})', rest):
        if use[2] not in kinds:
            return []
        used[use[2]] = True
        if use[1]:
            taken.add(use[2])
    if re.search(rf'\b{re.escape(var)}\b(?!\s*\.)', re.sub(rf'\b{re.escape(var)}\s*\.\s*{_ID}', '', rest)):
        return []
    others = source[:span[0]] + source[span[1]:]
    local_names, locals_ = {}, []
    for kind, field, array, pointer in members:
        if field in taken or field not in used:
            continue
        if array:
            return []
        wanted = field if not re.search(rf'\b{re.escape(field)}\b', text.replace(hit.group(0), '') + others) else f'{var}_{field}'
        local_names[field] = wanted
        locals_.append((' '.join(w for w in kind.split() if w != 'volatile'), wanted))
    if not locals_ and not all(field in used for _, field, _, _ in members):
        pass
    kept = [(kind, field, array) for kind, field, array, _ in members if field in taken]
    dropped = [field for _, field, _, _ in members if field not in used]
    if not locals_ and not dropped and not any('volatile' in kind for kind, _, _ in kept):
        return []
    body = re.sub(rf'\b{re.escape(var)}\s*\.\s*({_ID})', lambda use: f'{var}.{use[1]}' if use[1] in taken else local_names[use[1]], rest)
    indent = hit['indent']
    declarations = ''
    if kept:
        declarations += f'{indent}struct\n{indent}{{\n' + ''.join(
            f'{indent}  {_decl(kind, field)}{array};\n' for kind, field, array in kept) + f'{indent}}} {var};\n'
    declarations += ''.join(f'{indent}{_decl(kind, local)};\n' for kind, local in locals_)
    # a local array nothing reads: the frame filler that stood in for the slots reload now makes
    phantoms = []
    for decl in re.finditer(rf'(?m)^[ \t]*(?:{_ID}[ \t\*]+)+(?P<n>{_ID})\[[^\]]+\];[ \t]*\n', body):
        if len(re.findall(rf'\b{re.escape(decl["n"])}\b', body)) == 1:
            phantoms.append(decl)
    child_body = body
    for decl in reversed(phantoms):
        child_body = child_body[:decl.start()] + child_body[decl.end():]
    at = min(hit.start(), len(child_body))
    child = child_body[:at] + declarations + child_body[at:]
    out = [(FAMILY, source[:span[0]] + child + source[span[1]:])]
    parameters = _parameters(source, name, span)
    folded, fold_body = [], child
    for kind, local in locals_:
        found = _assigned_once_from_parameter(fold_body, local, parameters)
        if not found:
            continue
        sets, param = found
        width = lambda t: 4 if re.fullmatch(r'(?:s32|u32|int|unsigned int|unsigned)', t) or '*' in t else 0
        if not (width(kind) and width(parameters[param])):
            continue
        folded.append(local)
        fold_body = fold_body[:sets.start()] + fold_body[sets.end():]
        fold_body = re.sub(rf'(?m)^[ \t]*{re.escape(kind)}[ \t]+{re.escape(local)};[ \t]*\n', '', fold_body)
        fold_body = re.sub(rf'(?<![\w.>]){re.escape(local)}\b', param, fold_body)
    if folded:
        out.append((FOLD, source[:span[0]] + fold_body + source[span[1]:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 98}
