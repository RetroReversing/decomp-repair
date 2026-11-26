"""m2c's dispatch tree whose last case is the code after it, read back as the `switch` it came from.

gcc lowers a small `switch` to a tree of comparisons and lays the case bodies out after it. m2c writes the tree as
nested `if`s, but one case's body ends up *behind* the tree (the tree "falls through" into it), and the other arms
leave through `return` or through `goto`s into that body:

    if (v != 1) {                                   switch (v) {
        if (v >= 2) {                               case 0:
            if (v != 2) { return; }                     f();
            if (x > 0) { x--; }                         return;
            else { s = 1; goto block_15; }          case 1:
            goto block_16;                              if (x < K) { x++; } else { s = 2; store = s; }
        }                                               break;
        if (v != 0) { return; }                     case 2:
        f(); return;                                    if (x > 0) { x--; } else { s = 1; store = s; }
    }                                                   break;
    if (x < K) { x++; }                             default:
    else { s = 2; block_15: store = s; }                return;
    block_16:                                       }
    tail();                                         tail();

`if_tree_switch` and `embedded_if_tree_switch` read trees whose arms neither jump nor fall into later code, so this
shape had no child. The tree's meaning is worked out for each interval of the value: the values that run through to the
code after the tree are that code's case, the rest are their own arms, and the group both ends of the line share is
the default. The last label of that code that stands at the function body's level begins the shared tail: it goes after
the switch and `goto` to it becomes `break`. A `goto` into the middle of the fallen-into code is written out as the
statements from the label to the tail (cross-jumping merges the copies again). A second child keeps the `goto`s.

A 94-instruction N64 state routine (KMC GCC 2.7.2 `-O1`) was exact from its machine draft with this switch, its record
arrays and three more library steps. The exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'dispatch_fallthrough_switch'
FAMILIES = (FAMILY,)

TEST = re.compile(r'^\s*(?:\(\s*(?:s32|u32|int)\s*\)\s*)?([A-Za-z_]\w*)\s*(==|!=|<=|>=|<|>)\s*'
                  r'(-?(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*\s*$')
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b,
       '<=': lambda a, b: a <= b, '>': lambda a, b: a > b, '>=': lambda a, b: a >= b}
GOTO = re.compile(r'\bgoto\s+([A-Za-z_]\w*)\s*;')
LOOP = re.compile(r'\b(?:for|while|do|switch)\b')
SPACE = re.compile(r'\s*')
MARK = re.compile(r'[()\[\]{};]')
MAX_CASE_VALUES = 8
DEPTH = 4  # labels written out inside labels written out


class _Bail(Exception):
    pass


class _Node:
    def __init__(self, kind, start, end, **more):
        self.kind, self.start, self.end = kind, start, end
        self.__dict__.update(more)


def _skip(clean, at, end):
    return SPACE.match(clean, at, end).end()


def _closed(clean, at, pair='()'):
    stop = close(clean, at, *pair)
    if not stop:
        raise _Bail
    return stop


def _statement(clean, at, end):
    """The statement at `at` (not a space): a node."""
    if clean[at] == '{':
        stop = _closed(clean, at, '{}')
        return _Node('block', at, stop, items=_statements(clean, at + 1, stop - 1))
    label = re.compile(r'([A-Za-z_]\w*)\s*:(?!:)').match(clean, at, end)
    if label and label[1] not in ('case', 'default'):
        return _Node('label', at, label.end(), name=label[1])
    word = re.compile(r'(if|for|while|switch|do)\b').match(clean, at, end)
    if word and word[1] == 'do':
        body = _statement(clean, _skip(clean, word.end(), end), end)
        stop = clean.find(';', body.end, end)
        if stop < 0:
            raise _Bail
        return _Node('plain', at, stop + 1)
    if word:
        opening = _skip(clean, word.end(), end)
        if clean[opening:opening + 1] != '(':
            raise _Bail
        after = _closed(clean, opening)
        body = _statement(clean, _skip(clean, after, end), end)
        if word[1] != 'if':
            return _Node('plain', at, body.end)
        other, stop = None, body.end
        follow = _skip(clean, body.end, end)
        if re.compile(r'else\b').match(clean, follow, end):
            other = _statement(clean, _skip(clean, follow + 4, end), end)
            stop = other.end
        return _Node('if', at, stop, condition=clean[opening + 1:after - 1], then=body, other=other)
    depth = 0
    for hit in MARK.finditer(clean, at, end):
        depth += (hit[0] in '([{') - (hit[0] in ')]}')
        if hit[0] == ';' and depth == 0:
            return _Node('plain', at, hit.end())
    raise _Bail


def _statements(clean, at, end):
    items = []
    at = _skip(clean, at, end)
    while at < end:
        node = _statement(clean, at, end)
        items.append(node)
        at = _skip(clean, node.end, end)
    return items


def _inside(node):
    """The statements of a branch."""
    if node is None:
        return []
    return node.items if node.kind == 'block' else [node]


def _tested(node, var):
    return node.kind == 'if' and (test := TEST.match(node.condition)) is not None and test[1] == var


def _values(node, var, found, tests):
    if not _tested(node, var):
        return
    test = TEST.match(node.condition)
    constant = int(test[3], 0)
    tests.append(test[0])
    if test[2] in ('==', '!='):
        found.update((constant, constant + 1))
    elif test[2] in ('<', '>='):
        found.add(constant)
    else:
        found.add(constant + 1)
    for child in _inside(node.then) + _inside(node.other):
        _values(child, var, found, tests)


def _walk(clean, items, var, value, out):
    """The statements a value runs, appended to `out`; True when it leaves by `return` or `goto`."""
    for node in items:
        if _tested(node, var):
            test = TEST.match(node.condition)
            branch = node.then if OPS[test[2]](value, int(test[3], 0)) else node.other
            if _walk(clean, _inside(branch), var, value, out):
                return True
            continue
        if node.kind == 'label':
            raise _Bail
        text = clean[node.start:node.end]
        if re.search(r'(?<![\w.>])' + re.escape(var) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text):
            raise _Bail
        out.append(node)
        if node.kind == 'plain' and re.match(r'(?:return|goto)\b', text):
            return True
    return False


def _continuation(items, name, trail=()):
    """The statements that run after label `name` among `items`, to the end of those items; None when absent."""
    for index, node in enumerate(items):
        after = tuple(items[index + 1:])
        if node.kind == 'label' and node.name == name:
            return list(after) + list(trail)
        branches = ([node] if node.kind == 'block' else [node.then, node.other] if node.kind == 'if' else [])
        for branch in branches:
            if branch is None:
                continue
            found = _continuation(_inside(branch), name, after + tuple(trail))
            if found is not None:
                return found
    return None


class _Writer:
    def __init__(self, source, clean, head, tail_label):
        self.source, self.clean, self.head, self.tail = source, clean, head, tail_label

    def text(self, node, seen=()):
        """The node's source with its `goto`s replaced and the labels dropped."""
        if node.kind == 'label':
            return ''
        start, end = node.start, node.end
        found = list(GOTO.finditer(self.clean, start, end))
        labels = []
        stack = [node]
        while stack:
            item = stack.pop()
            if item.kind == 'label':
                labels.append((item.start, item.end, ''))
            elif item.kind == 'block':
                stack += item.items
            elif item.kind == 'if':
                stack += [child for child in (item.then, item.other) if child]
        if found and LOOP.search(self.clean, start, end):
            raise _Bail  # `break` would leave the loop, not the switch
        edits = labels + [(hit.start(), hit.end(), self.jump(hit, start, seen)) for hit in found]
        out, at = [], start
        for left, right, new in sorted(edits):
            out.append(self.source[at:left])
            out.append(new)
            at = right
        out.append(self.source[at:end])
        return ''.join(out)

    def jump(self, hit, start, seen):
        name = hit[1]
        if name == self.tail:
            return 'break;'
        run = _continuation(self.head, name)
        if run is None or name in seen or len(seen) >= DEPTH:
            raise _Bail
        parts = [self.text(node, (*seen, name)) for node in run]
        if not _leaves(self.clean, run):
            parts.append('break;')
        joined = ' '.join(part.strip() for part in parts if part.strip())
        before = self.clean[:hit.start()].rstrip()
        braced = before.endswith(')') or re.search(r'\belse$', before)  # a braceless branch holds one statement
        return '{ ' + joined + ' }' if braced else joined


