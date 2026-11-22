"""A sub-expression held in a temporary: declared local, assigned before its statement, used in its place.

The step that finished three of the small stalls in a whole-path audit of a KMC GCC 2.7.2 N64 game (`-G0 -mips3 -mgp32
-mfp32 -O2`): `return (x + (D + 0xFFFC)) & 0xFFFF;` written `t = D + 0xFFFC; return (x + t) & 0xFFFF;`, a pre-decremented
value held in a temporary and used once. m2c prints every intermediate as a local already, so the original's
*absence* of one is what other families undo (`local_inline_repairs`); this is the other direction, for code that
was written without the temporary. gcc 2.x numbers a pseudo per declared local and expands the temporary's
assignment where it is written, so holding a value in one changes which values live across a statement, the register
the allocator hands it, and where the scheduler may move the instructions around it. The judge says which.

Offered, for each statement (an expression statement, a `return`, an `if`'s condition) that sits directly in a block,
and for each sub-expression of it that is worth naming (an arithmetic, shift or bitwise operation, a cast, a negation,
a load through a pointer, an index or a member), repeated or not:

- `temporary_hoist`: the temporary declared with the function's locals, assigned right before the statement, and used
  in every place the expression occurs in that statement; and, when it occurs more than once there, only in the
  first. A run that continues into the following statements of the same block, for as long as none of them changes
  anything the expression reads, is one more child;
- `temporary_hoist_block`: the same, with the temporary declared at the head of the block the statement is in (gcc
  numbers a block's declarations when the block is entered, so the pseudo is numbered later);
- `temporary_hoist_pair`: two operands of an associative chain held in a temporary and the chain written with it
  (`x + D + 0xFFFC` -> `t = D + 0xFFFC; ... x + t`), only where the regrouping is the same value (`expression_terms.
  exact_regrouping`).

The temporary has the expression's own C type, so the value is the same: its operands are free of calls, assignments
and `volatile` names, it is not under the right side of `&&`, `||` or a `?:` arm (a load there may be guarded), and
when the statement calls a function, only an expression of plain locals (not address-taken) is held. Names the
function or its header don't type, a macro, a plain `char`, a struct by value, are left alone.
"""
import re

from .expression_terms import Node, Types, bare, chain, exact_regrouping, key, names, parse, pure, render, sites

FAMILY = 'temporary_hoist'
FAMILIES = ('temporary_hoist', 'temporary_hoist_block', 'temporary_hoist_pair')
LIMIT = 48
HOISTED = ('+', '-', '*', '/', '%', '<<', '>>', '&', '|', '^')
STATEMENTS = ('expr', 'return', 'if')


def _fresh(source):
    used = set(re.findall(r'[A-Za-z_]\w*', source))
    if 'temp' not in used:
        return 'temp'
    n = 2
    while f'temp{n}' in used:
        n += 1
    return f'temp{n}'


def _loads(node):
    return any(n.kind in ('index', 'member') or (n.kind == 'unary' and n.op == '*') for n in node.walk())


class _Statement:
    """A site's expression and what it does: its tree, its top-level assignment, whether it calls or has side effects."""

    def __init__(self, site, root):
        self.site, self.root = site, root
        top = bare(root)
        self.top = top if top.kind == 'assign' else None
        inner = [n for n in root.walk() if n is not self.top]
        self.has_call = any(n.kind == 'call' for n in inner)
        self.effects = (any(n.kind in ('assign', 'postfix', 'comma') for n in inner)
                        or any(n.kind == 'unary' and n.op in ('++', '--') for n in inner))
        self.target = bare(self.top.kids[0]) if self.top else None

        self.parents = {id(kid): n for n in root.walk() for kid in n.kids}
        self.protected = {id(bare(n.kids[0])) for n in root.walk() if n.kind == 'unary' and n.op == '&'}
        if self.target is not None:
            self.protected.add(id(self.target))

    def outer(self, node):
        """The node with the parentheses around it: replacing `(a + b)` by a name leaves no `(temp)`."""
        parent = self.parents.get(id(node))
        while parent is not None and parent.kind == 'paren':
            node, parent = parent, self.parents.get(id(parent))
        return node

    def clobbers(self, dependencies, register_pure, local_names):
        """Does the statement, once evaluated, change something an expression over `dependencies` reads?"""
        if self.target is None:
            return False
        if self.target.kind == 'id':
            return self.target.op in dependencies or not register_pure and self.target.op not in local_names
        return not register_pure


