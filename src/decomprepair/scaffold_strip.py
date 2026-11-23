"""A search-made draft written back as plain code: its scaffolding stripped in one child.

A saved best that a long search or a draft chain improved piles up shapes nobody wrote: a union that shares one
register between a pointer and an integer, an `if (x) { S } else { S }` that only keeps `x` alive, an identity inline
function around a cast, a `register` parameter, a `(long long)` index, a copy of `(u8) group` made early and read two
branches later, three locals that each hold that same byte, word-sized locals that every use truncates. Each of those
edits is neutral or worse on its own (145 -> 485 -> 385 -> ... -> 240 on a 129-instruction linked-list insertion,
`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), so a greedy chain never takes the first step, and the plain program they
add up to is where the next families (`loop_invariant_key_copy`, `pure_preheader_order`: 240 -> 50 -> 0) start.

`strip` applies them together, each only where it provably keeps the program's meaning (a small reaching-definition
analysis of structured C: no `goto`, `switch`, nested declarations or address-taken locals):
  * a union with a brace initializer or plain members becomes one local per member (`phase_storage_split`);
  * `if (c) { S } else { S }` becomes `S` (`identical_arm_collapse`);
  * `register` on a parameter, `(long long)` / `(s64)` around an index, and a call of an identity inline function go;
  * a read of a local that every reaching assignment set to the same pure expression (`(u8) group`, its operands
    unchanged since) is written as that expression when it is an array index; the assignments nothing reads any more go;
  * a local read once, set once to such an expression, is written at its use;
  * a local still read as a value is set once, right before the first statement that reads it (inside the branch when
    every read is there), not at its first assignment;
  * a word local that every use truncates to a narrow type, or that only ever holds such a value, takes that type.
`variants` offers the stripped function (`scaffold_strip`) and the stripped function with each child of
`loop_invariant_key_copy` on it (`scaffold_strip_key_copy`), the combination that matched the function above (the
steps are measured separately in the test). Every rule is a hypothesis about how the original was written, not a
statement about the compiler; the exact judge decides."""
import re

from . import (
    identical_arm_collapse_repairs,
    loop_invariant_key_copy,
    phase_storage_split_repairs,
)
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'scaffold_strip'
COMBINED = 'scaffold_strip_key_copy'
FAMILIES = (FAMILY, COMBINED)
ROUNDS = 6

TYPE = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|long\s+long|[su](?:8|16|32|64)|int|short|char|long)'
NARROW = {'u8': 8, 's8': 8, 'char': 8, 'unsigned char': 8, 'signed char': 8,
          'u16': 16, 's16': 16, 'short': 16, 'unsigned short': 16, 'signed short': 16}
CAST = re.compile(rf'\(\s*({TYPE})\s*\)')
KEYWORD = {'if', 'else', 'for', 'while', 'do', 'return', 'break', 'continue', 'goto', 'switch', 'case', 'default',
           'sizeof', 'void', 'static', 'extern', 'register', 'const', 'volatile', 'struct', 'union', 'typedef'}
DECLARATION = re.compile(rf'(?:(?:register|const)\s+)*(?P<type>{TYPE}|{IDENT})(?P<stars>[\s*]+)(?P<name>{IDENT})\s*(?P<rest>=[^;]*|\[[^;]*)?$')


class Unsupported(Exception):
    pass


class Node:
    def __init__(self, kind, start, end, parent=None):
        self.kind, self.start, self.end, self.parent = kind, start, end, parent
        self.kids = []
        self.index = 0

    def path(self):
        node, out = self, []
        while node:
            out.append(node)
            node = node.parent
        return out[::-1]


# ---------------------------------------------------------------- parsing

def _skip(clean, i, end):
    while i < end and clean[i].isspace():
        i += 1
    return i


def _word(clean, i):
    m = re.compile(r'[A-Za-z_]\w*').match(clean, i)
    return m[0] if m else ''


