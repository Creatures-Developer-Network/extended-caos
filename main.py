import sys
from extendedcaos import extendedcaos_to_caos


def main():
    if len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            text = f.read()
    elif len(sys.argv) == 1:
        sys.stderr.write("Reading from stdin...\n")
        text = sys.stdin.read()
    else:
        sys.stderr.write("USAGE: %s [FILE]" % sys.argv[0])
        exit(1)

    print(extendedcaos_to_caos(text))


if __name__ == "__main__":
    main()
