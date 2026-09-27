import argparse
import sys

from node import start_rpc_server
from server import launch_llama_server


def choose_mode():
    while True:
        print("=" * 64)
        print("LLAMA RPC PORTABLE")
        print("=" * 64)
        print("1. SERVER utama")
        print("2. NODE pembantu")
        print("0. Keluar")
        choice = input("Pilih mode: ").strip()
        if choice == "1":
            return "server"
        if choice == "2":
            return "node"
        if choice == "0":
            return None
        print("Eror: pilih 1, 2, atau 0.\n")


def main(argv=None):
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=("server", "node"))
    launcher_args, remaining = parser.parse_known_args(raw_args)

    mode = launcher_args.mode
    if not mode:
        mode = choose_mode()
        if mode is None:
            print("Program ditutup.")
            return 0

    if mode == "server":
        return launch_llama_server(remaining)

    original_argv = sys.argv
    try:
        sys.argv = [original_argv[0], *remaining]
        return start_rpc_server()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    sys.exit(main())
