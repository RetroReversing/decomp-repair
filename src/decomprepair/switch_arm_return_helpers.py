"""Switch arms that each do their work and return, written as a `static inline` helper per arm.

A message dispatcher of an N64 operating-system library (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, 150
instructions) switches on a message type into four arms, each of which calls the system and returns. The arms written in
place scored 3986: the second CSE kept the addresses of the arm's queues in saved registers and the function took one more
of them, which no change inside an arm undid. The same statements in one `static inline` function per arm, called as
`return helper(arg);`, were byte-identical. The original source is likely to have had one static function per message.
Why inlining stops the address sharing is a hypothesis (the body is expanded by integrate.c after it was compiled on its
own), not confirmed in the compiler source.

`switch_arm_return_helpers`
    For each `switch` of the function: every top-level `case K:` arm that ends in `return`, makes a call and has no
    `break`, `continue`, `goto`, label or nested `switch` moves into a `static inline` helper before the function, with
    the function's return type, the function's parameters the arm names as its parameters, and the arm-private locals
    declared inside it. Children: all those arms at once, then (with two or more) each arm alone.

A local the arm uses must be one it declares itself, or one whose first mention in the arm is a plain assignment and
whose address no other part of the function takes: the arm returns, so nothing after it reads the value. The exact judge
decides.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .switch_arm_helper import _arms, _parameters

FAMILY = 'switch_arm_return_helpers'
FAMILIES = (FAMILY,)
SINGLES = 8
NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}
DECLARATION = re.compile(
    r'(?:^|(?<=[;{}]))\s*(?P<type>(?:(?:register|unsigned|signed|struct|union|enum|const|volatile)\s+)*'
    r'(?!(?:return|goto|else|case|do)\b)' + IDENT + r'(?:\s+|\s*\*[\s*]*))(?P<name>' + IDENT + r')\s*(?=[;=\[,])')


def _declared(text):
    """`name -> [(type text, start, end, is a lone `type name;`)]` for the declarations written in `text`."""
    found = {}
    for hit in DECLARATION.finditer(text):
        semicolon = re.match(r'\s*;', text[hit.end():])
        stop = hit.end() + semicolon.end() if semicolon else hit.end()
        found.setdefault(hit['name'], []).append((hit['type'].strip(), hit.start('type'), stop, bool(semicolon)))
    return found


def _returns(clean, source, start, stop):
    """The arm's statements as (start, stop) without a block around all of them, or None when it doesn't qualify."""
    while start < stop and clean[start].isspace():
        start += 1
    while stop > start and clean[stop - 1].isspace():
        stop -= 1
    if start < stop and clean[start] == '{' and close(clean, start, '{', '}') == stop:
        start, stop = start + 1, stop - 1
    text = clean[start:stop]
    if (not re.search(r'(?:^|[;{}])\s*return\b[^;{}]*;\s*$', text)
            or re.search(r'\b(?:break|continue|goto|case|default|switch|static)\b', text)
            or re.search(r'(?:^|[;{}])\s*' + IDENT + r'\s*:(?!:)', text) or text.count('{') != text.count('}')):
        return None
    if not any(word not in NOT_CALLS for word in re.findall(r'(' + IDENT + r')\s*\(', text)):
        return None
    return start, stop


def _declaration(kind, word):
    return f'{kind}{"" if kind.endswith("*") else " "}{word}'


def _helper(source, clean, name, kind, label, arm, parameters, function, taken):
    """(helper definition, the call's arguments, the function's declarations the arm took with it) or None."""
    start, stop = arm
    text = clean[start:stop]
    used = []
    for hit in re.finditer(IDENT, text):
        before = text[:hit.start()].rstrip()
        if not before.endswith(('.', '->')) and hit[0] not in used:
            used.append(hit[0])
    own = _declared(text)
    locals_ = _declared(function['clean'])
    rest = function['clean'][:start - function['at']] + function['clean'][stop - function['at']:]
    moved = []
    for word in used:
        if word in own or word in parameters or word not in locals_:
            continue
        entries = locals_[word]
        first = re.search(r'(?<![\w.>])' + word + r'\b', text)
        assigned = (re.match(r'\s*=(?!=)', text[first.end():])
                    and re.search(r'(?:^|[;{}])\s*$', text[:first.start()]))
        if (len(entries) != 1 or not entries[0][3] or not assigned
                or re.search(r'(?<!&)&\s*' + word + r'\b', rest)
                or len(re.findall(r'\b' + word + r'\b', text[:text.find(';', first.end())])) != 1):
            return None
        moved.append(word)
    passed = [p for p in parameters if p in used and p not in own]
    if any(re.search(r'&\s*' + p + r'\b(?!\s*[\[.])', function['clean'].replace('&&', '  ')) for p in passed):
        return None
    base = f'{name}_case_{label}'
    helper, n = base, 2
    while helper in taken or re.search(r'\b' + helper + r'\b', source):
        helper, n = f'{base}_{n}', n + 1
    taken.add(helper)
    signature = ', '.join(_declaration(parameters[p], p) for p in passed) or 'void'
    body = [f'  {_declaration(locals_[word][0][0], word)};' for word in moved]
    lines = source[start:stop].strip('\n').rstrip().split('\n')
    indent = min((len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()), default=0)
    body.append('  ' + lines[0].strip())
    body += ['  ' + line[indent:] if line.strip() else '' for line in lines[1:]]
    definition = f'static inline {kind} {helper}({signature})\n{{\n' + '\n'.join(body) + '\n}\n\n'
    call = f'{helper}({", ".join(passed)})'
    return definition, call, moved


def _apply(source, clean, span, opening, kind, chosen):
    definitions = ''.join(item['definition'] for item in chosen)
    edits = [(span[0], span[0], definitions)]
    for item in chosen:
        call = f' {item["call"]};\n      return;' if kind == 'void' else f' return {item["call"]};'
        tail = source[item['body']:item['stop']]
        edits.append((item['body'], item['stop'], call + tail[len(tail.rstrip()):]))
    # a declaration only the moved arms named goes with them
    kept = clean[opening:span[1]]
    for item in chosen:
        low, high = item['body'] - opening, item['stop'] - opening
        kept = kept[:low] + ' ' * (high - low) + kept[high:]
    declarations = _declared(clean[opening:span[1]])
    for word in sorted({w for item in chosen for w in item['moved']}):
        if len(re.findall(r'\b' + word + r'\b', kept)) == 1:
            _, low, high, _ = declarations[word][0]
            low, high = opening + low, opening + high
            line = source.rfind('\n', 0, low) + 1
            end = source.find('\n', high)
            if not source[line:low].strip() and not source[high:end].strip():
                low, high = line, end + 1
            edits.append((low, high, ''))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    clean = part.clean
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:part.opening])
    if not head:
        return []
    kind = ' '.join(w for w in clean[span[0]:span[0] + head.start()].replace('*', ' * ').split()
                    if w not in ('static', 'inline', 'extern'))
    if not kind or not re.fullmatch(r'[\w\s*]+', kind):
        return []
    parameters = _parameters(clean, span[0], part.opening, name)
    function = {'clean': clean[part.opening:part.end], 'at': part.opening}
    results = []
    for switch in re.finditer(r'\bswitch\s*\(', function['clean']):
        after = close(clean, part.opening + switch.end() - 1, '(', ')')
        brace = after and re.match(r'\s*{', clean[after:])
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        found, taken = [], set()
        for arm in _arms(clean, opening, end):
            if arm is None:
                continue
            start, body, stop = arm
            statements = _returns(clean, source, body, stop)
            if not statements:
                continue
            label = re.sub(r'\W+', '', clean[start + 4:body - 1]) or 'value'
            made = _helper(source, clean, name, kind, label, statements, parameters, function, taken)
            if made:
                found.append({'body': body, 'stop': stop, 'definition': made[0], 'call': made[1], 'moved': made[2]})
        if not found:
            continue
        groups = [found] + ([[item] for item in found[:SINGLES]] if len(found) > 1 else [])
        results.extend((FAMILY, _apply(source, clean, span, part.opening, kind, group)) for group in groups)
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # the registry: no caller wiring (registry.py)
