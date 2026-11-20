"""Bounded C control-flow and lifetime edits selected by measured MIPS differences."""

import re

from .call_lifetime_repairs import block_path
from .csource import find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer, locals_for, plain_repair_view, refs
from .pattern_repairs import close
from .register_repairs import unwrap

SELECTOR = 'post_call_selector_initializer'
FIELD_GUARD = 'field_first_short_circuit'
TAIL_BOUND = 'loop_tail_bound'
INT_TYPE = rf'(?:{INTEGER}|unsigned|signed)'
LITERAL = rf'-?{NUMBER}'


def _prefix(part, index):
    return part.clean[part.opening+1:index].rstrip()[-1:] in ('', ';', '{', '}')


def automatic_integers(part, name):
    result = {d['name'] for d in locals_for(part)
              if not re.search(rf'(?<!&)&(?!&)\s*\(*\s*{d["name"]}\b',part.body)}
    span = find(part.source, name)
    if not span:
        return result
    signature = part.clean[span[0]:part.opening]
    for match in re.finditer(rf'\b{INT_TYPE}\s+({IDENT})\s*(?=[,)])', signature):
        token = match[1]
        if not re.search(rf'(?<!&)&(?!&)\s*\(*\s*{token}\b|\b{INT_TYPE}\s+{token}\b', part.body):
            result.add(token)
    return result


def _literal(text):
    token = text.lstrip('-')
    if token.isdigit() and len(token)>1 and token.startswith('0'):
        return None
    return (-1 if text.startswith('-') else 1)*integer(token)


def selector_after_call(source, name, header, sites):
    part = plain_repair_view(source,name,header)
    if not part or not sites:
        return []
    available = {decl['name']:decl for decl in locals_for(part)}
    pattern = re.compile(rf'(?:(?P<type>{INT_TYPE})\s+)?(?P<var>{IDENT})\s*=(?!=)\s*(?P<value>{LITERAL})\s*;')
    result = []
    for init in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if not _prefix(part,init.start()):
            continue
        value, var = _literal(init['value']), init['var']
        calls = {callee for callee, literal in sites if literal == value}
        if not calls or re.search(rf'(?<!&)&(?!&)\s*\(*\s*{var}\b',part.body):
            continue
        path = block_path(part,init.start())
        if init['type']:
            # Reject any shadow and any use through a saved address.
            if len(re.findall(rf'\b{INT_TYPE}\s+{var}\b',part.body)) != 1:
                continue
        elif var not in available or available[var].end() > init.start():
            continue
        elif len(path) < len(decl_path := block_path(part,available[var].start())) or path[:len(decl_path)] != decl_path:
            continue
        segment = part.clean[init.end():min(part.end-1,init.end()+500)]
        # Consider only whole straight-line statements before the first named
        # call. Stop before a possible transfer of control or a use of the local.
        cut = re.search(rf'\b{var}\b|[{{}}:]|\b(?:if|while|for|do|switch|return|break|continue)\b',segment)
        if cut:
            segment = segment[:cut.start()]
        choices = '|'.join(re.escape(callee) for callee in sorted(calls))
        call = re.search(rf'(?:^|;)\s*(?:{IDENT}\s*=\s*)?(?:{choices})\s*\(',segment)
        end = close(part.clean,init.end()+call.end()-1) if call else None
        tail = re.match(r'\s*;',part.clean[end:]) if end else None
        if not tail or end+tail.end() > init.end()+len(segment):
            continue
        stop = end+tail.end()
        if not re.search(rf'(?<![.>\w]){var}\b',part.clean[stop:part.end-1]):
            continue
        initial = source[init.start('var'):init.end()]
        declaration = f"{init['type']} {var};" if init['type'] else ''
        result.append((SELECTOR,edit(source,[(init.start(),init.end(),declaration),(stop,stop,' '+initial)])))
        if len(result) == 2:
            break
    return result


def _conjunction(text):
    """Find top-level && cuts, leaving OR, comma, and ternary inside subexpressions."""
    depth = 0
    start = 0
    result = []
    for i, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0:
            if text.startswith('||',i) or char in '?,=' and not (char == '=' and
                    (text[i:i+2] == '==' or text[i-1:i] in ('=', '!', '<', '>'))):
                return []
            if text.startswith('&&',i):
                result.append((start,i))
                start = i+2
    return [*result,(start,len(text))] if result else []


def _field_base(text, offsets):
    text = unwrap(text.strip())
    typed = re.fullmatch(rf'({IDENT})\s*->\s*{IDENT}\s*(?:==|!=)\s*{LITERAL}',text)
    if typed:
        return typed[1]
    raw = re.fullmatch(rf'\*\(\s*{INT_TYPE}\s*\*\s*\)\s*\(\s*'
                       rf'\(\s*(?:char|s8|u8)\s*\*\s*\)\s*({IDENT})\s*\+\s*'
                       rf'({NUMBER})\s*\)\s*(?:==|!=)\s*{LITERAL}',text)
    return raw[1] if raw and integer(raw[2]) in offsets else None


