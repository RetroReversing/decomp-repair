"""m2c's tree of `==`/`!=` tests on one value, written back as the `if` / `else if` chain it came from.

A source that tests one value against a few numbers in turn (`if (x == 1) {A} else if (x == 2) {B} ...`) compiles to
a run of `beq`/`bne` whose arms the compiler's cross-jumping then shares: two arms that end in the same stores become
one block, and the register that still holds an earlier compare's number supplies a later arm's value. m2c reads that
graph back as a nested tree with the shared block reached by `goto`, and the borrowed registers as a local:

    mode = 1;                               if (kind == 1) {
    if (kind == 1) {                            gPage = 1;
        gPage = kind;                           gStep = 0;
        gStep = 0;                  ->      } else if (kind == 2) {
        return;                                 gPage = 2;
    }                                           gStep = 1;
    if (kind != 2) {                        } else if (kind == 3) {
        if (kind == 3) { ...; return; }         ...
        mode = 5;
        if (kind == 4) { ... } else { goto block_9; }
    } else {
    block_9:
        gPage = kind;
        gStep = mode;
    }

The tree is run once per tested number (and once for "none of them"): conditions are decided, forward `goto`s
followed, a local that only ever takes literals is replaced by the literal that reaches each read, and what each run
executes becomes that number's arm, in the order the numbers are first tested.

Matched on a 34-instruction SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 page selector: `goto_shared_tail` alone stopped one
register short (565 -> 5), and the chain written from the machine draft is exact (565 -> 0).

equality_ladder_chain
    The function's body, after any plain statements, is one tree of `if`s that all test one parameter or local against
    integer literals with `==` or `!=` (at least three distinct numbers), holding only expression statements,
    `return`s, forward `goto`s and labels. Two children: the tested value stored by an arm
    written as its number (`gPage = 2;`), and left as it was (`gPage = kind;`). Declined when the tree writes the
    tested value or takes its address, holds a loop or `switch`, or when the result would grow past a few times the
    tree's size.

A hypothesis like every family's; the judge decides.
"""
import re

from .goto_structure_repairs import parse, walk
from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'equality_ladder_chain'
FAMILIES = (FAMILY,)

MIN_VALUES = 3
MAX_VALUES = 16
MAX_STATEMENTS = 400
MAX_STEPS = 2000
_ID = r'[A-Za-z_]\w*'
_NUMBER = r'-?(?:0[xX][0-9A-Fa-f]+|[1-9]\d*|0)[uU]?'
_TEST = re.compile(rf'\s*(?P<name>{_ID})\s*(?P<op>==|!=)\s*(?P<value>{_NUMBER})\s*')
_INTEGER = r'(?:(?:unsigned|signed)\s+(?:char|short|int|long)|unsigned|signed|[su](?:8|16|32)|char|short|int|long)'
_WIDE = r'(?:s32|int|long|signed(?:\s+(?:int|long))?)'
_SET = re.compile(rf'\s*(?P<name>{_ID})\s*=\s*(?P<value>{_NUMBER})\s*;')
_DECLARATION = re.compile(rf'\s*(?!return\b|goto\b|else\b)(?:(?:static|const|volatile|register|struct|union|enum|'
                          rf'unsigned|signed)\s+)*{_ID}(?:\s+|\s*\*+\s*)(?={_ID}\s*[;=,\[]){_ID}')


class _Decline(Exception):
    pass


def _written(name, text):
    return re.search(rf'(?<![\w.>]){name}\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^\-])?=(?!=))|(?:\+\+|--)\s*{name}\b|'
                     rf'(?<!&)&\s*{name}\b', text)


