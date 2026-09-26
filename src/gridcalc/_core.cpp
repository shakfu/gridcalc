#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include <cmath>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <utility>

#include <OpenXLSX.hpp>

namespace nb = nanobind;
using namespace OpenXLSX;

namespace {

// A cell's value as (kind, value): "n" double, "s" string, "b" bool, "e"
// error text, or "" for an empty cell. Typed, so text that looks like a number
// or a formula stays text on import.
std::pair<std::string, nb::object> cell_value(XLCell& cell) {
    XLCellValue val = cell.value();
    switch (val.type()) {
        case XLValueType::Boolean: return {"b", nb::bool_(val.get<bool>())};
        case XLValueType::Integer:
            return {"n", nb::float_(static_cast<double>(val.get<int64_t>()))};
        case XLValueType::Float: return {"n", nb::float_(val.get<double>())};
        case XLValueType::String: return {"s", nb::str(val.get<std::string>().c_str())};
        case XLValueType::Error: return {"e", nb::str(val.getString().c_str())};
        case XLValueType::Empty: break;
    }
    return {"", nb::none()};
}

// The number format attached to a cell, as (format code, numFmtId).
//
// A date in xlsx is a plain number whose cell style names a date format --
// there is no date value type -- so this is the only evidence that a column
// of floats is a column of dates. Built-in ids (14-22, 45-47) carry no code
// in the file at all, which is why the id is reported as well as the string.
//
// Every lookup can throw XLException on a file whose style table is missing
// or inconsistent, and a malformed style is not a reason to fail the whole
// read: an unstyled cell is still a number the user wants. So each stage
// degrades to "no format".
std::pair<std::string, uint32_t> cell_number_format(XLDocument& doc, XLCell& cell) {
    try {
        XLStyleIndex styleIndex = cell.cellFormat();
        auto formats = doc.styles().cellFormats();
        if (styleIndex >= formats.count()) return {"", 0};
        uint32_t fmtId = formats[styleIndex].numberFormatId();
        if (fmtId == 0) return {"", 0};
        try {
            return {doc.styles().numberFormats().numberFormatById(fmtId).formatCode(), fmtId};
        } catch (...) {
            // A built-in id: defined by the spec, so it has no entry in the
            // file's numFmts table. The id alone identifies it.
            return {"", fmtId};
        }
    } catch (...) {
        return {"", 0};
    }
}

// Style bits for a cell: 1 bold, 2 italic, 4 underline, 8 left-aligned,
// 16 right-aligned. A malformed style table degrades to 0, as in
// cell_number_format.
int cell_style_bits(XLDocument& doc, XLCell& cell) {
    try {
        XLStyleIndex styleIndex = cell.cellFormat();
        auto formats = doc.styles().cellFormats();
        if (styleIndex >= formats.count()) return 0;
        int flags = 0;
        try {
            XLAlignmentStyle h = formats[styleIndex].alignment().horizontal();
            if (h == XLAlignLeft) flags |= 8;
            if (h == XLAlignRight) flags |= 16;
        } catch (...) {
            // No alignment node: the default alignment.
        }
        XLStyleIndex fontIndex = formats[styleIndex].fontIndex();
        auto fonts = doc.styles().fonts();
        if (fontIndex >= fonts.count()) return flags;
        XLFont font = fonts[fontIndex];
        if (font.bold()) flags |= 1;
        if (font.italic()) flags |= 2;
        XLUnderlineStyle u = font.underline();
        if (u != XLUnderlineNone && u != XLUnderlineInvalid) flags |= 4;
        return flags;
    } catch (...) {
        return 0;
    }
}

nb::tuple xlsx_read(const std::string& path) {
    // Returns (worksheet_names, cells, fallbacks). cells is
    // list[(sheet, col, row, kind, value, numfmt_code, numfmt_id, style)] in workbook
    // order; kind is "f" (value = formula text) or a cell_value kind.
    // fallbacks counts shared and array formulas read as their cached value,
    // which OpenXLSX cannot return as text.
    nb::list names_out;
    nb::list out;
    int fallbacks = 0;
    XLDocument doc;
    doc.open(path);
    auto wbk = doc.workbook();
    // Worksheets only: a chartsheet has no cells, and worksheet() throws on one.
    for (auto const& sname : wbk.worksheetNames()) {
        names_out.append(nb::str(sname.c_str()));
        auto wks = wbk.worksheet(sname);
        for (auto& row : wks.rows()) {
            uint32_t r = row.rowNumber();
            for (auto& cell : row.cells()) {
                std::pair<std::string, nb::object> kv{"", nb::none()};
                if (cell.hasFormula()) {
                    try {
                        std::string f = cell.formula().get();
                        if (!f.empty()) kv = {"f", nb::str(((f.front() == '=') ? f : "=" + f).c_str())};
                    } catch (const XLException&) {
                        ++fallbacks;
                        kv = cell_value(cell);
                    }
                } else {
                    kv = cell_value(cell);
                }
                if (kv.first.empty()) continue;
                uint16_t c = cell.cellReference().column();
                auto fmt = cell_number_format(doc, cell);
                out.append(nb::make_tuple(nb::str(sname.c_str()),
                                          static_cast<int>(c) - 1,
                                          static_cast<int>(r) - 1,
                                          nb::str(kv.first.c_str()),
                                          kv.second,
                                          nb::str(fmt.first.c_str()),
                                          static_cast<int>(fmt.second),
                                          cell_style_bits(doc, cell)));
            }
        }
    }
    doc.close();
    return nb::make_tuple(names_out, out, fallbacks);
}

void xlsx_write(const std::string& path, nb::list cells, nb::list sheet_names) {
    // Accepts list[(sheet_name, col, row, kind, value)] plus the workbook's
    // full ordered sheet-name list. `sheet_names` is what makes an empty
    // sheet survive: the cell payload cannot describe a sheet with no cells,
    // so a workbook's empty sheets would otherwise vanish on export.
    // The caller writes to a fresh temp path and renames it into place, so
    // nothing here deletes or truncates the user's file.
    XLDocument doc;
    doc.create(path, XLForceOverwrite);
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

    // One cell-format entry per distinct number-format code, created lazily
    // and reused. Without the cache every dated cell would append its own
    // numFmt and cellXf entry, so a column of 1000 dates would write 1000
    // identical styles -- valid, but the file balloons and Excel's style
    // dialog fills with duplicates.
    std::unordered_map<std::string, XLStyleIndex> format_cache;
    // One font per distinct style-bit set, copied from the default font.
    std::unordered_map<int, XLStyleIndex> font_cache;
    // Custom number formats must use ids at or above 164; 0-163 are reserved
    // for the built-ins, and reusing one silently redefines it.
    uint32_t next_fmt_id = 164;

    // Bound by reference, once. `auto styles = doc.styles()` copies the
    // XLStyles object, and `create()` on the copy returns an index into the
    // copy's own vector -- so the second distinct format is written at an
    // index that, in the saved file, still holds the first. The symptom is a
    // cell silently wearing another cell's format.
    XLStyles& styles = doc.styles();

    auto font_for_flags = [&](int flags) -> XLStyleIndex {
        auto it = font_cache.find(flags);
        if (it != font_cache.end()) return it->second;
        XLStyleIndex fontIndex = styles.fonts().create(styles.fonts()[0]);
        styles.fonts()[fontIndex].setBold((flags & 1) != 0);
        styles.fonts()[fontIndex].setItalic((flags & 2) != 0);
        styles.fonts()[fontIndex].setUnderline((flags & 4) ? XLUnderlineSingle : XLUnderlineNone);
        font_cache[flags] = fontIndex;
        return fontIndex;
    };

    // One cell format per distinct (number-format code, style bits) pair.
    auto style_for = [&](const std::string& code, int flags) -> XLStyleIndex {
        std::string key = code + '\x01' + std::to_string(flags);
        auto it = format_cache.find(key);
        if (it != format_cache.end()) return it->second;
        uint32_t fmtId = 0;
        if (!code.empty()) {
            XLStyleIndex numberFormatIndex = styles.numberFormats().create();
            fmtId = next_fmt_id++;
            styles.numberFormats()[numberFormatIndex].setNumberFormatId(fmtId);
            styles.numberFormats()[numberFormatIndex].setFormatCode(code);
        }
        XLStyleIndex cellFormatIndex = styles.cellFormats().create();
        styles.cellFormats()[cellFormatIndex].setNumberFormatId(fmtId);
        styles.cellFormats()[cellFormatIndex].setApplyNumberFormat(!code.empty());
        int font_bits = flags & 7;
        styles.cellFormats()[cellFormatIndex].setFontIndex(font_bits ? font_for_flags(font_bits) : 0);
        styles.cellFormats()[cellFormatIndex].setApplyFont(font_bits != 0);
        if (flags & 24) {
            styles.cellFormats()[cellFormatIndex].alignment(XLCreateIfMissing).setHorizontal(
                (flags & 8) ? XLAlignLeft : XLAlignRight);
            styles.cellFormats()[cellFormatIndex].setApplyAlignment(true);
        }
        format_cache[key] = cellFormatIndex;
        return cellFormatIndex;
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
        } else if (kind == "b") {
            cell.value() = nb::cast<bool>(t[4]);
        } else if (kind == "f") {
            // Formula: t[4] is the formula text (with or without leading '='),
            // optional t[5] is the cached value (None, bool or float).
            std::string formula = nb::cast<std::string>(t[4]);
            if (!formula.empty() && formula.front() == '=') formula.erase(0, 1);
            if (!formula.empty()) cell.formula() = formula;
            bool cached = false;
            if (t.size() > 5 && nb::isinstance<nb::bool_>(t[5])) {
                cell.value() = nb::cast<bool>(t[5]);
                cached = true;
            } else if (t.size() > 5 && !t[5].is_none()) {
                double v = nb::cast<double>(t[5]);
                if (!std::isnan(v) && !std::isinf(v)) {
                    cell.value() = v;
                    cached = true;
                }
            }
            // Setting the formula wrote a cached 0; a text or error result has
            // no cached value rather than a wrong one.
            if (!cached) cell.value().clear();
        }
        // Trailing number-format code and style bits, when the caller
        // supplied them. They are last so shorter payloads stay valid.
        size_t fmt_slot = (kind == "f") ? 6 : 5;
        std::string code;
        int flags = 0;
        if (t.size() > fmt_slot && !t[fmt_slot].is_none()) {
            code = nb::cast<std::string>(t[fmt_slot]);
        }
        if (t.size() > fmt_slot + 1 && !t[fmt_slot + 1].is_none()) {
            flags = nb::cast<int>(t[fmt_slot + 1]) & 31;
        }
        if (!code.empty() || flags) {
            try {
                cell.setCellFormat(style_for(code, flags));
            } catch (...) {
                // A style table that will not take the format is not a
                // reason to lose the value that was already written.
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
          "Read an .xlsx file. Returns (worksheet_names, cells, fallbacks). cells is list[(sheet, col, row, kind, value, numfmt_code, numfmt_id, style)] (zero-indexed); style has bits 1 bold, 2 italic, 4 underline, 8 left-aligned, 16 right-aligned; kind is 'f' (formula text), 'n' (float), 's' (str), 'b' (bool) or 'e' (error text). numfmt_code is the cell's number-format string ('' for a built-in or unstyled cell) and numfmt_id its numFmtId (0 when unstyled). fallbacks counts shared or array formulas returned as their cached value.");
    m.def("xlsx_write", &xlsx_write, nb::arg("path"), nb::arg("cells"),
          nb::arg("sheet_names") = nb::list(),
          "Write cells to an .xlsx file. Each cell is (sheet, col, row, kind, value[, cached][, numfmt][, style]); kind in {'s','n','b','f'} where 'f' uses value as formula text and an optional cached float or bool (None writes no cached value). A trailing numfmt string applies that number format to the cell (slot 5, or 6 for 'f'); style follows it, with bits 1 bold, 2 italic, 4 underline, 8 left-aligned, 16 right-aligned. sheet_names lists every sheet in workbook order, so empty sheets are written too.");
}