def _statement(clean, i, end, parent):
    i = _skip(clean, i, end)
    if i >= end:
        raise Unsupported('end')
    if clean[i] == '{':
        stop = close(clean, i, '{', '}')
        if not stop or stop > end:
            raise Unsupported('block')
        node = Node('block', i, stop, parent)
        j = i + 1
        while True:
            j = _skip(clean, j, stop - 1)
            if j >= stop - 1:
                break
            kid, j = _statement(clean, j, stop - 1, node)
            kid.index = len(node.kids)
            node.kids.append(kid)
        return node, stop
    if clean[i] == ';':
        return Node('empty', i, i + 1, parent), i + 1
    word = _word(clean, i)
    if word in {'goto', 'switch', 'case', 'default'}:
        raise Unsupported(word)
    if word == 'if':
        head = clean.index('(', i)
        after = close(clean, head)
        node = Node('if', i, i, parent)
        node.cond = (head + 1, after - 1)
        then, j = _statement(clean, after, end, node)
        node.kids = [then]
        k = _skip(clean, j, end)
        if _word(clean, k) == 'else':
            other, j = _statement(clean, k + 4, end, node)
            node.kids.append(other)
        node.end = j
        return node, j
    if word in {'for', 'while'}:
        head = clean.index('(', i)
        after = close(clean, head)
        node = Node(word, i, i, parent)
        node.cond = (head + 1, after - 1)
        body, j = _statement(clean, after, end, node)
        node.kids = [body]
        node.end = j
        return node, j
    if word == 'do':
        node = Node('do', i, i, parent)
        body, j = _statement(clean, i + 2, end, node)
        node.kids = [body]
        tail = re.compile(r'\s*while\s*\(').match(clean, j)
        if not tail:
            raise Unsupported('do')
        after = close(clean, tail.end() - 1)
        node.cond = (tail.end(), after - 1)
        semi = clean.index(';', after)
        node.end = semi + 1
        return node, semi + 1
    stop = i
    depth = 0
    while stop < end:
        c = clean[stop]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '{':
            raise Unsupported('initializer')
        elif c == ';' and depth == 0:
            break
        stop += 1
    if stop >= end:
        raise Unsupported('semicolon')
    kind = word if word in {'return', 'break', 'continue'} else 'simple'
    return Node(kind, i, stop + 1, parent), stop + 1


# ---------------------------------------------------------------- the analysis

class Read:
    def __init__(self, var, start, end, node, index, cast, state, ops):
        self.var, self.start, self.end, self.node = var, start, end, node
        self.index, self.cast, self.state, self.ops = index, cast, state, ops


class Def:
    def __init__(self, ident, var, node, expr, span, ops, declared):
        self.ident, self.var, self.node, self.expr, self.span, self.ops, self.declared = ident, var, node, expr, span, ops, declared


