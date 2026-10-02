"""Desinstalador independiente de 0.8 con inventario de su instalador original.

Antes de ejecutar, extraer PDFModderPayload.tsv del instalador original a
build/legacy-uninstaller-v08/payload.tsv. No modifica la aplicación 0.8.3.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'build/legacy-uninstaller-v08'
RELEASE = ROOT / 'releases/v0.8-desinstalador'


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError('El desinstalador base ha cambiado: ' + before[:80])
    return text.replace(before, after, 1)


def build():
    RELEASE.mkdir(parents=True, exist_ok=True)
    rows = []
    seen = set()
    for line in (STAGE / 'payload.tsv').read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        digest, size, name = line.split('\t')
        if not name.startswith('PDFModder/'):
            raise ValueError('Inventario no reconocido.')
        relative = name[len('PDFModder/'):]
        if relative.casefold() in seen or '..' in relative.split('/') or '\\' in relative or ':' in relative:
            raise ValueError('Ruta no permitida: ' + relative)
        seen.add(relative.casefold())
        rows.append(f'{digest}\t{int(size)}\t{relative}')
    if 'pdfmodder.exe' not in seen:
        raise ValueError('El inventario no contiene PDFModder.exe.')
    inventory = STAGE / 'LegacyFiles.tsv'
    inventory.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    source = (ROOT / 'installer/PdfModderUninstaller.cs').read_text(encoding='utf-8-sig').replace('0.8.3', '0.8.0')
    source = replace_once(source,
        '''            if (!File.Exists(Safety.Extended(manifest)) || new FileInfo(Safety.Extended(manifest)).Length > 67108864)
                throw new IOException("No se encontró el manifiesto de archivos de PDF Modder 0.8.0.");''',
        '''            // The legacy installer did not persist a file inventory.
            // Use the original installer's inventory embedded in this tool.
            manifest = null;''')
    source = replace_once(source, 'Safety.NoReparsePath(marker); Safety.NoReparsePath(manifest);', 'Safety.NoReparsePath(marker);')
    source = replace_once(source, 'ManifestHash = Hashing.FileHash(manifest)', 'ManifestHash = null')
    source = replace_once(source,
        'new StreamReader(Safety.Extended(manifest), Encoding.UTF8, true)',
        'new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("LegacyFiles.tsv"), Encoding.UTF8, true)')
    source = replace_once(source,
        '''            if (!paths.Contains("Desinstalar.exe"))
                throw new IOException("El manifiesto no incluye el desinstalador y no es seguro continuar.");''',
        '''            if (!paths.Contains("PDFModder.exe"))
                throw new IOException("El inventario original no incluye PDFModder.exe.");''')
    source = replace_once(source,
        '            if (!File.Exists(Safety.Extended(path))) return;\n            Safety.NoReparsePath(path);',
        '            if (path == null || !File.Exists(Safety.Extended(path))) return;\n            Safety.NoReparsePath(path);')
    source = replace_once(source, '                removalOrder.Add(installedUninstaller);',
                          '                if (installedUninstaller != null) removalOrder.Add(installedUninstaller);')
    chooser = r'''
    internal static class LegacyTarget
    {
        static bool Matches(string folder)
        {
            try
            {
                string marker = Path.Combine(folder, Installation.MarkerName);
                Safety.NoReparsePath(marker);
                if (!File.Exists(Safety.Extended(marker)) || new FileInfo(Safety.Extended(marker)).Length > 32768) return false;
                var saved = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Safety.Extended(marker), Encoding.UTF8));
                return saved != null && saved.ContainsKey("application_id") && saved.ContainsKey("version") &&
                    Installation.AppId.Equals(saved["application_id"] as string) && Installation.Version.Equals(saved["version"] as string);
            }
            catch { return false; }
        }

        internal static bool Choose(Options options, string[] args)
        {
            if (Array.IndexOf(args, "--dir") >= 0) return true;
            var candidates = new List<string>();
            string parent = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "PDFModder");
            foreach (string path in new[] { Path.Combine(parent, "0.8"), Path.Combine(parent, "0.8.0"), options.Directory })
                if (Matches(path) && !candidates.Contains(path)) candidates.Add(path);
            if (candidates.Count == 1) { options.Directory = candidates[0]; return true; }
            if (options.Silent) throw new IOException("Indique --dir con la carpeta instalada de PDF Modder 0.8.");
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            using (var chooser = new FolderBrowserDialog {
                Description = "Seleccione la carpeta instalada de PDF Modder 0.8 que contiene PDFModder.exe. No seleccione el instalador ni la versión 0.8.3.",
                ShowNewFolderButton = false,
                SelectedPath = candidates.Count > 0 ? candidates[0] : parent })
            {
                if (chooser.ShowDialog() != DialogResult.OK) return false;
                options.Directory = chooser.SelectedPath;
                if (!Matches(options.Directory)) throw new IOException("Esa carpeta no es una instalación reconocida de PDF Modder 0.8.0.");
                return true;
            }
        }
    }

'''
    source = replace_once(source, '    internal static class Program\n', chooser + '    internal static class Program\n')
    source = replace_once(source, '                    SelfRelaunch.Start(options); return 0;',
                          '                    if (!LegacyTarget.Choose(options, args)) return 0;\n                    SelfRelaunch.Start(options); return 0;')
    source_path = RELEASE / 'PdfModderV08Uninstaller.cs'
    source_path.write_text(source, encoding='utf-8-sig')
    manifest = STAGE / 'asInvoker.manifest'
    manifest.write_text((ROOT / 'installer/asInvoker.manifest').read_text(encoding='utf-8').replace('0.8.3.1', '0.8.0.1'), encoding='utf-8')
    target = RELEASE / 'PDFModder-v0.8-Desinstalar.exe'
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/out:' + str(target), '/win32manifest:' + str(manifest),
        '/win32icon:' + str(ROOT / 'assets/icons/pdfmodder.ico'),
        '/resource:' + str(inventory) + ',LegacyFiles.tsv',
        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
        '/reference:System.Web.Extensions.dll', str(source_path)], check=True, cwd=ROOT)
    (RELEASE / 'LEEME.txt').write_text(
        'Desinstalador independiente para el instalador PDFModder-v0.8-Instalar.exe (0.8.0).\n'
        '1. Cierre PDF Modder 0.8.\n2. Abra PDFModder-v0.8-Desinstalar.exe.\n'
        '3. Si se solicita, seleccione la carpeta instalada que contiene PDFModder.exe.\n'
        '4. Pulse Desinstalar y confirme.\n\n'
        'Sólo retira archivos coincidentes con el inventario del instalador original.\n'
        'Conserva documentos añadidos, archivos modificados y versiones distintas, incluida 0.8.3.\n'
        'No necesita Python ni que el instalador original esté presente en el equipo.\n'
        'El desinstalador descargado permanece disponible para reutilizarlo.\n', encoding='utf-8')
    print(json.dumps({'executable': str(target), 'inventory_files': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    build()
