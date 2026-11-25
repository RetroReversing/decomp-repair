"""Three m2c shapes of a branch whose arms the compiler merged afterwards, written as the arms the game had.

Found matching a 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller-input routine by hand
(10695 -> 4645 in the isolated judge, these three steps -4200 of it). In each case the final jump pass cross-jumped
identical tails of two or three arms into one, and m2c read the merged code back as one join after the branch.

condition_bit_arm_tests
    m2c's `var_condition_bit` set to a *different* comparison at the end of each arm of an `if`/`else`, then tested
    after the join (with statements between that don't depend on it):

        if (f < 0.0f) { v = f + 0.02f; bit = v > 0.0f; } else { v = f - 0.02f; bit = v < 0.0f; }
        o->speed = v;
        if (bit) { o->speed = 0.0f; }

    The game wrote the test in each arm (`o->speed = v; if (v > 0.0f) { o->speed = 0.0f; }`); the two arms end with the
    same `bc1f`/`swc1`/`swc1` run after their own `c.lt.s`, which jump2 merges, so the target has one branch on the FP
    condition flag of either compare. `condition_bit_inline` reads only one expression for every assignment; this
    family moves the statements after the join and the test into each arm (the arm's own comparison), one child per
    local. 4755 -> 4645 and 5315 -> 4755 on the routine above.

switch_assign_if_chain
    A small `switch` whose every arm only assigns one local a constant (`case 2: c = 0x3F3FFFFF; break; case 1: ...;
    default: ...`), followed by the statements that use it. m2c reads a compare chain `x == 1`, `x == 2` (`bne`, then
    `bnel` with the default's first insn in its slot) back as a `switch` whose cases come in another order, and the
    statements after it as one tail, where the target has the tail's first load at the head of every arm (the arms
    were whole and cross-jumping merged their ends). The children are the `if`/`else if` chain, cases in ascending
    order and as written, with the next one to three plain statements copied into every arm. 10425 -> 7715 with two
    statements (a colour store and a flag read-modify-write), twice in the routine; the chain alone (no statements)
    was worse (10330), and a `switch` with the statements in its arms too (5725 against 4645).

negated_chain_switch
    m2c's `if (!(x != 2)) { A } else if (x != 5) { D } else { B }` (or `x == 2` first): a `switch` whose `default:` arm
    comes first, since gcc emits `beq x, 2` and `beq x, 5` and then falls into the code written first (the default),
    where the `if` chain branches over it. The first child writes `default:` first, the second last. 6935 -> 5315.

The cross-jumping reading is from jump.c's `find_cross_jump` (it matches insns backwards from two jumps to one label);
which source order made each tail is a hypothesis from the one routine. The exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY_TESTS = 'condition_bit_arm_tests'
FAMILY_CHAIN = 'switch_assign_if_chain'
FAMILY_SWITCH = 'negated_chain_switch'
FAMILIES = (FAMILY_TESTS, FAMILY_CHAIN, FAMILY_SWITCH)
LIMIT = 12

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_KEYWORD = re.compile(r'\b(?:if|else|switch|case|default|while|for|do|goto|return|break|continue)\b')
_HEAD = re.compile(r'(if|switch|while|for)\s*\(')


def _ws(t, i):
    while i < len(t) and t[i].isspace():
        i += 1
    return i


def _python_close(t, i, left, right):
    depth = 0
    for j in range(i, len(t)):
        if t[j] == left:
            depth += 1
        elif t[j] == right:
            depth -= 1
            if depth == 0:
                return j + 1
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(t, i, left, right):
        found = _scan.close_if_past(t, i, left, right, None)
        return _python_close(t, i, left, right) if found is NotImplemented else found


def _stmt(t, i):
    """End (exclusive) of the statement starting at `i` in blanked text, or None."""
    i = _ws(t, i)
    if i >= len(t):
        return None
    if t[i] == '{':
        return _close(t, i, '{', '}')
    head = _HEAD.match(t, i)
    if head:
        paren = _close(t, head.end() - 1, '(', ')')
        if paren is None:
            return None
        end = _stmt(t, paren)
        if end is None:
            return None
        if head[1] == 'if':
            nxt = _ws(t, end)
            if re.match(r'else\b', t[nxt:]):
                return _stmt(t, nxt + 4)
        return end
    if re.match(r'do\b', t[i:]):
        end = _stmt(t, i + 2)
        if end is None:
            return None
        m = re.compile(r'\s*while\s*\(').match(t, end)
        if not m:
            return None
        paren = _close(t, m.end() - 1, '(', ')')
        semi = _ws(t, paren) if paren else None
        return semi + 1 if semi is not None and semi < len(t) and t[semi] == ';' else None
    label = re.compile(rf'(?:case\s+[^:;{{}}]+|default|{IDENT})\s*:(?!:)').match(t, i)
    if label and not re.match(r'(?:if|else|while|for|do|switch|return|goto|break|continue)\b', t[i:]):
        return label.end()
    depth = 0
    for j in range(i, len(t)):
        c = t[j]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '{' and depth == 0:
            return None
        elif c == ';' and depth == 0:
            return j + 1
    return None


def _items(t, start, end):
    """The statements of the block whose braces are at `start` and `end - 1`: (start, end) pairs, or None."""
    out, i = [], start + 1
    while True:
        i = _ws(t, i)
        if i >= end - 1:
            return out
        e = _stmt(t, i)
        if e is None or e > end - 1:
            return None
        out.append((i, e))
        i = e


def _blocks(t, opening, end):
    for m in re.finditer(r'\{', t[opening:end]):
        start = opening + m.start()
        stop = _close(t, start, '{', '}')
        if stop:
            yield start, stop


def _if_parts(t, s, e):
    """(condition span, then span, else span or None) of the `if` statement at s..e."""
    m = re.compile(r'if\s*\(').match(t, s)
    if not m:
        return None
    paren = _close(t, m.end() - 1, '(', ')')
    then_start = _ws(t, paren)
    then_end = _stmt(t, then_start)
    if then_end is None:
        return None
    nxt = _ws(t, then_end)
    if nxt < e and re.match(r'else\b', t[nxt:]):
        else_start = _ws(t, nxt + 4)
        return (m.end(), paren - 1), (then_start, then_end), (else_start, e)
    return (m.end(), paren - 1), (then_start, then_end), None


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:]).group()


def _mentions(text, var):
    return len(re.findall(rf'(?<![\w.>]){re.escape(var)}\b', text))


def _written(name, text):
    return bool(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text)
                or re.search(rf'(?:\+\+|--)\s*{re.escape(name)}\b|\b{re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', text))


def _plain_statement(text):
    return not _KEYWORD.search(text) and '{' not in text and text.rstrip().endswith(';')


def _drop_declaration(source, opening, var):
    m = re.compile(rf'^[ \t]*(?:[A-Za-z_][\w ]*?)[ \t]+{re.escape(var)}[ \t]*;[ \t]*\n', re.M).search(source, opening)
    if m and _mentions(source[opening:], var) == 1:
        return source[:m.start()] + source[m.end():]
    return source


def _arm_tests(source, name):
    out = []
    opening, end = _span(source, name)
    if opening is None:
        return out
    t = _blank(source)
    for b_start, b_end in _blocks(t, opening, end):
        items = _items(t, b_start, b_end)
        if not items:
            continue
        for k, (s, e) in enumerate(items):
            parts = _if_parts(t, s, e)
            if not parts or not parts[2]:
                continue
            arms = []
            for a_start, a_end in (parts[1], parts[2]):
                if t[a_start] != '{':
                    break
                inner = _items(t, a_start, a_end)
                if not inner:
                    break
                last = source[inner[-1][0]:inner[-1][1]]
                m = re.fullmatch(rf'({IDENT})\s*=(?!=)\s*([^;{{}}]+?)\s*;', last.strip())
                if not m:
                    break
                arms.append((a_start, a_end, inner[-1], m[1], m[2]))
            if len(arms) != 2 or arms[0][3] != arms[1][3]:
                continue
            var = arms[0][3]
            between = []
            test = None
            for s2, e2 in items[k + 1:]:
                text = t[s2:e2]
                m = re.match(rf'if\s*\(\s*(!\s*)?{re.escape(var)}\s*\)', text)
                if m:
                    p = _if_parts(t, s2, e2)
                    if p and p[2] is None:
                        test = (s2, e2, bool(m[1]), p[1])
                    break
                if _mentions(text, var) or not _plain_statement(text):
                    break
                between.append((s2, e2))
            if not test:
                continue
            if _mentions(t[opening:end], var) != 3 + _decl_count(t, opening, end, var):
                continue
            stmts = [source[a:b] for a, b in between]
            exprs = [a[4] for a in arms]
            memory = any(re.search(r'->|\*|\[|[A-Za-z_)\]]\s*\.', x) for x in exprs)
            if any(_written(n, ' '.join(stmts)) for x in exprs for n in re.findall(IDENT, x)):
                continue
            if memory and any(re.search(r'(?<![=!<>])=(?!=)', x) for x in stmts):
                continue
            then_text = source[test[3][0]:test[3][1]]
            edits = []
            for a_start, a_end, (ls, le), _, expr in arms:
                pad = _indent(source, ls)
                cond = f'!({expr})' if test[2] else expr
                added = ''.join(f'{x.strip()}\n{pad}' for x in stmts) + f'if ({cond})\n{pad}{then_text.strip()}'
                edits.append((ls, le, added))
            last_end = test[1]
            first_start = between[0][0] if between else test[0]
            line = source.rfind('\n', 0, first_start) + 1
            edits.append((line, last_end, ''))
            child = source
            for a, b, text in sorted(edits, reverse=True):
                child = child[:a] + text + child[b:]
            child = _drop_declaration(child, opening, var)
            if child != source:
                out.append((FAMILY_TESTS, child))
    return out


def _decl_count(t, opening, end, var):
    return len(re.findall(rf'^[ \t]*[A-Za-z_][\w ]*?[ \t]+{re.escape(var)}[ \t]*;', t[opening:end], re.M))


def _span(source, name):
    span = find(source, name)
    if not span:
        return None, None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not head:
        return None, None
    return span[0] + head.end() - 1, span[1]


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def _arm(var, value, follow, pad):
    lines = [f'{var} = {value};'] + follow
    return '{\n' + ''.join(f'{pad}  {line}\n' for line in lines) + f'{pad}}}'


def _switch_chain(source, name):
    opening, end = _span(source, name)
    out, sites = [], []
    if opening is None:
        return out
    t = _blank(source)
    for b_start, b_end in _blocks(t, opening, end):
        items = _items(t, b_start, b_end)
        if not items:
            continue
        for k, (s, e) in enumerate(items):
            m = re.compile(rf'switch\s*\(\s*({IDENT})\s*\)\s*\{{').match(t, s)
            if not m:
                continue
            x = m[1]
            body = t[m.end():e - 1]
            arms = re.findall(rf'(case\s+({NUMBER})|default)\s*:\s*\{{?\s*({IDENT})\s*=(?!=)\s*([^;{{}}]+?)\s*;\s*break\s*;\s*\}}?', body)
            rest = re.sub(rf'(case\s+{NUMBER}|default)\s*:\s*\{{?\s*{IDENT}\s*=(?!=)\s*[^;{{}}]+?\s*;\s*break\s*;\s*\}}?', '', body)
            if rest.strip() or not 2 <= len(arms) <= 4 or len({a[2] for a in arms}) != 1:
                continue
            defaults = [a for a in arms if a[0] == 'default']
            cases = [a for a in arms if a[0] != 'default']
            if len(defaults) != 1 or not cases:
                continue
            var = arms[0][2]
            follow = []
            for s2, e2 in items[k + 1:k + 4]:
                text = source[s2:e2]
                if not _plain_statement(t[s2:e2]) or _written(x, text) or _written(var, text):
                    break
                follow.append(text.strip())
            pad = _indent(source, s)
            orders = {}
            for key, order in (('ascending', sorted(cases, key=lambda a: int(a[1].rstrip('uUlL'), 0))), ('written', cases)):
                orders[key] = order
            edits = {}
            for count in range(len(follow) + 1):
                for key, order in orders.items():
                    text = ''
                    for i, case in enumerate(order):
                        text += ('' if i == 0 else f'\n{pad}else ') + f'if ({x} == {case[1]})\n{pad}{_arm(var, case[3], follow[:count], pad)}'
                    text += f'\n{pad}else\n{pad}{_arm(var, defaults[0][3], follow[:count], pad)}'
                    stop = items[k + count][1] if count else e
                    edits[(key, count)] = (s, stop, text)
            sites.append((len(follow), edits))
    # every site rewritten the same way first (twice in the routine above: one site alone moved less), most
    # statements copied first; then each site alone
    choices = [(key, count) for count in (3, 2, 1, 0) for key in ('ascending', 'written')]
    for key, count in choices:
        chosen = [edits[(key, min(count, most))] for most, edits in sites]
        if len(sites) > 1 or count <= sites[0][0]:
            out.append((FAMILY_CHAIN, _apply(source, chosen)))
    if len(sites) > 1:
        for key, count in choices:
            for most, edits in sites:
                if count <= most:
                    out.append((FAMILY_CHAIN, _apply(source, [edits[(key, count)]])))
    return out


def _negated_switch(source, name):
    opening, end = _span(source, name)
    out = []
    if opening is None:
        return out
    t = _blank(source)
    for b_start, b_end in _blocks(t, opening, end):
        items = _items(t, b_start, b_end)
        if not items:
            continue
        for s, e in items:
            first = _if_parts(t, s, e)
            if not first or not first[2]:
                continue
            cond = re.sub(r'\s+', ' ', t[first[0][0]:first[0][1]]).strip()
            m = (re.fullmatch(rf'!\s*\(\s*({IDENT}) != ({NUMBER})\s*\)', cond)
                 or re.fullmatch(rf'({IDENT}) == ({NUMBER})', cond))
            if not m:
                continue
            x, a = m[1], m[2]
            second = _if_parts(t, first[2][0], first[2][1])
            if not second or not second[2]:
                continue
            cond2 = re.sub(r'\s+', ' ', t[second[0][0]:second[0][1]]).strip()
            m2 = re.fullmatch(rf'({IDENT}) != ({NUMBER})', cond2)
            if not m2 or m2[1] != x or int(m2[2].rstrip('uUlL'), 0) == int(a.rstrip('uUlL'), 0):
                continue
            b = m2[2]
            spans = (first[1], second[1], second[2])
            if any(re.search(r'\b(?:break|continue|case|default)\b', t[p:q]) for p, q in spans):
                continue
            if _written(x, t[s:e]):
                continue

            def inner(span):
                p, q = span
                text = source[p:q].strip()
                if text.startswith('{'):
                    text = text[1:-1]
                return '\n'.join(line for line in text.strip('\n').split('\n')) + '\n'
            pad = _indent(source, s)
            case_a, dflt, case_b = (inner(sp) for sp in spans)
            arms = {'default': f'{pad}default:\n{dflt}{pad}  break;\n',
                    'a': f'{pad}case {a}:\n{case_a}{pad}  break;\n',
                    'b': f'{pad}case {b}:\n{case_b}{pad}  break;\n'}
            for order in (('default', 'a', 'b'), ('a', 'b', 'default')):
                text = f'switch ({x})\n{pad}{{\n' + ''.join(arms[o] for o in order) + f'{pad}}}'
                out.append((FAMILY_SWITCH, source[:s] + text + source[e:]))
    return out


def variants(source, name):
    out = []
    for family in (_arm_tests, _negated_switch, _switch_chain):
        try:
            found = family(source, name)
        except (ValueError, TypeError, IndexError):
            found = []
        out.extend(found)
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
