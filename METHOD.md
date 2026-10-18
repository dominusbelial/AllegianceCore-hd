# AllegianceCore HD texture pilot — PRIVATE

Meshy-generated private add-on. Do not redistribute through AllegianceCore.
Native geometry, UVs, hardpoints, scale and orientation remain authoritative.
`models/<nativeModelName>/` contains basecolor, normal, metallic, roughness and
emission PNGs. Meshy 7 omits emission: the manifest labels a neutral black
fallback, which does not preserve authored glow. Text comparisons, if funded,
live under `variants/text/` and never overwrite the multiview pilot.

The current client does not load this pack. HD-2 must implement an opt-in pack
path, validate native model/texture SHA256 against manifest.json, require an
accepted review, and bind these maps to native UVs. Basecolor is sRGB; normal,
metallic, roughness and emission fallback are data maps. Never load generated
geometry or replace the native hardpoints. Missing/rejected packs retain native
art. PBR previews under review/ demonstrate the material on native geometry.

`inputs/` contains decoded native assets, GLBs and four 1024-square references.
`tasks/` retains Meshy GLBs for audit only. `manifest.json` is a durable credit
and duplicate-submission ledger. Do not delete it to restart a run. A SUBMITTING
entry without a task ID needs manual account reconciliation; never resubmit it.
No commits, remotes or pushes were made by this pipeline.
