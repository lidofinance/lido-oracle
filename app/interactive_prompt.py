def prompt(prompt, prompt_end):
    print(prompt, end = prompt_end)
    while True:
        choice = input().lower()
        if choice == 'y':
            return True
        elif choice == 'n':
            return False
        else:
            print('Please respond with ', end = prompt_end)
            continue