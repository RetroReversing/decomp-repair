"""A global inside a record array's first element, read through the zero index the game indexed it with.

m2c names a member of `pads[player]` by its own address when `player` is a local that is always 0:

    player = 0;                                   player = 0;
    state = step(player);                         state = step(player);
    if (D_801E99C0 == 1) {            ->          if ((*(s32 *) ((char *) &D_801E9990[player] + 0x30)) == 1) {

Both reach the same word (`lui; lw %lo`, the compiler folds the index), but not the same function. KMC GCC 2.7.2 `-O1`
counts the registers live across calls before combine folds the index away: with the indexed read after a call, the
zero local stays in a saved register, and the call's argument is widened in place (`andi $s0,$s0,0xffff; jal; move
$a0,$s0`) where the absolute read gives `move $a0,$zero`. A 994-instruction N64 menu dispatcher was 42 register rows
and 6 missing instructions from exact with the absolute reads, and exact with this form.

zero_index_member
    Some local is only ever assigned 0, the function indexes an address-named array with it (`D_A[v]`), and it also
    reads or writes a scalar whose address-named symbol lies less than 0x200 bytes above D_A, declared with a plain
    integer or float type. Each use of that scalar becomes `*(T *) ((char *) &D_A[v] + delta)`. One child per scalar,
    and one with every scalar.

The program reads and writes the same bytes. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find

FAMILY = 'zero_index_member'
FAMILIES = (FAMILY,)

LIMIT = 0x200
INDEXED = re.compile(r'\b(D_([0-9A-F]{8}))\s*\[\s*([A-Za-z_]\w*)\s*\]')
SCALAR = r'(?:[su](?:8|16|32)|f32|(?:(?:unsigned|signed)\s+)?(?:char|short|int|long))'


def _zero_only(body, local):
    """Every write of `local` in the body is a plain `= 0;`, and there is one."""
    name = r'\b' + re.escape(local) + r'\b'
    if re.search(r'(?:\+\+|--|(?<!&)&(?!&))\s*' + name + '|' + name + r'\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)=)', body):
        return False
    writes = re.findall(name + r'\s*=(?!=)\s*([^;,)]*)', body)
    return bool(writes) and all(value.strip() == '0' for value in writes)


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start = clean.find('{', span[0], span[1])
    if start < 0:
        return []
    body = clean[start:span[1]]
    arrays = {}
    for hit in INDEXED.finditer(body):
        if _zero_only(body, hit.group(3)):
            arrays.setdefault(int(hit.group(2), 16), (hit.group(1), hit.group(3)))
    if not arrays:
        return []
    declarations = clean[:span[0]] + '\n' + _blank(header or '')
    edits = {}
    for symbol in sorted(set(re.findall(r'\bD_[0-9A-F]{8}\b', body))):
        declared = re.search(r'\bextern\s+(?:volatile\s+)?(' + SCALAR + r')\s+' + symbol + r'\s*;', declarations)
        if not declared:
            continue
        address = int(symbol[2:], 16)
        below = [base for base in arrays if 0 < address - base < LIMIT]
        if not below:
            continue
        array, local = arrays[max(below)]
        text = f'(*({declared.group(1)} *) ((char *) &{array}[{local}] + {hex(address - max(below))}))'
        spans = [(start + hit.start(), start + hit.end())
                 for hit in re.finditer(r'(?<![&.>\w])' + symbol + r'\b(?!\s*[\[.])', body)]
        if spans:
            edits[symbol] = [(lo, hi, text) for lo, hi in spans]

    def apply(chosen):
        out = source
        for lo, hi, text in sorted(chosen, reverse=True):
            out = out[:lo] + text + out[hi:]
        return out

    found = [(FAMILY, apply(edit)) for edit in edits.values()]
    if len(edits) > 1:
        found.insert(0, (FAMILY, apply([item for edit in edits.values() for item in edit])))
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
