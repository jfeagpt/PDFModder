// PDF Modder installer. SPDX-License-Identifier: AGPL-3.0-only
// Build with the Windows .NET Framework C# 5 compiler; no downloaded runtime.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Instalar PDF Modder 1.7.0")]
[assembly: AssemblyProduct("PDF Modder")]
[assembly: AssemblyVersion("1.7.0.1")]
[assembly: AssemblyFileVersion("1.7.0.1")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

namespace PdfModderInstallation
{
    internal sealed class Options
    {
        public string Directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "PDFModder", "1.7.0");
        public string Report;
        public string PreviousDirectory;
        public int PreviousPid;
        public bool Silent, Shortcut = true, Launch, Update, RemovePrevious = true;
        public static Options Parse(string[] args)
        {
            var value = new Options();
            bool noLaunch = false;
            var seen = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 0; i < args.Length; i++)
            {
                if (!seen.Add(args[i])) throw new ArgumentException("Opción repetida: " + args[i]);
                switch (args[i])
                {
                    case "--silent": value.Silent = true; break;
                    case "--update": value.Update = true; break;
                    case "--keep-previous": value.RemovePrevious = false; break;
                    case "--no-shortcut": value.Shortcut = false; break;
                    case "--no-launch": noLaunch = true; break;
                    case "--dir": case "--report": case "--previous-dir": case "--previous-pid":
                        string option = args[i];
                        if (++i == args.Length) throw new ArgumentException("Falta el valor de " + option);
                        if (option == "--dir") value.Directory = args[i];
                        else if (option == "--report") value.Report = args[i];
                        else if (option == "--previous-dir") value.PreviousDirectory = args[i];
                        else if (!Int32.TryParse(args[i], NumberStyles.None, CultureInfo.InvariantCulture, out value.PreviousPid) || value.PreviousPid <= 0)
                            throw new ArgumentException("Identificador del proceso anterior inválido.");
                        break;
                    default: throw new ArgumentException("Opción desconocida: " + args[i]);
                }
            }
            if (value.PreviousPid != 0 && String.IsNullOrEmpty(value.PreviousDirectory))
                throw new ArgumentException("Falta la carpeta de la aplicación anterior.");
            if (value.Update)
            {
                value.Silent = true; value.Launch = !noLaunch;
                if (value.Report == null) value.Report = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "PDFModder", "updates", "actualizacion-" + Guid.NewGuid().ToString("N") + ".json");
            }
            return value;
        }
    }

    internal sealed class Result
    {
        public bool ok;
        public string directory, backup, error, diagnostic;
        public string previous_directory, previous_version, uninstall_report;
        public bool previous_removed;
        public int files;
        public double elapsed_seconds;
        public List<string> warnings = new List<string>();
    }

    internal sealed class ExpectedFile
    {
        public string Hash, Relative;
        public long Size;
    }

    internal sealed class PreviousInstallation
    {
        public string Directory, Version, UninstallerHash;
    }

    internal static class Installer
    {
        static Installer()
        {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
        }
        const string Marker = ".pdfmodder-installation.json";
        const string FileManifest = ".pdfmodder-files.tsv";
        const string AppId = "PDFModder.Windows.PerUser";
        const string Version = "1.7.0";
        const int InstallerRevision = 1;
        const string UninstallRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFModder-1.7.0";
        static readonly string[] Critical = { "PDFModder.exe", "Desinstalar.exe", "_internal/shiboken6/Shiboken.pyd",
            "_internal/shiboken6/shiboken6.abi3.dll", "_internal/PySide6/Qt6Core.dll",
            "_internal/PySide6/Qt6Gui.dll", "_internal/PySide6/Qt6Widgets.dll",
            "_internal/PySide6/plugins/platforms/qwindows.dll" };

        internal static string Absolute(string value)
        {
            if (String.IsNullOrWhiteSpace(value) || !Path.IsPathRooted(value) ||
                (value.Length > 1 && value[1] == ':' && (value.Length < 3 || (value[2] != '\\' && value[2] != '/'))))
                throw new IOException("Seleccione una ruta absoluta de Windows.");
            string full = Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (full.Length < 4 || full.Equals(Path.GetPathRoot(full).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                throw new IOException("No se puede instalar en la raíz de una unidad.");
            return full;
        }

        static bool Inside(string child, string parent)
        {
            return child.StartsWith(parent.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
        }

        static string Extended(string path)
        {
            if (path.StartsWith(@"\\?\", StringComparison.Ordinal)) return path;
            return path.StartsWith(@"\\", StringComparison.Ordinal) ? @"\\?\UNC\" + path.Substring(2) : @"\\?\" + path;
        }

        static string DisplayPath(string path)
        {
            if (path == null) return null;
            if (path.StartsWith(@"\\?\UNC\", StringComparison.Ordinal)) return @"\\" + path.Substring(8);
            return path.StartsWith(@"\\?\", StringComparison.Ordinal) ? path.Substring(4) : path;
        }

        internal static void NoLinks(string path)
        {
            string cursor = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(cursor))
            {
                try
                {
                    if ((File.GetAttributes(cursor) & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("La ruta contiene un enlace o punto de redirección: " + cursor + ". Elija otra carpeta local.");
                }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
                cursor = Path.GetDirectoryName(cursor);
            }
        }

        static void CheckTree(string root)
        {
            NoLinks(root);
            var pending = new Stack<string>(); pending.Push(root);
            while (pending.Count > 0)
            {
                foreach (string path in System.IO.Directory.EnumerateFileSystemEntries(pending.Pop()))
                {
                    FileAttributes attributes = File.GetAttributes(path);
                    if ((attributes & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("La instalación contiene un enlace; no se moverá: " + path);
                    if ((attributes & FileAttributes.Directory) != 0) pending.Push(path);
                }
            }
        }

        static void ValidateDestination(string target)
        {
            NoLinks(target);
            if (File.Exists(target)) throw new IOException("El destino es un archivo. Seleccione una carpeta nueva.");
            if (!System.IO.Directory.Exists(target)) return;
            CheckTree(target);
            string marker = Path.Combine(target, Marker);
            if (!File.Exists(marker) || new FileInfo(marker).Length > 32768)
                throw new IOException("La carpeta ya existe y no es una instalación reconocida de PDF Modder. Elija una carpeta nueva; sus archivos se conservarán.");
            var saved = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(marker, Encoding.UTF8));
            if (saved == null || !saved.ContainsKey("application_id") || !AppId.Equals(saved["application_id"] as string))
                throw new IOException("La carpeta no tiene un identificador válido de PDF Modder. Elija una carpeta nueva.");
        }

        static string Relative(string name)
        {
            if (!name.StartsWith("PDFModder/", StringComparison.Ordinal) || name.IndexOf('\\') >= 0)
                throw new IOException("Ruta inválida en el paquete: " + name);
            string relative = name.Substring(10);
            foreach (string part in relative.Split('/'))
            {
                if (String.IsNullOrEmpty(part) || part == "." || part == ".." || part != part.TrimEnd(' ', '.') ||
                    part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                    Regex.IsMatch(part, @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", RegexOptions.IgnoreCase))
                    throw new IOException("Nombre de archivo no permitido en el paquete: " + name);
            }
            return relative.Replace('/', Path.DirectorySeparatorChar);
        }

        static Dictionary<string, ExpectedFile> Manifest()
        {
            var files = new Dictionary<string, ExpectedFile>(StringComparer.OrdinalIgnoreCase);
            using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("PDFModderPayload.tsv"))
            {
                if (resource == null) throw new IOException("Falta el inventario de archivos del instalador.");
                using (var reader = new StreamReader(resource, Encoding.UTF8, true))
                {
                    string row;
                    while ((row = reader.ReadLine()) != null)
                    {
                        string[] parts = row.Split('\t'); long size;
                        if (parts.Length != 3 || !Regex.IsMatch(parts[0], "^[0-9a-f]{64}$") ||
                            !Int64.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out size) || size > 1073741824)
                            throw new IOException("El inventario está dañado.");
                        files.Add(parts[2], new ExpectedFile { Hash = parts[0], Size = size, Relative = Relative(parts[2]) });
                    }
                }
            }
            foreach (string required in Critical)
                if (!files.ContainsKey("PDFModder/" + required)) throw new IOException("Falta una dependencia obligatoria: " + required);
            return files;
        }

        static string Hash(string path)
        {
            using (var algorithm = SHA256.Create())
            using (var stream = File.OpenRead(path))
                return BitConverter.ToString(algorithm.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }

        static void WriteFileManifest(string staging)
        {
            Dictionary<string, ExpectedFile> expected = Manifest();
            var names = new List<string>(expected.Keys);
            names.Sort(StringComparer.Ordinal);
            var content = new StringBuilder();
            foreach (string name in names)
            {
                ExpectedFile file = expected[name];
                string relative = name.Substring("PDFModder/".Length);
                content.Append(file.Hash).Append('\t')
                    .Append(file.Size.ToString(CultureInfo.InvariantCulture)).Append('\t')
                    .Append(relative).Append('\n');
            }
            File.WriteAllText(Path.Combine(staging, FileManifest), content.ToString(), new UTF8Encoding(false));
        }

        static string Quoted(string value)
        {
            return "\"" + value + "\"";
        }

        static bool SameLocation(string left, string right)
        {
            try
            {
                return Absolute(left).Equals(Absolute(right), StringComparison.OrdinalIgnoreCase);
            }
            catch { return false; }
        }

        static PreviousInstallation Previous(string requested, string target)
        {
            string directory = Absolute(requested), destination = Absolute(target);
            if (SameLocation(directory, destination) || Inside(directory, destination) || Inside(destination, directory))
                throw new IOException("La nueva instalación debe estar en una carpeta independiente de la anterior.");
            CheckTree(directory);
            string marker = Path.Combine(directory, Marker), manifest = Path.Combine(directory, FileManifest);
            if (!File.Exists(marker) || new FileInfo(marker).Length > 32768 || !File.Exists(manifest) || new FileInfo(manifest).Length > 67108864)
                throw new IOException("La copia anterior no tiene marcador e inventario válidos; se conserva.");
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(marker, Encoding.UTF8));
            object id, savedVersion; System.Version previousVersion, currentVersion;
            if (data == null || !data.TryGetValue("application_id", out id) || !AppId.Equals(id as string) ||
                !data.TryGetValue("version", out savedVersion) || !System.Version.TryParse(savedVersion as string, out previousVersion) ||
                !System.Version.TryParse(Version, out currentVersion) || previousVersion >= currentVersion)
                throw new IOException("La copia indicada no es una versión anterior reconocida de PDF Modder; se conserva.");
            string uninstaller = Path.Combine(directory, "Desinstalar.exe"), expectedHash = null;
            long expectedSize = -1;
            using (var reader = new StreamReader(manifest, Encoding.UTF8, true))
            {
                string row; int count = 0;
                while ((row = reader.ReadLine()) != null)
                {
                    if (++count > 200000) throw new IOException("El inventario anterior contiene demasiados archivos.");
                    string[] parts = row.Split('\t');
                    if (parts.Length != 3) throw new IOException("El inventario anterior está dañado.");
                    if (!parts[2].Equals("Desinstalar.exe", StringComparison.OrdinalIgnoreCase)) continue;
                    if (expectedHash != null || !Regex.IsMatch(parts[0], "^[0-9a-f]{64}$") ||
                        !Int64.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out expectedSize))
                        throw new IOException("La identidad del desinstalador anterior no es verificable.");
                    expectedHash = parts[0];
                }
            }
            if (expectedHash == null || !File.Exists(uninstaller) || new FileInfo(uninstaller).Length != expectedSize ||
                !Hash(uninstaller).Equals(expectedHash, StringComparison.Ordinal))
                throw new IOException("El desinstalador anterior fue modificado o falta. La copia anterior se conserva.");
            return new PreviousInstallation { Directory = directory, Version = savedVersion as string, UninstallerHash = expectedHash };
        }

        internal static string DiscoverPrevious(string target)
        {
            string best = null; System.Version highest = new System.Version(0, 0, 0);
            using (RegistryKey root = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall", false))
            {
                if (root == null) return null;
                foreach (string name in root.GetSubKeyNames())
                {
                    if (!name.StartsWith("PDFModder-", StringComparison.Ordinal)) continue;
                    try
                    {
                        using (RegistryKey key = root.OpenSubKey(name, false))
                        {
                            if (key == null || !AppId.Equals(Convert.ToString(key.GetValue("PDFModderApplicationId", null)))) continue;
                            string location = Convert.ToString(key.GetValue("InstallLocation", null));
                            PreviousInstallation previous = Previous(location, target);
                            if (!previous.Version.Equals(Convert.ToString(key.GetValue("DisplayVersion", null)), StringComparison.Ordinal)) continue;
                            var version = new System.Version(previous.Version);
                            if (version > highest) { highest = version; best = previous.Directory; }
                        }
                    }
                    catch (Exception) { /* Unrecognized entries are never acted on. */ }
                }
            }
            return best;
        }

        static void WaitForPrevious(Options options, PreviousInstallation previous)
        {
            if (options.PreviousPid == 0)
            {
                // Older updaters have no PID handoff. Request an ordinary close
                // only for this exact installed instance; never terminate it.
                foreach (Process process in Process.GetProcessesByName("PDFModder"))
                {
                    using (process)
                    {
                        try
                        {
                            string executable = process.MainModule == null ? null : process.MainModule.FileName;
                            if (executable == null || !SameLocation(executable, Path.Combine(previous.Directory, "PDFModder.exe"))) continue;
                            if (!process.CloseMainWindow() || !process.WaitForExit(30000))
                                throw new IOException("Cierre la versión anterior de PDF Modder y vuelva a instalar. Sus cambios y su instalación se conservan.");
                        }
                        catch (InvalidOperationException) { }
                    }
                }
                return;
            }
            try
            {
                using (Process process = Process.GetProcessById(options.PreviousPid))
                {
                    string executable = process.MainModule == null ? null : process.MainModule.FileName;
                    if (executable == null || !SameLocation(executable, Path.Combine(previous.Directory, "PDFModder.exe")))
                        throw new IOException("El proceso anterior no corresponde a la instalación indicada. No se ha retirado nada.");
                    if (!process.WaitForExit(30000))
                        throw new IOException("PDF Modder no se cerró en 30 segundos. Cierre la aplicación y vuelva a actualizar; la versión anterior se conserva.");
                }
            }
            catch (ArgumentException) { /* The application has already closed. */ }
            catch (InvalidOperationException) { /* The process exited while being inspected. */ }
        }

        static void RetirePrevious(PreviousInstallation previous, string installed, Result result, Action<int, string> progress)
        {
            if (previous == null) return;
            result.previous_directory = previous.Directory; result.previous_version = previous.Version;
            try
            {
                PreviousInstallation rechecked = Previous(previous.Directory, installed);
                if (!previous.UninstallerHash.Equals(rechecked.UninstallerHash, StringComparison.Ordinal))
                    throw new IOException("El desinstalador anterior cambió durante la instalación.");
                progress(97, "Retirando PDF Modder " + previous.Version + "; se conservan sus documentos y archivos modificados…");
                string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PDFModder", "updates");
                NoLinks(folder); System.IO.Directory.CreateDirectory(folder);
                string report = Path.Combine(folder, "retirada-" + Guid.NewGuid().ToString("N") + ".json");
                result.uninstall_report = report;
                var start = new ProcessStartInfo(Path.Combine(previous.Directory, "Desinstalar.exe"),
                    "--silent --dir " + Quoted(previous.Directory) + " --report " + Quoted(report))
                    { WorkingDirectory = folder, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
                using (Process process = Process.Start(start))
                {
                    if (process == null || !process.WaitForExit(30000) || process.ExitCode != 0)
                        throw new IOException("No se pudo iniciar la retirada de la versión anterior.");
                }
                // The old uninstaller relaunches itself outside its installation.
                // Its completed JSON report, not the launcher's exit, proves removal.
                var watch = Stopwatch.StartNew(); Dictionary<string, object> data = null;
                while (watch.Elapsed.TotalSeconds < 120)
                {
                    try
                    {
                        if (File.Exists(report) && new FileInfo(report).Length > 0)
                        {
                            data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(report, Encoding.UTF8));
                            if (data != null && data.ContainsKey("ok")) break;
                        }
                    }
                    catch (IOException) { }
                    catch (ArgumentException) { }
                    System.Threading.Thread.Sleep(100);
                }
                if (data == null || !data.ContainsKey("ok") || !(data["ok"] is bool) || !(bool)data["ok"])
                    throw new IOException(data != null && data.ContainsKey("error") ? Convert.ToString(data["error"]) : "No se recibió el informe final de retirada.");
                result.previous_removed = true;
                if (data.ContainsKey("preserved") && Convert.ToInt32(data["preserved"], CultureInfo.InvariantCulture) > 0)
                    result.warnings.Add("Se retiró la versión anterior y se conservaron documentos o archivos modificados en " + previous.Directory + ".");
                if (data.ContainsKey("warnings"))
                {
                    var warnings = data["warnings"] as System.Collections.IEnumerable;
                    if (warnings != null) foreach (object warning in warnings) result.warnings.Add(Convert.ToString(warning));
                }
            }
            catch (Exception ex)
            {
                result.warnings.Add("La nueva versión está instalada. La retirada de " + previous.Version + " no terminó: " + ex.Message + " Revise " + (result.uninstall_report ?? previous.Directory) + ".");
            }
        }

        static int EstimatedSize(string target)
        {
            long bytes = 0;
            foreach (ExpectedFile file in Manifest().Values)
            {
                if (Int64.MaxValue - bytes < file.Size) return Int32.MaxValue;
                bytes += file.Size;
            }
            foreach (string generated in new[] { Marker, FileManifest })
            {
                string path = Path.Combine(target, generated);
                if (File.Exists(path) && Int64.MaxValue - bytes >= new FileInfo(path).Length)
                    bytes += new FileInfo(path).Length;
            }
            long kibibytes = (bytes + 1023L) / 1024L;
            return kibibytes > Int32.MaxValue ? Int32.MaxValue : (int)kibibytes;
        }

        static void RegisterInstallation(string target, Result result)
        {
            try
            {
                string exe = Path.Combine(target, "PDFModder.exe");
                string uninstaller = Path.Combine(target, "Desinstalar.exe");
                if (!File.Exists(exe) || !File.Exists(uninstaller))
                    throw new IOException("Falta el ejecutable principal o el desinstalador.");

                bool existed;
                using (RegistryKey existing = Registry.CurrentUser.OpenSubKey(UninstallRegistryPath, false))
                {
                    existed = existing != null;
                    if (existing != null)
                    {
                        string previous = Convert.ToString(existing.GetValue("InstallLocation", null));
                        string previousId = Convert.ToString(existing.GetValue("PDFModderApplicationId", null));
                        if (!AppId.Equals(previousId, StringComparison.Ordinal) || !SameLocation(previous, target))
                        {
                            result.warnings.Add("La aplicación está instalada, pero no se modificó una entrada de desinstalación que no pertenece a esta copia: " + previous);
                            return;
                        }
                    }
                }

                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegistryPath, RegistryKeyPermissionCheck.ReadWriteSubTree))
                {
                    if (key == null) throw new IOException("Windows no permitió crear la entrada de desinstalación.");
                    string current = Convert.ToString(key.GetValue("InstallLocation", null));
                    string currentId = Convert.ToString(key.GetValue("PDFModderApplicationId", null));
                    if ((existed && (!AppId.Equals(currentId, StringComparison.Ordinal) || !SameLocation(current, target))) ||
                        (!String.IsNullOrEmpty(current) && !SameLocation(current, target)))
                    {
                        result.warnings.Add("La aplicación está instalada, pero no se modificó una entrada de desinstalación que apunta a otra carpeta: " + current);
                        return;
                    }
                    key.SetValue("DisplayName", "PDF Modder " + Version, RegistryValueKind.String);
                    key.SetValue("DisplayVersion", Version, RegistryValueKind.String);
                    key.SetValue("Publisher", "S.A.T. AGROLEVANTE", RegistryValueKind.String);
                    key.SetValue("InstallLocation", target, RegistryValueKind.String);
                    key.SetValue("DisplayIcon", Quoted(exe) + ",0", RegistryValueKind.String);
                    key.SetValue("UninstallString", Quoted(uninstaller) + " --dir " + Quoted(target), RegistryValueKind.String);
                    key.SetValue("QuietUninstallString", Quoted(uninstaller) + " --dir " + Quoted(target) + " --silent", RegistryValueKind.String);
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    key.SetValue("EstimatedSize", EstimatedSize(target), RegistryValueKind.DWord);
                    key.SetValue("PDFModderApplicationId", AppId, RegistryValueKind.String);
                    key.SetValue("InstallerRevision", InstallerRevision, RegistryValueKind.DWord);
                }
            }
            catch (Exception ex)
            {
                result.warnings.Add("La aplicación está instalada, pero Windows no pudo registrar la desinstalación: " + ex.Message);
            }
        }

        static void Extract(string staging, Action<int, string> progress, Result result)
        {
            Dictionary<string, ExpectedFile> expected = Manifest();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("PDFModderPayload.zip"))
            {
                if (resource == null) throw new IOException("Falta el contenido del instalador.");
                using (var zip = new ZipArchive(resource, ZipArchiveMode.Read, false))
                {
                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        ExpectedFile file;
                        if (!expected.TryGetValue(entry.FullName, out file) || !seen.Add(entry.FullName) || entry.Length != file.Size)
                            throw new IOException("Archivo inesperado, repetido o incompleto: " + entry.FullName);
                        string destination = Path.GetFullPath(Path.Combine(staging, file.Relative));
                        if (!Inside(destination, staging)) throw new IOException("El archivo sale de la carpeta de instalación.");
                        NoLinks(destination);
                        System.IO.Directory.CreateDirectory(Path.GetDirectoryName(destination));
                        using (Stream input = entry.Open())
                        using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                        {
                            byte[] buffer = new byte[131072]; int read; long count = 0;
                            while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                            {
                                count += read;
                                if (count > file.Size) throw new IOException("Tamaño incorrecto: " + entry.FullName);
                                output.Write(buffer, 0, read);
                            }
                            if (count != file.Size) throw new IOException("Archivo incompleto: " + entry.FullName);
                            output.Flush(true);
                        }
                        if (!Hash(destination).Equals(file.Hash, StringComparison.Ordinal))
                            throw new IOException("La comprobación SHA-256 ha fallado: " + file.Relative + ". No se ha instalado el paquete.");
                        result.files++;
                        progress(Math.Min(95, result.files * 95 / expected.Count), "Copiando y comprobando archivos: " + result.files + " de " + expected.Count);
                    }
                }
            }
            if (seen.Count != expected.Count) throw new IOException("El paquete no contiene todos los archivos del inventario.");
            foreach (string required in Critical)
                if (!File.Exists(Path.Combine(staging, required.Replace('/', '\\')))) throw new IOException("Falta la dependencia " + required);
        }

        static void CreateShortcut(string path, string executable, string workingDirectory,
            string description, string icon, string arguments)
        {
            object shell = null, link = null;
            try
            {
                NoLinks(path);
                shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell", true));
                link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
                if (File.Exists(path))
                {
                    string previous = Convert.ToString(link.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null));
                    if (!String.Equals(previous, executable, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("Ya existe un acceso directo que apunta a otra copia: " + path);
                }
                link.GetType().InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { executable });
                link.GetType().InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { workingDirectory });
                link.GetType().InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { description });
                link.GetType().InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { icon + ",0" });
                link.GetType().InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[] { arguments ?? "" });
                link.GetType().InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            }
            finally
            {
                if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link);
                if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
            }
        }

        static void Shortcut(string target, Result result)
        {
            try
            {
                string exe = Path.Combine(target, "PDFModder.exe");
                string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "PDF Modder 1.7.0.lnk");
                CreateShortcut(path, exe, target, "PDF Modder " + Version, exe, null);
            }
            catch (Exception ex) { result.warnings.Add("El programa está instalado, pero no se creó el acceso directo del escritorio: " + ex.Message); }
        }

        static void StartMenuShortcuts(string target, Result result)
        {
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "PDF Modder " + Version);
            string exe = Path.Combine(target, "PDFModder.exe");
            string uninstaller = Path.Combine(target, "Desinstalar.exe");
            try
            {
                NoLinks(folder);
                System.IO.Directory.CreateDirectory(folder);
                CreateShortcut(Path.Combine(folder, "PDF Modder " + Version + ".lnk"), exe, target,
                    "PDF Modder " + Version, exe, null);
            }
            catch (Exception ex) { result.warnings.Add("El programa está instalado, pero no se creó su acceso directo del menú Inicio: " + ex.Message); }
            try
            {
                NoLinks(folder);
                System.IO.Directory.CreateDirectory(folder);
                CreateShortcut(Path.Combine(folder, "Desinstalar PDF Modder " + Version + ".lnk"), uninstaller, target,
                    "Desinstalar PDF Modder " + Version, exe, "--dir " + Quoted(target));
            }
            catch (Exception ex) { result.warnings.Add("El programa está instalado, pero no se creó el acceso directo de desinstalación del menú Inicio: " + ex.Message); }
        }

        internal static Result Run(Options options, Action<int, string> progress)
        {
            var result = new Result(); var watch = Stopwatch.StartNew();
            string staging = null, parent = null;
            try
            {
                string target = Extended(Absolute(options.Directory)); result.directory = DisplayPath(target);
                ValidateDestination(target);
                PreviousInstallation previous = null;
                if (!String.IsNullOrEmpty(options.PreviousDirectory) && options.RemovePrevious)
                {
                    previous = Previous(options.PreviousDirectory, result.directory);
                    progress(0, "Esperando a que termine PDF Modder " + previous.Version + "…");
                    WaitForPrevious(options, previous);
                }
                parent = Path.GetDirectoryName(target);
                System.IO.Directory.CreateDirectory(parent);
                NoLinks(parent);
                staging = Path.Combine(parent, ".pdfmodder-stage-" + Guid.NewGuid().ToString("N"));
                System.IO.Directory.CreateDirectory(staging);
                Extract(staging, progress, result);
                WriteFileManifest(staging);
                string marker = new JavaScriptSerializer().Serialize(new { application_id = AppId, version = "1.7.0", installer_revision = InstallerRevision,
                    installed_utc = DateTime.UtcNow.ToString("o"), verified_files = result.files });
                File.WriteAllText(Path.Combine(staging, Marker), marker, new UTF8Encoding(false));
                CheckTree(staging);
                // Recheck immediately before moving; only a recognized installation can be backed up.
                ValidateDestination(target);
                if (System.IO.Directory.Exists(target))
                {
                    result.backup = target + ".copia-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 8);
                    if (!Inside(result.backup, parent)) throw new IOException("Ruta de copia inválida.");
                    System.IO.Directory.Move(target, result.backup);
                }
                try { System.IO.Directory.Move(staging, target); staging = null; }
                catch
                {
                    if (result.backup != null && !System.IO.Directory.Exists(target))
                    { CheckTree(result.backup); System.IO.Directory.Move(result.backup, target); result.backup = null; }
                    throw;
                }
                result.ok = true;
                string installed = DisplayPath(target);
                RegisterInstallation(installed, result);
                StartMenuShortcuts(installed, result);
                if (options.Shortcut) Shortcut(installed, result);
                RetirePrevious(previous, installed, result, progress);
                if (options.Launch)
                {
                    try { Process.Start(new ProcessStartInfo(Path.Combine(installed, "PDFModder.exe")) { WorkingDirectory = installed, UseShellExecute = false }); }
                    catch (Exception ex) { result.warnings.Add("Instalado, pero no se pudo abrir automáticamente: " + ex.Message); }
                }
                progress(100, "Instalación comprobada. " + result.files + " archivos verificados.");
            }
            catch (Exception ex) { result.error = ex.Message; result.diagnostic = ex.ToString(); }
            finally
            {
                if (staging != null && System.IO.Directory.Exists(staging))
                {
                    try
                    {
                        string full = Path.GetFullPath(staging);
                        if (parent == null || !Inside(full, parent) || !Path.GetFileName(full).StartsWith(".pdfmodder-stage-", StringComparison.Ordinal))
                            throw new IOException("Ruta temporal inesperada.");
                        CheckTree(full); System.IO.Directory.Delete(full, true);
                    }
                    catch (Exception ex) { result.warnings.Add("Se conservó la carpeta temporal " + staging + ": " + ex.Message); }
                }
                result.elapsed_seconds = Math.Round(watch.Elapsed.TotalSeconds, 3);
                result.backup = DisplayPath(result.backup);
            }
            return result;
        }

        internal static FileStream ReserveReport(Options options)
        {
            if (options.Report == null) return null;
            string report = Absolute(options.Report), target = Absolute(options.Directory);
            if (Inside(report, target) || report.Equals(target, StringComparison.OrdinalIgnoreCase))
                throw new IOException("Guarde el informe fuera de la carpeta de instalación.");
            NoLinks(report);
            System.IO.Directory.CreateDirectory(Extended(Path.GetDirectoryName(report)));
            return new FileStream(Extended(report), FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        }

        internal static void WriteReport(FileStream stream, Result result)
        {
            if (stream == null) return;
            byte[] bytes = new UTF8Encoding(false).GetBytes(new JavaScriptSerializer().Serialize(result));
            stream.Write(bytes, 0, bytes.Length); stream.Flush(true);
        }
    }

    internal sealed class InstallerWindow : Form
    {
        readonly TextBox pathBox = new TextBox { Dock = DockStyle.Fill, Name = "destinationPath" };
        readonly CheckBox shortcutCheck = new CheckBox { Text = "Crear acceso directo en el escritorio", Checked = true, AutoSize = true, Name = "createShortcut" };
        readonly CheckBox launchCheck = new CheckBox { Text = "Abrir PDF Modder al terminar", Checked = false, AutoSize = true, Name = "launchApplication" };
        readonly CheckBox removePreviousCheck = new CheckBox { Text = "Retirar la versión anterior tras instalar correctamente", Checked = true, AutoSize = true, Name = "removePreviousVersion" };
        readonly Button installButton = new Button { Text = "Instalar", AutoSize = true, Name = "installButton" };
        readonly Button closeButton = new Button { Text = "Cancelar", AutoSize = true, Name = "closeButton" };
        readonly Button browseButton = new Button { Text = "Elegir…", AutoSize = true };
        readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Fill };
        readonly TextBox status = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None,
            BackColor = SystemColors.Control, ScrollBars = ScrollBars.Vertical, Name = "installationStatus" };
        readonly Options options;
        bool busy;

        internal InstallerWindow(Options initial)
        {
            options = initial; pathBox.Text = options.Directory; shortcutCheck.Checked = options.Shortcut;
            if (options.PreviousDirectory == null) options.PreviousDirectory = Installer.DiscoverPrevious(options.Directory);
            removePreviousCheck.Checked = options.RemovePrevious;
            removePreviousCheck.Enabled = options.PreviousDirectory != null;
            if (options.PreviousDirectory == null) removePreviousCheck.Checked = false;
            else launchCheck.Checked = true;
            Text = "Instalar PDF Modder 1.7.0"; Font = new Font("Segoe UI", 10F);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch { }
            AutoScaleMode = AutoScaleMode.Dpi; StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(710, 440); MinimumSize = new Size(640, 460); MaximizeBox = false;
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, RowCount = 11 };
            for (int i = 0; i < 11; i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles[8] = new RowStyle(SizeType.Percent, 100);
            layout.Controls.Add(new Label { Text = "PDF Modder 1.7.0", AutoSize = true, Font = new Font("Segoe UI", 19F, FontStyle.Bold), Margin = new Padding(0, 0, 0, 12) }, 0, 0);
            layout.Controls.Add(new Label { Text = "Instala el editor completo y comprueba todos sus archivos.\nNo necesita Python ni conexión a Internet.", AutoSize = true, Margin = new Padding(0, 0, 0, 16) }, 0, 1);
            layout.Controls.Add(new Label { Text = "Carpeta de instalación", AutoSize = true }, 0, 2);
            var pathLine = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2 };
            pathLine.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); pathLine.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            pathLine.Controls.Add(pathBox, 0, 0); pathLine.Controls.Add(browseButton, 1, 0); layout.Controls.Add(pathLine, 0, 3);
            layout.Controls.Add(shortcutCheck, 0, 4); layout.Controls.Add(launchCheck, 0, 5);
            layout.Controls.Add(removePreviousCheck, 0, 6);
            layout.Controls.Add(progress, 0, 7); layout.Controls.Add(status, 0, 8);
            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
            buttons.Controls.Add(closeButton); buttons.Controls.Add(installButton); layout.Controls.Add(buttons, 0, 9);
            Controls.Add(layout); AcceptButton = installButton; CancelButton = closeButton;
            status.Text = options.PreviousDirectory == null ? "Tus PDF y preferencias se conservan. No se ha detectado una instalación anterior reconocida." :
                "Versión anterior: " + options.PreviousDirectory + "\r\nSe retirará después de instalar correctamente, conservando PDF, preferencias y archivos modificados.";
            closeButton.Click += delegate { Close(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) e.Cancel = true; };
            browseButton.Click += delegate
            {
                using (var chooser = new FolderBrowserDialog { Description = "Seleccione la carpeta PADRE. Se creará una subcarpeta PDFModder-1.7.0." })
                    if (chooser.ShowDialog(this) == DialogResult.OK) pathBox.Text = Path.Combine(chooser.SelectedPath, "PDFModder-1.7.0");
            };
            installButton.Click += StartInstall;
        }

        void StartInstall(object sender, EventArgs e)
        {
            if (busy) return;
            options.Directory = pathBox.Text; options.Shortcut = shortcutCheck.Checked; options.Launch = launchCheck.Checked;
            options.RemovePrevious = removePreviousCheck.Checked;
            busy = true; pathBox.Enabled = browseButton.Enabled = shortcutCheck.Enabled = launchCheck.Enabled = removePreviousCheck.Enabled = installButton.Enabled = closeButton.Enabled = false;
            status.ForeColor = SystemColors.ControlText; status.Text = "Preparando la instalación…";
            var worker = new BackgroundWorker { WorkerReportsProgress = true };
            worker.DoWork += delegate(object s, DoWorkEventArgs args)
            {
                using (FileStream report = Installer.ReserveReport(options))
                {
                    Result result = Installer.Run(options, delegate(int percent, string message) { worker.ReportProgress(percent, message); });
                    Installer.WriteReport(report, result); args.Result = result;
                }
            };
            worker.ProgressChanged += delegate(object s, ProgressChangedEventArgs args) { progress.Value = args.ProgressPercentage; status.Text = (string)args.UserState; };
            worker.RunWorkerCompleted += delegate(object s, RunWorkerCompletedEventArgs args)
            {
                busy = false; closeButton.Enabled = true; closeButton.Text = "Cerrar";
                Result result = args.Error == null ? args.Result as Result : new Result { error = args.Error.Message };
                if (result != null && result.ok)
                {
                    progress.Value = 100; status.ForeColor = Color.DarkGreen;
                    status.Text = "Instalación terminada: " + result.files + " archivos comprobados.\r\n" + result.directory;
                    if (result.previous_removed) status.Text += "\r\nVersión anterior " + result.previous_version + " retirada.";
                    if (result.backup != null) status.Text += "\r\nCopia anterior: " + result.backup;
                    if (result.warnings.Count > 0) status.Text += "\r\n" + String.Join("\r\n", result.warnings);
                    installButton.Text = "Instalado";
                }
                else
                {
                    status.ForeColor = Color.Firebrick; status.Text = "No se ha completado la instalación. " + (result == null ? "Error desconocido." : result.error);
                    pathBox.Enabled = browseButton.Enabled = shortcutCheck.Enabled = launchCheck.Enabled = installButton.Enabled = true;
                    removePreviousCheck.Enabled = options.PreviousDirectory != null;
                    if (result != null && result.warnings.Count > 0) status.Text += "\r\n" + String.Join("\r\n", result.warnings);
                }
                worker.Dispose();
            };
            worker.RunWorkerAsync();
        }
    }

    internal static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            // Set before constructing Options: even Path.Combine can cache
            // the .NET Framework compatibility switches for the process.
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
            bool silent = Array.IndexOf(args, "--silent") >= 0;
            bool update = Array.IndexOf(args, "--update") >= 0;
            try
            {
                Options options = Options.Parse(args);
                if (options.Silent)
                {
                    using (FileStream report = Installer.ReserveReport(options))
                    {
                        Result result = Installer.Run(options, delegate { });
                        Installer.WriteReport(report, result);
                        if (options.Update && !silent && (!result.ok || result.warnings.Count > 0))
                            MessageBox.Show((result.ok ? "La nueva versión está instalada.\n" : "No se ha completado la actualización.\n" + result.error + "\n") +
                                String.Join("\n", result.warnings) + "\nInforme: " + options.Report,
                                "Actualización de PDF Modder", MessageBoxButtons.OK, result.ok ? MessageBoxIcon.Warning : MessageBoxIcon.Error);
                        return result.ok ? 0 : 1;
                    }
                }
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new InstallerWindow(options)); return 0;
            }
            catch (Exception ex)
            {
                if (!silent || update) MessageBox.Show("No se ha completado la instalación.\n" + ex.Message, "PDF Modder 1.7.0", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
}
