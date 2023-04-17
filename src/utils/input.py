def get_input():
    return input()


def prompt(prompt_message: str) -> bool:
    print(prompt_message, end='')
    while True:
        choice = get_input().lower()

        if choice in ['Y', 'y']:
            return True

        if choice in ['N', 'n']:
            return False

        print('Please respond with [y or n]: ', end='')
