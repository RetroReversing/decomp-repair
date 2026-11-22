from decomprepair.private_record_padding import variants

SOURCE = """
void sample(float **out)
{
    struct {
        float first[3];
        u32 padFirst;
        float second[3];
        u32 padSecond;
    } frame;
    float coords[8];
    volatile s32 flag;
    out[0] = frame.first;
    out[1] = frame.second;
    out[2] = coords;
}
"""

ROWS = [('s', 'addiu $sp, $sp, -0x48', 'addiu $sp, $sp, -0x50')]


def test_removes_private_padding_and_moves_neighbor_together():
    [(family, result)] = variants(SOURCE, 'sample', ROWS)
    assert family == 'private_record_padding'
    assert 'padFirst' not in result
    assert 'padSecond' not in result
    assert result.index('volatile s32 flag;') < result.index('float coords[8];')
    assert 'out[1] = frame.second;' in result


def test_preserves_used_padding_and_observable_layout():
    for text in ('inspect(&frame);', 'inspect(frame.padFirst);', 'inspect(sizeof(frame));'):
        assert variants(SOURCE.replace('    out[0]', f'    {text}\n    out[0]'), 'sample', ROWS) == []
    assert variants(SOURCE, 'sample', [('s', ROWS[0][1], ROWS[0][1])]) == []
