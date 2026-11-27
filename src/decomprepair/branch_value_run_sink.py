"""Statements that use a value both arms of an `if`/`else` set, written out in each arm.

When both arms of an `if` set a volume and then write it through a `volatile` pointer several times, GCC 2.8.1 merges
the arms' identical tails itself, from the first store on: only the first load of the pointer and the constant differ.
m2c reads the merged form back as a value picked by the branch and used after it:

    if (kind == 2) {
        v = 0x1199;
    } else {
        v = 0x1000;
    }
    voice->level = v;
    voice->level = v;
    voice->level = v;

and a compiler given that C allocates and schedules the diamond differently. An N64 function (SN GCC 2.8.1, -O2) was
645 from exact this way and 110 with each arm writing its own run (the last step to 0 was a compound store).
`carried_store_arms` handles one store of a variable each arm sets last; this takes the whole run, including stores an
arm already makes of the value before the join, and offers every such diamond of a function in one child (rewriting
only one of the two on that function scored worse than the seed).

A literal value (or a local initialised to one and never set again) is written into the moved statements when the
variable has no other use; the other child keeps the assignment in each arm. Only flat arms and flat statements move,
so no path runs anything it didn't run before, and the order within each path is the source's.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'branch_value_run_sink'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
LITERAL = r'-?(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_IF = re.compile(r'(?<![\w.])if\s*\(')
_LINE = re.compile(r'[ \t\r\n]*(?P<text>[^;{}#]+;)')
_ASSIGN = re.compile(r'\s*(?P<var>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;]+);\s*\Z')
_CONTROL = re.compile(r'(?<![\w.])(?:if|else|for|while|do|switch|case|default|goto|return|break|continue)\b|(?<!\?):(?!:)')
LIMIT = 8


def _skip(clean, at):
    while at < len(clean) and clean[at].isspace():
        at += 1
    return at


def _flat(text):
    """The `;`-terminated statements of a block with no nested braces, labels or control flow; None otherwise."""
    if '{' in text or '}' in text or '#' in text:
        return None
    parts = text.split(';')
    if parts[-1].strip():
        return None
    statements = [part + ';' for part in parts[:-1]]
    if any(_CONTROL.search(item) and '?' not in item for item in statements):
        return None
    return statements


def _word(name):
    return re.compile(r'(?<![\w.])(?<!->)' + re.escape(name) + r'\b')


def _writes(name, text):
    word = re.escape(name)
    return re.search(r'(?<![\w.>])' + word + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--|(?<!&)&)\s*' + word
                     + r'\b|(?<![\w.>])' + word + r'\s*(?:\+\+|--)', text)


def _diamonds(clean, start, end):
    """(if start, then-body span, else-body span, position after the else arm) for every braced if/else."""
    for hit in _IF.finditer(clean, start, end):
        after = close(clean, hit.end() - 1)
        if after is None:
            continue
        first = _skip(clean, after)
        if clean[first:first + 1] != '{':
            continue
        first_end = close(clean, first, '{', '}')
        if first_end is None:
            continue
        keyword = re.compile(r'\s*else\s*\{').match(clean, first_end)
        if not keyword:
            continue
        second = keyword.end() - 1
        second_end = close(clean, second, '{', '}')
        if second_end is None:
            continue
        yield hit.start(), (first + 1, first_end - 1), (second + 1, second_end - 1), second_end


def _arm(source, clean, span):
    """(variable, value, statements before, statements after the assignment) of one arm, for each assigned local."""
    statements = _flat(clean[span[0]:span[1]])
    if not statements:
        return []
    texts, at = [], span[0]
    for statement in statements:
        texts.append(source[at:at + len(statement)].strip())
        at += len(statement)
    found = []
    for index, statement in enumerate(statements):
        assigned = _ASSIGN.match(statement)
        if not assigned:
            continue
        var = assigned['var']
        rest = statements[index + 1:]
        if any(not _word(var).search(item) or _writes(var, item) for item in rest):
            continue
        if any(_word(var).search(item) for item in statements[:index]):
            continue
        value = _ASSIGN.match(texts[index])
        if value:
            found.append((var, value['value'].strip(), texts[:index], texts[index + 1:]))
    return found


def _run(source, clean, at, var):
    """The statements straight after the if/else that read `var` without writing it: (texts, end position)."""
    texts, end = [], at
    while True:
        hit = _LINE.match(clean, end)
        if not hit:
            break
        statement = hit['text']
        if _CONTROL.search(statement) or not _word(var).search(statement) or _writes(var, statement):
            break
        texts.append(source[hit.start('text'):hit.end('text')].strip())
        end = hit.end()
    return texts, end


def _constant(body, value):
    """`value` as a literal: itself, or what the local of that name was initialised to when nothing sets it again."""
    if re.fullmatch(LITERAL, value):
        return value
    if not re.fullmatch(IDENT, value):
        return None
    declared = re.findall(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t]+)+' + value + r'[ \t]*=[ \t]*(' + LITERAL + r')[ \t]*;', body)
    writes = len(re.findall(r'(?<![\w.>])' + value + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--|(?<!&)&)\s*' + value
                            + r'\b|(?<![\w.>])' + value + r'\s*(?:\+\+|--)', body))
    return declared[0] if len(declared) == 1 and writes == 1 else None


def _sites(source, clean, start, end):
    """(from, to, {'literal': text, 'kept': text}) for every diamond whose run can move into its arms."""
    body = clean[start:end]
    sites = []
    for _, first, second, after in _diamonds(clean, start, end):
        left, right = _arm(source, clean, first), _arm(source, clean, second)
        for var, value, before, own in left:
            other = next((item for item in right if item[0] == var), None)
            if not other:
                continue
            run, stop = _run(source, clean, after, var)
            # one store after arms that end with the assignment is `carried_store_arms`
            if not run or (len(run) < 2 and not own and not other[3]):
                continue
            arms = [(first, value, before, own), (second, other[1], other[2], other[3])]
            # `var` must be a local of this function that nothing reads after the run
            outside = clean[stop:end]
            later = _word(var).search(outside)
            declared = re.search(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t*]+)+' + var + r'[ \t]*(?:=[^;]*)?;', body)
            live = bool(later) and not re.match(r'\s*=(?!=)', outside[later.end():])
            forms = {}
            for form in ('literal', 'kept'):
                if form == 'literal':
                    values = [_constant(body, item[1]) for item in arms]
                    if live or later or not declared or None in values:
                        continue
                rebuilt = []
                for number, (span, written, head, tail) in enumerate(arms):
                    moved = [*tail, *run]
                    if form == 'literal':
                        moved = [_word(var).sub(values[number], item) for item in moved]
                        lines = [*head, *moved]
                    else:
                        lines = [*head, f'{var} = {written};', *moved]
                    old = source[span[0]:span[1]]
                    pad = re.search(r'\n([ \t]+)\S', old)
                    pad = pad[1] if pad else '        '
                    closing = old[old.rfind('\n'):] if '\n' in old else '\n    '
                    rebuilt.append(''.join(f'\n{pad}{line}' for line in lines) + closing)
                text = (source[_start(clean, first):first[0]] + rebuilt[0] + source[first[1]:second[0]] + rebuilt[1]
                        + source[second[1]:after])
                forms[form] = text
            if forms:
                sites.append((_start(clean, first), stop, forms))
            break
    return sites


def _start(clean, first):
    """Where the `if` that owns the then-body at `first` starts."""
    return max(hit.start() for hit in _IF.finditer(clean, 0, first[0]))


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = _sites(source, clean, opening, end)
    if not sites:
        return []
    apart = []
    for site in sorted(sites, key=lambda item: item[:2]):
        if not apart or site[0] >= apart[-1][1]:
            apart.append(site)
    result = []
    for form, other in (('literal', 'kept'), ('kept', 'literal')):
        if len(apart) > 1:
            result.append(_apply(source, [(start, stop, forms.get(form, forms.get(other)))
                                          for start, stop, forms in apart]))
    for start, stop, forms in apart:
        result += [_apply(source, [(start, stop, text)]) for text in forms.values()]
    return [(FAMILY, text) for text in dict.fromkeys(result) if text != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 500}
