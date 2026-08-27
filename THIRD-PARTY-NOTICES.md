# Third-party notices

gridcalc itself is MIT licensed (see `LICENSE`). The binary extension modules
statically link the vendored components below, so a distributed wheel contains
their code and is subject to their terms as well.

## HiGHS -- MIT

* Location: `thirdparty/HiGHS/`
* Licence: MIT (`thirdparty/HiGHS/LICENSE.txt`)
* Upstream: <https://github.com/ERGO-Code/HiGHS>
* Used by: `gridcalc._opt` (the `:opt` / `:goal` solver)

Permissive, and the same licence as gridcalc itself. HiGHS vendors its own
third-party code under `thirdparty/HiGHS/extern/`; see
`thirdparty/HiGHS/THIRD_PARTY_NOTICES.md` for that inventory.

This replaced lp_solve 5.5 (LGPL-2.1). gridcalc is MIT and links the solver
statically, which is the case the LGPL treats most strictly; moving to a
permissively-licensed solver removed the obligation rather than managing it.

## OpenXLSX -- BSD 3-Clause

* Location: `thirdparty/OpenXLSX/`
* Licence: BSD 3-Clause (`thirdparty/OpenXLSX/LICENSE.md`)
* Copyright (c) 2020, Kenneth Troldal Balslev
* Used by: `gridcalc._core` (xlsx read/write)

Permissive; requires only that the copyright notice and disclaimer be retained,
which this file and the vendored `LICENSE.md` do.

## nanobind -- BSD 3-Clause

Not vendored. Fetched at build time (`pyproject.toml` `build-system.requires`)
and its headers are compiled into both extension modules. Permissive.

---

This file is a factual inventory, not legal advice. Every vendored component
is now permissively licensed (MIT or BSD-3-Clause), so static linking imposes
no copyleft obligation on a distributed wheel.
