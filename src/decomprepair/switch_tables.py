"""Read-only target jump-table ordering; reorder whole case groups, preserving fallthrough."""
import ast
import re

from decomprepair.pattern_repairs import close

from .csource import _blank, find

LABEL = re.compile(r"\bcase\s+('(?:\\.|[^'\\])'|-?(?:0[xX][0-9a-fA-F]+|\d+))\s*:|\bdefault\s*:")


def value(text):
    return ord(ast.literal_eval(text)) if text.startswith("'") else int(text, 0) if 'x' in text.lower() else int(text)


def relabeled(source, name, low, compiled, target, default):
    """Propose case-label changes from two bounded, independently read tables.

    Destinations are offsets in the same function. Recompilation and the
    ordinary exact judge must still verify every instruction and table entry.
    """
    span = find(source, name)
    if not span or not 2 <= len(target) <= 256 or len(compiled) != len(target) or default not in target:
        return []
    clean = _blank(source)
    results = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[span[0]:span[1]]):
        cond = close(clean, span[0] + switch.end() - 1)
        if not cond:
            continue
        brace = cond + len(clean[cond:]) - len(clean[cond:].lstrip())
        if clean[brace:brace + 1] != '{' or not (end := close(clean, brace, '{', '}')):
            continue
        labels = [m for m in LABEL.finditer(source, brace + 1, end - 1)
                  if clean[brace + 1:m.start()].count('{') == clean[brace + 1:m.start()].count('}')
                  and clean[m.start():m.start() + 4] in ('case', 'defa')]
        all_labels = [m for m in re.finditer(r'\b(?:case|default)\b', clean[brace + 1:end - 1])
                      if clean[brace + 1:brace + 1 + m.start()].count('{')
                      == clean[brace + 1:brace + 1 + m.start()].count('}')]
        if (not 2 <= len(labels) <= 64 or len(labels) != len(all_labels)
                or any(label[1] is None for label in labels) or clean[brace + 1:labels[0].start()].strip()):
            continue
        groups = []
        for i, label in enumerate(labels):
            try:
                number = value(label[1])
            except (ValueError, SyntaxError, TypeError):
                break
            stop = labels[i + 1].start() if i + 1 < len(labels) else end - 1
            body = clean[label.end():stop].strip()
            terminal = re.search(r'\b(?:break|return(?:\s+[^;{}]+)?)\s*;\s*$', body)
            prefix = body[:terminal.start()].rstrip() if terminal else ''
            if (not low <= number < low + len(target) or not terminal
                    or prefix.count('{') != prefix.count('}') or prefix and prefix[-1] not in ';}'):
                break
            groups.append((label, stop, number, compiled[number - low], body))
        else:
            if len({group[2] for group in groups}) != len(groups):
                continue
            destinations = [group[3] for group in groups]
            if len(set(destinations)) != len(destinations):
                continue
            desired = {}
            for index, destination in enumerate(target):
                if destination != default:
                    desired.setdefault(destination, []).append(low + index)
            if not set(desired) <= set(destinations):
                continue
            spare = [low + index for index, destination in enumerate(target) if destination == default]
            edits = []
            for label, stop, old, destination, body in groups:
                numbers = desired.get(destination, [])
                replacement_body = None
                if not numbers:
                    if not re.fullmatch(r'(?:return|break)\s*;', body) or not spare:
                        break
                    number = old if old in spare else spare[0]
                    spare.remove(number)
                    numbers = [number]
                    tail = re.search(r'\s*$', source[label.end():stop])[0]
                    replacement_body = ' break;' + tail
                fmt = (lambda number: f'0x{number:X}' if number >= 0 else str(number)) if 'x' in label[1].lower() else str
                replacement = ' '.join(f'case {fmt(number)}:' for number in numbers)
                edits.append((label.start(), label.end(), replacement))
                if replacement_body is not None:
                    edits.append((label.end(), stop, replacement_body))
            else:
                proposal = source
                for start, stop, replacement in sorted(edits, reverse=True):
                    proposal = proposal[:start] + replacement + proposal[stop:]
                if proposal != source:
                    results.append(('verified_switch_labels', proposal))
    return list(dict.fromkeys(results))


