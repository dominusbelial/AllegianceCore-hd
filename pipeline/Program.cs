using System.Security.Cryptography;
using System.Text.Json;
using Allegiance.Core;
using Allegiance.Core.Model;
using Allegiance.ClientCore.MonoGame.Rendering;

// GPU-free bridge: use the exact runtime MDL graph, texture and namespace decoders.
var art = ExternalPaths.Require(ExternalResourceKind.Artwork);
var core = StaticCore.Load(IgcReader.ParseFile(Path.Combine(art, "PCore001.igc")));
var options = new JsonSerializerOptions { WriteIndented = false };
if (args.Length == 1 && args[0] == "--catalog")
{
    Console.WriteLine(JsonSerializer.Serialize(new {
        Civilizations = core.Civilizations.Values.Select(c => new { c.CivilizationId, c.Name, c.Lifepod }),
        Hulls = core.HullTypes.Values.Select(h => new { h.HullId, h.Name, h.ModelName, h.TextureName, h.Length, h.GroupId })
    }, options));
    return;
}
if (args.Length != 2) throw new ArgumentException("usage: hd-native <native-model> <external-output.json> | --catalog");
var name = args[0];
if (Path.GetFileName(name) != name || !System.Text.RegularExpressions.Regex.IsMatch(name, "^[a-zA-Z0-9_]+$"))
    throw new ArgumentException("Invalid native model name");
var hulls = core.HullTypes.Values.Where(h => h.ModelName.Equals(name, StringComparison.OrdinalIgnoreCase)).ToArray();
if (hulls.Length == 0) throw new InvalidDataException("Model is not a ship in PCore001");
var overrides = hulls.Select(h => h.TextureName).Distinct().ToArray();
if (overrides.Length != 1) throw new InvalidDataException("Model has multiple hull texture overrides; select an unambiguous family");
var path = Path.Combine(art, name + ".mdl");
var mdl = MdlFile.Parse(path);
if (mdl.Meshes.Count == 0 || mdl.UnsupportedGeometryNodes.Count > 0)
    throw new InvalidDataException("Missing or unsupported native geometry");
var stem = NativeShipResolver.ResolveTextureStem(mdl, overrides[0], name, s => File.Exists(Path.Combine(art, s + ".mdl")))
    ?? throw new InvalidDataException("No native texture");
// A single add-on texture set cannot represent independent native material atlases.
if (mdl.Meshes.Any(m => m.TextureStem is not null && m.TextureStem != stem))
    throw new InvalidDataException("Multiple native texture atlases: resolved=" + stem + "; mesh=" + string.Join(",", mdl.Meshes.Select(m => m.TextureStem).Distinct()));
var texPath = Path.Combine(art, stem + ".mdl");
var tex = MdlTextureDecoder.Decode(File.ReadAllBytes(texPath));
string Hash(string p) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(p)));
var output = new { Model = name, Texture = stem, ModelSha256 = Hash(path), TextureSha256 = Hash(texPath),
    Hulls = hulls.Select(h => new { h.HullId, h.Name, h.Length }), mdl.Meshes, mdl.Frames,
    Width = tex.Width, Height = tex.Height, Rgba = tex.Rgba };
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1]))!);
File.WriteAllText(args[1], JsonSerializer.Serialize(output, options));
