# HD texture add-on pipeline

Export **native ships**, render references, run Meshy **Retexture**, download PBR
maps, measure them on native UVs, and make matched PNG contact sheets. All art,
task data and account balances go into a separate **private** local repository.
This directory contains code and the ten-ship pilot selection only. No client
rendering behavior changes here; loading the PBR pack belongs to HD-2.

Requirements: .NET 10, Python 3 with NumPy/Pillow, headless Blender with Cycles
CPU support, git, and native artwork configured through `local.env` or
`ALLEGIANCE_ARTWORK_PATH`. No GPU, display, vision model, or image-generation
service is used to evaluate results. The C# bridge reuses `MdlFile`,
`NativeShipResolver` and `MdlTextureDecoder` from the actual client libraries.

```sh
# Optional isolated Python environment (uv can substitute for python -m venv).
uv venv /tmp/hd-python
uv pip install --python /tmp/hd-python/bin/python -r tools/hd-textures/requirements.txt
NUGET_HTTP_CACHE_PATH=/tmp/hd-nuget dotnet build tools/hd-textures/hd-native.csproj

PYTHON=/tmp/hd-python/bin/python
$PYTHON tools/hd-textures/hd.py --dry-run --variant both --budget 100
$PYTHON tools/hd-textures/hd.py --prepare-only
$PYTHON tools/hd-textures/hd.py --variant both --budget 100
# Resume only existing paid tasks after an interruption:
$PYTHON tools/hd-textures/hd.py --poll-only --variant both --budget 100
```

Default output: `~/Development/AllegianceCore-hd`. If sandbox permissions prevent
that directory, `--addon /tmp/AllegianceCore-hd` stages the separate private repo;
move the **entire** directory including `.git` and `manifest.json` afterward.
Never copy generated outputs into AllegianceCore. The pipeline rejects an
output directory resolving inside this checkout and output symlinks. It creates
the add-on git repo without commits or remotes and refuses any existing remote.
`--blender /snap/blender/current/blender` can select the actual binary where the
snap launcher cannot run in a container. Blender logs stay in the private repo.

`--models wc_icfig,wc_gtpod` selects unique ship names from `pilot.json`. To
extend later batches, audit and update that selection first. The decoder checks
that each model is a PCore001 ship, rejects unsupported geometry, ambiguous hull
texture overrides and multiple texture atlases. These exclusions prevent silent
repacking or mixing of native UV layouts. Native references are four 1024² PNGs:
front, three-quarter, side and top. The GLB keeps vertex coordinates, normals and
UV floats exactly; only a whole mesh's triangle winding can reverse to agree
with its authored normals. Named native hardpoints are retained as GLB extras.
Blender's glTF importer handles its Y-up to Z-up preview coordinate conversion.

`--variant multiview` is the default. `text` submits text prompts instead, while
`both` submits all selected multiview jobs **first**, followed by text comparisons
for the first two selected ships. Comparison textures have separate paths and
cannot overwrite the primary maps. Multi-view and text conditioning are mutually
exclusive in each API request. Model/image inputs are data URIs, bounded at
100 MB/20 MB respectively. Settings are meshy-7, 4k, PBR, original UVs,
remove_lighting and GLB-only output.

`--budget` defaults to **100** and applies cumulatively to this add-on ledger,
including previous invocations. Current [Retexture pricing](https://docs.meshy.ai/en/api/pricing)
is 10 credits for 4K: ten ships exhaust the default cap. Text comparisons are
skipped when the remaining budget cannot cover them. Raising the cap is a
separate spending decision; this pilot does not do so. The script checks
`GET /openapi/v1/balance` immediately before every new submission, persists the
balance, reserves ten credits durably, and records the task ID before checking
the balance again. Actual `consumed_credits` and post-completion balances are
also recorded. Shared-account activity can make balance differences larger than
the pilot's actual task charges; those are not used as pilot cost estimates.

Only one process can hold the ledger lock. Existing model/variant entries are
never resubmitted, including FAILED or CANCELED jobs. POSTs are never retried.
An interrupted or timed-out POST may have charged the account: `SUBMITTING`
without a task ID stays reserved, and must be reconciled manually against the
account task list before an operator attaches the correct task ID to that same
entry. A reservation is retained conservatively even if a failed task is
refunded. Never delete the ledger or start another output directory as a retry.
This avoids duplicate charges at the cost of requiring reconciliation for an
ambiguous network outcome. No API idempotency guarantee is assumed.

The key is read at runtime from `~/meshyApi.txt` (or `--key-file`). It is never
passed on the command line, logged, persisted in JSON, or used for asset CDN
downloads. API error bodies and full requests are suppressed. `--dry-run`
prints a plan without filesystem changes, key access, rendering, or network
calls. `--prepare-only` makes native inputs without paid API calls. `--poll-only`
never submits new jobs. Polling deadlines preserve task IDs for resumption.

Each texture set includes basecolor, normal, metallic, roughness and emission.
The [Retexture API](https://docs.meshy.ai/en/api/retexture) explicitly says Meshy 7
does **not** generate emission and accepts but ignores `remove_lighting`.
The pipeline labels a **neutral black emission fallback** in the manifest; it
does not claim to extract generated emission or preserve authored glow. Other
missing required maps stop extraction. Non-4096² maps are retained at their true
resolution and fail the size gate; there is no upscaling or silent acceptance.
The returned GLB is archived for audit and **never** used for the contact-sheet
geometry. PBR previews bind the downloaded textures onto the original native
GLB with identical camera, framing, lighting and render settings for both rows.

Metrics record every map's size and SHA256; native-UV raster coverage and alpha
coverage IoU; tolerant native/HD luminance-edge precision, recall and F1; mean
distance between marginal CIELab distribution quantiles; and the 95th percentile
of fitted luminance slopes within native triangles whose original texture is
locally flat. Comparisons run at native texture resolution (maximum 512 per
axis), so HD microdetail does not dominate. Thresholds are explicit in
`metrics.py` and copied into each result. No flat panels means an inconclusive,
failed lighting gate. Out-of-range/wrapped UV triangles are counted as unmeasured
and fail the UV-range gate rather than being silently clamped or mis-rasterized.
Coverage alone is weak on opaque maps; edge/palette/lighting gates are heuristic
diagnostics and cannot prove correct alignment or the absence of baked lighting.
Rejected sets remain available for review with `accepted: false` and must not
be enabled automatically by HD-2. Tune thresholds only with recorded evidence.

Native rules used by the bridge (relative to `~/Development/Allegiance/src/`):

| Rule | Native evidence |
| --- | --- |
| Ship loads ModelName and TextureName, radius from hull length | `Igc/shipIGC.cpp:1412`, `Igc/shipIGC.cpp:1419` |
| Empty/non-alpha/model-equal override discarded | `WinTrek/trekigc.cpp:1837` |
| Otherwise texture from mesh FindTexture | `effect/thinggeo.cpp:1035` |
| Nested TextureGeo can bind its own texture | `engine/geometry.cpp:1079` |
| Group geometry selects first discoverable texture | `engine/geometry.cpp:1459` |
| Binary native vertices and WORD indices | `engine/modeler.cpp:1637` |
| Named position/forward/up frame records | `effect/efapp.cpp:383` |

Run tool tests (including a real localhost HTTP server):

```sh
cd tools/hd-textures
/tmp/hd-python/bin/python -m unittest -v test_hd
```