def _nonnull_entry(part, base, position):
    pattern = re.compile(rf'\b(?:if|while)\s*\(\s*{base}\s*!=\s*(?:NULL|0)\s*\)\s*(?:do\s*)?{{')
    write = rf'\b{base}\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{base}\b'
    for guard in pattern.finditer(part.clean,part.opening+1,position):
        end = close(part.clean,guard.end()-1,'{','}')
        if end is None or not guard.end()<=position<end:
            continue
        if re.search(write,part.clean[guard.end():position]):
            continue
        if re.search(r'\bdo\s*{$',guard[0]) and not re.match(rf'\s*while\s*\(\s*{base}\s*!=\s*(?:NULL|0)\s*\)',part.clean[end:]):
            continue
        return True
    return False


def field_first(source, name, header, offsets):
    part = plain_repair_view(source,name,header)
    if not part:
        return []
    result = []
    for guard in re.compile(r'\bif\s*\(').finditer(part.clean,part.opening+1,part.end-1):
        start = guard.end()
        end = close(part.clean,start-1)
        block = re.match(r'\s*{',part.clean[end:]) if end else None
        stop = close(part.clean,end+block.end()-1,'{','}') if block else None
        if not stop or re.match(r'\s*else\b',part.clean[stop:]):
            continue
        condition = part.clean[start:end-1]
        terms = _conjunction(condition)
        if not 2 <= len(terms) <= 8:
            continue
        field = next(((i,base) for i,(a,b) in enumerate(terms[:2])
                      if (base := _field_base(condition[a:b],offsets))),None)
        if field is None:
            continue
        offset,base = field
        if offset:
            # Only cross a plain pointer comparison. The target's first read
            # authorizes this order, and a visible non-null entry guard keeps
            # that read off the null path in the source.
            a,b = terms[0]
            compare = re.fullmatch(rf'({IDENT})\s*!=\s*({IDENT})',unwrap(condition[a:b].strip()))
            if not compare or base not in compare.groups() or not _nonnull_entry(part,base,guard.start()):
                continue
        a,b = terms[offset]
        first = source[start+a:start+b].strip()
        remaining = ' && '.join(source[start+l:start+r].strip() for i,(l,r) in enumerate(terms) if i != offset)
        result.append((FIELD_GUARD,edit(source,[(start,end-1,f'{first}) {{ if ({remaining}'),(stop,stop,' }')])))
        if len(result) == 2:
            break
    return result


def loop_tail_bound(source, name, header, immediates):
    part = plain_repair_view(source,name,header)
    if not part:
        return []
    declarations = {decl['name']:decl for decl in locals_for(part)}
    stable = automatic_integers(part,name)
    shape = re.compile(rf'(?P<bound>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}]+);\s*do\s*{{')
    result = []
    for loop in shape.finditer(part.clean,part.opening+1,part.end-1):
        bound, expr = loop['bound'], loop['expr']
        if bound not in declarations or not _prefix(part,loop.start()):
            continue
        decl = declarations[bound]
        decl_scope = block_path(part,decl.start())
        if decl.end() > loop.start() or decl_scope != block_path(part,loop.start())[:len(decl_scope)]:
            continue
        # Preserve the signedness and narrowing at the original expression.
        # Accept one integer input and a constant adjustment, with casts.
        adjust = re.fullmatch(rf'\s*(?:\(\s*{INT_TYPE}\s*\)\s*)*({IDENT})\s*([+-])\s*({NUMBER})\s*',expr)
        if not adjust or adjust[1] not in stable or adjust[1] == bound:
            continue
        value = _literal(adjust[3])
        if value is None or (value if adjust[2] == '+' else -value) not in immediates:
            continue
        end = close(part.clean,loop.end()-1,'{','}')
        condition = re.match(r'\s*while\s*\(',part.clean[end:]) if end else None
        tail = close(part.clean,end+condition.end()-1) if condition else None
        if not tail or not re.search(rf'\b{bound}\b',part.clean[end+condition.end():tail]):
            continue
        body = part.clean[loop.end():end-1]
        if re.search(rf'\b(?:{bound}|continue)\b|\w\s*:',body):
            continue
        if re.search(rf'\b{adjust[1]}\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{adjust[1]}\b',body):
            continue
        if any(ref.start() >= tail for ref in refs(part,declarations[bound])):
            continue
        assignment_end = part.clean.index(';',loop.start(),loop.end())+1
        result.append((TAIL_BOUND,edit(source,[(end-1,end-1,' '+source[loop.start():assignment_end]+' '),
                                               (loop.start(),assignment_end,'')])))
        if len(result) == 2:
            break
    return result
