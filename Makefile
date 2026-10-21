# FoveaCam Duo Driver build orchestration (one board: board/FoveaCamDuo-PCB).
#
# Incremental: the board files are real targets of their generators and every
# check leaves a stamp in board/build/, so a target reruns only when its inputs
# changed.  `make -B <target>` forces a rerun.
#
# Generate
#   layout     board/FoveaCamDuo-PCB.kicad_sch (schematic.py) and .kicad_pcb
#              (layout.py), board/pins.h (tools/gen_pins.py), board/bringup.md
#              (tools/gen_bringup.py); each only while its generator exists.
#              Inputs: board/*.py, lib/**/*.py, lib/footprints/**, lib/symbols/**,
#              FAB and VARIANT.  A failing generator fails make and leaves its
#              output marked stale.
#   harvest    tools/harvest_routes.py ARGS="..." (board worker's tool)
# Check (one summary line each; details only on failure)
#   quick      layout, then DRC + track tidiness + DFM (always rerun)
#   erc        ERC on the schematic, fails on errors   -> board/build/erc.json
#   drc        DRC, fails on errors / unconnected       -> board/build/drc.json
#   check      track tidiness, DFM (FAB profile), 3D models
# Look
#   preview    stacked per-layer preview                -> board/build/layers.png
#   render3d   3D views, top + bottom isometric         -> board/build/3d.png
#   diff       overlay against REF (default: last v<x.y.z> tag, else HEAD~1)
#                                                       -> board/build/diff/
#   info       tools/board_info.py --text (what agents read instead of .kicad_*)
#   changelog  draft CHANGELOG.md entry since the last v<x.y.z> tag (stdout)
# Order (export the board file as it is on disk; never regenerate)
#   bom        grouped BOM from the schematic           -> board/build/bom.csv
#   fab        fabrication set                          -> board/fab<SFX>/
#   assembly   assembly set incl. hand-assembly sheets  -> board/assembly<SFX>/
#   release    checks + fab + assembly from the committed board
#              -> release/FoveaCamDuo-PCB[-rev<X>]<SFX>-<date>-<hash>/ and .zip
# Aggregates
#   all        (default) layout erc drc preview fab check
#   help       this text
#
# Parameters (environment or make variables, passed to generators, checks
# and order packages):
#   FAB=<profile>     fab rule profile (lib/rules.py PROFILES; default both = JLCPCB + Advanced PCB)
#   VARIANT=<name>    part variant (board/netlist.py VARIANTS; default default)
#   <SFX> is -<FAB>-<VARIANT> for non-default values, else empty.
#   REF=<git rev>     diff base.   MASK=, ZOOM=   render3d colour and zoom.
#   ALLOW_INCOMPLETE=1   fab / assembly / release finish with gaps (INCOMPLETE)
#   ALLOW_DIRTY_TOOLS=1  release builds with uncommitted tools/lib/Makefile
#   VERSION_TAG=v<x.y.z>   act as if HEAD carried that tag (release naming tests)
#   NOGEN=1              never run the generators: the board files on disk are
#                        the sources (a generator is mid-edit, or a quick look)
#
# KiCad is called through tools/kicli (PATH on macOS, 3D model dirs, noise
# filter); ImageMagick (magick or convert/montage) for previews and diffs.

# bash, so that a failing check is not hidden by a pipe
SHELL := /bin/bash

BOARD   := FoveaCamDuo-PCB
DIR     := board
PCB     := $(DIR)/$(BOARD).kicad_pcb
SCH     := $(DIR)/$(BOARD).kicad_sch
PRO     := $(DIR)/$(BOARD).kicad_pro
PINS    := $(DIR)/pins.h
BRINGUP := $(DIR)/bringup.md
BUILD   := $(DIR)/build

KICLI := tools/kicli
PY    := $(KICLI) py
CLI   := $(KICLI) cli

# ---- parameters ---------------------------------------------------------------
FAB     ?=
VARIANT ?=
export FAB VARIANT ALLOW_DIRTY_TOOLS VERSION_TAG
SFX := $(if $(filter-out both,$(FAB)),-$(FAB))$(if $(filter-out default,$(VARIANT)),-$(VARIANT))

# text variables for exports (the silkscreen's V${REVISION} / ${GIT_SHORT});
# the committed board keeps the variables, so it stays byte-stable.  The version
# is declared once (board/layout.py VERSION -> the project's REVISION variable);
# a tag V<version> at HEAD marks the commit that was ordered (docs/ordering.md).
VERSION_TAG ?= $(lastword $(shell git tag --points-at HEAD --list '[vV][0-9]*' 2>/dev/null))
REVISION := $(shell sed -n 's/.*"REVISION": *"\([^"]*\)".*/\1/p' $(PRO) 2>/dev/null)
GIT_SHORT := $(shell git rev-parse --short=7 HEAD 2>/dev/null | tr a-z A-Z)$(if $(shell git status --porcelain -- $(DIR) 2>/dev/null),+)
TEXT_VARS := -D REVISION=$(REVISION) -D GIT_SHORT=$(GIT_SHORT)

