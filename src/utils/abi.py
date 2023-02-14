from operator import itemgetter


def get_function_output_names(abi, function_name: str) -> list[str]:
    abi = next(filter(lambda x: x.get('name') == function_name, abi))
    return list(map(itemgetter('name'), abi['outputs'][0]['components']))