def _constant_locals(clean, body_start, body_end):
    """{name: (declaration start, end, initial literal or None)} for integer locals that only ever take literals."""
    body = clean[body_start:body_end]
    found = {}
    pattern = re.compile(rf'(?m)^[ \t]*(?P<type>{_INTEGER})\s+(?P<name>{_ID})\s*(?:=\s*(?P<value>{_NUMBER})\s*)?;[ \t]*\n?')
    for hit in pattern.finditer(body):
        name = hit['name']
        rest = body[:hit.start()] + ' ' * (hit.end() - hit.start()) + body[hit.end():]
        if re.search(rf'(?<!&)&\s*{name}\b|(?:\+\+|--)\s*{name}\b|(?<![\w.>]){name}\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^\-])=)',
                     rest):
            continue
        sets = re.findall(rf'(?<![\w.>]){name}\s*=(?!=)', rest)
        literal = re.findall(rf'(?:^|[;{{}}:])\s*{name}\s*=\s*{_NUMBER}\s*;', rest)
        if len(sets) != len(literal) or not (sets or hit['value']):
            continue
        values = [v for v in (hit['value'], *(re.findall(rf'(?<![\w.>]){name}\s*=\s*({_NUMBER})\s*;', rest))) if v]
        # A narrow or unsigned local converts what it is given: only numbers every integer type holds as they are.
        if not re.fullmatch(_WIDE, hit['type']) and not all(0 <= int(v.rstrip('uU'), 0) <= 127 for v in values):
            continue
        found[name] = (body_start + hit.start(), body_start + hit.end(), hit['value'])
    return found


class _Tree:
    def __init__(self, source, clean, stmts, selector, constants, spelled):
        self.source, self.clean, self.selector, self.constants = source, clean, selector, constants
        self.spelled = spelled
        self.labels, self.where = {}, {}
        self._index(stmts, ())

    def _index(self, stmts, follow):
        for i, s in enumerate(stmts):
            here = ((stmts, i), *follow)
            self.where[id(s)] = here
            if s.kind == 'label':
                if s.parts['name'] in self.labels:
                    raise _Decline
                self.labels[s.parts['name']] = here
            elif s.kind == 'if':
                after = ((stmts, i + 1), *follow)
                for key in ('then', 'other'):
                    if s.parts[key]:
                        self._index(s.parts[key]['stmts'], after)
            elif s.kind not in ('simple', 'goto'):
                raise _Decline

    def run(self, stmts, value, literal, env):
        """The statements the tree executes when the selector is `value` (None: none of the tested numbers)."""
        out, stack, steps = [], [(stmts, 0)], 0
        env = dict(env)
        while stack:
            block, i = stack.pop()
            if i >= len(block):
                continue
            steps += 1
            if steps > MAX_STEPS:
                raise _Decline
            s = block[i]
            stack.append((block, i + 1))
            if s.kind == 'if':
                test = _TEST.fullmatch(self.clean[s.parts['cond'][0]:s.parts['cond'][1]])
                if not test or test['name'] != self.selector:
                    raise _Decline
                equal = value is not None and _number(test['value']) == value
                part = s.parts['then'] if equal == (test['op'] == '==') else s.parts['other']
                if part:
                    stack.append((part['stmts'], 0))
            elif s.kind == 'goto':
                target = self.labels.get(s.parts['target'])
                if not target or target[0][0][target[0][1]].start < s.start:
                    raise _Decline
                # The place after the label in its block, then whatever follows that block.
                stack = [*reversed(target[1:]), (target[0][0], target[0][1] + 1)]
            elif s.kind == 'simple':
                code = self.clean[s.start:s.end]
                setting = _SET.fullmatch(code)
                if setting and setting['name'] in self.constants:
                    env[setting['name']] = setting['value']
                    continue
                if _written(self.selector, code) or _DECLARATION.match(code):
                    raise _Decline
                out.append(self._text(s, code, value if literal else None, env))
                if re.match(r'\s*return\b', code):
                    return out
        return out

    def _text(self, s, code, value, env):
        edits = []
        for name in self.constants:
            for hit in re.finditer(rf'(?<![\w.>]){name}\b', code):
                if env.get(name) is None:
                    raise _Decline
                number = env[name]
                edits.append((hit.start(), hit.end(), f'({number})' if number.startswith('-') else number))
        if value is not None:
            read = re.search(rf'(?<![=!<>+\-*/%&|^])=\s*(?:\(\s*{_ID}\s*\**\s*\)\s*)?(?P<read>{self.selector})\s*;', code)
            if read:
                edits.append((*read.span('read'), self.spelled[value]))
        text = self.source[s.start:s.end]
        for start, end, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[end:]
        return text.strip()


