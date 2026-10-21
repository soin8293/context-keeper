"""Run a discovered unittest suite, rejecting a misleading zero-test success."""
from pathlib import Path
import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.discover(str(Path(sys.argv[1]).resolve()), pattern='test_*.py')
    count = suite.countTestCases()
    if count == 0:
        print('No discoverable tests: wrap script-only scenarios in unittest.TestCase.', file=sys.stderr)
        return 2
    print(f'Discovered {count} tests', flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
