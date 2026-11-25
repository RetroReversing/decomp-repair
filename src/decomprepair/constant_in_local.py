"""A constant operand held in a local of its own, set on the line before its use.

GCC 2.8 (SN, `-O2 -mips3 -mgp32`) materialises a literal where its use needs it, and a literal operand of a multiply or
a loop compare is folded into the insn (`slti`, an immediate multiplier) or shares the register of an equal literal
elsewhere. A developer's `c = 7000.0f; g = x * c;`, or a bound kept in `n = 5;` above the loop, is a pseudo of its own
that is live from its set to its use: the load is a separate insn the scheduler places, it ties up a register for that
span (so it changes the allocation around it), and a loop compare against it is `slt` where the literal gives `slti`.
Hand matches on N64 SN GCC 2.8.1 code needed exactly that (a float scale held in a local, a loop bound `n = 5`, a
widening multiply `(s32)((s64)f(x) * k) >> 15` with `k = 400`), each found by hand because no family offered it
(`loop_constant_holder`/`entry_constant_local`/`loop_literal_local` hold a literal in a counter or store it, and
`float_literal_locals` is for the stores after a call).

Children, each one statement and its local (`LIMIT` in all, a function with a first-found order of multipliers
before bounds):
- `constant_in_local_multiplier`: a statement `lhs = ... * K ...;` at the start of a block line (K a float literal, or
  an integer literal of at least 3 that is not a power of two) becomes `k_K = K;` on the line before and the multiply reads
  `k_K`. The declaration is added after the function's leading declarations (`f32` for a float literal, `s32`).
- `constant_in_local_bound`: a loop whose test is `i < N`, `i <= N` (or the flipped `N > i`) with N an integer literal
  gets `n_N = N;` right above the loop and the test reads `n_N`. A loop that already tests a local is left alone.

Gates: when the target's assembly is given, a bound is offered only when the target compares with a register
(`slt`/`sltu`, and no `slti`/`sltiu` against N) and a multiplier only when the target multiplies (`mul.s`, `mult`,
`mul`); the assembly is optional (a caller without it gets the children without that gate, since the judge decides).
- `constant_in_local_argument`: a float literal passed as an argument of a call (`z = f(180.0f, z, k);`, not 0.0 and 1.0)
  becomes `k_180p0 = 180.0f;` set on the line before the statement, or, in a second child, on the line before the
  `if`/loop statement that holds it (a constant a block earlier than its use: a hand match needed `tgt = 180.0f;` set
  before the `if` whose body passes it, which holds it in a register across the test), and the call reads `k_180p0`.
A function with `volatile`, `asm` or a preprocessor line is left alone. Proposals only; the compiler and the byte judge
decide."""
import re

from .integer_repair_support import IDENT, edit, view
from .store_run_order import _insert_declaration

FAMILY_MULTIPLIER = 'constant_in_local_multiplier'
FAMILY_BOUND = 'constant_in_local_bound'
FAMILY_ARGUMENT = 'constant_in_local_argument'
FAMILIES = (FAMILY_MULTIPLIER, FAMILY_BOUND, FAMILY_ARGUMENT)
LIMIT = 8
_FLOAT = r'\d+\.\d*[fF]?|\.\d+[fF]?'
_INT = r'0[xX][0-9a-fA-F]+|\d+'
_MULTIPLY_RIGHT = re.compile(rf'(?<=[\w)\]])\s*\*\s*(?P<k>(?:{_FLOAT})|(?:{_INT}))(?![\w.])')
_MULTIPLY_LEFT = re.compile(rf'(?<![\w.])(?P<k>(?:{_FLOAT})|(?:{_INT}))\s*\*\s*(?=[\w(])')
_STATEMENT = re.compile(r'(?m)^([ \t]*)([^\n{};]*;)[ \t]*$')
_NOT_STATEMENT = ('if', 'while', 'for', 'switch', 'return', 'case', 'else', 'do', 'goto')
_LOOP = re.compile(r'\b(?P<kind>while|for)\s*\(')


def _float_text(text):
    return bool(re.fullmatch(_FLOAT, text))


def _int(text):
    return int(text, 0)


def _eligible(text):
    if _float_text(text):
        try:
            return float(text.rstrip('fF')) not in (0.0, 1.0, 2.0)
        except ValueError:
            return False
    value = _int(text)
    return value >= 3 and value & (value - 1) != 0


