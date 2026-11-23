"""m2c's saved floating-point condition (`var_condition_bit`) written as the comparison where it is tested.

m2c names the result of a MIPS `c.lt.s`/`c.le.s` compare that is read after other code `condition_bit`: the draft says
`var_condition_bit = var_fs0 > 0.0f;` in one place and `if (var_condition_bit)` further down. A local that holds a
comparison is a value the compiler has to produce in a register (`bc1t` over `addiu $a2, $zero, 1`, a second `move`,
a repeated `c.lt.s`), where the game compared at the test itself: the target has one `c.lt.s` in front of the branch.
Matched on a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) player-update routine of 1137 instructions: with the two
assignments and the `if` rewritten to `if (var_fs0 > 0.0f)` the score went 3871 -> 2651 (the `bc1t`, `move`, `addiu`
and extra `c.lt.s` rows were gone; one step of a chain that ended at 0 but for two scheduling rows).

condition_bit_inline
    Every `V = EXPR;` (V a local whose name contains `condition_bit`) is dropped and every `if (V)` / `if (!V)`
    becomes `if (EXPR)` / `if (!(EXPR))`, when all the assignments write the same side-effect-free EXPR, the only
    other mention of V is its declaration, and none of EXPR's names is written between the first assignment and the
    last test (a plain `=`, a compound assignment, `++`/`--` or `&name`). A `label:` left holding nothing gets an empty
    statement. One child per local.

Hypothesis from the match (not from the compiler source): a comparison kept in an `int` local is expanded to its own
store-flag sequence before the branch that tests it. The exact judge decides every child."""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'condition_bit_inline'
FAMILIES = (FAMILY,)
LIMIT = 4
_KEYWORDS = frozenset({'if', 'else', 'sizeof', 'u8', 's8', 'u16', 's16', 'u32', 's32', 'f32', 'f64', 'int', 'char', 'short',
                       'unsigned', 'signed', 'float', 'double', 'long', 'void', 'NULL'})
_NAME = re.compile(rf'(?<![\w.>])({IDENT}\w*condition_bit\w*|condition_bit\w*)\b')


def _squash(text):
    return re.sub(r'\s+', ' ', text).strip()


def _plain(expr):
    """True for a comparison or arithmetic over names and literals: no call, store, increment or address."""
    if re.search(rf'{IDENT}\s*\(|\+\+|--|[^=!<>]=(?!=)|(?<![&])&(?!&)|\?|,|\[|\bvolatile\b', expr):
        return False
    return True


def _written(name, text):
    store = re.search(rf'(?<![\w.>])(?:\*\s*)?{re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text)
    return bool(store or re.search(rf'(?:\+\+|--)\s*{re.escape(name)}\b|\b{re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', text))


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    body_start, body_end = part.opening + 1, part.end - 1
    for var in sorted(set(_NAME.findall(clean, body_start, body_end))):
        mention = re.compile(rf'(?<![\w.>]){re.escape(var)}\b')
        assigns = list(re.compile(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)\s*(?P<expr>[^;{{}}]+?)\s*;').finditer(clean, body_start, body_end))
        tests = list(re.compile(rf'\bif\s*\(\s*(?P<not>!\s*)?{re.escape(var)}\s*\)').finditer(clean, body_start, body_end))
        declared = list(re.finditer(rf'^[ \t]*(?:u8|s8|u16|s16|u32|s32|int|char|short|unsigned|signed)[ \t]+{re.escape(var)}[ \t]*;[ \t]*\n?',
                                    clean[body_start:body_end], re.M))
        if not assigns or not tests:
            continue
        exprs = {_squash(a['expr']) for a in assigns}
        if len(exprs) != 1:
            continue
        expr = assigns[0]['expr'].strip()
        if not _plain(expr):
            continue
        counted = len(assigns) + len(tests) + len(declared)
        if len(mention.findall(clean, body_start, body_end)) != counted:
            continue
        first, last = assigns[0].start(), max(t.end() for t in tests)
        names = {n for n in re.findall(IDENT, expr) if n not in _KEYWORDS and not re.fullmatch(r'\d\w*', n)}
        between = clean[first:last]
        # a test above the first assignment would read an earlier value of V
        if any(t.start() < first for t in tests) or any(_written(n, _squash(between).replace(_squash(expr), ' ')) for n in names):
            continue
        edits = []
        for assign in assigns:
            start, end = assign.start(), assign.end()
            line = source.rfind('\n', 0, start) + 1
            tail = source.find('\n', end)
            tail = len(source) if tail < 0 else tail + 1
            if source[line:start].strip() or source[end:tail].strip():
                edits.append((start, end, ';'))
            elif re.search(r'(?<![?:])\b\w+\s*:\s*$', source[:line]):  # a label would end the block
                edits.append((start, end, ';'))
            else:
                edits.append((line, tail, ''))
        for test in tests:
            edits.append((test.start(), test.end(), f'if (!({expr}))' if test['not'] else f'if ({expr})'))
        for decl in declared:
            edits.append((body_start + decl.start(), body_start + decl.end(), ''))
        child = source
        for start, end, text in sorted(edits, reverse=True):
            child = child[:start] + text + child[end:]
        if child != source and var not in child[child.find(name):]:
            out.append((FAMILY, child))
    return out[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
