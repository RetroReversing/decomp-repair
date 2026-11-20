"""Source storage edits using specific MIPS address and store evidence."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .csource import _blank, find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer, view
from .measured_control_repairs import automatic_integers
from .pattern_repairs import close
from .pointer_pair_repairs import declarations

POINTER = 'delayed_scaled_pointer'
GLOBAL = 'guard_local_global_address'
COPY = 'post_copy_store_scope'
STACK = 'observed_stack_array_record'
STRIDE = 'relocated_strided_field_views'

WIDTH = {'u8':1,'s8':1,'char':1,'u16':2,'s16':2,'short':2,
         'u32':4,'s32':4,'int':4,'f32':4,'float':4,'f64':8,'double':8}
TYPES = '(?:'+'|'.join(WIDTH)+')'
FLOAT = r'(?:f32|float)'


def _standard_field_macro(context):
    definitions = re.findall(rf'#\s*define\s+M2C_FIELD\(\s*({IDENT})\s*,\s*({IDENT})\s*,'
                             rf'\s*({IDENT})\s*\)\s+([^\n]+)', context)
    if not definitions:
        return False
    for obj,kind,offset,body in definitions:
        allowed = set()
        for byte_type in ('s8','char'):
            address = f'(({byte_type}*)({obj})+({offset}))'
            allowed.update((f'(*({kind}){address})',f'(*({kind})({address}))'))
        if re.sub(r'\s+','',body) not in allowed:
            return False
    return True


def _visible(source, name, header, *, labels=False):
    part = view(source,name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b',part.body):
        return None
    if not labels and re.search(r'\bgoto\b',part.body):
        return None
    return part


def delayed_pointer(source, name, header, scale):
    part = _visible(source,name,header)
    if not part:
        return []
    pointers = {d['name']:d for d in declarations(part,nested=True)}
    integers = automatic_integers(part,name)
    pattern = re.compile(
        rf'(?P<p>{IDENT})\s*=(?!=)\s*(?P<address>\(?\s*(?P<index>{IDENT})\s*\*\s*'
        rf'(?P<scale>{NUMBER})\s*\)?\s*\+\s*(?P<base>{IDENT}))\s*;\s*'
        rf'(?P<store>[^;{{}}]+?\s*=(?!=)\s*(?:{NUMBER}|NULL)\s*;)\s*'
        rf'{IDENT}\s*=(?!=)\s*(?P<read>\*\s*(?P=p))\s*;')
    results = []
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        pointer, base, index = hit['p'],hit['base'],hit['index']
        decl = pointers.get(pointer)
        base_decl = pointers.get(base)
        if not decl or decl.end() > hit.start() or index not in integers or base==pointer:
            continue
        if len(scale) and integer(hit['scale']) not in scale:
            continue
        if (not base_decl or base_decl.end()>hit.start()
                or not re.fullmatch(r'\s*(?:char|s8|u8)\s*\*\s*',base_decl['type'])):
            continue
        if part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('',';','{','}'):
            continue
        # Only a qualified lvalue store may intervene. Its rhs is a constant,
        # and it must leave all inputs to the deferred address intact.
        lhs = hit['store'].rsplit('=',1)[0].strip()
        if not (re.fullmatch(rf'{IDENT}\s*->\s*{IDENT}',lhs)
                or lhs.startswith('*(') and not re.search(r'\b\w+\s*\(',lhs)
                or re.fullmatch(rf'M2C_FIELD\(\s*{IDENT}\s*,\s*{TYPES}\s*\*\s*,\s*{NUMBER}\s*\)',lhs)):
            continue
        if re.search(rf'\b(?:{pointer}|{base}|{index})\b|\+\+|--|\bvolatile\b',lhs):
            continue
        if 'M2C_FIELD' in lhs and not _standard_field_macro(header+'\n'+part.clean):
            continue
        old_end = part.clean.index(';',hit.start(),hit.start('store'))+1
        address = source[hit.start('address'):hit.end('address')]
        text = f"*(({decl['type']})({address}))"
        assignment = source[hit.start():old_end]
        later = re.search(rf'\b{pointer}\b',part.clean[hit.end():part.end])
        changes = [(hit.start(),old_end,''),(*hit.span('read'),text)]
        if later:
            changes.append((hit.end(),hit.end(),' '+assignment))
        results.append((POINTER,edit(source,changes)))
        if len(results) == 2:
            break
    return results


def guarded_global_address(source, name, header, symbols):
    part = _visible(source,name,header)
    if not part:
        return []
    span = find(source,name)
    declarations_text = _blank(header)+'\n'+part.clean[:span[0]]
    results = []
    for symbol in sorted(symbols):
        typ = re.search(rf'\bextern\s+({INTEGER})\s+{re.escape(symbol)}\s*;',declarations_text)
        if not typ or re.search(rf'#\s*define\s+{symbol}\b',declarations_text):
            continue
        for guard in re.compile(r'\bif\s*\(').finditer(part.clean,part.opening+1,part.end-1):
            if part.clean[part.opening+1:guard.start()].rstrip()[-1:] not in ('',';','{','}'):
                continue
            end = close(part.clean,guard.end()-1)
            if not end:
                continue
            test = part.clean[guard.end():end-1]
            terms = list(re.finditer(rf'(?<![.>\w]){symbol}\b',test))
            if len(terms) != 1 or not re.search(r'(?:==|!=|<=|>=|<|>)',test):
                continue
            if re.search(r'\w\s*\(|(?<![!=<>])=(?!=)|\+\+|--|[?;,]|\bvolatile\b',test):
                continue
            write = re.match(rf'\s*{{\s*(?P<lhs>{symbol})\s*=(?!=)\s*(?P<rhs>[^;{{}}]+);\s*}}',
                             part.clean[end:part.end])
            if not write or re.search(rf'\b{symbol}\b|\w\s*\(|\+\+|--|[?,]',write['rhs']):
                continue
            stop = end+write.end()
            if re.match(r'\s*else\b',part.clean[stop:]):
                continue
            pointer = fresh(source,header,'repair_guard_address')
            field = terms[0]
            results.append((GLOBAL,edit(source,[
                (guard.start(),guard.start(),f'{{ {typ[1]} *{pointer} = &{symbol}; '),
                (guard.end()+field.start(),guard.end()+field.end(),f'(*{pointer})'),
                (end+write.start('lhs'),end+write.end('lhs'),f'(*{pointer})'),
                (stop,stop,' }'),
            ])))
            if len(results) == 2:
                return results
    return results


def post_copy_store(source, name, header, offsets):
    part = _visible(source,name,header)
    if not part:
        return []
    # Numeric offsets tie these C stores to the measured reordered accesses.
    # A following scalar write and three adjacent word writes anchor the site.
    store = re.compile(rf'\*\(\s*{FLOAT}\s*\*\s*\)\s*\(\s*(?P<ptr>{IDENT})\s*\+\s*'
                       rf'(?P<offset>{NUMBER})\s*\)\s*=(?!=)\s*{IDENT}\s*;')
    edits = []
    for hit in store.finditer(part.clean,part.opening+1,part.end-1):
        offset = integer(hit['offset'])
        if offset not in offsets:
            continue
        ptr = hit['ptr']
        previous = part.clean[max(part.opening+1,hit.start()-650):hit.start()]
        following = part.clean[hit.end():part.end]
        words = [integer(word) for word in re.findall(
            rf'\*\(\s*(?:volatile\s+)?(?:u32|s32|int)\s*\*\s*\)\s*\(\s*{ptr}\s*\+\s*({NUMBER})\s*\)\s*=(?!=)',
            previous)]
        if len(words)<3 or words[-3:] != list(range(words[-3],words[-3]+12,4)):
            continue
        if not 12 <= offset-words[-3] <= 24:
            continue
        if not re.match(rf'\s*\*\([^;{{}}]+\)\s*\(\s*{ptr}\s*\+\s*{NUMBER}\s*\)\s*=(?!=)',following):
            continue
        text = source[hit.start():hit.end()]
        edits.append((hit.start(),hit.end(),f'do {{ {text} }} while (0);'))
        if len(edits) == 3:
            break
    return [(COPY, edit(source,edits))] if edits else []


def stack_array_record(source, name, header, slots, moved):
    part = _visible(source,name,header)
    if not part or len(moved) < 2:
        return []
    decl = re.compile(rf'(?P<type>{TYPES})\s+(?P<name>sp(?P<offset>[0-9a-fA-F]+))\s*'
                      rf'\[\s*(?P<count>{NUMBER})\s*\]\s*;')
    arrays = [hit for hit in decl.finditer(part.clean,part.opening+1,part.end-1)
              if block_path(part,hit.start())==[part.opening]]
    groups = []
    for hit in arrays:
        if groups and not part.clean[groups[-1][-1].end():hit.start()].strip():
            groups[-1].append(hit)
        else:
            groups.append([hit])
    results = []
    for group in groups:
        if not 2 <= len(group) <= 8:
            continue
        lo,hi = group[0].start(),group[-1].end()
        if part.clean[part.opening+1:lo].rstrip()[-1:] not in ('',';'):
            continue
        named = {hit['name'] for hit in group}
        if len(named)!=len(group) or set(re.findall(r'^\s*#\s*define\s+('+IDENT+')',header+'\n'+part.clean,re.M)) & named:
            continue
        ordered = sorted(group,key=lambda hit:int(hit['offset'],16))
        base = int(ordered[0]['offset'],16)
        fields = []
        used = set()
        offset = base
        align = max(WIDTH[hit['type']] for hit in ordered)
        if base % align:
            continue
        for hit in ordered:
            at,kind,count = int(hit['offset'],16),hit['type'],integer(hit['count'])
            if (at not in slots or at < offset or at-offset > 32 or at%WIDTH[kind]
                    or not 1 <= count <= 128):
                break
            if at > offset:
                fields.append(f'unsigned char gap_{offset:X}[{at-offset}];')
            fields.append(f"{kind} {hit['name']}[{hit['count']}];")
            used.update(address for address in moved if at <= address < at+WIDTH[kind]*count)
            offset = at+WIDTH[kind]*count
        else:
            if len(used)<2 or offset-base > 512:
                continue
            token = fresh(source,header,'repair_stack_record')
            tail = part.clean[hi:part.end-1]
            if any(re.search(rf'\b(?:{TYPES}|struct\s+{IDENT})\s*\**\s*{n}\b',tail) for n in named):
                continue
            references = re.compile(r'(?<![.>\w])(?:'+'|'.join(sorted(named))+r')\b').finditer(tail)
            changes = [(hi+ref.start(),hi+ref.end(),f'{token}.{ref[0]}') for ref in references]
            if all(any(value.endswith('.'+n) for _,_,value in changes) for n in named):
                results.append((STACK,edit(source,[(lo,hi,'struct { '+' '.join(fields)+f' }} {token};'),*changes])))
            if len(results)==2:
                break
    return results


def strided_fields(source, name, header, views):
    part = _visible(source,name,header,labels=True)
    if not part:
        return []
    direct = re.compile(rf'\*\(\s*(?P<type>{TYPES})\s*\*\s*\)\s*\(\s*'
                        rf'(?P<symbol>{IDENT})\s*\+\s*(?P<expr>{IDENT}(?:\s*\*\s*{NUMBER})?)\s*\)')
    stable = automatic_integers(part,name)
    declarations_text = _blank(header)+'\n'+part.clean[:find(source,name)[0]]
    results = []
    for stride,widths in views:
        edits = []
        symbols = set()
        for hit in direct.finditer(part.clean,part.opening+1,part.end-1):
            typ,symbol,expr = hit['type'],hit['symbol'],hit['expr']
            size = WIDTH[typ]
            if widths.get(symbol)!=size or stride <= size or stride%size:
                continue
            if not re.search(rf'\bextern\s+(?:char|u8|s8)\s+{symbol}\s*\[\s*\]\s*;',declarations_text):
                continue
            product = re.fullmatch(rf'({IDENT})\s*\*\s*({NUMBER})',expr)
            if not product:
                # A visible preceding byte-offset definition may be reused only
                # in the same straight-line block with no intervening changes.
                before = part.clean[max(part.opening+1,hit.start()-400):hit.start()]
                if expr not in stable:
                    continue
                assignments = list(re.finditer(rf'\b{expr}\s*=(?!=)\s*({IDENT})\s*\*\s*({NUMBER})\s*;',before))
                if not assignments:
                    continue
                match = assignments[-1]
                modified = rf'\b(?:{expr}|{match[1]})\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)'
                if re.search(rf'[{{}}:]|{modified}|(?:\+\+|--)\s*(?:{expr}|{match[1]})\b',before[match.end():]):
                    continue
                product = match
            idx = product[1]
            if integer(product[2])!=stride or idx not in stable:
                continue
            view_type = f'struct {{ {typ} value; unsigned char padding[{stride-size}]; }}'
            replacement = f'(({view_type} *){symbol})[{idx}].value'
            edits.append((hit.start(),hit.end(),replacement))
            symbols.add(symbol)
            if len(edits)>=8:
                break
        if len(symbols)>=2:
            results.append((STRIDE,edit(source,edits)))
        if len(results)==2:
            break
    return results
