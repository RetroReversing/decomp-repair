"""Conservative shadow and member checks for float-local source rewrites."""
import re


def unshadowed(clean, opening, end, *names):
    """Reject other local declarations and member names that could bind a different object."""
    body = clean[opening + 1:end]
    for name in names:
        escaped = re.escape(name)
        # Statement boundaries avoid mistaking a multiplication for a pointer declaration.
        declarations = re.findall(r'(?m)(?:^|[;{}])\s*(?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*'
                                  r'[ \t]+\**\s*' + escaped + r'\s*(?=[;=,\[])', body)
        float_declarations = re.findall(r'(?m)^\s*f32\s+' + escaped + r'\s*;', body)
        if len(declarations) > len(float_declarations) or re.search(r'(?:\.|->)\s*' + escaped + r'\b', body):
            return False
        # A second declarator may follow another name on the same declaration line.
        if re.search(r'(?m)^\s*(?:const\s+|volatile\s+|unsigned\s+|signed\s+)*[A-Za-z_]\w*'
                     r'[ \t]+[^;{}\n]*,[^;{}\n]*\b' + escaped + r'\s*(?=[;=,\[])', body):
            return False
    return True
