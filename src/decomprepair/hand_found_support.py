"""What the hand-found families share: the target's instructions, `M2C_FIELD` accesses, and straight-line statements.

Four rewrites found by hand on a GCC 2.8.1 N64 project (`second_field_read`, `callback_pointer_local`,
`constant_minuend_split`, `cursor_load_modify_store` and `adjacent_store_swap`) read the same three things: the
target's assembly (to gate on what the original compiled to), a field access written `M2C_FIELD(base, T *, offset)`, and
the plain statements of a block. This module only reads text; it never compiles or judges.
"""
import re

from .arm_block_support import IDENT, NUMBER, brace_pairs, local_declaration, statements
from .integer_repair_support import split_args
from .line_scan import with_local
from .pattern_repairs import close

LOADS = {'lw', 'lh', 'lhu', 'lb', 'lbu', 'lwc1', 'lwl', 'lwr'}
STORES = {'sw', 'sh', 'sb', 'swc1', 'swl', 'swr'}
MEMORY = re.compile(rf'(?P<offset>-?{NUMBER})?\((?P<base>\$\w+)\)')
RELOCATED = re.compile(rf'%lo\(\s*(?P<symbol>{IDENT})\s*(?:\+\s*(?P<add>{NUMBER}))?[^)]*\)\((?P<base>\$\w+)\)')
HIGH = re.compile(rf'%hi\(\s*(?P<symbol>{IDENT})')
_FIELD_AT = re.compile(r'(?<![\w.>])M2C_FIELD\s*\(')
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
          'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'unsigned': 4, 'f32': 4, 'float': 4,
          's64': 8, 'u64': 8, 'f64': 8, 'double': 8}


def number(text):
    """An assembly or C integer (`0x80`, `-0x4`, `12`, with C suffixes) as a Python int."""
    text = re.sub(r'[uUlL]+$', '', text.strip())
    sign = -1 if text.startswith('-') else 1
    text = text.lstrip('+-')
    return sign * int(text, 16 if text.lower().startswith('0x') else 10)


def operands(text):
    """The comma-separated operands of an instruction, commas inside parentheses kept."""
    found, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if char == ',' and depth == 0:
            found.append(text[start:at].strip())
            start = at + 1
    if text[start:].strip():
        found.append(text[start:].strip())
    return found


def instructions(asm):
    """[(mnemonic, [operands])] of an assembly listing: labels, directives and the `/* ... */` address columns dropped."""
    found = []
    for line in (asm or '').splitlines():
        text = re.sub(r'/\*.*?\*/', ' ', line).strip()
        if not text or text.endswith(':') or text.startswith(('.', 'glabel', 'endlabel', 'dlabel', 'jlabel', 'enddlabel')):
            continue
        hit = re.match(r'(\S+)\s*(.*)', text)
        found.append((hit[1], operands(hit[2])))
    return found


def copy_source(op, args):
    """(destination, source) register of a register copy (`move`, `addu rd, rs, $zero`, `or rd, rs, $zero`, `mov.s`)."""
    if op in ('move', 'mov.s') and len(args) == 2:
        return args[0], args[1]
    if op in ('addu', 'or', 'daddu') and len(args) == 3:
        if args[2] == '$zero':
            return args[0], args[1]
        if args[1] == '$zero':
            return args[0], args[2]
    return None


def memory(operand):
    """(offset, base register) of `0x80($s0)`; None for anything else (a relocated operand included)."""
    hit = MEMORY.fullmatch(operand.strip())
    return (number(hit['offset']) if hit['offset'] else 0, hit['base']) if hit else None


def field_size(type_text):
    """Bytes of a field type as m2c writes it (`s32 *`, `void (**)(void)`): None when it is not one this reads."""
    text = ' '.join(type_text.split())
    if '(**)' in text:
        return 4
    hit = re.fullmatch(r'(.+?)\s*\*', text)
    if not hit:
        return None
    inner = hit[1].strip()
    return 4 if inner.endswith('*') else _SIZES.get(inner)


class Field:
    """One `M2C_FIELD(base, T *, offset)` in a function's blanked text: `start`/`end` span the whole access."""

    def __init__(self, start, end, base, kind, offset):
        self.start, self.end, self.base, self.kind, self.offset = start, end, base, kind, offset
        self.size = field_size(kind)

    def text(self, clean):
        return clean[self.start:self.end]

    def overlaps(self, other):
        return (self.size is None or other.size is None
                or not (self.offset + self.size <= other.offset or other.offset + other.size <= self.offset))


