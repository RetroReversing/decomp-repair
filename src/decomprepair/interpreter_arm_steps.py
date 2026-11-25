"""Four arm-level steps of a sound-sequence interpreter that moved its register rows (KMC GCC 2.7.2).

- `sum_accumulate_steps`: `v = H + (((s32) (X * Y)) >> K);` as `v = X; v = (v * Y) >> K; v += H;`. One user variable
  that holds the factor, the shifted product and the sum is one pseudo with several sets; local-alloc then keeps the
  product's chain in that variable's register and the other operand's loads go to the free ones, where the one-shot sum
  ties the sum to `H`'s register (a pan command: 13 register rows, 1400 -> 1335). Hypothesis read from the allocation.
- `arm_tail_share`: `if (c) { ...; r = K; break; } r = K; break;` as `if (c) { ...; } r = K; break;`: the arm falls
  into the shared tail, which jump2 cross-jumps into another arm's, so the arm ends with `j` and its last store in the
  delay slot instead of a `move $a0, $zero` of its own (a curve command, 1335 -> 1085).
- `compare_into_arms`: `if (c) { x = A; y = B; } else { x = C; y = D; } if (y == x) { return 1; }` in a helper as
  the comparison in each arm (`if (B' == A) return 1;`): the two-arm pseudos are global and take `$v0`/`$v1` the other
  way round; per arm they are block-local and the identical compare tails cross-jump (a slot check, 1085 -> 1055).
- `operand_preload_temp`: `x = A + G; t = x;` as `t = G; x = A + t;` with the next statement's local: the global's
  load is scheduled first, as the target has it (a group-link command, 1010 -> 995 with the existing `s16` temp).

Proposals only; the compiler and the byte judge decide."""
import re

from .csource import find

FAMILIES = ('sum_accumulate_steps', 'arm_tail_share', 'compare_into_arms', 'operand_preload_temp')


def _python_balanced(text, at):
    """End (exclusive) of the parenthesised group starting at text[at] == '('."""
    depth = 0
    for i in range(at, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


_balanced = _python_balanced
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _balanced(text, at):
        found = _scan.close_if_past(text, at, '(', ')', -1)
        return _python_balanced(text, at) if found is NotImplemented else found


def _split_top(expr, op):
    depth = 0
    for i, ch in enumerate(expr):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0 and expr[i:i + len(op)] == op and expr[i - 1] == ' ' and expr[i + len(op)] == ' ':
            return expr[:i].strip(), expr[i + len(op):].strip()
    return None


def _strip(expr):
    expr = expr.strip()
    while expr.startswith('(') and _balanced(expr, 0) == len(expr):
        expr = expr[1:-1].strip()
    return expr


def sum_accumulate_steps(body):
    out = []
    for m in re.finditer(r'\n([ \t]*)(\w+) = ([^;\n]+);', body):
        name, expr = m.group(2), m.group(3)
        parts = _split_top(expr, '+')
        if not parts:
            continue
        for head, prod in (parts, parts[::-1]):
            p = re.fullmatch(r'\(\(\(s32\) \((.*)\)\) >> (\w+)\)', prod.strip())
            if not p:
                continue
            xy = _split_top(_strip(p.group(1)), '*')
            if not xy:
                continue
            ind = m.group(1)
            new = '\n%s%s = %s;\n%s%s = (%s * %s) >> %s;\n%s%s += %s;' % (
                ind, name, _strip(xy[0]), ind, name, name, xy[1], p.group(2), ind, name, head)
            out.append(body[:m.start()] + new + body[m.end():])
            break
    return out


def arm_tail_share(body):
    out = []
    pat = re.compile(r'\n[ \t]*(\w+) = (\w+);\s*\n[ \t]*break;\s*\n([ \t]*)\}(\s*\n[ \t]*)\1 = \2;\s*\n[ \t]*break;')
    for m in pat.finditer(body):
        out.append(body[:m.start()] + '\n' + m.group(3) + '}' + m.group(4) + '%s = %s;\n%sbreak;' % (
            m.group(1), m.group(2), m.group(4).lstrip('\n')) + body[m.end():])
    return out


def compare_into_arms(body):
    out = []
    pat = re.compile(r'(\n[ \t]*)if \(([^\n]+)\)\s*\{(.*?)\n[ \t]*\}\s*else\s*\{(.*?)\n[ \t]*\}\s*\n[ \t]*'
                     r'if \((\w+) == (\w+)\)\s*\{\s*return (\w+);\s*\}', re.S)
    for m in pat.finditer(body):
        a, b = m.group(5), m.group(6)
        arms = []
        for arm in (m.group(3), m.group(4)):
            sets = re.findall(r'\n[ \t]*(%s|%s) = ([^;]+);' % (a, b), arm)
            values = dict(sets)
            if set(values) != {a, b}:
                break
            rest = re.sub(r'\n[ \t]*(%s|%s) = [^;]+;' % (a, b), '', arm)
            va = values[a]
            vb = values[b]
            # a value that reads the other one (y = T[x]) takes its value in place
            vb = re.sub(r'\b%s\b' % a, values[a], vb) if re.search(r'\b%s\b' % a, vb) else vb
            va = re.sub(r'\b%s\b' % b, values[b], va) if re.search(r'\b%s\b' % b, va) else va
            arms.append((rest, va, vb))
        else:
            ind = m.group(1)
            for swap in (False, True):
                parts = []
                for k, (rest, va, vb) in enumerate(arms):
                    left, right = (vb, va) if swap and k == 1 else (va, vb)
                    parts.append('%s%s  if (%s == %s)%s  {%s    return %s;%s  }' % (
                        rest, ind, left, right, ind, ind, m.group(7), ind))
                new = '%sif (%s)%s{%s%s}%selse%s{%s%s}' % (ind, m.group(2), ind, parts[0], ind, ind, ind, parts[1],
                                                         ind)
                out.append(body[:m.start()] + new + body[m.end():])
    return out


def operand_preload_temp(body):
    out = []
    pat = re.compile(r'\n([ \t]*)(\w+) = ([^;\n]+?) \+ (\(?\*\(\([us]\d+ \*\) \(&\w+\)\)\)?);\s*\n[ \t]*(\w+) = \2;')
    for m in pat.finditer(body):
        ind, x, a, g, t = m.groups()
        new = '\n%s%s = %s;\n%s%s = %s + %s;\n%s%s = %s;' % (ind, t, g, ind, x, a, t, ind, t, x)
        out.append(body[:m.start()] + new + body[m.end():])
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    s, e = span
    body = source[s:e]
    out = []
    for fam, fn in zip(FAMILIES, (sum_accumulate_steps, arm_tail_share, None, operand_preload_temp)):
        if fn is None:
            continue
        for child in fn(body)[:8]:
            out.append((fam, source[:s] + child + source[e:]))
    # the compare usually sits in a static helper above the function
    for child in compare_into_arms(source[:s])[:4]:
        out.append((FAMILIES[2], child + source[s:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
