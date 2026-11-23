"""A `volatile struct` of stack words with `#define` names for its members, written as plain locals.

An agent that wants an argument to live in a stack slot (the target loads it back with `lw $t0, 0x14($sp)` on every
pass of a loop) writes a scratch frame by hand:

    volatile struct { int unused; int filter; } stack;
    #define sp14 stack.filter

and assigns `sp14 = arg2;`. The frame's slot is right, but the `volatile` makes every access a load and a store the
compiler may not move or fold, and the `#define` hides the name from every family that reads a function's text
(`integer_repair_support.view` declines a body with a `#`, so no local family ran on the draft at all). GCC 2.x spills
a parameter that loses the register race to a slot like that without being asked, so the plain local is usually what
the game had. Measured on a 313-instruction display-list loop (KMC GCC 2.7.2, `-O2 -G0 -mips3`): 2165 with the
volatile frame, a chain of the library's families stuck there; 2155 with a plain `s32 sp14;`, and the same chain
(`gbi_macro_commands`, `statement_group_order`, `field_struct_view_printed`) reached 0 from it.

`variants` takes a function that declares such a struct inside its body, removes the declaration and the `#define`
lines that name its members, and declares each named member as a plain local of its own type (a member read as
`stack.field` without a name becomes `stack_field`). Members nothing names are padding and go. It declines a struct
whose address is taken, one with a member that is itself an aggregate, and a name used outside the function. It reads the
function's own `#define` lines, so it declares `directives` (registry.py): a caller that masks a function with a `#`
in it still runs it on the text as written. The exact judge decides whether the frame still comes out the same."""
import re

from .csource import find

FAMILY = 'volatile_stack_struct_drop'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_STRUCT = re.compile(rf'(?m)^(?P<indent>[ \t]*)volatile[ \t]+struct[ \t]*\{{(?P<fields>[^{{}}]*)\}}[ \t]*(?P<var>{_ID})[ \t]*;[ \t]*\n')
_DEFINE = re.compile(rf'(?m)^[ \t]*#[ \t]*define[ \t]+(?P<alias>{_ID})[ \t]+(?P<var>{_ID})[ \t]*\.[ \t]*(?P<field>{_ID})[ \t]*\n')
_FIELD = re.compile(rf'\s*(?P<type>[A-Za-z_][\w \t]*?)[ \t]+(?P<name>{_ID})[ \t]*$')


def _fields(text):
    """The members as (type, name) pairs, or None for anything but plain scalar members."""
    out = []
    for part in text.split(';'):
        if not part.strip():
            continue
        hit = _FIELD.fullmatch(part)
        if not hit or '*' in part or '[' in part or re.search(r'\b(?:struct|union)\b', part):
            return None
        out.append((' '.join(hit['type'].split()), hit['name']))
    return out or None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    hit = _STRUCT.search(text)
    if not hit:
        return []
    var = hit['var']
    members = _fields(hit['fields'])
    if not members:
        return []
    kinds = dict((field, kind) for kind, field in members)
    defines = {}
    for define in _DEFINE.finditer(text):
        if define['var'] == var and define['field'] in kinds:
            defines[define['alias']] = define
    rest = text[:hit.start()] + text[hit.end():]
    for define in defines.values():
        rest = rest.replace(define.group(0), '', 1)
    if re.search(rf'&\s*{re.escape(var)}\b', rest):
        return []
    plain = {}
    for alias, define in defines.items():
        plain[alias] = (kinds[define['field']], alias)
    direct = {}
    for use in re.finditer(rf'\b{re.escape(var)}\s*\.\s*({_ID})', rest):
        if use[1] not in kinds:
            return []
        direct[use[1]] = f'{var}_{use[1]}'
    if not plain and not direct:
        return []
    rest = re.sub(rf'\b{re.escape(var)}\s*\.\s*({_ID})', lambda use: direct[use[1]], rest)
    if re.search(rf'\b{re.escape(var)}\b', rest):
        return []
    for alias in plain:
        if re.search(rf'(?m)^[ \t]*#[ \t]*(?:define|undef)[ \t]+{re.escape(alias)}\b', rest) or re.search(rf'\b{re.escape(alias)}\b', source[:span[0]] + source[span[1]:]):
            return []
    declarations = ''.join(f"{hit['indent']}{kind} {alias};\n" for kind, alias in plain.values())
    declarations += ''.join(f"{hit['indent']}{kinds[field]} {local};\n" for field, local in direct.items())
    child = text[:hit.start()] + declarations + rest[hit.start():]
    return [(FAMILY, source[:span[0]] + child + source[span[1]:])]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 99, 'directives': True}  # the registry: no caller wiring (registry.py)