class Analysis:
    def __init__(self, source, name):
        part = view(source, name)
        if not part or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp|volatile)\b|(?m:^\s*#)', part.body):
            raise Unsupported('view')
        self.source, self.clean, self.part = source, part.clean, part
        signature = re.search(r'\(([^{};]*)\)\s*$', part.clean[:part.opening])
        self.params = []
        for piece in (signature[1] if signature else '').split(','):
            found = re.search(rf'({IDENT})\s*$', piece.strip())
            if found and piece.strip() not in ('void', ''):
                self.params.append(found[1])
        self.locals, self.types, self.escaped = {}, {}, set()
        self.defs, self.reads, self.count = [], [], 0
        self.root, _ = _statement(self.clean, part.opening, part.end, None)
        self.tracked = set(self.params)
        self._declarations(self.root)
        self.loops = []
        state = {p: frozenset({('entry', p)}) for p in self.params}
        for v in self.locals:
            state[v] = frozenset({('undef', v)})
        self.node_reads = {}
        self._block_walk(self.root, state)

    # declarations are only accepted at the top of the function body
    def _declarations(self, root):
        for kid in root.kids:
            if kid.kind != 'simple':
                continue
            text = self.clean[kid.start:kid.end - 1].strip()
            m = DECLARATION.match(text)
            if m and m['type'] not in KEYWORD and not re.match(r'(?:return)\b', text):
                kind = re.sub(r'^(?:register|const)\s+', '', text[:m.start('name')]).strip()
                self.locals[m['name']] = kid
                self.types[m['name']] = re.sub(r'\s+', ' ', kind.replace('*', ' * ')).strip()
                self.tracked.add(m['name'])
        self.pointer = {v for v, t in self.types.items() if '*' in t or not re.fullmatch(TYPE, t)}

    def _names(self, text, base):
        for m in re.finditer(IDENT, text):
            if m[0] in self.tracked and not (m.start() and text[m.start() - 1] in '.>' and text[max(0, m.start() - 2):m.start()] in ('->', '. ', ' .')) \
                    and text[max(0, m.start() - 1):m.start()] != '.' and text[max(0, m.start() - 2):m.start()] != '->':
                yield m[0], base + m.start(), base + m.end()

    def _expression(self, start, end, node, state):
        """Record the reads of tracked names in clean[start:end] (an expression with no assignment of a local)."""
        text = self.clean[start:end]
        if self.tracked and re.search(rf'(?<![\w.>\]])(?:{"|".join(map(re.escape, self.tracked))})\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text):
            raise Unsupported('assignment in expression')
        for var, a, b in self._names(text, start):
            before = self.clean[max(start, a - 40):a]
            if re.search(r'&\s*$', before) and not re.search(r'&\s*&\s*$', before):
                self.escaped.add(var)
            if re.match(r'\s*(?:\+\+|--)', self.clean[b:b + 3]) or re.search(r'(?:\+\+|--)\s*$', before):
                raise Unsupported('increment')
            brackets = re.search(r'\[\s*((?:\(\s*[^()]*\)\s*)*)$', before)
            tail = re.match(r'\s*\]', self.clean[b:b + 5])
            index = bool(brackets and tail)
            cast = None
            c = re.search(rf'\(\s*({TYPE})\s*\)\s*$', before)
            if c:
                cast = re.sub(r'\s+', ' ', c[1])
            ops = {v: state.get(v) for v in self.tracked}
            self.reads.append(Read(var, a, b, node, index, cast, state.get(var), ops))

    def _simple(self, node, state):
        clean = self.clean
        text = clean[node.start:node.end - 1]
        stripped = text.strip()
        lead = node.start + (len(text) - len(text.lstrip()))
        m = DECLARATION.match(stripped)
        if node.kind == 'simple' and m and m['name'] in self.locals and self.locals[m['name']] is node:
            rest = m['rest']
            if rest and rest.startswith('='):
                var = m['name']
                span = (lead + m.start('rest') + 1, node.end - 1)
                self._expression(span[0], span[1], node, state)
                return self._define(node, var, span, state, declared=True)
            return state
        if node.kind == 'simple' and m and m['type'] not in KEYWORD:
            raise Unsupported('nested declaration')
        a = re.match(rf'\s*({IDENT})\s*=(?!=)', text)
        if a and a[1] in self.tracked:
            var = a[1]
            span = (node.start + a.end(), node.end - 1)
            self._expression(span[0], span[1], node, state)
            return self._define(node, var, span, state)
        compound = re.match(rf'\s*({IDENT})\s*(?:[-+*/%&|^]|<<|>>)=', text)
        if compound and compound[1] in self.tracked:
            self._expression(node.start, node.end - 1, node, state)
            return self._define(node, compound[1], None, state)
        if re.search(rf'(?<![\w.>])({"|".join(re.escape(v) for v in self.tracked) or "$^"})\s*(?:\+\+|--)|(?:\+\+|--)\s*(?:{"|".join(re.escape(v) for v in self.tracked) or "$^"})\b', text):
            raise Unsupported('increment')
        self._expression(node.start, node.end - 1, node, state)
        return state

    def _define(self, node, var, span, state, declared=False):
        self.count += 1
        ident = ('def', self.count)
        expr = self.clean[span[0]:span[1]].strip() if span else None
        ops = {v: state.get(v) for v in self.tracked}
        self.defs.append(Def(ident, var, node, expr, span, ops, declared))
        new = dict(state)
        new[var] = frozenset({ident})
        return new

    @staticmethod
    def _merge(states):
        states = [s for s in states if s is not None]
        if not states:
            return None
        out = {}
        for s in states:
            for k, v in s.items():
                out[k] = out.get(k, frozenset()) | v
        return out

    def _block_walk(self, node, state):
        if node.kind == 'block':
            for kid in node.kids:
                if state is None:
                    break
                state = self._block_walk(kid, state)
            return state
        if node.kind == 'empty':
            return state
        if node.kind == 'simple':
            return self._simple(node, state)
        if node.kind in ('return', 'break', 'continue'):
            if node.kind == 'return':
                self._expression(node.start + 6, node.end - 1, node, state)
            if self.loops:
                if node.kind == 'break':
                    self.loops[-1][0].append(state)
                elif node.kind == 'continue':
                    self.loops[-1][1].append(state)
            return None
        if node.kind == 'if':
            self._expression(*node.cond, node, state)
            then = self._block_walk(node.kids[0], dict(state))
            other = self._block_walk(node.kids[1], dict(state)) if len(node.kids) > 1 else state
            return self._merge([then, other])
        if node.kind in ('for', 'while', 'do'):
            return self._loop(node, state)
        raise Unsupported(node.kind)

    def _loop(self, node, state):
        if node.kind == 'for':
            parts = self.clean[node.cond[0]:node.cond[1]].split(';')
            if len(parts) != 3 or any(re.search(r'=(?!=)|\+\+|--', p) for p in parts):
                raise Unsupported('for header')
        head = state
        mark = (len(self.reads), len(self.defs))
        for _ in range(4):
            del self.reads[mark[0]:]
            del self.defs[mark[1]:]
            self.loops.append(([], []))
            if node.kind != 'do':
                self._expression(*node.cond, node, head)
            end = self._block_walk(node.kids[0], dict(head))
            breaks, continues = self.loops.pop()
            if node.kind == 'do':
                back = self._merge([end] + continues)
                if back is not None:
                    self._expression(*node.cond, node, back)
            else:
                back = self._merge([end] + continues)
            newhead = self._merge([state, back])
            if newhead == head:
                break
            head = newhead
        if node.kind == 'do':
            return self._merge(breaks + [back])
        unconditional = node.kind == 'for' and not self.clean[node.cond[0]:node.cond[1]].replace(';', '').strip()
        return self._merge(breaks + ([] if unconditional else [head]))


# ---------------------------------------------------------------- the rules

def _strip_syntax(source, name):
    part = view(source, name)
    if not part:
        return source
    clean, edits = part.clean, []
    signature_start = clean.rfind('\n', 0, part.opening - 1) + 1
    for m in re.finditer(r'\bregister\s+', clean[signature_start:part.opening]):
        edits.append((signature_start + m.start(), signature_start + m.end(), ''))
    for m in re.finditer(r'\[\s*\(\s*(?:long long|s64)\s*\)\s*', clean[part.opening:part.end]):
        edits.append((part.opening + m.start() + 1, part.opening + m.end(), ''))
    text = edit(source, edits)
    identity = re.findall(rf'(?:inline\s+static|static\s+inline|static|inline)\s+{TYPE}\s+({IDENT})\s*\(\s*{TYPE}\s+({IDENT})\s*\)\s*\{{\s*return\s+\2\s*;\s*\}}', _blank(text))
    if identity:
        part = view(text, name)
        if part:
            body = text[part.opening:part.end]
            for fn, _ in identity:
                body = re.sub(rf'\b{fn}\s*\(((?:[^()]|\([^()]*\))*)\)', lambda m: _paren(m[1]), body)
            text = text[:part.opening] + body + text[part.end:]
    return text


def _drop(source, start, end):
    """The edit that deletes source[start:end]; the whole line when nothing else is on it."""
    left = source.rfind('\n', 0, start) + 1
    right = source.find('\n', end)
    right = len(source) if right < 0 else right
    if not source[left:start].strip() and not source[end:right].strip():
        return (left, min(right + 1, len(source)), '')
    while end < len(source) and source[end] in ' \t':
        end += 1
    return (start, end, '')


def _canon(expr):
    return re.sub(r'\s+', '', expr)


def _plain(expr):
    stripped = CAST.sub('', expr)
    return bool(stripped.strip()) and re.fullmatch(r'[\w\s()+\-*/%&|^~<>!]+', stripped) and not re.search(r'\w\s*\(', stripped)


def _operands(expr):
    return {m for m in re.findall(IDENT, CAST.sub('', expr)) if m not in KEYWORD and not re.fullmatch(TYPE, m)}


def _value(analysis, read):
    """The pure expression every assignment reaching `read` gave its variable, with its operands unchanged since."""
    reaching = read.state
    if not reaching:
        return None
    defs = {d.ident: d for d in analysis.defs}
    exprs = set()
    for ident in reaching:
        d = defs.get(ident)
        if d is None or not d.expr or not _plain(d.expr):
            return None
        for op in _operands(d.expr):
            if op not in analysis.tracked or op in analysis.escaped:
                return None
            if d.ops.get(op) != read.ops.get(op) or d.ops.get(op) is None:
                return None
            if len(d.ops[op]) != 1:
                return None
        exprs.add(_canon(d.expr))
    if len(exprs) != 1:
        return None
    return next(defs[i].expr for i in reaching)


def _paren(expr):
    expr = expr.strip()
    if re.fullmatch(rf'(?:\(\s*{TYPE}\s*\)\s*)?(?:{IDENT}|\d+|0[xX][0-9a-fA-F]+)', expr):
        return expr
    return '(' + expr + ')'


def _substitute(source, name):
    """Index reads (and the only read of a local set once) written as the value they hold; dead assignments dropped."""
    try:
        a = Analysis(source, name)
    except Unsupported:
        return source
    reads_of = {}
    for r in a.reads:
        reads_of.setdefault(r.var, []).append(r)
    edits, gone = [], set()
    for var, reads in reads_of.items():
        if var in a.params or var in a.escaped or var in a.pointer or var not in a.locals:
            continue
        single = len(reads) == 1
        for r in reads:
            value = _value(a, r)
            if value is None or not (r.index or single):
                continue
            if r.start >= r.end or any(e[0] <= r.start < e[1] for e in edits):
                continue
            edits.append((r.start, r.end, _paren(value)))
            gone.add(id(r))
    if not edits:
        return source
    # an assignment no remaining read can see is dropped
    live = set()
    for r in a.reads:
        if id(r) not in gone and r.state:
            live |= set(r.state)
    for d in a.defs:
        if d.ident in live or d.var in a.params or d.var in a.escaped or d.var in a.pointer or d.var not in a.locals:
            continue
        if any(r.var == d.var and id(r) not in gone for r in a.reads if r.node is d.node):
            continue
        if d.declared:
            edits.append((d.span[0] - 1, d.span[1], ''))
        else:
            edits.append(_drop(source, d.node.start, d.node.end))
    return edit(source, edits)


def _global_types(text):
    """{name: element type} of `extern T name;` / `extern T name[];` and {struct type: {member: type}} from the header text."""
    clean = _blank(text)
    objects = {}
    for m in re.finditer(rf'\bextern\s+(?:const\s+)?({IDENT})\s*\*?\s*({IDENT})\s*(?:\[[^\]]*\])?\s*;', clean):
        objects[m[2]] = m[1]
    records = {}
    for m in re.finditer(rf'\btypedef\s+struct\s*(?:{IDENT})?\s*\{{([^{{}}]*)\}}\s*({IDENT})\s*;', clean):
        fields = {}
        for f in re.finditer(rf'({TYPE}|{IDENT})\s+({IDENT})\s*(?:\[[^\]]*\])?\s*;', m[1]):
            fields[f[2]] = re.sub(r'\s+', ' ', f[1])
        records[m[2]] = fields
    return objects, records


def _typed(expr, a, narrowed, objects, records):
    """How many bits the value of `expr` can need, or 32 when that is not known."""
    expr = expr.strip()
    c = re.match(rf'\(\s*({TYPE})\s*\)', expr)
    if c and re.fullmatch(rf'\(\s*{TYPE}\s*\)\s*[\w\s()]+', expr):
        return NARROW.get(re.sub(r'\s+', ' ', c[1]), 32)
    if re.fullmatch(IDENT, expr):
        if expr in a.types:
            return NARROW.get(narrowed.get(expr) or a.types[expr], 32)
        return NARROW.get(objects.get(expr, ''), 32)
    if re.fullmatch(r'\d+|0[xX][0-9a-fA-F]+', expr):
        value = int(expr, 0)
        return 8 if value < 256 else 16 if value < 65536 else 32
    m = re.fullmatch(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*(?:\.|->)\s*({IDENT})', expr)
    if m and objects.get(m[1]) in records:
        return NARROW.get(records[objects[m[1]]].get(m[2], ''), 32)
    m = re.fullmatch(rf'({IDENT})\s*\[[^\]]*\]', expr)
    if m:
        return NARROW.get(objects.get(m[1], ''), 32)
    return 32


def _narrow(source, name, header=''):
    """A word local that every use truncates (or that only ever holds a narrow value) declared as that narrow type."""
    try:
        a = Analysis(source, name)
    except Unsupported:
        return source
    objects, records = _global_types(source + '\n' + header)
    by_var, defs_of = {}, {}
    for r in a.reads:
        by_var.setdefault(r.var, []).append(r)
    for d in a.defs:
        defs_of.setdefault(d.var, []).append(d)
    narrowed = {}
    for _ in range(3):
        for var, kind in a.types.items():
            if kind not in ('s32', 'u32', 'int', 'unsigned int') or var in narrowed or var in a.escaped:
                continue
            reads, defs = by_var.get(var, []), defs_of.get(var, [])
            if not defs or any(d.expr is None for d in defs):
                continue
            casts = {r.cast for r in reads if r.cast in NARROW}
            wanted = None
            if len(casts) == 1:
                bits = NARROW[next(iter(casts))]
                truncating = all(r.cast in NARROW or _truncating(a, r, narrowed) for r in reads)
                fits = all(_typed(d.expr, a, narrowed, objects, records) <= bits for d in defs)
                if truncating or fits:
                    wanted = next(iter(casts))
            if wanted is None and not casts:
                evidence = {re.sub(r'\s+', ' ', c[1]) for d in defs for c in [CAST.match(d.expr)] if c}
                if len(evidence) == 1 and next(iter(evidence)) in NARROW:
                    bits = NARROW[next(iter(evidence))]
                    if all(_typed(d.expr, a, narrowed, objects, records) <= bits for d in defs):
                        wanted = next(iter(evidence))
            if wanted and NARROW[wanted] >= 16:
                narrowed[var] = wanted
    edits = []
    for var, kind in narrowed.items():
        node = a.locals[var]
        m = re.search(rf'\b{re.escape(a.types[var])}\b', source[node.start:node.end])
        if m:
            edits.append((node.start + m.start(), node.start + m.end(), kind))
    return edit(source, edits) if edits else source


def _truncating(a, read, narrowed):
    """`read` is the whole right side of an assignment to a narrow local (`previous = current;`)."""
    for d in a.defs:
        if d.node is read.node and d.expr and d.expr.strip() == a.clean[read.start:read.end] and d.var in a.types:
            return NARROW.get(narrowed.get(d.var) or a.types[d.var], 32) <= 16
    return False


def _unused(source, name):
    """Declarations of locals nothing reads or sets any more."""
    try:
        a = Analysis(source, name)
    except Unsupported:
        return source
    used = {r.var for r in a.reads} | {d.var for d in a.defs}
    edits = []
    for var, node in a.locals.items():
        text = a.clean[node.start:node.end - 1].strip()
        if var not in used and var not in a.escaped and '=' not in text and DECLARATION.match(text):
            edits.append(_drop(source, node.start, node.end))
    return edit(source, edits) if edits else source


def _sink(source, name):
    """A local set once to a pure expression is set right before the first statement that reads it."""
    try:
        a = Analysis(source, name)
    except Unsupported:
        return source
    defs_of, reads_of = {}, {}
    for d in a.defs:
        defs_of.setdefault(d.var, []).append(d)
    for r in a.reads:
        reads_of.setdefault(r.var, []).append(r)
    edits = []
    for var, defs in defs_of.items():
        if var in a.params or var in a.escaped or var in a.pointer or var not in a.locals or len(defs) < 1:
            continue
        reads = reads_of.get(var, [])
        exprs = {_canon(d.expr) for d in defs if d.expr}
        if not reads or len(exprs) != 1 or any(not d.expr or not _plain(d.expr) or d.declared for d in defs):
            continue
        expr = defs[0].expr
        if _operands(expr) - set(a.params):
            continue  # only expressions of the parameters, which nothing assigns, can move without a check
        if any(d.var in _operands(expr) for d in a.defs):
            continue
        target = _sink_target(a, defs, reads)
        if target is None:
            continue
        where, anchor = target
        line = f'{var} = {expr};'
        if anchor == 'before':
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, where) + 1:where])[0]
            if source[source.rfind('\n', 0, where) + 1:where].strip():
                edits.append((where, where, line + ' '))
            else:
                edits.append((where, where, line + '\n' + indent))
        for d in defs:
            edits.append(_drop(source, d.node.start, d.node.end))
    return edit(source, edits) if edits else source


