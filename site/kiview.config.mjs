// The FoveaCam Duo Driver board viewer: the config of KiView (@zdv/kiview, installed
// by site/package.json), which replaced the hand-written web/ viewer (owner,
// 2026-10-20). Built and deployed to GitHub Pages by .github/workflows/publish.yml
// (under /<repository>/: the workflow passes --base).
//
// The CLI's root is the repository root (paths below are relative to it); this file is
// passed with -c (site/package.json scripts):
//
//   cd site && npm ci && npm run dev      # = kiview dev .. on 0.0.0.0:8082 (LAN)
//   cd site && npm run build              # static site in site/.kiview/dist
//
// The config keys: UserConfig in the package's index.d.ts (KiView docs/config.md).
// KiCad is reached through tools/kicli for the order package (macOS app bundle or the
// CI image's python3 with pcbnew), as everywhere else in this repository.

import { execFileSync, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from '@zdv/kiview'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const BOARD = 'FoveaCamDuo-PCB'
const KICLI = join(ROOT, 'tools', 'kicli')
const TOOL = join(ROOT, 'tools', 'order_package.py')
/** Sources of the order-package fab step; their content is part of the bundle's cache key. */
const TOOL_SOURCES = ['tools/order_package.py', 'tools/order_notes.py', 'tools/check_dfm.py',
                      'lib/rules.py', 'lib/stackup.py']
/** Bump when the way the hook runs the tool or reads its output changes. */
const HOOK_RECIPE = 'foveacam-duo-order-package-1'
const FAB_TIMEOUT_MS = 10 * 60_000
const NOISE = /PROPERTY|Debug|m_choices|^\s*$/

// Silkscreen version stamp "V${REVISION} | ${GIT_SHORT}" (board/specs.md): the same
// rule as the Makefile and tools/order_package.py. REVISION is the version the board
// declares (board/layout.py VERSION, written to the project's text variables);
// GIT_SHORT is the commit, upper case, "+" when board/ differs from it. Read once when
// the server starts: restart the dev server after a commit.
const git = (...args) => {
  try { return execFileSync('git', args, { cwd: ROOT, encoding: 'utf8' }).trim() } catch { return '' }
}
const declaredVersion = (() => {
  try {
    const pro = JSON.parse(readFileSync(join(ROOT, 'board', `${BOARD}.kicad_pro`), 'utf8'))
    return String(pro.text_variables?.REVISION ?? '')
  } catch { return '' }
})()
const TEXT_VARS = {
  REVISION: declaredVersion || 'DEV',
  GIT_SHORT: ((git('rev-parse', '--short=7', 'HEAD') || (process.env.GITHUB_SHA ?? 'unknown').slice(0, 7)) +
              (git('status', '--porcelain', '--', 'board') ? '+' : '')).toUpperCase(),
}

function run(cmd, args, { cwd, timeoutMs }) {
  return new Promise(done => {
    const child = spawn(cmd, args, { cwd, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] })
    let buf = ''
    child.stdout.on('data', d => { buf += d })
    child.stderr.on('data', d => { buf += d })
    const timer = setTimeout(() => { buf += `\n(killed after ${timeoutMs} ms)`; child.kill('SIGKILL') }, timeoutMs)
    child.on('error', e => { clearTimeout(timer); done({ code: -1, out: [String(e)] }) })
    child.on('close', code => { clearTimeout(timer); done({ code, out: buf.split(/\r?\n/).filter(l => !NOISE.test(l)) }) })
  })
}

/** STATUS line of README-fab.txt and the "  - item" lines under it (the fab hook contract of KiView). */
function parseFabStatus(readme) {
  const lines = readme.split(/\r?\n/)
  const i = lines.findIndex(l => l.startsWith('STATUS:'))
  if (i < 0) throw new Error('README-fab.txt has no STATUS line')
  if (/^STATUS:\s*ORDERABLE\b/.test(lines[i])) return { status: 'ok', missing: [] }
  const missing = []
  for (const l of lines.slice(i + 1)) {
    const m = /^\s+-\s+(.*)$/.exec(l)
    if (!m) break
    missing.push(m[1].trim())
  }
  if (!missing.length) missing.push(lines[i].replace(/^STATUS:\s*/, ''))
  return { status: 'incomplete', missing }
}

