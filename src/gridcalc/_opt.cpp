// Minimal nanobind binding around HiGHS.
//
// Surface is intentionally narrow: one function, dense matrices in, no
// callbacks, no LP/MPS file I/O. Spreadsheet-scale problems fit comfortably in
// dense form; sparse input can be added later if a real workload demands it.
// LP, MIP (via integrality), convex QP (via a Hessian), and sensitivity
// analysis are supported.
//
// This replaced an lp_solve backend. HiGHS is MIT rather than LGPL, solves
// convex QP natively (so a separable-only piecewise-linear workaround could be
// deleted), and uses a real infinity instead of lp_solve's 1e30 sentinel --
// which removes a class of bound-handling bugs rather than working around it.
//
// The Python-facing surface is deliberately unchanged from the lp_solve
// version: the same `solve_lp` signature, the same `Solution` fields, and the
// same integer values for the LE/GE/EQ and status constants. Those values are
// this module's own contract, translated to and from HiGHS internally, so the
// Python layer above did not have to change and its existing tests carried
// over as the migration's verification.

#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>

#include <cmath>
#include <stdexcept>
#include <vector>  // IWYU pragma: keep -- used directly; clangd sees it transitively from nanobind/stl/vector.h

extern "C" {
#include "highs_c_api.h"
}

namespace nb = nanobind;

namespace {

// Row senses. These values are this module's API, inherited from the lp_solve
// era so callers did not have to change; HiGHS models a row as a
// [lower, upper] pair instead, which `row_bounds` below derives.
constexpr int SENSE_LE = 1;
constexpr int SENSE_GE = 2;
constexpr int SENSE_EQ = 3;

// Status codes, likewise this module's API rather than a passthrough.
constexpr int ST_OPTIMAL    = 0;
constexpr int ST_SUBOPTIMAL = 1;
constexpr int ST_INFEASIBLE = 2;
constexpr int ST_UNBOUNDED  = 3;
constexpr int ST_DEGENERATE = 4;
constexpr int ST_NUMFAILURE = 5;
constexpr int ST_USERABORT  = 6;
constexpr int ST_TIMEOUT    = 7;

int translate_status(int highs_status) {
    if (highs_status == kHighsModelStatusOptimal)     return ST_OPTIMAL;
    if (highs_status == kHighsModelStatusInfeasible)  return ST_INFEASIBLE;
    if (highs_status == kHighsModelStatusUnbounded)   return ST_UNBOUNDED;
    // HiGHS reports "unbounded or infeasible" when presolve cannot separate
    // the two. Callers act on this by looking for a runaway variable or a
    // conflicting constraint set, and reporting UNBOUNDED sends them down the
    // branch that can distinguish the cases by re-solving.
    if (highs_status == kHighsModelStatusUnboundedOrInfeasible)
        return ST_UNBOUNDED;
    if (highs_status == kHighsModelStatusTimeLimit)       return ST_TIMEOUT;
    if (highs_status == kHighsModelStatusIterationLimit)  return ST_SUBOPTIMAL;
    if (highs_status == kHighsModelStatusInterrupt)       return ST_USERABORT;
    if (highs_status == kHighsModelStatusSolutionLimit ||
        highs_status == kHighsModelStatusObjectiveBound ||
        highs_status == kHighsModelStatusObjectiveTarget)
        return ST_SUBOPTIMAL;
    return ST_NUMFAILURE;
}

struct Solution {
    int status;
    double objective;
    std::vector<double> x;