def _sink_target(a, defs, reads):
    """Where the one assignment goes: before the statement (of the block that holds every read) that reads first."""
    chains = []
    for r in reads:
        node = r.node
        chains.append(node.path())
    common = chains[0]
    for chain in chains[1:]:
        k = 0
        while k < min(len(common), len(chain)) and common[k] is chain[k]:
            k += 1
        common = common[:k]
    # descend from the common ancestor block into the branch that holds all reads
    block = None
    for node in reversed(common):
        if node.kind == 'block':
            block = node
            break
    if block is None:
        return None
    first = None
    for kid in block.kids:
        if any(kid in chain for chain in chains):
            first = kid
            break
    if first is None:
        return None
    # statements that read: a simple statement itself or the compound one containing the first read
    if first.kind in ('simple', 'return'):
        pass
    for d in defs:
        if d.node.start > first.start:
            return None
    if not any(d.node.start < first.start for d in defs):
        return None
    return first.start, 'before'


def strip(source, name, header=''):
    """The function with the scaffolding written out in one go, or None when nothing changed."""
    text = source
    for module in (phase_storage_split_repairs,):
        while True:
            plain = module.split(text, name)
            if not plain or plain == text:
                break
            text = plain
    for _ in range(ROUNDS):
        arms = identical_arm_collapse_repairs.variants(text, name)
        if not arms:
            break
        text = arms[0][1]
    text = _strip_syntax(text, name)
    for _ in range(ROUNDS):
        before = text
        text = _substitute(text, name)
        text = _sink(text, name)
        text = _narrow(text, name, header)
        if text == before:
            break
    text = _unused(text, name)
    return text if text != source else None