def _leaves(clean, nodes):
    last = next((node for node in reversed(nodes) if node.kind != 'label'), None)
    return bool(last and last.kind == 'plain' and re.match(r'(?:return|goto)\b', clean[last.start:last.end]))


def _lines(parts, indent):
    out = []
    for part in parts:
        lines = [line.strip() for line in part.split('\n') if line.strip()]
        depth = 0
        for line in lines:
            if line.startswith('}'):
                depth -= 1
            out.append(indent + '    ' * max(depth, 0) + line + '\n')
            depth += line.count('{') - line.count('}') + (1 if line.startswith('}') else 0)
    return ''.join(out)


def _number(value):
    return str(value) if -10 < value < 10 else hex(value)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    try:
        items = _statements(clean, opening + 1, end - 1)
        at, tree = next(((index, node) for index, node in enumerate(items)
                         if node.kind == 'if' and TEST.match(node.condition)), (None, None))
        if tree is None:
            return []
        var = TEST.match(tree.condition)[1]
        rest = items[at + 1:]
        if not rest:
            return []
        found, tests = set(), []
        _values(tree, var, found, tests)
        if len(tests) < 2:
            return []  # one test is an `if`
        starts = [min(found) - 1] + sorted(found)
        paths = []
        for value in starts:
            out = []
            left = _walk(clean, [tree], var, value, out)
            paths.append((tuple((node.start, node.end) for node in out), not left, out))
        key = lambda path: (tuple(clean[a:b] for a, b in path[0]), path[1])  # noqa: E731
        default = key(paths[0])
        if key(paths[-1]) != default:
            return []
        groups = []  # [key, path, values]
        for index, value in enumerate(starts):
            if key(paths[index]) == default:
                continue
            last = starts[index + 1] - 1
            if last - value + 1 > MAX_CASE_VALUES:
                return []
            for group in groups:
                if group[0] == key(paths[index]):
                    group[2].extend(range(value, last + 1))
                    break
            else:
                groups.append([key(paths[index]), paths[index], list(range(value, last + 1))])
        groups.append([default, paths[0], None])
        falls = [group for group in groups if group[1][1]]
        if len(falls) != 1 or len(groups) < 3:
            return []  # (the arms that leave and the one that runs on, or it is an `if`/`else`)

        targets = set()
        for group in groups:
            for node in group[1][2]:
                targets.update(GOTO.findall(clean[node.start:node.end]))
        if any(_continuation(rest, target) is None for target in targets):
            return []
        tails = [index for index, node in enumerate(rest) if node.kind == 'label' and node.name in targets]
        cut = tails[-1] if tails else len(rest)
        head, tail = rest[:cut], rest[cut + 1:]
        tail_label = rest[cut].name if tails else None
        if any(node.kind == 'label' for node in tail):
            return []
        writer = _Writer(source, clean, head, tail_label)

        line = source.rfind('\n', 0, tree.start) + 1
        indent = re.match(r'[ \t]*', source[line:tree.start])[0]
        inner = indent + '    '
        result = []
        for keep in (False, True):
            if keep and not targets:
                break
            body = 'switch (' + var + ') {\n'
            for group in sorted(groups, key=lambda g: (g[2] is None, g[2][0] if g[2] else 0)):
                for value in group[2] if group[2] is not None else []:
                    body += indent + f'case {_number(value)}:\n'
                if group[2] is None:
                    body += indent + 'default:\n'
                nodes = list(group[1][2])
                if group[1][1]:
                    nodes += rest if keep else head
                if keep:
                    parts = [source[node.start:node.end] for node in nodes]
                else:
                    parts = [writer.text(node) for node in nodes]
                body += _lines(parts, inner)
                if not _leaves(clean, nodes):
                    body += inner + 'break;\n'
            body += indent + '}'
            if not keep and tail:
                body += '\n' + _lines([source[tail[0].start:tail[-1].end]], indent).rstrip('\n')
            text = source[:tree.start] + body + '\n' + source[end - 1:]
            if all(text != other for _, other in result):
                result.append((FAMILY, text))
        return result
    except _Bail:
        return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
