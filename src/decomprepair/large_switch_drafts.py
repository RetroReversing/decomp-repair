"""Make m2c's draft of a large switch-heavy function compile, keeping what it does.

m2c's drafts of big state machines (a 4,399-instruction N64 function with 18 jump tables) failed to compile on
four things it writes: a case of one switch emitted inside another, callees declared from their longest call,
float loads through an address it couldn't type, and `nanf` or a float reinterpreted as a pointer in argument
lists. Each rewrite keeps the draft's behaviour; the compiler and judge decide the rest.
"""
import re

_EXTERN = re.compile(r'^(?P<ret>[^\n;()]*?\b)(?P<name>\w+)\((?P<params>[^()\n]*)\);(?P<tail>[ \t]*/\* extern \*/)$', re.M)


def _python_arguments(source, start):
    """Argument count of the call whose `(` is at `start`, and the index after its `)`; None if unbalanced."""
    depth, count, saw = 0, 0, False
    for i in range(start, len(source)):
        c = source[i]
        if c == '(':
            depth += 1
            if depth == 1:
                continue
        elif c == ')':
            depth -= 1
            if depth == 0:
                return (count + 1 if saw else 0), i + 1
        elif c == ',' and depth == 1:
            count += 1
        if depth >= 1 and not c.isspace():
            saw = True
    return None


_arguments = _python_arguments
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _arguments(source, start):
        found = _scan.call_argument_count(source, start)
        return _python_arguments(source, start) if found is NotImplemented else found


def unprototyped_externs(source):
    """m2c declares a callee it inferred from the longest call; calls passing fewer arguments then don't compile.
    Only callees whose calls disagree lose their parameter list."""
    edits = {}
    for match in _EXTERN.finditer(source):
        name = match['name']
        counts = set()
        for call in re.finditer(r'\b' + name + r'\s*\(', source[match.end():]):
            found = _arguments(source, match.end() + call.end() - 1)
            if found:
                counts.add(found[0])
        if len(counts) > 1:
            edits[match.span()] = match['ret'] + name + '();' + match['tail']
    for (a, b), text in sorted(edits.items(), reverse=True):
        source = source[:a] + text + source[b:]
    return source


_SWITCH = re.compile(r'\bswitch\s*\(.*\)\s*\{\s*/\* switch (\d+)(?:; irregular)? \*/')
_LABEL = re.compile(r'^(?P<indent>[ \t]*)(?P<label>case (?P<value>[^:\n]+)|default):[ \t]*/\* switch (?P<n>\d+) \*/[ \t]*$', re.M)


def cross_switch_cases(source):
    """m2c emits a case of switch N inside switch M where both share a block. C attaches it to M (a duplicate case,
    or a second default). Keep the block, label it, and make N's case jump there."""
    stack = []  # (switch number, brace depth of its body)
    depth = 0
    opened = {}  # switch number -> offset after its `{`
    moves = []
    tokens = re.compile(r'[{}]|' + _SWITCH.pattern + r'|' + _LABEL.pattern, re.M)
    for m in tokens.finditer(source):
        text = m.group(0)
        if text.startswith('switch'):
            number = int(m.group(1))
            depth += 1
            stack.append((number, depth))
            opened[number] = m.end()
        elif text == '{':
            depth += 1
        elif text == '}':
            while stack and stack[-1][1] == depth:
                stack.pop()
            depth -= 1
        elif m.group('n'):
            number = int(m.group('n'))
            inner = stack[-1][0] if stack else None
            # (also a label outside every switch: m2c leaves the target of an irregular jump table where the code is)
            if inner != number:
                moves.append((m.start(), m.end(), number, m.group('label'), m.group('value'), m.group('indent')))
    if not moves:
        return source
    inserts = {}
    replaced = []
    for start, end, number, label, value, indent in moves:
        if number not in opened:
            return source
        name = 'switch_%d_%s' % (number, 'default' if label == 'default' else
                                  re.sub(r'\W', '_', value.strip()).strip('_'))
        replaced.append((start, end, name + ':'))
        inserts.setdefault(opened[number], []).append('\n%s: goto %s;' % (label, name))
    edits = replaced + [(at, at, ''.join(texts)) for at, texts in inserts.items()]
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def float_loads(source):
    """`(f32) *(expr)` is m2c's lwc1 through an address it couldn't type; read the float there."""
    return re.sub(r'\((f32|f64)\) \*\(', r'*(\1 *)(', source)


def placeholder_arguments(source):
    """`nanf` stands for a float register m2c thought was an argument; the call has no such argument."""
    return re.sub(r',\s*nanf\b(?=\s*[,)])', '', source)


def float_pointer_arguments(source):
    """A float variable passed where m2c guessed a pointer: pass its bits, as the register did."""
    return re.sub(r'M2C_BITWISE\(void \*, (\w+)\)', r'*(void **)&\1', source)


def rewrite(source, name='', asm='', header=''):
    """The rewritten draft, or None when no step applies. `name`, `asm` and `header` are accepted for the draft
    chain's calling convention and unused."""
    out = source
    for step in (cross_switch_cases, unprototyped_externs, float_loads, placeholder_arguments,
                 float_pointer_arguments):
        out = step(out)
    return out if out != source else None