def _candidates(statement, types, source):
    """The sub-expressions of the statement that may be held: (node, register_pure) in document order."""
    found = []
    taken = set(re.findall(r'&\s*([A-Za-z_]\w*)', source[types.body_start:types.body_end]))

    def eligible(node):
        if node.kind not in ('binary', 'cast', 'unary', 'index', 'member'):
            return None
        if node.kind == 'binary' and node.op not in HOISTED:
            return None
        if node.kind == 'unary' and node.op not in ('-', '~', '*'):
            return None
        ids = names(node)
        if not pure(node) or not ids:
            return None
        if ids & types.volatile or any(n.kind == 'member' and n.info in types.volatile for n in node.walk()):
            return None
        ty = types.of(node)
        if ty is None or ty.kind not in ('int', 'float', 'ptr') or (ty.kind == 'ptr' and ty.target is None):
            return None
        register_pure = not _loads(node) and all(i in types.locals and i not in taken for i in ids)
        if statement.has_call and not register_pure:
            return None
        return register_pure

    def visit(node, guarded):
        if node.kind == 'paren':
            visit(node.kids[0], guarded)
            return
        if node is statement.top:
            for kid in bare(node.kids[0]).kids:
                visit(kid, guarded)
            visit(node.kids[1], guarded)
            return
        if node.kind in ('sizeof', 'str', 'num', 'id'):
            return
        if node.kind == 'unary' and node.op == '&':
            return
        if node.kind == 'binary' and node.op in ('&&', '||'):
            visit(node.kids[0], guarded)
            visit(node.kids[1], True)
            return
        if node.kind == 'cond':
            visit(node.kids[0], guarded)
            visit(node.kids[1], True)
            visit(node.kids[2], True)
            return
        if not guarded:
            register_pure = eligible(node)
            if register_pure is not None:
                found.append((node, register_pure))
        for kid in node.kids[1:] if node.kind == 'call' else node.kids:
            visit(kid, guarded)

    visit(statement.root, False)
    return found


def _line_indent(source, position):
    line = source.rfind('\n', 0, position) + 1
    prefix = source[line:position]
    return prefix if not prefix.strip() else None


def _declaration_edit(source, types, sites, block, tmp, ty):
    """(start, end, text) that declares the temporary after the leading declarations of `block`."""
    text = f'{ty.spelling}{tmp}' if ty.spelling.endswith('*') else f'{ty.spelling} {tmp}'
    last = None
    for site in sites:
        if site.block != block:
            continue
        if not site.declaration:
            break
        if site.kind == 'declaration':
            last = site
    if last is not None:
        indent = _line_indent(source, last.start)
        return last.end + 1, last.end + 1, f'\n{indent if indent is not None else "  "}{text};'
    first = next((s for s in sites if s.block == block), None)
    indent = _line_indent(source, first.start) if first else None
    return block + 1, block + 1, f'\n{indent if indent is not None else "  "}{text};'


def _apply(source, edits):
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _assignment(source, site, tmp, expression):
    indent = _line_indent(source, site.statement)
    return (site.statement, site.statement, f'{tmp} = {expression};\n{indent}' if indent is not None
            else f'{tmp} = {expression}; ')


