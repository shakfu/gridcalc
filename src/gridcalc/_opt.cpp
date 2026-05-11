// Minimal nanobind binding around lp_solve's LP entry points.
//
// Surface is intentionally narrow: one function, dense matrices, no MIP, no
// callbacks, no LP/MPS file I/O. Spreadsheet-scale problems fit comfortably
// in dense form; sparse / sensitivity / column-generation can be added later
// if a real workload demands them.
//
// Status codes pass through lp_solve's values unchanged (OPTIMAL=0,
// SUBOPTIMAL=1, INFEASIBLE=2, UNBOUNDED=3, DEGENERATE=4, NUMFAILURE=5,
// USERABORT=6, TIMEOUT=7).

#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>

#include <cmath>
#include <stdexcept>
#include <vector>  // IWYU pragma: keep -- used directly; clangd sees it transitively from nanobind/stl/vector.h

extern "C" {
#include "lp_lib.h"
}

namespace nb = nanobind;

namespace {

// lp_solve treats |value| >= 1e30 as the infinity sentinel internally, but
// `set_bounds` itself does not interpret the sentinel as "free" -- it stores
// the literal 1e30 as a finite bound, which produces a feasible-but-huge
// optimum on otherwise unbounded problems instead of returning UNBOUNDED.
// To get true free / one-sided variables we must use `set_unbounded`,
// `set_lowbo`, and `set_upbo`, which the helpers below dispatch on.
constexpr double LP_INF = 1e30;

bool is_neg_inf(double v) { return std::isinf(v) < 0 || v <= -LP_INF; }
bool is_pos_inf(double v) { return std::isinf(v) > 0 || v >=  LP_INF; }

struct Solution {
    int status;
    double objective;
    std::vector<double> x;
};

// Solve a linear program (or mixed-integer LP) in standard form:
//
//     {min,max} c^T x
//     subject to  A_i x  {<=, >=, ==}  b_i   for each row i
//                 lb <= x <= ub
//                 x[j] integer for j in integer_vars
//                 x[j] in {0, 1} for j in binary_vars
//
// `sense` uses lp_solve's row-type constants: 1 = LE, 2 = GE, 3 = EQ.
// `integer_vars` and `binary_vars` hold 0-based column indices. A variable
// flagged binary has its bounds clamped to [0,1] by lp_solve regardless of
// what was passed in `lb`/`ub`; mixing the two flags on the same column is
// rejected as a programming error.
Solution solve_lp(
    const std::vector<double>& c,
    const std::vector<std::vector<double>>& A,
    const std::vector<int>& sense,
    const std::vector<double>& rhs,
    const std::vector<double>& lb,
    const std::vector<double>& ub,
    bool maximize,
    const std::vector<int>& integer_vars,
    const std::vector<int>& binary_vars)
{
    const int n = static_cast<int>(c.size());
    const int m = static_cast<int>(A.size());

    if (n == 0) throw std::invalid_argument("c must be non-empty");
    if (lb.size() != static_cast<size_t>(n) || ub.size() != static_cast<size_t>(n)) {
        throw std::invalid_argument("lb and ub must match length of c");
    }
    if (sense.size() != static_cast<size_t>(m) || rhs.size() != static_cast<size_t>(m)) {
        throw std::invalid_argument("sense and rhs must match number of rows in A");
    }
    for (int i = 0; i < m; ++i) {
        if (A[i].size() != static_cast<size_t>(n)) {
            throw std::invalid_argument("each row of A must have length n");
        }
        if (sense[i] != LE && sense[i] != GE && sense[i] != EQ) {
            throw std::invalid_argument("sense entries must be 1 (LE), 2 (GE), or 3 (EQ)");
        }
    }
    // Validate integer/binary indices and reject overlap. Overlap would
    // silently make set_binary win because it's applied second below;
    // returning an error keeps the surprise out of the user's results.
    std::vector<bool> is_binary(n, false);
    for (int j : integer_vars) {
        if (j < 0 || j >= n) throw std::invalid_argument("integer_vars index out of range");
    }
    for (int j : binary_vars) {
        if (j < 0 || j >= n) throw std::invalid_argument("binary_vars index out of range");
        is_binary[j] = true;
    }
    for (int j : integer_vars) {
        if (is_binary[j]) {
            throw std::invalid_argument("variable cannot be both integer and binary");
        }
    }

    lprec* lp = make_lp(0, n);
    if (!lp) throw std::runtime_error("make_lp failed");

    // RAII guard: any throw between here and `delete_lp` would leak the
    // model. Use a small destructor-only struct rather than a full smart-ptr
    // type for one local resource.
    struct LpGuard {
        lprec* lp;
        ~LpGuard() { if (lp) delete_lp(lp); }
    } guard{lp};

    set_verbose(lp, CRITICAL);

    // Row-mode bulk-add is the documented fast path for building a model.
    set_add_rowmode(lp, TRUE);

    // Objective: lp_solve expects a 1-indexed REAL[n+1] with row[0] unused.
    {
        std::vector<REAL> row(n + 1, 0.0);
        for (int j = 0; j < n; ++j) row[j + 1] = c[j];
        if (!set_obj_fn(lp, row.data())) {
            throw std::runtime_error("set_obj_fn failed");
        }
    }

    // Constraint rows, same 1-indexed convention.
    {
        std::vector<REAL> row(n + 1, 0.0);
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < n; ++j) row[j + 1] = A[i][j];
            if (!add_constraint(lp, row.data(), sense[i], rhs[i])) {
                throw std::runtime_error("add_constraint failed");
            }
        }
    }

    set_add_rowmode(lp, FALSE);

    // Variable bounds (1-indexed columns). lp_solve's default is [0, +inf),
    // which is wrong for variables the caller wants to be free or
    // negative-only. Dispatch by infinity-ness so each combination uses the
    // right C API:
    //   both infinite      -> set_unbounded         => (-inf, +inf)
    //   lb = -inf, ub finite-> set_unbounded then set_upbo => (-inf, hi]
    //   lb finite, ub = +inf-> set_lowbo                  => [lo, +inf)
    //   both finite        -> set_bounds                  => [lo, hi]
    for (int j = 0; j < n; ++j) {
        const double lo = lb[j];
        const double hi = ub[j];
        if (std::isnan(lo) || std::isnan(hi)) {
            throw std::invalid_argument("NaN bound is not allowed");
        }
        const bool lo_inf = is_neg_inf(lo);
        const bool hi_inf = is_pos_inf(hi);
        if (!lo_inf && !hi_inf && lo > hi) {
            throw std::invalid_argument("lb[j] > ub[j]");
        }

        bool ok = true;
        if (lo_inf && hi_inf) {
            ok = set_unbounded(lp, j + 1);
        } else if (lo_inf) {
            ok = set_unbounded(lp, j + 1) && set_upbo(lp, j + 1, hi);
        } else if (hi_inf) {
            ok = set_lowbo(lp, j + 1, lo);
        } else {
            ok = set_bounds(lp, j + 1, lo, hi);
        }
        if (!ok) {
            throw std::runtime_error("setting variable bound failed");
        }
    }

    // Apply integer/binary flags. `set_binary` clamps bounds to [0,1] so
    // it must come after the bounds dispatch above, otherwise an explicit
    // bound set later would override it.
    for (int j : integer_vars) {
        if (!set_int(lp, j + 1, TRUE)) {
            throw std::runtime_error("set_int failed");
        }
    }
    for (int j : binary_vars) {
        if (!set_binary(lp, j + 1, TRUE)) {
            throw std::runtime_error("set_binary failed");
        }
    }

    if (maximize) set_maxim(lp); else set_minim(lp);

    Solution out;
    out.status = solve(lp);
    out.objective = 0.0;
    out.x.assign(n, 0.0);

    if (out.status == OPTIMAL || out.status == SUBOPTIMAL) {
        out.objective = get_objective(lp);
        std::vector<REAL> vars(n, 0.0);
        if (!get_variables(lp, vars.data())) {
            throw std::runtime_error("get_variables failed");
        }
        for (int j = 0; j < n; ++j) out.x[j] = vars[j];

        // Guard against lp_solve's degenerate-presolve case: a free variable
        // that never appears in a constraint can be reported as OPTIMAL with
        // its value pinned at the internal 1e30 sentinel rather than as
        // UNBOUNDED. Detect by checking the objective magnitude; the bound
        // is well outside any plausible spreadsheet workload.
        if (std::abs(out.objective) >= LP_INF) {
            out.status = UNBOUNDED;
            out.objective = 0.0;
            std::fill(out.x.begin(), out.x.end(), 0.0);
        }
    }
    return out;
}

} // namespace

