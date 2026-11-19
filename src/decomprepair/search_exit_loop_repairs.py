"""Search loops m2c turned inside out, with the found case put back inside the loop.

gcc 2.7.2 lays a search out with the found case first in the loop body and the step after it. m2c reads that back as
a loop on "not found" with the found case after it, or as a `for (;;)` with a `goto` to the shared step:

    while (*(s16 *)p != arg0) {          for (;;) {
        i += 1;                              v = ...;
        p += 2;                              if (A) { i += 1; goto block_8; }
        if (i >= 0x20U) {                    if (B) { break; }
            return;                          i += 1;
        }                                block_8:
    }                                        w = i & 0xFF;
    D = i;                                   if (w >= 0x1EU) { return 0; }
                                         }
                                         return 1;

An N64 function of each shape was 35% and 34% so; written with the found case inside, `do { if (*p == arg0) { D = i;
return; } i += 1; p += 2; } while (i < 0x20U);`, the first was exact, and the second came to 80% (exact once its masked
counter is a `u8`). Both rewrites keep the meaning: the same tests in the same order, the same steps.

`found_inside_loop`: a `while (C) { STEPS; if (E) { return R; } }` followed only by the function's remaining statements
(and its end). `shared_step_loop`: m2c's `for (;;)` with an `if (A) { S; goto L; } if (B) { break; } S; L:` body.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FOUND = 'found_inside_loop'
SHARED = 'shared_step_loop'
BREAK = 'break_search_loop'
FAMILIES = (FOUND, SHARED, BREAK)

IDENT = r'[A-Za-z_]\w*'
SIMPLE = r'(?:[ \t]*[^\n{}:]*;[ \t]*\n)'


def _not(condition):
    condition = condition.strip()
    flipped = negate(condition)
    if flipped:
        return flipped
    # `!(X)` as a whole (its opening parenthesis closes at the end) is X
    if condition.startswith('!') and condition[1:].lstrip().startswith('('):
        at = condition.index('(')
        if close(condition, at) == len(condition):
            return condition[at + 1:-1].strip()
    return f'!({condition})'


def _balanced(text):
    depth = 0
    for ch in text:
        depth += (ch == '(') - (ch == ')')
        if depth < 0:
            return False
    return depth == 0


def _lines(text, indent):
    return ''.join(indent + line.strip() + '\n' for line in text.splitlines() if line.strip())


def _condition_at(clean, keyword_end):
    """(open, close) of the parenthesised condition that starts right after a keyword."""
    opening = clean.find('(', keyword_end)
    if opening < 0 or clean[keyword_end:opening].strip():
        return None
    end = close(clean, opening)
    return (opening, end) if end else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    result += _found_inside(source, clean, opening, end)
    result += _shared_step(source, clean, opening, end)
    result += _break_search(source, clean, opening, end)
    return result[:4]


def _found_inside(source, clean, opening, end):
    result = []
    for loop in re.finditer(r'(?m)^(?P<indent>[ \t]*)while\b', clean[:end]):
        if loop.start() <= opening:
            continue
        condition = _condition_at(clean, loop.end())
        if not condition:
            continue
        brace = re.match(r'\s*\{', clean[condition[1]:])
        if not brace:
            continue
        body_open = condition[1] + brace.end() - 1
        body_close = close(clean, body_open, '{', '}')
        if not body_close:
            continue
        body = clean[body_open + 1:body_close - 1]
        exit_ = re.search(r'(?s)\n(?P<i>[ \t]*)if\s*\((?P<e>.*)\)\s*\{\s*return(?P<r>[^;]*);\s*\}\s*$', body)
        if not exit_ or not _balanced(exit_['e']):
            continue
        steps = body[:exit_.start()]
        if not re.fullmatch(SIMPLE + '*', steps.lstrip('\n') + ('' if steps.endswith('\n') or not steps.strip() else '\n')):
            continue
        tail = clean[body_close:end - 1]
        # the rest of the function: plain statements, ending (when it returns a value) in its return
        if not tail.strip() or re.search(r'[{}]|\b(?:goto|case|default|break|continue)\b|^\s*\w+\s*:', tail, re.M):
            continue
        if re.search(r'\breturn\b', clean[body_open:body_close][:exit_.start()]):
            continue
        indent = loop['indent']
        inner = indent + '    '
        raw = lambda a, b: source[a:b]  # noqa: E731
        cond = raw(condition[0] + 1, condition[1] - 1)
        exit_cond = raw(body_open + 1 + exit_.start('e'), body_open + 1 + exit_.end('e'))
        returned = raw(body_open + 1 + exit_.start('r'), body_open + 1 + exit_.end('r')).strip()
        tail_text = raw(body_close, end - 1)
        ends_returning = re.search(r'\breturn\b[^;]*;\s*$', tail_text)
        found = _lines(tail_text, inner + '    ') + ('' if ends_returning else inner + '    return;\n')
        text = (source[:loop.start()]
                + f'{indent}do {{\n{inner}if ({_not(cond)}) {{\n' + found + f'{inner}}}\n'
                + _lines(raw(body_open + 1, body_open + 1 + exit_.start()), inner)
                + f'{indent}}} while ({_not(exit_cond)});\n'
                + (f'{indent}return {returned};\n' if returned else '')
                + source[end - 1:])
        if text != source:
            result.append((FOUND, text))
    return result


SHARED_SHAPE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)for\s*\(\s*;\s*;\s*\)\s*\{[ \t]*\n'
    r'(?P<pre>' + SIMPLE + r'*?)'
    r'[ \t]*if \((?P<a>.*)\) \{[ \t]*\n(?P<s1>' + SIMPLE + r'*?)[ \t]*goto (?P<label>\w+);[ \t]*\n[ \t]*\}[ \t]*\n'
    r'[ \t]*if \((?P<b>.*)\) \{[ \t]*\n[ \t]*break;[ \t]*\n[ \t]*\}[ \t]*\n'
    r'(?P<s2>' + SIMPLE + r'*?)(?P=label):[ \t]*\n'
    r'(?P<step>' + SIMPLE + r'*?)'
    r'[ \t]*if \((?P<e>.*)\) \{[ \t]*\n[ \t]*return (?P<left>[^;\n]+);[ \t]*\n[ \t]*\}[ \t]*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*return (?P<found>[^;\n]+);[ \t]*\n')


def _shared_step(source, clean, opening, end):
    result = []
    for hit in SHARED_SHAPE.finditer(clean, opening, end):
        if ' '.join(hit['s1'].split()) != ' '.join(hit['s2'].split()):
            continue
        if len(re.findall(r'\bgoto\s+' + hit['label'] + r'\b', clean[opening:end])) != 1:
            continue
        if not all(_balanced(hit[g]) for g in ('a', 'b', 'e')):
            continue
        indent = hit['indent']
        inner = indent + '    '

        def raw(group, hit=hit):
            return source[hit.start(group):hit.end(group)]
        loop = (f'{indent}do {{\n' + _lines(raw('pre'), inner)
                + f'{inner}if (({_not(raw("a"))}) && ({raw("b").strip()})) {{\n'
                + f'{inner}    return {raw("found").strip()};\n{inner}}}\n'
                + _lines(raw('s1'), inner) + _lines(raw('step'), inner)
                + f'{indent}}} while ({_not(raw("e"))});\n'
                + f'{indent}return {raw("left").strip()};\n')
        result.append((SHARED, source[:hit.start()] + loop + source[hit.end():]))
    return result


BREAK_SHAPE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)for\s*\(\s*;\s*;\s*\)\s*\{[ \t]*\n'
    r'(?P<pre>' + SIMPLE + r'*?)'
    r'[ \t]*if \((?P<b>.*)\) \{[ \t]*\n[ \t]*break;[ \t]*\n[ \t]*\}[ \t]*\n'
    r'(?P<post>' + SIMPLE + r'*?)'
    r'[ \t]*if \((?P<e>.*)\) \{[ \t]*\n[ \t]*return (?P<left>[^;\n]+);[ \t]*\n[ \t]*\}[ \t]*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*return (?P<found>[^;\n]+);[ \t]*\n')


def _break_search(source, clean, opening, end):
    result = []
    for hit in BREAK_SHAPE.finditer(clean, opening, end):
        if not all(_balanced(hit[g]) for g in ('b', 'e')) or re.search(r'\b(?:break|continue|goto)\b', hit['pre'] + hit['post']):
            continue
        indent = hit['indent']
        inner = indent + '    '

        def raw(group, hit=hit):
            return source[hit.start(group):hit.end(group)]
        loop = (f'{indent}do {{\n' + _lines(raw('pre'), inner)
                + f'{inner}if ({raw("b").strip()}) {{\n{inner}    return {raw("found").strip()};\n{inner}}}\n'
                + _lines(raw('post'), inner)
                + f'{indent}}} while ({_not(raw("e"))});\n'
                + f'{indent}return {raw("left").strip()};\n')
        result.append((BREAK, source[:hit.start()] + loop + source[hit.end():]))
    return result
