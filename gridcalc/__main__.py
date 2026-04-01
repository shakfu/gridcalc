import os
import sys

# Support both `python -m gridcalc` (relative import) and direct execution
if __package__:
    from .tui import main
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gridcalc.tui import main

main()