NB_MODULE(_opt, m) {
    m.doc() = "lp_solve-backed LP solver (minimal nanobind binding).";

    // Re-export lp_solve's row-type and status constants so Python callers
    // can refer to them by name rather than by magic integer.
    m.attr("LE")          = LE;
    m.attr("GE")          = GE;
    m.attr("EQ")          = EQ;
    m.attr("OPTIMAL")     = OPTIMAL;
    m.attr("SUBOPTIMAL")  = SUBOPTIMAL;
    m.attr("INFEASIBLE")  = INFEASIBLE;
    m.attr("UNBOUNDED")   = UNBOUNDED;
    m.attr("DEGENERATE")  = DEGENERATE;
    m.attr("NUMFAILURE")  = NUMFAILURE;
    m.attr("USERABORT")   = USERABORT;
    m.attr("TIMEOUT")     = TIMEOUT;

    nb::class_<Solution>(m, "Solution")
        .def_ro("status",    &Solution::status)
        .def_ro("objective", &Solution::objective)
        .def_ro("x",         &Solution::x);

    m.def("solve_lp", &solve_lp,
        nb::arg("c"),
        nb::arg("A"),
        nb::arg("sense"),
        nb::arg("rhs"),
        nb::arg("lb"),
        nb::arg("ub"),
        nb::arg("maximize") = false,
        nb::arg("integer_vars") = std::vector<int>{},
        nb::arg("binary_vars")  = std::vector<int>{},
        "Solve an LP or MIP. Returns a Solution with .status, .objective, .x. "
        "integer_vars / binary_vars are 0-based column indices flagged "
        "integer or binary; binary variables are clamped to [0,1] by lp_solve.");
}
