"""A code symbol that m2c declared as data: `extern M2C_UNK func_800393F4;` used only through its address.

m2c knows nothing about a symbol the game only takes the address of (a callback stored into a field, a table of entry
points) and declares it `extern M2C_UNK name;`, a one-word variable. The compiler then treats `&name` as the address of
data, and the address of a function is another thing to it: KMC GCC 2.7.2 and the SN compiler (N64, MIPS) load a
function's address as `lui`/`addiu` at the point the C needs it in one schedule, and a data symbol's address in
another (the data address is a constant that sits in the instruction stream where the value is first formed; a
function's is a SYMBOL_REF that the call and store patterns schedule with the rest of the expression). The target is
the function's: the declaration decides the order of the `lui` against the other loads. This is a hypothesis about the
compiler's schedule, not read from its source; what was measured is below.

A symbol the project knows as code is a name splat gives a function (`func_80039F4C`, any hex width splat writes) or one
the callees' C or the header declares with a parameter list. Used only as an address (`&name`, `(s8 *)&name + N`, or an
array-declared `name` as an address), its declaration is rewritten, and nothing else:
- `code_symbol_function`: `extern void name(void);`, one symbol at a time and all of them together. The uses stay
  (`&name` of a function is a function pointer, and `&name + N` is byte arithmetic on it in GNU C).
- `code_symbol_byte_offset`: the same declaration and each `&name + N` written `((s8 *)&name + N)`: N is counted in
  bytes there and the function form says so, the way a matched address-plus-offset function symbol was written.
A symbol read as data (a bare use of a scalar declaration), called, dereferenced or indexed is left alone: a function
declaration would change what that code means.

On an N64 game's 30-instruction constructor that stores a callback address into a field (SN compiler `-O2 -mips2`,
`-G8`): declared `extern M2C_UNK`, the `lui %hi(callback)` came after the float global's `lui $at, %hi(...)` load and
scored 80; declared `extern void callback(void);` the order was the target's, score 0. Statement orders, pointer and
float locals and the other cast spellings stayed at 80 or worse. One function's evidence.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, view
from .pattern_repairs import close

FAMILY = 'code_symbol_function'
OFFSET_FAMILY = 'code_symbol_byte_offset'
FAMILIES = (FAMILY, OFFSET_FAMILY)
LIMIT = 8  # symbols with a child of their own; the together child covers any more

_CODE_NAME = re.compile(r'func_[0-9A-Fa-f]{6,8}')
_DECL = re.compile(
    r'^(?P<head>[ \t]*extern[ \t]+(?:const[ \t]+)?(?P<type>(?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]*)'
    r'(?P<name>' + IDENT + r')[ \t]*(?P<array>\[[^\]\n]*\])?[ \t]*;', re.M)
_DATA_TYPES = re.compile(r'(?:M2C_UNK(?:8|16|32)?|[su](?:8|16|32)|f32|(?:unsigned|signed)[ \t]+(?:char|short|int)|char|short|int|long)')
_CAST = re.compile(r'\(\s*(?:s8|u8|char|signed\s+char|unsigned\s+char)\s*\*\s*\)\s*$')


def _known_as_code(name, context):
    return bool(_CODE_NAME.fullmatch(name)) or bool(re.search(r'(?<![\w&.>])' + re.escape(name) + r'\s*\(', context))


def _uses(clean, declaration, name, array):
    """The uses of `name` outside its declaration: (address sites, `&name + N` sites), or None when it isn't only an address.

    A site is (start of `&`, end of the offset's operand or None)."""
    addresses, offsets = [], []
    for hit in re.finditer(r'(?<![\w.])' + re.escape(name) + r'(?!\w)', clean):
        start, end = hit.span()
        if declaration[0] <= start < declaration[1]:
            continue
        after = clean[end:].lstrip()
        before = clean[:start].rstrip()
        if before.endswith('->'):
            return None  # a field of that name, not the symbol
        if after.startswith('(') or (after.startswith('[') and array is not None):
            return None  # called, or indexed: a function declaration would change what it means
        if before.endswith('&') and not before.endswith('&&'):
            amp = clean.rfind('&', 0, start)
            before_amp = clean[:amp].rstrip()
            if re.search(r'(?:^|[(=,\[;{}])\s*\*$', before_amp):
                return None  # `*&name`: a read through the address
            plus = re.match(r'\s*\+\s*', clean[end:])
            if plus:
                operand = _operand(clean, end + plus.end())
                if operand is None:
                    return None
                if not _CAST.search(before_amp):
                    offsets.append((amp, operand))
            addresses.append(amp)
        elif array is None:
            return None  # a scalar read as data
        else:
            addresses.append(start)  # an array's bare name is its address
    return (addresses, offsets) if addresses else None


def _operand(clean, at):
    """End of the one operand after `&name +`: a number, a name or a parenthesised expression; None when it is more."""
    if clean.startswith('(', at):
        end = close(clean, at)
        stop = end if end else None
    else:
        hit = re.match(NUMBER + '|' + IDENT, clean[at:])
        stop = at + hit.end() if hit else None
    if stop is None:
        return None
    if re.match(r'\s*(?:[*/%\[.]|->|<<|>>)', clean[stop:]):
        return None  # `&name + 2 * x`: the operand is wider than what was matched
    return stop


def _candidates(source, context):
    clean = _blank(source)
    found = []
    for hit in _DECL.finditer(clean):
        name, kind = hit['name'], hit['type']
        if not _DATA_TYPES.fullmatch(kind) or not _known_as_code(name, context):
            continue
        if re.search(r'\bextern[^;\n]*\b' + re.escape(name) + r'\s*\(', clean):
            continue
        uses = _uses(clean, hit.span(), name, hit['array'])
        if uses:
            found.append((hit, uses))
    return found


def _rewrite(source, chosen, with_offsets):
    edits = []
    for hit, (addresses, offsets) in chosen:
        edits.append((hit.start(), hit.end(), f'{hit["head"][:hit["head"].index("extern")]}extern void {hit["name"]}(void);'))
        if with_offsets:
            edits += [(amp, amp, '((s8 *)') for amp, _ in offsets] + [(stop, stop, ')') for _, stop in offsets]
    text = source
    for start, end, new in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
        text = text[:start] + new + text[end:]
    return text


def variants(source, name, header='', callees=''):
    part = view(source, name)
    if not part:
        return []
    found = _candidates(source, _blank(header) + '\n' + callees + '\n' + part.clean)
    found = [item for item in found if _within(item, part)]
    if not found:
        return []
    out = []
    for with_offsets in (False, True):
        family = OFFSET_FAMILY if with_offsets else FAMILY
        if with_offsets and not any(offsets for _, (_, offsets) in found):
            continue
        groups = [[item] for item in found[:LIMIT]]
        if len(found) > 1:
            groups.append(found)
        for group in groups:
            if with_offsets and not any(offsets for _, (_, offsets) in group):
                continue
            text = _rewrite(source, group, with_offsets)
            if text != source and (family, text) not in out:
                out.append((family, text))
    return out


def _within(item, part):
    """Only symbols the function itself uses (the file's other functions are not this repair's business)."""
    hit, (addresses, _) = item
    return any(part.opening < at < part.end for at in addresses)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'callees')}  # the registry: no caller wiring (registry.py)
