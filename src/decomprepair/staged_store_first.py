"""A value computed into a local, other locals derived from it, and only then stored: the store first, the local reloaded.

m2c stages an update the way the first compiler pass saw it, in a local, and writes it back after the statements that
read the local:

    s1 = p->head + 0xA0;                     p->head = p->head + 0xA0;
    s2 = p->size;                    ->      s1 = p->head;
    v1 = s1 - p->tail;                       s2 = p->size;
    p->head = s1;                            v1 = s1 - p->tail;

The two programs are the same when the lines between the local's definition and the store only assign locals, read
no memory the store changes, and the local keeps its value through the store (the field is as wide as the local);
what changes is where the derived locals read from: `s1` is the field after the store, so a later
`reload_temp_inline` turns `v1` into `p->head - p->tail` read once the field is written, which is the target's order in
a 222-instruction stream refill built by IDO 7.1 (the loop's second cursor: 555 -> 60 together with the inlined reads
and 60 -> 0 with `guard_prefix_while`). The reload is also the form the loop pass sees as an increment of the field
itself. Whether a given compiler prefers it is a hypothesis for the judge; the checks below only keep the rewrite
faithful: a lvalue that is a plain field read (`p->head`, `a[i].f`, an m2c cast-and-offset), the lines between pure,
none of them naming the field (its last name or offset), and the local and the field one width (found from the
local's declaration and the field's in the source or `header`; unknown widths decline).

Children: one per such definition and store.
"""
import re

from .integer_repair_support import edit
from .line_scan import mentions, words
from .reload_temp_inline import _DEF, _Function, _pure

FAMILY = 'staged_store_first'
FAMILIES = (FAMILY,)
LIMIT = 6
_CAST_LVALUE = r'\(\*\((?P<type>[A-Za-z_][\w ]*?) \*\)\([^;=]*\)\)'
_MEMBER_LVALUE = r'[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[^\];=]+\])+'
_STORE = re.compile(rf'(?P<l>{_CAST_LVALUE}|{_MEMBER_LVALUE}) = (?P<t>[A-Za-z_]\w*);')
_WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
          'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned': 4, 'unsigned int': 4, 'long': 4,
          'unsigned long': 4}


def _width(name):
    return _WIDTH.get(' '.join(name.replace('*', ' *').split()))


def _local_width(fn, t):
    for k in fn.declarations:
        s = fn.body[k].stripped
        m = re.fullmatch(r'(?P<type>(?:[A-Za-z_]\w*[ \t]+)+?)\**[ \t]*(?P<names>[A-Za-z_]\w*(?:[ \t]*,[ \t]*\**[ \t]*[A-Za-z_]\w*)*);', s)
        if m and t in re.findall(r'[A-Za-z_]\w*', m['names']):
            return _width(m['type'].replace('register', '').strip())
    return None


def _member_width(lvalue, cast_type, text):
    if cast_type:
        return _width(cast_type)
    member = re.findall(r'[A-Za-z_]\w*', lvalue)[-1]
    found = {_width(m[1]) for m in re.finditer(rf'(?:^|[;{{])\s*((?:unsigned |signed )?[A-Za-z_]\w*)[ \t]+{re.escape(member)}[ \t]*;', text)}
    return found.pop() if len(found) == 1 else None


def _marker(lvalue):
    """The token another line would have to name to read the stored place."""
    tokens = re.findall(r'0[xX][0-9A-Fa-f]+|[A-Za-z_]\w*', lvalue)
    return tokens[-1] if tokens else None


def variants(source, name, header=''):
    fn = _Function(source, name)
    if not fn.ok:
        return []
    out = []
    body = fn.body
    for b, line in enumerate(body):
        store = _STORE.fullmatch(line.stripped)
        if not store or store['t'] not in fn.locals or not _pure(store['l']):
            continue
        t, lvalue = store['t'], store['l']
        marker = _marker(lvalue)
        a = b - 1
        while a >= 0 and not (_DEF.fullmatch(body[a].stripped) and _DEF.fullmatch(body[a].stripped)['t'] == t):
            if not fn.local_set(body[a].stripped, {t}) or marker is None or re.search(rf'\b{re.escape(marker)}\b', body[a].text) \
                    or any(mentions(body[a].text, w) for w in words(lvalue) if w in fn.assigned):
                a = -1
                break
            a -= 1
        if a < 0 or a == b - 1:
            continue
        definition = _DEF.fullmatch(body[a].stripped)
        if not _pure(definition['e']) or mentions(definition['e'], t):
            continue
        cast = re.fullmatch(_CAST_LVALUE, lvalue)
        width, wanted = _member_width(lvalue, cast['type'] if cast else None, source + '\n' + header), _local_width(fn, t)
        if width is None or width != wanted:
            continue
        indent = re.match(r'[ \t]*', body[a].source)[0]
        first = f'{indent}{lvalue} = {definition["e"]};\n{indent}{t} = {lvalue};\n'
        out.append((FAMILY, edit(source, [(body[a].start, body[a].end, first), (body[b].start, body[b].end, '')])))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
