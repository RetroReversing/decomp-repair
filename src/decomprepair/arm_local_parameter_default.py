"""A local that only one arm of a test on a parameter assigns, given the parameter as its value on the other path.

m2c writes the pointer a function walks as a local that the test on the parameter sets in one arm only:

    if (arg1 == NULL) { ...; var_a1 = sp; ... }
    ... var_a1->field ...                       (read after the join)

On the path where the test fails the local was never set: the original program used the parameter itself there (the
caller's record), and m2c, which names the register `$a1` that is both the parameter and the local, never wrote the
copy. The program that compiled to the target reads the parameter's value into the local before the test:

    var_a1 = arg1;
    if (arg1 == NULL) { ...; var_a1 = sp; ... }

so the local has a value on every path and lives in `$a1` from the entry. A KMC GCC 2.7.2 N64 function
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 86 instructions, a local array whose address the null arm takes) kept the
parameter's pointer in `$a1`, the loop counter in `$a2` and the record copy in `$a3`; the draft without the copy had
`$a3`, `$a1`, `$a2` (75 rows -> 0 with the copy). Where the copy goes matters: the same assignment as `else { var_a1 =
arg1; }` after the arm scored 560 (hypothesis, not checked in the compiler's source: an assignment in an arm of its own
is a second set of the pseudo that starts its live range after the test, where the copy before the test makes the
pseudo live from the entry, the parameter's own register).

`variants`, for each parameter the body never writes (no assignment, increment or `&`) and each local of the same type
declared without an initialiser that is neither assigned nor read before the test, takes each `if (cond) { ... }` (a
braced then arm; no `else if`) whose condition names the parameter and not the local, whose then arm assigns the local
(and whose other arm, if any, does not), when the local is not assigned anywhere else and is read after the join. Three
children each: `local = param;` right before the `if`, the declaration given the parameter as its initialiser, and
`local = param;` as the other arm (a new `else { }`, or the start of the existing one). At most 9 children."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'arm_local_parameter_default'
FAMILIES = (FAMILY,)
LIMIT = 9
_IF = re.compile(r'(?<![\w.])if\s*\(')
_ELSE = re.compile(r'\s*else\s*\{')
_KEYWORDS = {'return', 'goto', 'break', 'continue', 'if', 'else', 'while', 'do', 'for', 'switch', 'case', 'default',
             'sizeof', 'typedef', 'extern', 'static'}
_TYPE = rf'(?P<type>(?:(?:const|volatile|unsigned|signed|struct|union|enum)\s+)*{IDENT}(?:\s+{IDENT})*?)'


def _shape(words, stars):
    return re.sub(r'\s+', ' ', words).strip(), stars.count('*')


def _parameters(part):
    """{name: shape} of the definition's parameters (type words, number of stars)."""
    head = part.clean[:part.opening]
    if '(' not in head or ')' not in head:
        return {}
    out = {}
    for piece in head[head.rindex('(') + 1:head.rindex(')')].split(','):
        found = re.fullmatch(rf'\s*{_TYPE}\s*(?P<stars>[\s*]*)(?P<name>{IDENT})\s*', piece)
        if found and found['type'] not in _KEYWORDS:
            out[found['name']] = _shape(found['type'], found['stars'])
    return out


def _locals(clean, body_at, body_end):
    """[(name, shape, start of the declaration, end of it)] of the plain `T *name;` declarations at the body's top."""
    out = []
    for hit in re.finditer(rf'(?m)^[ \t]*{_TYPE}\s*(?P<stars>[\s*]*)(?P<name>{IDENT})\s*;', clean[body_at:body_end]):
        if hit['type'].split()[0] in _KEYWORDS or clean[body_at:body_end][:hit.start()].count('{') != \
                clean[body_at:body_end][:hit.start()].count('}'):
            continue
        out.append((hit['name'], _shape(hit['type'], hit['stars']), body_at + hit.start('name'), body_at + hit.end()))
    return out


def _uses(text, name, start=0, end=None):
    return [start + hit.start() for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text[start:end])]


def _assigns(text, name, start=0, end=None):
    return [start + hit.start() for hit in
            re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text[start:end])]


def _written(body, parameter):
    name = re.escape(parameter)
    return bool(re.search(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body)
                or re.search(rf'(?:\+\+|--)\s*{name}\b|(?<![\w.>]){name}\s*(?:\+\+|--)', body)
                or re.search(rf'&\s*{name}\b(?!\s*[-.\[])', body))


def _line_start(clean, at):
    return clean.rfind('\n', 0, at) + 1


def variants(source, name):
    """Proposals: a local set in one arm of a test on a parameter, given the parameter's value on every path."""
    part = view(source, name)
    if not part:
        return []
    clean, body_at = part.clean, part.opening + 1
    body = clean[body_at:part.end]
    parameters = _parameters(part)
    if not parameters:
        return []
    out = []
    for local, shape, name_at, decl_end in _locals(clean, body_at, part.end):
        if local in parameters:
            continue
        for parameter, kind in parameters.items():
            if kind != shape or _written(body, parameter) or not _uses(body, parameter):
                continue
            for hit in _IF.finditer(clean, decl_end, part.end):
                if re.search(r'\belse\s*$', clean[body_at:hit.start()]):
                    continue
                condition_end = close(clean, hit.end() - 1, '(', ')')
                if not condition_end:
                    continue
                condition = clean[hit.end():condition_end - 1]
                if not _uses(condition, parameter) or _uses(condition, local):
                    continue
                then_open = re.match(r'\s*\{', clean[condition_end:])
                if not then_open:
                    continue
                then_at = condition_end + then_open.end() - 1
                then_end = close(clean, then_at, '{', '}')
                if not then_end or not _assigns(clean, local, then_at, then_end):
                    continue
                other = _ELSE.match(clean, then_end)
                else_end = close(clean, other.end() - 1, '{', '}') if other else None
                if other and not else_end:
                    continue
                join = else_end or then_end
                if re.match(r'\s*else\b', clean[join:]) or (not other and re.match(r'\s*else\b', clean[then_end:])):
                    continue  # an `else if` / unbraced else: not every path is seen
                arms = [(then_at, then_end)] + ([(other.end() - 1, else_end)] if other else [])
                inside = sum(len(_assigns(clean, local, a, b)) for a, b in arms[:1])
                if len(_assigns(clean, local, decl_end)) != inside:
                    continue  # assigned elsewhere (the other arm, before or after the join)
                if _uses(clean, local, decl_end, hit.start()) or not _uses(clean, local, join, part.end):
                    continue
                line = _line_start(clean, hit.start())
                indent = re.match(r'[ \t]*', clean[line:]).group()
                before = clean[line:hit.start()].strip()
                if before:
                    continue  # the `if` shares its line with other code
                out.append(edit(source, [(line, line, f'{indent}{local} = {parameter};\n')]))
                out.append(edit(source, [(decl_end - 1, decl_end - 1, f' = {parameter}')]))
                if other:
                    out.append(edit(source, [(other.end(), other.end(), f'\n{indent}    {local} = {parameter};')]))
                else:
                    out.append(edit(source, [(then_end, then_end,
                                              f' else {{\n{indent}    {local} = {parameter};\n{indent}}}')]))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