def _number(text):
    """The 32-bit word a literal compares as, so `-1` and `0xFFFFFFFF` are one number."""
    return int(text.rstrip('uU'), 0) & 0xFFFFFFFF


def _indent(source, at):
    start = source.rfind('\n', 0, at) + 1
    lead = source[start:at]
    return lead if not lead.strip() else '    '


def _arm(lines, pad):
    return ''.join(f'{pad}    {line}\n' for line in lines)


def _chain(source, tree, stmts, values, selector, literal, env, pad):
    runs = {value: tree.run(stmts, value, literal, env) for value in (*values, None)}
    for value, lines in runs.items():
        if lines and lines[-1] == 'return;':
            runs[value] = lines[:-1]
    if sum(len(lines) for lines in runs.values()) > MAX_STATEMENTS:
        raise _Decline
    arms = [value for value in values if runs[value] != runs[None]]
    if len(arms) < MIN_VALUES:
        raise _Decline
    text = ''
    for value in arms:
        lead = 'if' if not text else f'{pad}}} else if'
        text += f'{lead} ({selector} == {tree.spelled[value]}) {{\n' + _arm(runs[value], pad)
    if runs[None]:
        text += f'{pad}}} else {{\n' + _arm(runs[None], pad)
    return text + f'{pad}}}'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        function = parse(part.clean, part.opening + 1, end - 1)
    except (ValueError, RecursionError):
        return []
    first = next((i for i, s in enumerate(function) if s.kind == 'if'), None)
    if first is None:
        return []
    test = _TEST.fullmatch(part.clean[function[first].parts['cond'][0]:function[first].parts['cond'][1]])
    if not test:
        return []
    selector = test['name']
    header = part.clean[:part.opening]
    body = part.clean[part.opening:end]
    owned = (re.search(rf'{name}\s*\([^()]*\b{selector}\s*[,)]', header)
             or re.search(rf'(?m)^[ \t]*(?:{_INTEGER}|{_ID}\s*\*+)\s*{selector}\s*[;=]', body))
    if not owned or re.search(rf'(?<!&)&\s*{selector}\b|\bvolatile\b[^;\n]*\b{selector}\b', body):
        return []
    values, spelled = [], {}
    for s, _ in walk(function[first:]):
        if s.kind != 'if':
            continue
        found = _TEST.fullmatch(part.clean[s.parts['cond'][0]:s.parts['cond'][1]])
        if not found or found['name'] != selector:
            return []
        value = _number(found['value'])
        if value not in spelled:
            values.append(value)
            spelled[value] = found['value']
    if not MIN_VALUES <= len(values) <= MAX_VALUES:
        return []
    constants = _constant_locals(part.clean, part.opening + 1, end - 1)
    constants.pop(selector, None)
    # The statements before the tree stay as they are; a constant local's literal there is what reaches the tree.
    env = {key: found[2] for key, found in constants.items()}
    removed = [(start, end) for start, end, _ in constants.values()]
    for s in function[:first]:
        code = part.clean[s.start:s.end]
        if s.kind != 'simple':
            return []
        setting = _SET.fullmatch(code)
        if setting and setting['name'] in constants:
            env[setting['name']] = setting['value']
            removed.append((source.rfind('\n', 0, s.start) + 1, s.end + (source[s.end:s.end + 1] == '\n')))
        elif any(re.search(rf'(?<![\w.>]){key}\b', code) for key in constants
                 if not any(a <= s.start < b for a, b, _ in constants.values())):
            return []
    result = []
    try:
        tree = _Tree(source, part.clean, function[first:], selector, constants, spelled)
        pad = _indent(source, function[first].start)
        for literal in (True, False):
            chain = _chain(source, tree, function[first:], values, selector, literal, env, pad)
            text = source[:function[first].start] + chain + source[function[-1].end:]
            for start, end in sorted(removed, reverse=True):
                text = text[:start] + text[end:]
            text = re.sub(r'\{\n(?:[ \t]*\n)+', '{\n', text)
            if text != source and all(text != other for _, other in result):
                result.append((FAMILY, text))
    except _Decline:
        return []
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
