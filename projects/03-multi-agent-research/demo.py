"""Independent project entrypoint through the evidence-capturing public CLI."""
import sys

from pais.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["demo", "03", *sys.argv[1:]]))
