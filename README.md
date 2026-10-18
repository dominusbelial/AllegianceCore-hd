# AllegianceCore HD

Optional high-definition texture add-on for [AllegianceCore](https://github.com/dominusbelial/AllegianceCore).
The base game is complete without it; with it installed, ships (later stations, missiles, probes and asteroids) get
4K PBR materials.

## What this is (and isn't)

- **Same models, same look, sharper.** Every asset keeps its native mesh, UVs, silhouette, colours and markings. The
  method (since 2026-10-18) is **ESRGAN ×4 of each native texture atlas plus derived normal/roughness/metallic maps**
  (`pipeline/esrgan_variant.py`): free and 100% faithful. Meshy retextures were tried (rounds 1–2, slice 20) and
  dropped: at close range they invented stencil text, canopy frames and panel lines, and once those were filtered out
  (`pipeline/hybrid_v4.py`) they added little over ESRGAN. See `review/sheets/SLICE20_V4_COMPARE_*.jpg` and
  [METHOD.md](METHOD.md).
- **No invented features.** No canopies, windows, lights, text or decals that the original doesn't have. Every model
  is reviewed side by side with the native one (`review/sheets/`).
- **Nothing generated lives in git.** This repo holds the pipeline, prompts, manifest and review sheets. The
  textures are built locally and published as release downloads (`allegiance-hd-ships-vN.zip`).

## Layout

| Path | Contents | In git |
|---|---|---|
| `pipeline/` | `hd.py` (Meshy retexture driver, cumulative credit ledger), `hd-native` (native mesh/texture exporter, C#), `esrgan_variant.py`, `hybrid_variant.py`, `blender_preview.py`, `pilot.json` (per-model prompts) | yes |
| `manifest.json` | jobs, Meshy task ids, credits, checks | yes |
| `review/sheets/` | native vs HD comparison sheets (JPG) | yes |
| `inputs/`, `variants/`, `models/`, `tasks/`, `validation/` | generated data | **no** |

## Batch on the mini

`deploy/mini/`: a Docker Compose ESRGAN worker for the UM690. It upscales every `inputs/<model>/native.png`
that has no output yet and pauses while the test runner is busy. Natives are exported on the workstation
(`pipeline/esrgan_batch.py ships.txt --export-only`) and synced over.

## Running

Needs: a sibling checkout of AllegianceCore (or `ALLEGIANCE_CORE_REPO=<path>`, with its `local.env` pointing at the
native artwork), .NET 10, Blender, Python (`pipeline/requirements.txt`; ESRGAN needs torch + spandrel), and a Meshy API
key file (`--key-file`, default `~/meshyApi.txt`, never committed).

```bash
cd pipeline
dotnet build hd-native.csproj -p:AllegianceCoreRoot=$ALLEGIANCE_CORE_REPO
python hd.py --models fig04,fig03 --variant text6 --budget <cumulative credits> --dry-run   # plan
python hd.py --models fig04,fig03 --variant text6 --budget <cumulative credits>             # submit + poll
python esrgan_variant.py fig04 fig03
HYBRID_CLAMP=0.10 HYBRID_SUFFIX=-v3 python hybrid_variant.py fig04:text6 fig03:text6
```

## Licence and credits

- 3D models generated with **Meshy** (retexture of the native meshes) on a paid plan; outputs owned by the author
  (Meshy Terms §3.2). Meshy's AI-generation metadata in the outputs is preserved (Terms §2.4).
- Native meshes and source textures: Microsoft Allegiance, MIT licence (see AllegianceCore).
- **Licence for the HD textures: to be decided before the first public release.**