def variants(source, name, tables=()):
    """tables contain (minimum case value, destination addresses). No guessed table earns a match."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source); result=[]
    for switch in re.finditer(r'\bswitch\s*\(', clean[span[0]:span[1]]):
        cond=close(clean,span[0]+switch.end()-1)
        if not cond:
            continue
        brace=cond+len(clean[cond:])-len(clean[cond:].lstrip())
        if clean[brace:brace+1]!='{':
            continue
        end=close(clean,brace,'{','}')
        if not end:
            continue
        labels=[m for m in LABEL.finditer(source,brace+1,end-1)
                if clean[brace+1:m.start()].count('{')==clean[brace+1:m.start()].count('}')
                and clean[m.start():m.start()+4] in ('case','defa')]
        all_cases=[m for m in re.finditer(r'\b(?:case|default)\b',clean[brace+1:end-1])
                   if clean[brace+1:brace+1+m.start()].count('{')==clean[brace+1:brace+1+m.start()].count('}')]
        if len(all_cases)!=len(labels):
            continue
        if not 2<=len(labels)<=64 or clean[brace+1:labels[0].start()].strip():
            continue
        # Move all fallthrough-connected cases together, including grouped labels and default.
        groups=[];start=labels[0].start();values=[];default=False
        for i,label in enumerate(labels):
            stop=labels[i+1].start() if i+1<len(labels) else end-1
            if label[1] is None: default=True
            else: values.append(value(label[1]))
            body=clean[label.end():stop].strip()
            if not body:
                continue
            # A terminal unconditional goto/return/break at case depth, not a nested if body.
            terminal=re.search(r'\b(?:goto\s+\w+|break|continue|return(?:\s+[^;{}]+)?)\s*;\s*$',body)
            prefix=body[:terminal.start()].rstrip() if terminal else ''
            if terminal and (not prefix or prefix[-1] in ';}') and prefix.count('{')==prefix.count('}'):
                groups.append((start,stop,values,default));start=stop;values=[];default=False
        if start!=end-1 or len(groups)<2:
            continue
        # Cross-case labels and unscoped local declarations can change scope when moved.
        if any(any(clean[a:a+m.start()].count('{') == clean[a:a+m.start()].count('}')
                   for m in re.finditer(r'\b(?:char|int|short|long|float|double|[su]\d+)\s+\**\w+\s*(?:[=;\[])',clean[a:b]))
               for a,b,_,_ in groups):
            continue
        for low,destinations in tables:
            from collections import Counter
            default_address=Counter(destinations).most_common(1)[0][0]
            addresses=[]
            for _,_,numbers,isdefault in groups:
                if (not numbers and not isdefault) or any(not 0<=n-low<len(destinations) for n in numbers):
                    break
                group={destinations[n-low] for n in numbers}
                if isdefault: group.add(default_address)
                # Fallthrough groups may have distinct entry points; their physical order is the lowest.
                addresses.append(min(group))
            else:
                order=sorted(range(len(groups)),key=lambda i:addresses[i])
                if order!=list(range(len(groups))):
                    text=''.join(source[groups[i][0]:groups[i][1]] for i in order)
                    result.append(('target_switch_order',source[:groups[0][0]]+text+source[groups[-1][1]:]))
    return (list(dict.fromkeys(result))[:2] + gap_variants(source, name, tables)
            + label_variants(source, name, tables))



GAP_FAMILY = 'switch_gap_goto'
GAP_LIMIT = 12


def gap_variants(source, name, tables=()):
    """A jump-table entry the target points somewhere of its own, for a value the source's switch has no case for.

    The compiled table sends such a value to `default:`, so the table differs in that one entry (the judge's "linked
    jump-table differences" line) while every instruction reads the same. A function that was one entry short of a
    match (KMC GCC 2.7.2, a switch of `var - 2` with the call arms and a `default:` that held the real code) needed
    `case 7: goto L;`, L the label the other arms jump to when they are done: the entry then names that label's own
    code, and jump threading removes the `goto`, so nothing else moves.

    Two rules, both proposals for the judge: a missing value whose target destination equals the destination of a
    value the source does have gets its label stacked on that case (`case 7: case 4:`); a missing value with a
    destination of its own gets `case N: goto L;` for each label the function already jumps to (bounded). The
    default's destination is the table's most common one (a hypothesis, as in `hints`)."""
    from collections import Counter
    span = find(source, name)
    if not span or not tables:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    defined = {m[1] for m in re.finditer(r'(?:^|[;{}])\s*(?!case\b|default\b)([A-Za-z_]\w*)\s*:(?!:)', body)}
    targets = [m for m in dict.fromkeys(re.findall(r'\bgoto\s+([A-Za-z_]\w*)\s*;', body)) if m in defined]
    out = []
    for switch in re.finditer(r'\bswitch\s*\(', body):
        cond = close(clean, span[0] + switch.end() - 1)
        if not cond:
            continue
        brace = cond + len(clean[cond:]) - len(clean[cond:].lstrip())
        if clean[brace:brace + 1] != '{' or not (end := close(clean, brace, '{', '}')):
            continue
        inside = clean[brace + 1:end - 1]
        labels = [m for m in LABEL.finditer(source, brace + 1, end - 1)
                  if clean[brace + 1:m.start()].count('{') == clean[brace + 1:m.start()].count('}')
                  and clean[m.start():m.start() + 4] in ('case', 'defa')]
        every = [m for m in re.finditer(r'\b(?:case|default)\b', inside)
                 if inside[:m.start()].count('{') == inside[:m.start()].count('}')]
        if len(labels) != len(every) or not labels or clean[brace + 1:labels[0].start()].strip():
            continue
        try:
            numbers = {value(m[1]): m for m in labels if m[1] is not None}
        except (ValueError, SyntaxError, TypeError):
            continue
        if not numbers:
            continue
        for low, destinations in tables:
            if not 2 <= len(destinations) <= 256:
                continue
            for base in dict.fromkeys((low, 0)):  # the switch may be on the value the table's own index is biased from
                if all(0 <= n - base < len(destinations) for n in numbers):
                    break
            else:
                continue
            common = Counter(destinations).most_common(1)[0][0]
            have = {n: destinations[n - base] for n in numbers}
            for index, destination in enumerate(destinations):
                number = base + index
                if number in numbers or destination == common:
                    continue
                same = [n for n, where in have.items() if where == destination]
                if same:
                    at = numbers[min(same)].start()
                    out.append((GAP_FAMILY, source[:at] + f'case {number}: ' + source[at:]))
                    continue
                first = labels[0].start()
                for label in targets[:6]:
                    out.append((GAP_FAMILY, source[:first] + f'case {number}: goto {label};\n' + source[first:]))
    return list(dict.fromkeys(out))[:GAP_LIMIT]


LABEL_FAMILY = 'switch_table_labels'


def label_variants(source, name, tables=()):
    """Every case label rebuilt from the target's jump table, the arms keeping their order.

    GCC lays the arms out in source order, so when a switch has as many arms (apart from `default:`) as the table has
    destinations of its own, the i-th arm is the i-th lowest destination and its labels are every value the table
    sends there. This covers a source with only some of a long grouped list (a decompiler that could not read the
    table writes one value per arm, or leaves them all to `default:`), which no relabelling of the existing labels
    reaches. The table's most common destination is taken for the default (a hypothesis, as in `hints`); the first
    and last values are written on the default arm when the table sends them there, so the table keeps its span.
    The judge decides."""
    from collections import Counter
    span = find(source, name)
    if not span or not tables:
        return []
    clean = _blank(source)
    out = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[span[0]:span[1]]):
        cond = close(clean, span[0] + switch.end() - 1)
        if not cond:
            continue
        brace = cond + len(clean[cond:]) - len(clean[cond:].lstrip())
        if clean[brace:brace + 1] != '{' or not (end := close(clean, brace, '{', '}')):
            continue

        def top(at, brace=brace):
            return clean[brace + 1:at].count('{') == clean[brace + 1:at].count('}')

        labels = [m for m in LABEL.finditer(source, brace + 1, end - 1)
                  if top(m.start()) and clean[m.start():m.start() + 4] in ('case', 'defa')]
        every = [m for m in re.finditer(r'\b(?:case|default)\b', clean[brace + 1:end - 1])
                 if top(brace + 1 + m.start())]
        if not labels or len(labels) != len(every) or clean[brace + 1:labels[0].start()].strip():
            continue
        runs = [[labels[0]]]  # labels stacked with nothing between them name one arm
        for before, label in zip(labels, labels[1:]):
            if clean[before.end():label.start()].strip():
                runs.append([label])
            else:
                runs[-1].append(label)
        arms = [run for run in runs if all(label[1] is not None for label in run)]
        fallback = [run for run in runs if run not in arms]
        for low, destinations in tables:
            if not 2 <= len(destinations) <= 256:
                continue
            common = Counter(destinations).most_common(1)[0][0]
            own = sorted(set(destinations) - {common})
            if len(own) != len(arms) or not arms:
                continue
            hexed = any('x' in (label[1] or '').lower() for label in labels)

            def case(number, hexed=hexed):
                return f'case 0x{number:X}:' if hexed and number >= 0 else f'case {number}:'

            edits = []
            for run, address in zip(arms, own):
                text = ' '.join(case(low + i) for i, where in enumerate(destinations) if where == address)
                edits.append((run[0].start(), run[-1].end(), text))
            ends = [low + i for i in (0, len(destinations) - 1) if destinations[i] == common]
            if fallback:
                edits.append((fallback[0][0].start(), fallback[0][-1].end(),
                              ' '.join([*map(case, ends), 'default:'])))
            elif ends:
                continue
            proposal = source
            for start, stop, text in sorted(edits, reverse=True):
                proposal = proposal[:start] + text + proposal[stop:]
            if proposal != source:
                out.append((LABEL_FAMILY, proposal))
    return list(dict.fromkeys(out))[:4]


def hints(source, name, tables=(), header=''):
    """Compare source labels with bounded retail tables; never infer a missing case body."""
    span=find(source,name)
    if not span:return []
    text=_blank(source[span[0]:span[1]])
    constants={m[1]:int(m[2],0) for m in re.finditer(r'(?m)^\s*#define\s+(\w+)\s+(-?(?:0x[0-9a-fA-F]+|[0-9]+))\s*(?://[^\n]*)?$',header)}
    result=[]
    for switch in re.finditer(r'\bswitch\s*\(',text):
        cond=close(text,switch.end()-1)
        if not cond:continue
        brace=cond+len(text[cond:])-len(text[cond:].lstrip())
        if text[brace:brace+1]!='{':continue
        end=close(text,brace,'{','}')
        if not end:continue
        labels=[];positions=[];unknown=False
        for hit in re.finditer(r'\bcase\s+([^:]+):',text[brace+1:end-1]):
            before=text[brace+1:brace+1+hit.start()]
            if before.count('{')!=before.count('}'):continue
            token=hit[1].strip().strip('()').strip()
            try:number=constants[token] if token in constants else value(token)
            except (ValueError,SyntaxError):unknown=True;continue
            labels.append(number);positions.append((hit.start(),hit.end()))
        if unknown:continue
        for low,destinations in tables:
            inside={n for n in labels if low<=n<low+len(destinations)}
            if len(inside)<2:continue
            for i in range(len(labels)-1):
                a,b= list(labels[i:i+2])
                between=text[brace+1+positions[i][1]:brace+1+positions[i+1][0]].strip()
                if not between and a in inside and b in inside and destinations[a-low]!=destinations[b-low]:
                    result.append(f'Retail switch-table review: grouped source labels {a}/{b} have different target entry points. Check fallthrough and revision-specific case grouping; no labels were changed.')
            from collections import Counter
            counts=Counter(destinations);common=counts.most_common(1)[0]
            # A modal destination is only a default hypothesis. Ties give no evidence.
            if len(counts)>1 and list(counts.values()).count(common[1])==1:
                missing=[low+i for i,address in enumerate(destinations) if low+i not in inside and address!=common[0]]
                if missing:result.append('Retail switch-table review: distinct target destinations for source-absent case(s) '+', '.join(map(str,missing[:12]))+'. The modal destination is only a default hypothesis; inspect retail arms before changing archived source. No case body was synthesized.')
    return list(dict.fromkeys(result))[:4]