def variants(source, name, header='', int_bits=None):
    """(family, source) for each held sub-expression; see the module's docstring."""
    if int_bits not in (None, 32):
        return []
    types = Types(source, name, header)
    if not types.ok:
        return []
    all_sites = sites(source, types)
    statements = {}
    for site in all_sites:
        if site.kind in STATEMENTS or site.kind == 'init':
            root = parse(source, site.start, site.end, types.typedefs)
            if root is not None:
                statements[site.index] = _Statement(site, root)
    tmp = _fresh(source)
    result, seen = [], {source}

    def add(label, text):
        if text not in seen:
            seen.add(text)
            result.append((label, text))

    for site in all_sites:
        statement = statements.get(site.index)
        if site.kind not in STATEMENTS or statement is None or site.statement is None or statement.effects:
            continue
        groups = {}
        for node, register_pure in _candidates(statement, types, source):
            groups.setdefault(key(node), []).append((node, register_pure))
        function_block = types.body_start
        for occurrences in groups.values():
            first, register_pure = occurrences[0]
            ty = types.of(first)
            expression = source[first.start:first.end]
            nodes = [n for n, _ in occurrences]
            hold = _assignment(source, site, tmp, expression)
            uses = [(o.start, o.end, tmp) for o in (statement.outer(n) for n in nodes)]
            decl = _declaration_edit(source, types, all_sites, function_block, tmp, ty)
            add('temporary_hoist', _apply(source, [decl, hold] + uses))
            if site.block != function_block:
                block_decl = _declaration_edit(source, types, all_sites, site.block, tmp, ty)
                add('temporary_hoist_block', _apply(source, [block_decl, hold] + uses))
            if len(nodes) > 1:
                add('temporary_hoist', _apply(source, [decl, hold, uses[0]]))
            run = _run(source, types, all_sites, statements, site, statement, first, register_pure, tmp)
            if run:
                add('temporary_hoist', _apply(source, [decl, hold] + uses + run))
        for sibling in _pairs(source, types, statement, tmp):
            expression, replacement, ty = sibling
            decl = _declaration_edit(source, types, all_sites, function_block, tmp, ty)
            hold = _assignment(source, site, tmp, expression)
            add('temporary_hoist_pair', _apply(source, [decl, hold, replacement]))
    return result[:LIMIT]


def _run(source, types, all_sites, statements, site, statement, node, register_pure, tmp):
    """Edits that use the temporary in the following statements of the block too, or [] when none has the expression."""
    dependencies = names(node)
    if statement.clobbers(dependencies, register_pure, types.locals):
        return []
    wanted = key(node)
    edits = []
    for later in all_sites:
        if later.index <= site.index:
            continue
        if later.block != site.block or later.kind not in STATEMENTS or later.labeled or later.statement is None:
            break
        other = statements.get(later.index)
        if other is None or other.effects or (other.has_call and not register_pure):
            break
        for n in other.root.walk():
            if n.kind == node.kind and id(n) not in other.protected and key(n) == wanted:
                edits.append((other.outer(n).start, other.outer(n).end, tmp))
        if other.clobbers(dependencies, register_pure, types.locals):
            break
    return _outermost(edits)


def _outermost(edits):
    kept = []
    for edit in sorted(edits):
        if not kept or edit[0] >= kept[-1][1]:
            kept.append(edit)
    return kept


def _pairs(source, types, statement, tmp):
    """(expression, edit, type): two operands of an exact chain held, the chain rewritten with the temporary."""
    found, covered = [], set()
    for node in statement.root.walk():
        if node.kind != 'binary' or id(node) in covered:
            continue
        info = chain(node)
        if info is None:
            continue
        covered.update(id(n) for n in _spine(node))
        op, operands, shape = info
        if len(operands) < 3 or len(operands) > 5 or not exact_regrouping(types, op, operands):
            continue
        if statement.has_call and not all(not _loads(o) and names(o) <= types.locals for o in operands):
            continue
        if any(names(o) & types.volatile for o in operands):
            continue
        texts = [source[o.start:o.end] for o in operands]
        for i in range(len(operands)):
            for j in range(i + 1, len(operands)):
                pair = Node('binary', op, [operands[i], operands[j]], operands[i].start, operands[j].end)
                ty = types.of(pair)
                if ty is None or ty.kind not in ('int', 'ptr') or (ty.kind == 'ptr' and ty.target is None):
                    continue
                rest = [k for k in range(len(operands)) if k != j]
                held = [tmp if k == i else texts[k] for k in rest]
                spine = 0
                for n in range(1, len(held)):
                    spine = (spine, n)
                text = render(spine if len(held) > 1 else 0, held, op)
                found.append((f'{texts[i]} {op} {texts[j]}', (node.start, node.end, text), ty))
    return found


def _spine(node):
    """The same-operator nodes a chain flattens, the root first."""
    yield node
    for kid in node.kids:
        inner = bare(kid)
        if inner.kind == 'binary' and inner.op == node.op:
            yield from _spine(inner)
