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

void xlsx_write(const std::string& path, nb::list cells) {
    // Accepts list[(sheet_name, col, row, kind, value)]. Sheets are
    // created lazily in payload order; the default sheet that
    // OpenXLSX produces on `create()` is renamed to the first
    // unique sheet name in the payload (or kept if it already
    // matches).
    XLDocument doc;
    std::remove(path.c_str());
    doc.create(path);
    auto wbk = doc.workbook();
    bool default_renamed = false;
    std::string default_name = wbk.sheetNames().front();

    auto ensure_sheet = [&](const std::string& name) {
        auto current = wbk.sheetNames();
        for (auto const& s : current) {
            if (s == name) return;
        }
        if (!default_renamed) {
            // First payload sheet: rename the auto-created default.
            wbk.sheet(default_name).setName(name);
            default_renamed = true;
            return;
        }
        wbk.addWorksheet(name);
    };

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
          "Write cells to an .xlsx file. Each cell is (col, row, kind, value); kind in {'s','n'}.");
}
