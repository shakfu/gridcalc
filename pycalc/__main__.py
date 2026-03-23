import os
import sys

# Support both `python -m pycalc` (relative import) and direct execution
if __package__:
    from .tui import main
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pycalc.tui import main

main()