    bool sensitivity_valid = false;
    std::vector<double> duals;
    std::vector<double> dual_from;
    std::vector<double> dual_till;
    std::vector<double> reduced_costs;
    std::vector<double> obj_from;
    std::vector<double> obj_till;
};

// RAII for the Highs handle: every error path below throws, and the C API has
// no other way to release it.
struct HighsGuard {
    void* h;
    ~HighsGuard() { if (h) Highs_destroy(h); }
};

// Solve a linear, mixed-integer, or convex quadratic program:
//
//     {min,max} c^T x + 0.5 x^T Q x
//     subject to  A_i x  {<=, >=, ==}  b_i   for each row i
//                 lb <= x <= ub
//                 x[j] integer for j in integer_vars
//                 x[j] in {0, 1} for j in binary_vars
//
// `sense` uses this module's row-type constants: 1 = LE, 2 = GE, 3 = EQ.
// `integer_vars` and `binary_vars` hold 0-based column indices; a binary
// column additionally has its bounds clamped to [0,1]. Mixing the two flags on
// one column is rejected as a programming error.
//
// `hessian` is the dense lower triangle of Q, row-major and ragged: entry
// [i][j] for j <= i. Empty means a purely linear objective. Q must be positive
// semi-definite for a minimisation (negative semi-definite for a
// maximisation); HiGHS rejects an indefinite Hessian and the error surfaces as
// a solver failure rather than a wrong answer.
//
// `sensitivity` opts into duals, reduced costs, and ranging. It is off by
// default because it requires a second HiGHS call over the solved basis.
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
    bool sensitivity,
    const std::vector<std::vector<double>>& hessian)
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
        if (sense[i] != SENSE_LE && sense[i] != SENSE_GE && sense[i] != SENSE_EQ) {
            throw std::invalid_argument("sense entries must be 1 (LE), 2 (GE), or 3 (EQ)");
        }
    }
    if (!hessian.empty() && hessian.size() != static_cast<size_t>(n)) {
        throw std::invalid_argument("hessian must have one row per column of c");
    }

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

    void* highs = Highs_create();
    if (!highs) throw std::runtime_error("Highs_create failed");
    HighsGuard guard{highs};
    // The solver is chatty by default and would corrupt the curses display.
    Highs_setBoolOptionValue(highs, "output_flag", 0);

    const double inf = Highs_getInfinity(highs);

    // Column bounds. NaN is rejected here rather than passed through: HiGHS
    // would accept it and produce nonsense.
    std::vector<double> col_lower(n), col_upper(n);
    for (int j = 0; j < n; ++j) {
        double lo = lb[j], hi = ub[j];
        if (std::isnan(lo) || std::isnan(hi)) {
            throw std::invalid_argument("NaN bound is not allowed");
        }
        if (is_binary[j]) {
            // Match the previous backend's documented behaviour: a binary
            // column is clamped to [0,1] whatever bounds were passed.
            lo = 0.0;
            hi = 1.0;
        }
        if (!std::isinf(lo) && !std::isinf(hi) && lo > hi) {
            throw std::invalid_argument("lb[j] > ub[j]");
        }
        col_lower[j] = std::isinf(lo) ? (lo < 0 ? -inf : inf) : lo;
        col_upper[j] = std::isinf(hi) ? (hi < 0 ? -inf : inf) : hi;
    }

    // Row bounds. A one-sided row gets an infinite bound on the free side;
    // this is where HiGHS's real infinity replaces lp_solve's sentinel.
    std::vector<double> row_lower(m), row_upper(m);
    for (int i = 0; i < m; ++i) {
        if (sense[i] == SENSE_LE)      { row_lower[i] = -inf;   row_upper[i] = rhs[i]; }
        else if (sense[i] == SENSE_GE) { row_lower[i] = rhs[i]; row_upper[i] = inf;    }
        else                           { row_lower[i] = rhs[i]; row_upper[i] = rhs[i]; }
    }

    // Constraint matrix, row-wise CSR. Zeros are dropped: the caller hands us
    // dense rows, but spreadsheet models are typically sparse and HiGHS is
    // happier without the explicit zeros.
    //
    // HiGHS rejects a model containing a matrix entry smaller than its
    // `small_matrix_value` tolerance (1e-9) -- such a coefficient is
    // numerically indistinguishable from zero and the model is ill-posed.
    // The API only reports that as a generic failure, so check here and say
    // which coefficient is at fault.
    constexpr double SMALL_MATRIX_VALUE = 1e-9;
    std::vector<int> a_start;
    std::vector<int> a_index;
    std::vector<double> a_value;
    a_start.reserve(static_cast<size_t>(m));
    for (int i = 0; i < m; ++i) {
        a_start.push_back(static_cast<int>(a_index.size()));
        for (int j = 0; j < n; ++j) {
            const double v = A[i][j];
            if (v == 0.0) continue;
            if (std::abs(v) <= SMALL_MATRIX_VALUE) {
                throw std::invalid_argument(
                    "constraint coefficient is too small to be distinguished "
                    "from zero (|value| <= 1e-9); rescale the constraint");
            }
            a_index.push_back(j);
            a_value.push_back(v);
        }
    }
    const int a_nnz = static_cast<int>(a_index.size());

    std::vector<int> integrality;
    const bool is_mip = !integer_vars.empty() || !binary_vars.empty();
    if (is_mip) {
        integrality.assign(static_cast<size_t>(n), kHighsVarTypeContinuous);
        for (int j : integer_vars) integrality[j] = kHighsVarTypeInteger;
        for (int j : binary_vars)  integrality[j] = kHighsVarTypeInteger;
    }

    const int obj_sense = maximize ? kHighsObjSenseMaximize : kHighsObjSenseMinimize;

    if (Highs_passLp(highs, n, m, a_nnz, kHighsMatrixFormatRowwise, obj_sense,
                     0.0, c.data(), col_lower.data(), col_upper.data(),
                     row_lower.data(), row_upper.data(),
                     a_start.data(), a_index.data(), a_value.data()) != kHighsStatusOk) {
        throw std::runtime_error("Highs_passLp failed");
    }

    if (is_mip) {
        for (int j = 0; j < n; ++j) {
            if (Highs_changeColIntegrality(highs, j, integrality[j]) != kHighsStatusOk) {
                throw std::runtime_error("Highs_changeColIntegrality failed");
            }
        }
    }

    // Hessian, as the lower triangle in CSC. HiGHS optimises
    // c'x + 0.5 x'Qx, so a caller wanting `q_j * x_j^2` passes 2*q_j on the
    // diagonal; that scaling is the Python layer's job, not this one's.
    if (!hessian.empty()) {
        std::vector<int> q_start;
        std::vector<int> q_index;
        std::vector<double> q_value;
        q_start.reserve(static_cast<size_t>(n));
        for (int j = 0; j < n; ++j) {
            q_start.push_back(static_cast<int>(q_index.size()));
            // Column j of the lower triangle is rows i >= j, i.e. entries
            // hessian[i][j] for each i from j to n-1.
            for (int i = j; i < n; ++i) {
                if (static_cast<size_t>(j) >= hessian[i].size()) continue;
                const double v = hessian[i][j];
                if (v != 0.0) {
                    q_index.push_back(i);
                    q_value.push_back(v);
                }
            }
        }
        const int q_nnz = static_cast<int>(q_index.size());
        if (q_nnz > 0) {
            if (Highs_passHessian(highs, n, q_nnz, kHighsHessianFormatTriangular,
                                  q_start.data(), q_index.data(),
                                  q_value.data()) != kHighsStatusOk) {
                throw std::runtime_error("Highs_passHessian failed");
            }
        }
    }

    Solution out;
    Highs_run(highs);
    out.status = translate_status(static_cast<int>(Highs_getModelStatus(highs)));
    out.objective = 0.0;
    out.x.assign(static_cast<size_t>(n), 0.0);

    if (out.status == ST_OPTIMAL || out.status == ST_SUBOPTIMAL) {
        out.objective = Highs_getObjectiveValue(highs);
        std::vector<double> col_value(static_cast<size_t>(n), 0.0);
        std::vector<double> col_dual(static_cast<size_t>(n), 0.0);
        std::vector<double> row_value(static_cast<size_t>(m > 0 ? m : 1), 0.0);
        std::vector<double> row_dual(static_cast<size_t>(m > 0 ? m : 1), 0.0);
        Highs_getSolution(highs, col_value.data(), col_dual.data(),
                          row_value.data(), row_dual.data());
        for (int j = 0; j < n; ++j) out.x[j] = col_value[j];

        // Sensitivity is withheld for MIPs and QPs: a branch-and-bound dual
        // describes one relaxation rather than the integer problem, and a QP's
        // duals do not carry the shadow-price reading the caller reports.
        if (sensitivity && !is_mip && hessian.empty() && m > 0) {
            std::vector<double> cost_up_v(n), cost_up_o(n), cost_dn_v(n), cost_dn_o(n);
            std::vector<int>    cost_up_i(n), cost_up_o2(n), cost_dn_i(n), cost_dn_o2(n);
            std::vector<double> cb_up_v(n), cb_up_o(n), cb_dn_v(n), cb_dn_o(n);
            std::vector<int>    cb_up_i(n), cb_up_o2(n), cb_dn_i(n), cb_dn_o2(n);
            std::vector<double> rb_up_v(m), rb_up_o(m), rb_dn_v(m), rb_dn_o(m);
            std::vector<int>    rb_up_i(m), rb_up_o2(m), rb_dn_i(m), rb_dn_o2(m);

            if (Highs_getRanging(highs,
                    cost_up_v.data(), cost_up_o.data(), cost_up_i.data(), cost_up_o2.data(),
                    cost_dn_v.data(), cost_dn_o.data(), cost_dn_i.data(), cost_dn_o2.data(),
                    cb_up_v.data(), cb_up_o.data(), cb_up_i.data(), cb_up_o2.data(),
                    cb_dn_v.data(), cb_dn_o.data(), cb_dn_i.data(), cb_dn_o2.data(),
                    rb_up_v.data(), rb_up_o.data(), rb_up_i.data(), rb_up_o2.data(),
                    rb_dn_v.data(), rb_dn_o.data(), rb_dn_i.data(), rb_dn_o2.data())
                == kHighsStatusOk) {
                out.duals.assign(row_dual.begin(), row_dual.begin() + m);
                out.reduced_costs.assign(col_dual.begin(), col_dual.begin() + n);
                out.dual_from = rb_dn_v;
                out.dual_till = rb_up_v;
                out.obj_from = cost_dn_v;
                out.obj_till = cost_up_v;
                out.sensitivity_valid = true;
            }
        }
    }
    return out;
}

} // namespace