def fields(clean, lo=0, hi=None):
    """Every `M2C_FIELD(IDENT, T *, number)` in clean[lo:hi], in order; a field whose base is not a plain name is skipped."""
    hi = len(clean) if hi is None else hi
    found = []
    for hit in _FIELD_AT.finditer(clean, lo, hi):
        opening = hit.end() - 1
        closing = close(clean, opening)
        if not closing or closing > hi:
            continue
        parts = split_args(clean[opening + 1:closing - 1])
        if len(parts) != 3:
            continue
        base, kind, offset = (clean[opening + 1 + a:opening + 1 + b].strip() for a, b in parts)
        if not re.fullmatch(IDENT, base) or not re.fullmatch(NUMBER, offset):
            continue
        found.append(Field(hit.start(), closing, base, kind, number(offset)))
    return found


def blocks(part):
    """The `(lo, hi)` interiors of the function body and of every brace pair inside it."""
    pairs = brace_pairs(part.clean, part.opening, part.end) or {}
    return [(part.opening + 1, part.end - 1)] + [(a + 1, b) for a, b in sorted(pairs.items()) if a != part.opening]


def simple(text):
    """A statement that is one `;`-ended expression with no block, label or jump."""
    text = text.strip()
    return (text.endswith(';') and '{' not in text and '}' not in text
            and not re.match(r'(?:return|goto|break|continue|case|default|if|else|while|for|do|switch)\b', text)
            and not re.match(rf'{IDENT}\s*:(?!:)', text))


def calls_in(text, allow=('M2C_FIELD', 'sizeof')):
    """Names called in `text`, the macros m2c wraps fields in not counted."""
    return [name for name in re.findall(rf'(?<![\w.>])({IDENT})\s*\(', text) if name not in allow]


def store_target(text):
    """(lvalue text, value text) of `LVALUE = VALUE;` (a plain `=`), or None."""
    hit = re.fullmatch(r'\s*(?P<lvalue>[^=;]+?)\s*=(?!=)\s*(?P<value>[^;]*?)\s*;\s*', text)
    if not hit or re.search(r'[-+*/%&|^<>!]$', hit['lvalue']):
        return None
    return hit['lvalue'], hit['value']


def writes(text, name):
    """True when `text` assigns to, steps or takes the address of local `name` (a read-only use is False)."""
    n = re.escape(name)
    return bool(re.search(rf'(?<![\w.>]){n}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{n}\b|\b{n}\s*(?:\+\+|--)|&\s*{n}\b', text))


def mentions_of(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text)]


def fresh(name, taken, suffix):
    """`name_suffix` (with underscores added until it is a name nothing in `taken` uses)."""
    new = f'{name}_{suffix}'
    while new in taken:
        new += '_'
    return new


def declare(source, part, declarations):
    """An edit adding each of `declarations` (a list of `type name;`) after the leading declarations, or just inside the
    opening brace of a function that has none."""
    first = with_local(source, part, declarations[0])
    if not first:
        body = source[part.opening + 1:part.end - 1]
        indent = re.match(r'\s*?([ \t]*)\S', body)
        indent = indent[1] if indent else '    '
        first = (part.opening + 1, part.opening + 1, '\n' + indent + declarations[0])
    else:
        indent = re.match(r'\n([ \t]*)', first[2])[1]
    return first[0], first[1], first[2] + ''.join('\n' + indent + text for text in declarations[1:])


def declaring(kind, name):
    """`T name;` with a pointer type written the way m2c does (`T *name;`)."""
    kind = kind.strip()
    return f'{kind}{"" if kind.endswith("*") else " "}{name};'


def local_type(part, name):
    """The declared type text of local `name` (`s32`, `void *`), None when it is not a plain local of the function."""
    found = local_declaration(part.clean, part.opening, name)
    return (found[0] + (' ' if found[1] else '') + found[1]).strip() if found else None


def indentation(source, at):
    start = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[start:at])[0]


def stmts(part, lo, hi):
    return statements(part.clean, lo, hi)


__all__ = ['IDENT', 'NUMBER', 'LOADS', 'STORES', 'HIGH', 'RELOCATED', 'Field', 'fields', 'blocks', 'simple', 'calls_in',
           'copy_source', 'declare', 'declaring', 'field_size', 'fresh', 'indentation', 'instructions', 'local_type', 'memory',
           'mentions_of', 'number', 'operands', 'statements', 'store_target', 'stmts', 'writes']
