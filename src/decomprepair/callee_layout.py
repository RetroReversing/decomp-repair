"""Constant-index write footprints from a known C callee."""
import re

from .integer_repair_support import IDENT, INTEGER

SCALAR = rf'(?:{INTEGER}|float|double|f32|f64)'


def extent(body, parameter):
    """Infer a possible buffer extent from a complete, nonescaping set of writes."""
    parameter = re.escape(parameter)
    writes = list(re.finditer(rf'\b{parameter}\s*\[\s*(\d+)\s*\]\s*=(?!=)', body))
    indices = {int(write[1]) for write in writes}
    limit = max(indices, default=-1)+1
    if not 2 <= limit <= 32 or indices != set(range(limit)):
        return None
    if len(re.findall(rf'\b{parameter}\b',body)) != len(writes):
        return None
    if re.search(r'\b(?:for|while|goto)\b|\b'+IDENT+r'\s*\(',body):
        return None
    return limit
