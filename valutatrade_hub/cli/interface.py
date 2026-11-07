from valutatrade_hub.infra.database import Storage


def run_cli(storage: Storage) -> None:
    """Run the interactive command-line interface."""
    print("ValutaTrade Hub")
    print("Для завершения работы введите exit.")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input == "exit":
            break

        print("Обработка команд пока не реализована.")