FENCE = re.compile(r'\bdo\s*\{')
FENCE_END = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;')


def unfence(source, name):
    """Every `do { S } while (0);` in the function written as the block `{ S }`, where S has no `break` or `continue`
    (which the fence would scope), or None when there is none. A search's fences keep a loop note between statements
    (sched.c orders across it, cse2 merges across it); the plain block is where an agent restarts from."""
    text, skip = source, 0
    for _ in range(64):  # one fence a round, the text read again: nested fences shift each other's offsets
        part = view(text, name)
        if not part:
            return None
        clean, found = part.clean, None
        for index, hit in enumerate(FENCE.finditer(clean, part.opening, part.end)):
            if index < skip:
                continue
            brace = hit.end() - 1
            end = close(clean, brace, '{', '}')
            tail = FENCE_END.match(clean, end) if end else None
            if not tail or re.search(r'\b(?:break|continue)\b', clean[brace:end]):
                skip = index + 1
                continue
            found = (hit.start(), brace + 1, end - 1, tail.end())
            break
        if not found:
            break
        start, body, close_at, stop = found
        text = text[:start] + '{' + text[body:close_at] + '}' + text[stop:]
    return text if text != source else None


def plain(source, name, header=''):
    """The saved best as a person would restart from it: its fences opened (`unfence`) and its scaffolding stripped
    (`strip`), or None when neither changed anything. Offered beside the best when a function is claimed (the
    match-function skill's setup.py), not a permuter child: a fence is often what a near-match's score rests on."""
    text = unfence(source, name) or source
    text = strip(text, name, header) or text
    return text if text != source else None


def variants(source, name, header=''):
    plain = strip(source, name, header)
    if not plain:
        return []
    out = [(FAMILY, plain)]
    out += [(COMBINED, text) for _, text in loop_invariant_key_copy.variants(plain, name)]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 98}
