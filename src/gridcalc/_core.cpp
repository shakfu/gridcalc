#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

#include <OpenXLSX.hpp>

namespace nb = nanobind;
using namespace OpenXLSX;

namespace {

std::string format_double(double v) {
    if (std::isnan(v) || std::isinf(v)) return "";
    if (std::abs(v) < 1e15) {
        double truncated = std::trunc(v);
        if (v == truncated) {
            char buf[32];
            std::snprintf(buf, sizeof(buf), "%lld", static_cast<long long>(truncated));
            return buf;
        }
    }
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%g", v);
    return buf;
}

std::string cell_to_text(XLCell& cell) {
    if (cell.hasFormula()) {
        std::string f = cell.formula().get();
        if (f.empty()) return "";
        return (f.front() == '=') ? f : ("=" + f);
    }
    XLCellValue val = cell.value();
    switch (val.type()) {
        case XLValueType::Empty: return "";
        case XLValueType::Boolean: return val.get<bool>() ? "TRUE" : "FALSE";
        case XLValueType::Integer: return std::to_string(val.get<int64_t>());
        case XLValueType::Float: return format_double(val.get<double>());
        case XLValueType::String: return val.get<std::string>();
        case XLValueType::Error: return "";
    }
    return "";
}

nb::list xlsx_read(const std::string& path) {
    // Returns list[(sheet_name, col, row, text)] across every sheet
    // in the workbook, in workbook order.
    nb::list out;
    XLDocument doc;
    doc.open(path);
    auto wbk = doc.workbook();
    auto names = wbk.sheetNames();
    for (auto const& sname : names) {
        auto wks = wbk.worksheet(sname);
        for (auto& row : wks.rows()) {
            uint32_t r = row.rowNumber();
            for (auto& cell : row.cells()) {
                if (!cell.hasFormula() && cell.value().type() == XLValueType::Empty) continue;
                std::string text = cell_to_text(cell);
                if (text.empty()) continue;
                uint16_t c = cell.cellReference().column();
                out.append(nb::make_tuple(sname,
                                          static_cast<int>(c) - 1,
                                          static_cast<int>(r) - 1,
                                          text));
            }
        }
    }
    doc.close();
    return out;
}

void xlsx_write(const std::string& path, nb::list cells, nb::list sheet_names) {
    // Accepts list[(sheet_name, col, row, kind, value)] plus the workbook's
    // full ordered sheet-name list. `sheet_names` is what makes an empty
    // sheet survive: the cell payload cannot describe a sheet with no cells,
    // so a workbook's empty sheets would otherwise vanish on export.
    XLDocument doc;
    std::remove(path.c_str());
    doc.create(path);
    auto wbk = doc.workbook();
    const std::string default_name = wbk.sheetNames().front();
    bool default_consumed = false;

    auto ensure_sheet = [&](const std::string& name) {
        auto current = wbk.sheetNames();
        for (auto const& s : current) {
            if (s == name) {
                // A name that matches the auto-created default sheet is not
                // an existing sheet the caller asked for -- it is the default
                // itself. Claiming it here marks the default consumed, so a
                // later sheet gets a new worksheet instead of renaming (and
                // merging into) this one.
                if (!default_consumed && name == default_name) {
                    default_consumed = true;
                }
                return;
            }
        }
        if (!default_consumed) {
            // Reuse the auto-created default rather than leaving it as a
            // stray empty sheet.
            wbk.sheet(default_name).setName(name);
            default_consumed = true;
            return;
        }
        wbk.addWorksheet(name);
    };

    // Create every sheet the workbook has, in model order, before any cell
    // is written. This fixes sheet order too: it no longer depends on which
    // sheet happens to hold the first non-empty cell.
    for (auto handle : sheet_names) {
        ensure_sheet(nb::cast<std::string>(handle));
    }

    for (auto handle : cells) {
        nb::tuple t = nb::cast<nb::tuple>(handle);
        std::string sname = nb::cast<std::string>(t[0]);
        int c0 = nb::cast<int>(t[1]);
        int r0 = nb::cast<int>(t[2]);
        std::string kind = nb::cast<std::string>(t[3]);
        ensure_sheet(sname);
        auto wks = wbk.worksheet(sname);
        XLCellReference ref(static_cast<uint32_t>(r0 + 1),
                            static_cast<uint16_t>(c0 + 1));
        auto cell = wks.cell(ref);
        if (kind == "s") {
            cell.value() = nb::cast<std::string>(t[4]);
        } else if (kind == "n") {
            double v = nb::cast<double>(t[4]);
            if (!std::isnan(v) && !std::isinf(v)) cell.value() = v;
        } else if (kind == "f") {
            // Formula: t[4] is the formula text (with or without leading '='),
            // optional t[5] is the cached numeric value (None or float).
            std::string formula = nb::cast<std::string>(t[4]);
            if (!formula.empty() && formula.front() == '=') formula.erase(0, 1);
            if (!formula.empty()) cell.formula() = formula;
            if (t.size() > 5 && !t[5].is_none()) {
                double v = nb::cast<double>(t[5]);
                if (!std::isnan(v) && !std::isinf(v)) cell.value() = v;
            }
        }
    }
    // If the payload was empty, the auto-created default sheet is left
    // in place untouched -- OpenXLSX requires at least one sheet.
    doc.save();
    doc.close();
}

}  // namespace

NB_MODULE(_core, m) {
    m.doc() = "gridcalc native extensions";
    m.def("xlsx_read", &xlsx_read, nb::arg("path"),
          "Read an .xlsx file. Returns list[(col, row, text)] (zero-indexed).");
    m.def("xlsx_write", &xlsx_write, nb::arg("path"), nb::arg("cells"),
          nb::arg("sheet_names") = nb::list(),
          "Write cells to an .xlsx file. Each cell is (sheet, col, row, kind, value[, cached]); kind in {'s','n','f'} where 'f' uses value as formula text and optional cached numeric. sheet_names lists every sheet in workbook order, so empty sheets are written too.");
}
