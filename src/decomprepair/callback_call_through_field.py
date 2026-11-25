"""A callback address stored in a field and then called by name: call it through the field.

m2c sees the target store `&cb` into an object's field and, in the next instructions, a `jalr` through the register that
still holds the address. It cannot know the register came from the field, so it writes the call by name:

    M2C_FIELD(obj, M2C_UNK (**)(void *), 0x9C) = func_80080AF0;
    func_80080AF0(obj);                                    /* the target: jalr $v0 */

A direct call compiles to `jal func_80080AF0`; the game wrote the call through the field (`o->x9C = cb; o->x9C(o);`), which
the compiler cannot fold to the known callee, so it emits `jalr` with the address it just stored (a loaded `lui/addiu` pair
used for the store and the call; four spawn and state-change helpers of an N64 game). The rewrite calls through the field
it just stored: `M2C_FIELD(obj, T (**)(args), 0x9C)(obj)`, the stored type cast when the field is `M2C_UNK **`.

The shape: a statement storing a plain function name to `M2C_FIELD(P, T, OFF)` (`T` a pointer to pointer: `X (**)(...)`,
`M2C_UNK **` or `void **`), directly followed by the statement `CB(args);` calling the same name, `P` a plain name or
an expression with no call and no side effect. Evidence in the target (MIPS): a `jalr`, and no `jal CB` in the function
(the direct call is not there). One child rewriting every such pair, and one per pair (at most six) when there are several.
The judge decides; a `jalr` that belongs to another call leaves the pair as it is."""
import re

from .arm_block_support import IDENT
from .integer_repair_support import edit, view

FAMILY = 'callback_call_through_field'
FAMILIES = (FAMILY, FAMILY + '_one')

PAIR = re.compile(
    rf'(?P<store>(?P<lead>[ \t]*)M2C_FIELD\(\s*(?P<p>[^,;{{}}]+?)\s*,\s*(?P<t>[^,;{{}}]*?\(\s*\*\*\s*\)\s*\([^()]*\)|M2C_UNK\s*\*\*|void\s*\*\*)\s*,'
    rf'\s*(?P<off>0x[0-9A-Fa-f]+|\d+)\s*\)\s*=\s*&?\s*(?P<cb>{IDENT})\s*;[ \t]*\n)'
    rf'(?P<call>[ \t]*(?P=cb)\s*\((?P<args>[^;{{}}]*)\)\s*;)')
MAX_ONE = 6


def _evidence(asm, names):
    """The callback names the target calls with `jalr` and never with `jal`: all of `names` when so, else none."""
    text = asm or ''
    if not re.search(r'\bjalr\b', text):
        return set()
    return {n for n in names if not re.search(rf'\bjal\s+{re.escape(n)}\b', text)}


def _rewrite(hit):
    kind = hit['t'].strip()
    field = f'M2C_FIELD({hit["p"].strip()}, {kind}, {hit["off"]})'
    if '(' not in kind:
        field = f'((void (*)()) {field})'
    return f'{hit["lead"]}{field}({hit["args"].strip()});'


def variants(source, name, asm, header=''):
    part = view(source, name)
    if not part:
        return []
    hits = [h for h in PAIR.finditer(part.clean, part.opening, part.end) if '(' not in h['p'] or re.fullmatch(r'[\w\s>.\-\[\]*()]+', h['p'])]
    ok = _evidence(asm, {h['cb'] for h in hits})
    hits = [h for h in hits if h['cb'] in ok]
    if not hits:
        return []
    spans = [(h.start('call'), h.end('call'), _rewrite(h)) for h in hits]
    out = [(FAMILY, edit(source, spans))]
    if len(spans) > 1:
        out += [(FAMILY + '_one', edit(source, [s])) for s in spans[:MAX_ONE]]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 66, 'archs': ('mips',)}