MASK ?= Black
ZOOM ?= 1.1

# ImageMagick 7 (magick) or 6 (convert, montage); a font that exists, for labels
IM      := $(if $(shell command -v magick),magick,convert)
MONTAGE := $(if $(shell command -v magick),magick montage,montage)
FONT    := $(firstword $(wildcard /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
             /usr/share/fonts/dejavu/DejaVuSans.ttf /System/Library/Fonts/Supplemental/Arial.ttf))
FONTARG := $(if $(FONT),-font $(FONT))

# ---- inputs -------------------------------------------------------------------
LIB_FILES := $(shell find lib -type f \( -name '*.py' -o -path 'lib/footprints/*' \
               -o -path 'lib/symbols/*' -o -path 'lib/3dmodels/*' \) \
               -not -path '*/__pycache__/*' 2>/dev/null)
GEN_PY    := $(wildcard $(DIR)/*.py)
PARAMS    := $(BUILD)/params
ORDER_PARAMS := $(BUILD)/order-params
STALE     = touch -t 197001010000 $@ 2>/dev/null; exit 1

GENERATED := $(PCB) $(SCH)
ifeq ($(NOGEN),)
GENERATED += $(if $(wildcard tools/gen_pins.py),$(PINS))
GENERATED += $(if $(wildcard tools/gen_bringup.py),$(BRINGUP))
endif

.PHONY: all help layout harvest quick erc drc check preview render3d diff info \
        changelog bom fab assembly release FORCE

all: layout erc drc preview fab check

help:
	@sed -n '1,/^$$/{s/^# \{0,1\}//;p;}' $(firstword $(MAKEFILE_LIST))

# rewritten only when the values change, so a new FAB / VARIANT regenerates
$(PARAMS): FORCE
	@mkdir -p $(BUILD)
	@echo "FAB=$(FAB) VARIANT=$(VARIANT)" | cmp -s - $@ || echo "FAB=$(FAB) VARIANT=$(VARIANT)" > $@
$(ORDER_PARAMS): FORCE
	@mkdir -p $(BUILD)
	@echo "FAB=$(FAB) VARIANT=$(VARIANT) ALLOW_INCOMPLETE=$(ALLOW_INCOMPLETE) REVISION=$(REVISION)" \
	  | cmp -s - $@ || echo "FAB=$(FAB) VARIANT=$(VARIANT) ALLOW_INCOMPLETE=$(ALLOW_INCOMPLETE) REVISION=$(REVISION)" > $@

# ---- generate -----------------------------------------------------------------
# A generator that exists makes its file a target; without it the file in git
# is the source.  On failure the output's mtime is set to 1970, so the next
# make reruns the generator instead of trusting a half-written file.
layout: $(GENERATED)
	@echo "layout: current: $(notdir $(GENERATED))"

ifeq ($(NOGEN),)
ifneq ($(wildcard $(DIR)/schematic.py),)
$(SCH): $(DIR)/schematic.py $(wildcard $(DIR)/netlist.py) $(LIB_FILES) $(PARAMS)
	@$(PY) $(DIR)/schematic.py || { $(STALE); }
	@touch $@
endif

ifneq ($(wildcard $(DIR)/layout.py),)
$(PCB): $(GEN_PY) $(LIB_FILES) $(PARAMS) $(if $(wildcard $(DIR)/schematic.py),$(SCH))
	@$(PY) $(DIR)/layout.py || { $(STALE); }
	@touch $@
endif

ifneq ($(wildcard tools/gen_pins.py),)
$(PINS): tools/gen_pins.py $(GEN_PY) $(PARAMS)
	@$(PY) tools/gen_pins.py || { $(STALE); }
	@touch $@
endif

ifneq ($(wildcard tools/gen_bringup.py),)
$(BRINGUP): tools/gen_bringup.py $(GEN_PY) $(PARAMS) $(wildcard $(PINS))
	@$(PY) tools/gen_bringup.py || { $(STALE); }
	@touch $@
endif
endif   # NOGEN

harvest:
	@if [ -f tools/harvest_routes.py ]; then $(PY) tools/harvest_routes.py $(ARGS); \
	else echo "harvest: tools/harvest_routes.py does not exist yet"; fi

# ---- checks (stamps in board/build/<check>.ok, written by tools/checks.py) -----
quick: layout
	@$(PY) tools/checks.py drc tracks dfm

erc: $(BUILD)/erc.ok
drc: $(BUILD)/drc.ok
check: $(BUILD)/tracks.ok $(BUILD)/dfm.ok $(BUILD)/models.ok

$(BUILD)/erc.ok: $(SCH) tools/checks.py
	@$(PY) tools/checks.py --stamp erc
$(BUILD)/drc.ok: $(PCB) $(PRO) $(wildcard $(DIR)/$(BOARD).kicad_dru) tools/checks.py
	@$(PY) tools/checks.py --stamp drc
$(BUILD)/tracks.ok: $(PCB) tools/check_tracks.py tools/checks.py
	@$(PY) tools/checks.py --stamp tracks
$(BUILD)/dfm.ok: $(PCB) $(PARAMS) tools/checks.py $(wildcard tools/check_dfm.py lib/rules.py)
	@$(PY) tools/checks.py --stamp dfm
$(BUILD)/models.ok: $(PCB) tools/pkg3d.py tools/checks.py $(filter lib/3dmodels/% lib/models.py,$(LIB_FILES))
	@$(PY) tools/checks.py --stamp models

# ---- look -----------------------------------------------------------------------
# layer sets of the preview stack, front to back; layers the board does not
# have (In1/In2 on a 2-layer board) produce no svg and are skipped
PREVIEW_LAYERS := F.Cu,F.Silkscreen,Edge.Cuts \
                  In1.Cu,Edge.Cuts \
                  In2.Cu,Edge.Cuts \
                  B.Cu,B.Silkscreen,Edge.Cuts

preview: $(BUILD)/layers.png
$(BUILD)/layers.png: $(PCB) $(ORDER_PARAMS)
	@mkdir -p $(BUILD)
	@set -e; cd $(DIR); n=0; m=0; args=""; \
	for layers in $(PREVIEW_LAYERS); do \
	  n=$$((n+1)); \
	  rm -f build/layer$$n.svg build/layer$$n.png; \
	  ../$(CLI) pcb export svg --layers "$$layers" --page-size-mode 2 \
	    --exclude-drawing-sheet --mode-single $(TEXT_VARS) \
	    -o build/layer$$n.svg $(BOARD).kicad_pcb >/dev/null 2>&1 || true; \
	  [ -f build/layer$$n.svg ] || continue; \
	  m=$$((m+1)); \
	  perl -0pi -e 's/<text\b.*?<\/text>//gs' build/layer$$n.svg; \
	  $(IM) -density 400 build/layer$$n.svg -background white \
	    -flatten build/layer$$n.png; \
	  args="$$args -label $${layers%%,*} build/layer$$n.png"; \
	done; \
	$(MONTAGE) $(FONTARG) $$args -tile 1x$$m -geometry +0+8 -pointsize 28 \
	  build/layers.png; \
	echo "$(BUILD)/layers.png"

render3d: $(BUILD)/3d.png
$(BUILD)/3d.png: $(PCB) $(PRO) $(ORDER_PARAMS) $(filter lib/3dmodels/%,$(LIB_FILES))
	@mkdir -p $(BUILD)
	@set -e; cd $(DIR); \
	../$(PY) ../tools/render_prep.py $(BOARD).kicad_pcb build/render.kicad_pcb "$(MASK)"; \
	cp -f $(BOARD).kicad_pro build/render.kicad_pro; \
	for side in top bottom; do \
	  rx=-40; [ $$side = bottom ] && rx=40; \
	  ../$(CLI) pcb render --side $$side --background opaque --quality high \
	    --use-board-stackup-colors --perspective --floor --zoom $(ZOOM) \
	    --rotate "$$rx,0,25" -w 2000 -h 1100 \
	    -D KIPRJMOD=$$(pwd) $(TEXT_VARS) \
	    -o build/3d_$$side.png build/render.kicad_pcb >/dev/null; \
	done; \
	$(MONTAGE) $(FONTARG) -label top build/3d_top.png -label bottom build/3d_bottom.png \
	  -tile 1x2 -geometry +0+8 -pointsize 28 build/3d.png; \
	rm -f build/render.kicad_pcb build/render.kicad_pro build/render.kicad_prl; \
	echo "$(BUILD)/3d.png"

diff: layout
	@$(PY) tools/visual_diff.py $(if $(REF),--ref $(REF))

info: layout
	@$(PY) tools/board_info.py --text

changelog:
	@$(PY) tools/changelog.py $(if $(REF),--since $(REF))

# ---- order ------------------------------------------------------------------------
ORDER = $(PY) tools/order_package.py
ORDER_FLAGS = $(if $(filter 1 yes true,$(ALLOW_INCOMPLETE)),--allow-incomplete)
ORDER_DEPS = $(ORDER_PARAMS) tools/order_package.py tools/order_notes.py

bom: $(BUILD)/bom.csv
$(BUILD)/bom.csv: $(SCH)
	@mkdir -p $(BUILD)
	@$(CLI) sch export bom --fields 'Reference,Value,Footprint,$${QUANTITY}' \
	  --labels 'Refs,Value,Footprint,Qty' --group-by Value,Footprint \
	  --exclude-dnp -o $@ $(SCH)

fab: $(DIR)/fab$(SFX)/README-fab.txt
$(DIR)/fab$(SFX)/README-fab.txt: $(PCB) $(PRO) $(ORDER_DEPS)
	@$(ORDER) fab $(ORDER_FLAGS) || { $(STALE); }

assembly: $(DIR)/assembly$(SFX)/README-assembly.txt
$(DIR)/assembly$(SFX)/README-assembly.txt: $(PCB) $(SCH) $(ORDER_DEPS)
	@$(ORDER) assembly $(ORDER_FLAGS) || { $(STALE); }

release:
	@$(ORDER) release $(ORDER_FLAGS)

FORCE:
