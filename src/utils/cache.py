
def clear_object_lru_cache(obj: object):
    wrappers = [a for a in dir(obj) if hasattr(getattr(obj, a), 'cache_clear')]
    for wrapper in wrappers:
        getattr(obj, wrapper).cache_clear()