/** The real order package (default profile `both`): `tools/order_package.py fab` on the export's snapshot. */
async function orderPackageFab(ctx) {
  const out = join(ctx.workDir, 'order-fab')
  const r = await run(KICLI, ['py', TOOL, 'fab', '--out', out, '--pcb', ctx.pcb, '--allow-incomplete'],
                      { cwd: ROOT, timeoutMs: FAB_TIMEOUT_MS })
  if (r.code !== 0) throw new Error(`order_package.py fab exited ${r.code}: ${r.out.slice(-4).join(' | ')}`)
  const files = await readdir(out)
  const zip = files.find(f => f.startsWith(`${ctx.name}-fab-`) && f.endsWith('.zip'))
  if (!zip) throw new Error('order_package.py fab produced no zip')
  const { status, missing } = parseFabStatus(await readFile(join(out, 'README-fab.txt'), 'utf8'))
  for (const w of new Set(r.out.filter(l => l.startsWith('WARNING:')).map(l => l.slice(8).trim())))
    ctx.log(`${ctx.name}: order_package.py: ${w}`)
  return { zip: join(out, zip), filename: zip, status, missing, contents: files.filter(f => f !== zip).sort() }
}

/** KiView's generic bundle, when the order-package tool cannot run. */
async function genericFab(ctx) {
  if (!ctx.backend?.capabilities.ops.fab) return null
  const label = (ctx.rev?.label ?? ctx.hash).replace(/[^\w.+-]+/g, '_')
  const filename = `${ctx.name}-fab-${label}-generic.zip`
  const r = await ctx.backend.exportFab(ctx.pcb, { sch: ctx.sch ?? undefined, zipName: filename },
                                        { workDir: ctx.workDir, vars: { KIPRJMOD: dirname(ctx.pcb), ...TEXT_VARS }, warn: ctx.log })
  // flagged incomplete so the page's badge says this is not the order package
  return { zip: r.zip, filename, status: 'incomplete', contents: r.contents,
           missing: ['the order package (tools/order_package.py failed; this is the generic KiCad bundle)', ...r.missing] }
}

export default defineConfig({
  title: 'FoveaCam Duo Driver',
  description: 'Teensy 4.0 carrier for two Mirrorcle MEMS drivers and three FLIR cameras: layers, 3D, schematic, BOM and the fab order package.',

  boards: ['board'],            // board/FoveaCamDuo-PCB.kicad_pcb
  cacheDir: 'site/.kiview/cache',
  outDir: 'site/.kiview/dist',

  // filled into the silk's version stamp on every export (kicad-cli -D)
  env: TEXT_VARS,

  // the board's own stackup colour (default profile: black mask, ENIG)

  // no VERSION file: the card shows the v<x.y.z> tag at HEAD, else the title-block
  // revision (board/layout.py VERSION), else the commit
  revision: { git: true, versionFile: false, diff: false },

  bom: { showDnp: true },       // the optional capacitors C1-C4 are DNP by default

  fab: {
    async build(ctx) {
      try {
        return await orderPackageFab(ctx)
      } catch (e) {
        ctx.log(`${ctx.name}: ${e instanceof Error ? e.message : e}; falling back to the generic fab bundle`)
        return genericFab(ctx)
      }
    },
    // rebuild the bundle when the tool, its rules or this hook change
    async recipe() {
      const h = createHash('sha256').update(HOOK_RECIPE)
      for (const f of TOOL_SOURCES) {
        const p = join(ROOT, f)
        h.update('\0' + f + '\0' + (existsSync(p) ? await readFile(p, 'utf8') : ''))
      }
      return h.digest('hex').slice(0, 16)
    },
  },

  // Assembly mode: every part is on the back (board/specs.md, tools/order_notes.py)
  assembly: {
    boards: {
      [BOARD]: {
        sideOrder: 'back-first',
        order: ['C1', 'C2', 'C3', 'C4', 'J_SPI1', 'J_SPI2', 'J_CAM0', 'J_CAM1', 'J_CAM2',
                'J_UART1', 'J_UART2', 'J_PWR1', 'J_PWR2', 'J_PWR3', 'U1'],
        notes: [
          '**Hand assembly, every part on the back** (low parts first; `assembly/*-hand-assembly-bottom.md` in the order package).',
          '',
          '- **C1–C4** are optional (not fitted by default): fit them only if fan noise needs them.',
          '- **J_SPI1 / J_SPI2** share one solder-mask opening over all ten pins (Advanced PCB standard spec): fine tip, little solder, check for bridges.',
          '- **Side connectors** (DAC, camera, side fan): mating face 1.0 mm past the board edge, body flat on the board.',
          '- **U1**: solder two 1×14 socket strips (8.5 mm) last, then plug the Teensy 4.0 with its USB end at the USB icon.',
        ].join('\n'),
        refNotes: {
          U1: 'Teensy 4.0 on two 1×14 socket strips (Sullins PPPC141LFBN-RC); USB end at the USB icon; soldered last',
          J_SPI1: 'Gang mask opening: no solder dam between pins; fine tip, little solder',
          J_SPI2: 'Gang mask opening: no solder dam between pins; fine tip, little solder',
        },
      },
    },
  },
})