NB_MODULE(_opt, m) {
    m.doc() = "HiGHS-backed LP / MIP / convex-QP solver (minimal nanobind binding).";

    // Row-type and status constants. These are this module's own values,
    // preserved across the lp_solve -> HiGHS migration so the Python layer and
    // its saved workbooks were unaffected.
    m.attr("LE")          = SENSE_LE;
    m.attr("GE")          = SENSE_GE;
    m.attr("EQ")          = SENSE_EQ;
    m.attr("OPTIMAL")     = ST_OPTIMAL;
    m.attr("SUBOPTIMAL")  = ST_SUBOPTIMAL;
    m.attr("INFEASIBLE")  = ST_INFEASIBLE;
    m.attr("UNBOUNDED")   = ST_UNBOUNDED;
    m.attr("DEGENERATE")  = ST_DEGENERATE;
    m.attr("NUMFAILURE")  = ST_NUMFAILURE;
    m.attr("USERABORT")   = ST_USERABORT;
    m.attr("TIMEOUT")     = ST_TIMEOUT;

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
        nb::arg("hessian")      = std::vector<std::vector<double>>{},
        "Solve an LP, MIP, or convex QP. Returns a Solution with .status, "
        ".objective, .x. integer_vars / binary_vars are 0-based column indices; "
        "binary columns are clamped to [0,1]. hessian is the dense lower "
        "triangle of Q for the 0.5*x'Qx objective term, empty for a linear "
        "objective. sensitivity=True populates .duals (shadow price per "
        "constraint), .reduced_costs, and the .dual_from / .dual_till / "
        ".obj_from / .obj_till ranging arrays; it is ignored for MIPs and QPs "
        "-- check .sensitivity_valid.");
}
