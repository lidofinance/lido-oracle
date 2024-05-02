def seq(start: int, stop: int):
    """Returns inclusive range object [start;stop]"""
    assert stop > 0
    return range(start, stop + 1)
