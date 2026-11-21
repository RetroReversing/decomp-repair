from decomprepair.queue_cursor_index_repairs import variants

SOURCE = """void walk(void *root) {
    void *queue[16];
    void **write;
    void **read;
    u32 count;
    u32 i;
    void *item;
    count = 0;
    write = queue;
    do {
        item = next(root);
        *write++ = item;
        count++;
    } while (item);
    i = 0;
    read = &queue[i];
    do {
        use(*read);
        i++;
        read++;
    } while (i < count);
}
"""


def test_write_and_read_cursors_become_indexed_accesses():
    (family, candidate), = variants(SOURCE, 'walk')
    assert family == 'queue_cursor_index'
    assert 'queue[count] = item;\n        count++;' in candidate
    assert 'use(queue[i]);\n        i++;\n' in candidate
    for gone in ('write', 'read', '**'):
        assert gone not in candidate.replace('void *queue', '')
    assert 'void **write;' not in candidate and 'void **read;' not in candidate


def test_a_cursor_set_at_the_counter_is_rewritten_with_that_counter():
    reseated = SOURCE.replace('    write = queue;\n', '    count++;\n    count--;\n    write = &queue[count];\n')
    (_, candidate), = variants(reseated, 'walk')
    assert 'queue[count] = item;' in candidate


def _rewritten(source):
    found = variants(source, 'walk')
    return found[0][1] if found else ''


def test_a_cursor_that_is_not_just_the_counter_is_left_alone():
    # the write cursor stays when the counter is not zero where it starts, or does not step with it
    for changed in (SOURCE.replace('count = 0;', 'count = 2;'), SOURCE.replace('        count++;\n', '')):
        assert '*write++ = item;' in _rewritten(changed)
        assert 'use(queue[i]);' in _rewritten(changed)
    # the read cursor stays when the pointer escapes, steps by two, or steps twice
    for changed in (SOURCE.replace('use(*read);', 'use(read);'),
                    SOURCE.replace('        read++;\n', '        read += 2;\n'),
                    SOURCE.replace('    } while (i < count);', '        read++;\n    } while (i < count);')):
        assert 'use(queue[i])' not in _rewritten(changed)
        assert 'queue[count] = item;' in _rewritten(changed)
    assert not variants(SOURCE.replace('count = 0;', 'count = 2;').replace('i = 0;', 'i = 2;').replace('use(*read);', 'use(read);'), 'walk')
