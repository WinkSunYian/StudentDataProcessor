import sys

from Bootstrap.AppRunner import AppRunner

if __name__ == "__main__":
    runner = AppRunner(sys.argv)
    sys.exit(runner.run())