def _name(prefix, text):
    return f'{prefix}_' + re.sub(r'\W', 'p', text.lower().rstrip('f') if _float_text(text) else text.upper().replace('X', 'x'))


def _target_multiplies(asm):
    return bool(re.search(r'\b(?:mul\.s|mult|multu)\b', asm or ''))


def _target_register_compare(asm, number):
    if not re.search(r'\bsltu?\s+\$', asm or ''):
        return False
    return not re.search(rf'\bsltiu?\s+\$\w+\s*,\s*\$\w+\s*,\s*(?:{number}|0x{number:x})\b', asm, re.I)


def _multiplier_children(source, part, name):
    out = []
    used = set(re.findall(IDENT, part.clean[part.opening:part.end]))
    body = part.clean
    for hit in _STATEMENT.finditer(body, part.opening + 1, part.end):
        text = hit[2]
        first = re.match(rf'\s*({IDENT})', text)
        if not first or first[1] in _NOT_STATEMENT or '=' not in text:
            continue
        lhs, _, rhs = text.partition('=')
        if re.search(r'[<>!=]$', lhs.strip()) or rhs.startswith('='):
            continue  # a compare, not an assignment (a compound `+=` is an assignment too)
        start = hit.start(2)
        previous = body[:hit.start(1)].rstrip()[-1:]
        if previous not in ('', ';', '{', '}'):
            continue  # under an unbraced if/else/loop: the set would leave the statement's block
        found = [m for m in list(_MULTIPLY_RIGHT.finditer(rhs)) + list(_MULTIPLY_LEFT.finditer(rhs)) if _eligible(m['k'])]
        if not found:
            continue
        literal = found[0]['k']
        local = _name('k', literal)
        if local in used:
            continue
        shift = len(lhs) + 1
        indent = hit[1]
        kind = 'f32' if _float_text(literal) else 's32'
        own = [(start + shift + m.start('k'), start + shift + m.end('k'), local) for m in found if m['k'] == literal]
        # the rest of the block: `k = 400;` once above two statements that both multiply by it
        depth, stop = 0, part.end
        for at in range(hit.end(), part.end):
            depth += {'{': 1, '}': -1}.get(body[at], 0)
            if depth < 0:
                stop = at
                break
        rest = [(hit.end() + m.start('k'), hit.end() + m.end('k'), local)
                for pattern in (_MULTIPLY_RIGHT, _MULTIPLY_LEFT) for m in pattern.finditer(body[hit.end():stop])
                if m['k'] == literal]
        for extra in ([own + rest] if rest else []) + [own]:
            child = edit(source, extra + [(hit.start(2), hit.start(2), f'{local} = {literal};\n{indent}')])
            moved = view(child, name)
            if moved:
                out.append((FAMILY_MULTIPLIER, _insert_declaration(child, moved, f'{kind} {local};')))
        used.add(local)
    return out


def _loops(clean, lo, hi):
    for hit in _LOOP.finditer(clean, lo, hi):
        depth, i = 1, hit.end()
        while i < hi and depth:
            depth += {'(': 1, ')': -1}.get(clean[i], 0)
            i += 1
        if depth:
            continue
        yield hit, hit.end(), i - 1


