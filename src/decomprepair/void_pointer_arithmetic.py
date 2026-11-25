"""Make m2c's `void *` locals and parameters usable in arithmetic, for compilers that refuse it.

m2c types an address it knows nothing about as `void *` and then adds to it (`arg0 + 4`, `var_v1 += 8`, `*arg0`).
GCC 2.x allows that as an extension, but IDO's compiler does not: `Unacceptable operand of '+'` and `Bad operand type
for += or -=` were on 16,136 and 2,004 draft failures of 43 N64 games, in nearly every function that walks a
buffer, so none of those drafts compiled before any repair. A `u8 *` takes the same arithmetic, converts to a
`void *` argument or return by itself, and reads the same bytes, so a `void *` name the body does arithmetic or a
subscript on is declared `u8 *` instead. Names that are only passed on or compared stay `void *`; `void **` and deeper
(the element is a pointer, so the arithmetic is fine) are left alone.
"""
import re

from . import c_scan

_PARAM = re.compile(r'(?<![\w*])void \*(?=\w)')
_DECL = re.compile(r'^([ \t]+)void \*(\w+)((?:[ \t]*=[^;\n]*)?;[ \t]*)$', re.M)


def _head(source, name):
    return re.search(rf'^[^\n;]*\b{re.escape(name)}[ \t]*\(([^)]*)\)[ \t]*\{{[ \t]*$', source, flags=re.M)


def _arithmetic(body, name):
    """Whether `name` is added to, subtracted from, indexed or read through in `body`."""
    n = re.escape(name)
    return bool(
        re.search(rf'(?<![\w.]){n}[ \t]*(?:\+\+|--|[+\-]=?|\[)', body)  # name + k, name += k, name++, name[i]
        or re.search(rf'(?<=[\w)\]])[ \t]*[+\-][ \t]*{n}\b(?![\w.(])', body)  # k + name
        or re.search(rf'(?:^|[=(,;{{}}!&|?:<>+\-*/])[ \t]*\*[ \t]*{n}\b(?![\w.(])', body, re.M))  # *name


def rewrite(source, name):
    """`source` with the `void *` names of function `name` that take arithmetic declared `u8 *`, or None."""
    head = _head(source, name)
    if head is None:
        return None
    body = source[head.end():]
    params = head.group(1)
    declared = [m[1] for m in re.finditer(r'(?<![\w*])void \*(\w+)', params)]
    declared += [m[2] for m in _DECL.finditer(body)]
    chosen = {n for n in declared if _arithmetic(body, n)}
    if not chosen:
        return None
    new_params = re.sub(r'(?<![\w*])void \*(\w+)', lambda m: ('u8 *' if m[1] in chosen else 'void *') + m[1], params)
    new_body = _DECL.sub(lambda m: f'{m[1]}{"u8" if m[2] in chosen else "void"} *{m[2]}{m[3]}', body)
    out = source[:head.start(1)] + new_params + source[head.end(1):head.end()] + new_body
    return out if out != source else None


_EXTERN = re.compile(r'^extern void \*(\w+);', re.M)


def externs(source, name):
    """`source` with each `extern void *NAME;` the draft declares for a global that function `name` does arithmetic on
    declared `extern u8 *NAME;`, or None. (A global the project's header declares is not redeclared by the draft.)"""
    head = _head(source, name)
    if head is None:
        return None
    body = source[head.end():]
    chosen = {m[1] for m in _EXTERN.finditer(source[:head.start()]) if _arithmetic(body, m[1])}
    if not chosen:
        return None
    out = _EXTERN.sub(lambda m: f'extern u8 *{m[1]};' if m[1] in chosen else m[0], source)
    return out if out != source else None


_CALL_STORE = re.compile(r'\(\(void \(\*\)\(\)\) \*\((\w+(?: \*)?)\)\)\(')


def stores(source):
    """m2c's `((void (*)()) *(s32 *))(address) = value;` (a store through an address it printed as a call through a
    cast: no compiler reads it) as the store it is, `*(s32 *)(address) = value;`; None when there is none."""
    out, at = [], 0
    for found in _CALL_STORE.finditer(source):
        if found.start() < at:
            continue
        end = c_scan.close(source, found.end() - 1, '(', ')')
        if end < 0:
            return None
        out.append(source[at:found.start()] + f'*({found[1]})(' + source[found.end():end + 1])
        at = end + 1
    if not out:
        return None
    return ''.join(out) + source[at:]
