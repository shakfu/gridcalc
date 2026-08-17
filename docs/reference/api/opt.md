# opt

Linear, mixed-integer, and convex quadratic programs built from cells in a sheet and solved through the HiGHS-backed `_opt` extension. See the [Optimization guide](../../guide/optimization.md) for the user-facing commands.

::: gridcalc.opt
    options:
      members:
        - solve
        - sweep
        - OptModel
        - SolveResult
        - Sensitivity
        - VarSensitivity
        - ConstraintSensitivity
        - SweepPoint
        - LinearForm
        - QuadForm
        - extract_linear
        - extract_quadratic
        - extract_constraint
        - parse_cells
        - parse_bounds
        - cells_to_spec
        - OptError
        - NotLinear
        - NotQuadratic
