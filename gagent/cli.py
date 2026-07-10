import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("gagent - coding agent skeleton")
        return 0
    print(f"gagent: unknown args {args}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