def _bound_children(source, part, name, asm):
    out = []
    clean = part.clean
    used = set(re.findall(IDENT, clean[part.opening:part.end]))
    for loop, lo, hi in _loops(clean, part.opening + 1, part.end):
        header = clean[lo:hi]
        test = header.split(';')[1] if loop['kind'] == 'for' and header.count(';') >= 2 else header
        base = lo + (header.index(test) if loop['kind'] == 'for' else 0)
        m = re.fullmatch(rf'\s*(?P<a>{IDENT})\s*(?P<op><=?)\s*(?P<k>{_INT})\s*', test) or \
            re.fullmatch(rf'\s*(?P<k>{_INT})\s*(?P<op>>=?)\s*(?P<a>{IDENT})\s*', test)
        if not m or _int(m['k']) < 2:
            continue
        number = _int(m['k'])
        if asm and not _target_register_compare(asm, number):
            continue
        local = f'n_{number}'
        if local in used:
            continue
        line = source.rfind('\n', 0, loop.start()) + 1
        lead = source[line:loop.start()]
        if lead.strip() and not re.fullmatch(r'\s*(?:\}\s*)?', lead):
            continue
        indent = re.match(r'[ \t]*', lead)[0]
        # a `do { } while (i < N);` has its test after the body: the set goes above the `do`
        keyword = None
        if loop['kind'] == 'while':
            tail = clean[hi + 1:].lstrip()
            if tail.startswith(';'):
                back = clean.rfind('do', part.opening, loop.start())
                if back < 0 or not re.fullmatch(r'do\s*\{', clean[back:clean.find('{', back) + 1]):
                    continue
                keyword = back
            elif loop.start() and clean[:loop.start()].rstrip()[-1:] not in (';', '{', '}'):
                continue
        at = keyword if keyword is not None else loop.start()
        line = source.rfind('\n', 0, at) + 1
        if source[line:at].strip():
            continue
        indent = re.match(r'[ \t]*', source[line:at])[0]
        k_at = base + m.start('k')
        edits = [(k_at, base + m.end('k'), local), (line, line, f'{indent}{local} = {number};\n')]
        child = edit(source, edits)
        moved = view(child, name)
        if not moved:
            continue
        out.append((FAMILY_BOUND, _insert_declaration(child, moved, f's32 {local};')))
        used.add(local)
    return out


_CALL_ARGUMENT = re.compile(rf'(?<![\w.>])(?P<callee>{IDENT})\s*\((?P<args>[^()]*)\)')


def _argument_children(source, part, name):
    out = []
    body = part.clean
    used = set(re.findall(IDENT, body[part.opening:part.end]))
    for hit in _STATEMENT.finditer(body, part.opening + 1, part.end):
        text = hit[2]
        first = re.match(r'\s*(\w+)', text)
        if not first or first[1] in _NOT_STATEMENT and first[1] != 'return':
            continue
        previous = body[:hit.start(1)].rstrip()[-1:]
        if previous not in ('', ';', '{', '}'):
            continue
        for call in _CALL_ARGUMENT.finditer(text):
            if call['callee'] in _NOT_STATEMENT or call['callee'] == 'sizeof':
                continue
            for argument in re.finditer(rf'(?:^|,)\s*(?P<k>{_FLOAT})\s*(?=,|$)', call['args']):
                literal = argument['k']
                if not _float_text(literal) or float(literal.rstrip('fF')) in (0.0, 1.0):
                    continue
                local = _name('k', literal)
                if local in used:
                    continue
                at = hit.start(2) + call.start('args') + argument.start('k')
                indent = hit[1]
                # one line above the statement, then above the compound statement round it
                spots = [(hit.start(2), indent)]
                outer = _enclosing_statement(body, hit.start(1), part.opening)
                if outer is not None:
                    line = source.rfind('\n', 0, outer) + 1
                    lead = source[line:outer]
                    if not lead.strip():
                        spots.append((outer, lead))
                for where, lead in spots:
                    child = edit(source, [(at, at + len(literal), local), (where, where, f'{local} = {literal};\n{lead}')])
                    moved = view(child, name)
                    if moved:
                        out.append((FAMILY_ARGUMENT, _insert_declaration(child, moved, f'f32 {local};')))
                used.add(local)
    return out


def _enclosing_statement(clean, at, opening):
    """The start of the `if`/`for`/`while` statement whose block holds `at`, when that statement starts a line of its own
    directly in a block (a constant set one block earlier goes above it), else None."""
    depth = 0
    for cursor in range(at - 1, opening, -1):
        depth += {'}': 1, '{': -1}.get(clean[cursor], 0)
        if depth < 0:
            head = clean[:cursor].rstrip()
            if not head.endswith(')'):
                return None
            level, back = 0, len(head)
            while back > 0:
                back -= 1
                level += (head[back] == ')') - (head[back] == '(')
                if level == 0:
                    break
            keyword = re.search(r'\b(?:if|for|while)\s*$', head[:back])
            if not keyword:
                return None
            start = keyword.start()
            if clean[:start].rstrip()[-1:] not in (';', '{', '}') or clean[:start].rstrip().endswith('else'):
                return None
            return start
    return None


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body, re.M):
        return []
    out = []
    if not asm or _target_multiplies(asm):
        out += _multiplier_children(source, part, name)
    out += _bound_children(source, part, name, asm)
    out += _argument_children(source, part, name)
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
