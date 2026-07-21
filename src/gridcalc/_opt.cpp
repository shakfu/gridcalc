// Minimal nanobind binding around lp_solve's LP entry points.
//
// Surface is intentionally narrow: one function, dense matrices, no
// callbacks, no LP/MPS file I/O. Spreadsheet-scale problems fit comfortably
// in dense form; sparse / column-generation can be added later if a real
// workload demands them. MIP (via set_int / set_binary) and sensitivity
// analysis are supported.
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

// lp_lib.h defines `isnan` as a macro (-> `_isnan`) on MSVC, which turns our
// later `std::isnan(...)` into `std::_isnan(...)` and fails to compile
// (error C2039: '_isnan' is not a member of 'std'). Drop the macro here so the
// standard library name resolves; lp_solve's own sources compile separately
// and keep their macro.
#ifdef isnan
#undef isnan
#endif

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

    // Sensitivity analysis. Empty unless `sensitivity=true` was requested
    // and the solve succeeded. `sensitivity_valid` distinguishes "not asked
    // for" from "asked for but not meaningful" -- see the MIP note below.
    bool sensitivity_valid = false;
    std::vector<double> duals;         // per constraint: shadow price
    std::vector<double> dual_from;     // per constraint: RHS range lower
    std::vector<double> dual_till;     // per constraint: RHS range upper
    std::vector<double> reduced_costs; // per variable
    std::vector<double> obj_from;      // per variable: obj-coef range lower
    std::vector<double> obj_till;      // per variable: obj-coef range upper
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
//
// `sensitivity` opts into dual values, reduced costs, and RHS / objective
// ranging. It is off by default because obtaining duals requires enabling
// PRESOLVE_SENSDUALS before the solve, which changes lp_solve's presolve
// behaviour; callers that do not need sensitivity should not pay for it or
// risk the perturbation.
Solution solve_lp(
    const std::vector<double>& c,
    const std::vector<std::vector<double>>& A,
    const std::vector<int>& sense,
    const std::vector<double>& rhs,
    const std::vector<double>& lb,
    const std::vector<double>& ub,
    bool maximize,
    const std::vector<int>& integer_vars,
    const std::vector<int>& binary_vars,
    bool sensitivity)
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

    // Duals are only produced when the solver is told to compute them, and
    // only before solving -- asking afterwards returns nothing.
    const bool is_mip = !integer_vars.empty() || !binary_vars.empty();
    if (sensitivity) {
        set_presolve(lp, PRESOLVE_SENSDUALS, get_presolveloops(lp));
    }

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

        // Sensitivity is deliberately withheld for MIPs. lp_solve will hand
        // back numbers, but the dual of a branch-and-bound node is the dual
        // of one LP relaxation, not of the integer problem -- there is no
        // valid shadow-price interpretation. Reporting them anyway would be
        // worse than reporting nothing.
        if (sensitivity && !is_mip && out.status != UNBOUNDED) {
            REAL* duals = nullptr;
            REAL* dfrom = nullptr;
            REAL* dtill = nullptr;
            REAL* ofrom = nullptr;
            REAL* otill = nullptr;
            const bool got_rhs = get_ptr_sensitivity_rhs(lp, &duals, &dfrom, &dtill);
            const bool got_obj = get_ptr_sensitivity_obj(lp, &ofrom, &otill);

            if (got_rhs && duals != nullptr) {
                // One array of length rows+columns: constraint duals first,
                // then per-variable reduced costs. lp_solve's own reporting
                // (lp_report.c REPORT_lp) indexes it exactly this way.
                out.duals.assign(duals, duals + m);
                out.reduced_costs.assign(duals + m, duals + m + n);
                if (dfrom != nullptr) out.dual_from.assign(dfrom, dfrom + m);
                if (dtill != nullptr) out.dual_till.assign(dtill, dtill + m);
                out.sensitivity_valid = true;
            }
            if (got_obj && ofrom != nullptr && otill != nullptr) {
                out.obj_from.assign(ofrom, ofrom + n);
                out.obj_till.assign(otill, otill + n);
            }
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
        .def_ro("status",            &Solution::status)
        .def_ro("objective",         &Solution::objective)
        .def_ro("x",                 &Solution::x)
        .def_ro("sensitivity_valid", &Solution::sensitivity_valid)
        .def_ro("duals",             &Solution::duals)
        .def_ro("dual_from",         &Solution::dual_from)
        .def_ro("dual_till",         &Solution::dual_till)
        .def_ro("reduced_costs",     &Solution::reduced_costs)
        .def_ro("obj_from",          &Solution::obj_from)
        .def_ro("obj_till",          &Solution::obj_till);

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
        nb::arg("sensitivity")  = false,
        "Solve an LP or MIP. Returns a Solution with .status, .objective, .x. "
        "integer_vars / binary_vars are 0-based column indices flagged "
        "integer or binary; binary variables are clamped to [0,1] by lp_solve. "
        "sensitivity=True additionally populates .duals (shadow price per "
        "constraint), .reduced_costs (per variable), and the .dual_from / "
        ".dual_till / .obj_from / .obj_till ranging arrays; it is ignored for "
        "MIPs, where duals have no valid interpretation -- check "
        ".sensitivity_valid.");
}
