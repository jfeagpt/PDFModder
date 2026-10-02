// PDF Modder uninstaller. SPDX-License-Identifier: AGPL-3.0-only
// Build with the Windows .NET Framework C# 5 compiler; no downloaded runtime.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Desinstalar PDF Modder 1.7.0")]
[assembly: AssemblyProduct("PDF Modder")]
[assembly: AssemblyVersion("1.7.0.0")]
[assembly: AssemblyFileVersion("1.7.0.0")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

namespace PdfModderUninstallation
{
    internal sealed class Options
    {
        public string Directory = Path.GetDirectoryName(Application.ExecutablePath);
        public string Report;
        public bool Silent, Worker;
        public int ParentPid;
        public long ParentStartedUtcTicks;

        public static Options Parse(string[] args)
        {
            var value = new Options();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 0; i < args.Length; i++)
            {
                string option = args[i];
                if (!seen.Add(option)) throw new ArgumentException("Opción repetida: " + option);
                switch (option)
                {
                    case "--silent": value.Silent = true; break;
                    case "--pdfmodder-worker": value.Worker = true; break;
                    case "--dir":
                    case "--report":
                    case "--parent-pid":
                    case "--parent-start":
                        if (++i == args.Length) throw new ArgumentException("Falta el valor de " + option);
                        string argument = args[i];
                        if (option == "--dir") value.Directory = argument;
                        else if (option == "--report") value.Report = argument;
                        else if (option == "--parent-pid")
                        {
                            if (!Int32.TryParse(argument, NumberStyles.None, CultureInfo.InvariantCulture, out value.ParentPid) || value.ParentPid <= 0)
                                throw new ArgumentException("Identificador del proceso padre inválido.");
                        }
                        else if (!Int64.TryParse(argument, NumberStyles.None, CultureInfo.InvariantCulture, out value.ParentStartedUtcTicks) || value.ParentStartedUtcTicks <= 0)
                            throw new ArgumentException("Marca de tiempo del proceso padre inválida.");
                        break;
                    default: throw new ArgumentException("Opción desconocida: " + option);
                }
            }
            if (value.Worker && (value.ParentPid <= 0 || value.ParentStartedUtcTicks <= 0))
                throw new ArgumentException("Faltan los datos del proceso que inició la desinstalación.");
            if (!value.Worker && (value.ParentPid != 0 || value.ParentStartedUtcTicks != 0))
                throw new ArgumentException("Las opciones internas sólo son válidas en el proceso temporal.");
            return value;
        }
    }

    internal sealed class Result
    {
        public bool ok;
        public int removed, preserved, shortcuts_removed;
        public string directory, error, diagnostic;
        public double elapsed_seconds;
        public List<string> removed_files = new List<string>();
        public List<string> preserved_files = new List<string>();
        public List<string> warnings = new List<string>();
    }

    internal sealed class ExpectedFile
    {
        public string Hash, Relative, FullPath;
        public long Size;
        public bool Exists, Matches, IsDirectory;
    }

    internal sealed class InstallationPlan
    {
        public string Root, MarkerPath, ManifestPath, MarkerHash, ManifestHash;
        public List<ExpectedFile> Files = new List<ExpectedFile>();
    }

    internal static class Safety
    {
        static readonly Regex DeviceName = new Regex(@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        static readonly IntPtr InvalidHandleValue = new IntPtr(-1);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct FindData
        {
            public FileAttributes Attributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
            public uint FileSizeHigh, FileSizeLow, Reserved0, Reserved1;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string FileName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)] public string AlternateFileName;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr FindFirstFile(string fileName, out FindData findData);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool FindClose(IntPtr findFile);

        internal static string Absolute(string value, string description)
        {
            if (String.IsNullOrWhiteSpace(value) || value.StartsWith(@"\\?\", StringComparison.Ordinal) ||
                value.StartsWith(@"\\.\", StringComparison.Ordinal) || !Path.IsPathRooted(value))
                throw new IOException(description + " debe ser una ruta absoluta normal de Windows.");
            if (value.Length > 1 && value[1] == ':' && (value.Length < 3 || (value[2] != '\\' && value[2] != '/')))
                throw new IOException(description + " debe incluir la raíz completa de la unidad.");
            int allowedColon = value.Length > 1 && value[1] == ':' ? 1 : -1;
            for (int i = 0; i < value.Length; i++)
                if (value[i] == ':' && i != allowedColon)
                    throw new IOException(description + " contiene un flujo alternativo o un nombre no permitido.");
            string full = Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (String.IsNullOrEmpty(full)) throw new IOException(description + " no es válida.");
            return full;
        }

        internal static bool Same(string left, string right)
        {
            return String.Equals(left.TrimEnd('\\', '/'), right.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase);
        }

        internal static bool Inside(string child, string parent)
        {
            return child.StartsWith(parent.TrimEnd('\\', '/') + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        }

        internal static string Extended(string path)
        {
            if (path.StartsWith(@"\\?\", StringComparison.Ordinal)) return path;
            return path.StartsWith(@"\\", StringComparison.Ordinal) ? @"\\?\UNC\" + path.Substring(2) : @"\\?\" + path;
        }

        internal static string Display(string path)
        {
            if (path.StartsWith(@"\\?\UNC\", StringComparison.Ordinal)) return @"\\" + path.Substring(8);
            return path.StartsWith(@"\\?\", StringComparison.Ordinal) ? path.Substring(4) : path;
        }

        static IEnumerable<string> ProtectedRoots()
        {
            yield return Path.GetPathRoot(Environment.SystemDirectory);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            yield return Environment.SystemDirectory;
            yield return Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.Programs);
            yield return Environment.GetFolderPath(Environment.SpecialFolder.CommonPrograms);
            string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            if (!String.IsNullOrEmpty(profile)) yield return Path.GetDirectoryName(profile);
        }

        internal static string InstallationRoot(string value)
        {
            string root = Absolute(value, "La carpeta de instalación");
            string drive = Path.GetPathRoot(root);
            if (!String.IsNullOrEmpty(drive) && Same(root, drive))
                throw new IOException("No se puede desinstalar desde la raíz de una unidad.");
            string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            string programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
            foreach (string protectedRoot in ProtectedRoots())
                if (!String.IsNullOrEmpty(protectedRoot) && Same(root, Path.GetFullPath(protectedRoot)))
                    throw new IOException("La carpeta elegida es una raíz de usuario o del sistema y no se puede desinstalar.");
            foreach (string systemTree in new[] { windows, programFiles, programFilesX86, programData })
                if (!String.IsNullOrEmpty(systemTree) && Inside(root, Path.GetFullPath(systemTree)))
                    throw new IOException("La carpeta elegida está dentro de una ubicación protegida del sistema.");
            if (!System.IO.Directory.Exists(Extended(root))) throw new DirectoryNotFoundException("No existe la carpeta de instalación: " + root);
            NoReparsePath(root);
            return root;
        }

        internal static void NoReparsePath(string path)
        {
            string cursor = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(cursor))
            {
                try
                {
                    if ((File.GetAttributes(Extended(cursor)) & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("La ruta contiene un enlace o punto de redirección: " + cursor);
                }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
                cursor = Path.GetDirectoryName(cursor);
            }
        }

        internal static void RejectReparseTree(string root)
        {
            NoReparsePath(root);
            var pending = new Stack<string>();
            pending.Push(root);
            while (pending.Count > 0)
            {
                string directory = pending.Pop();
                foreach (string rawPath in System.IO.Directory.EnumerateFileSystemEntries(Extended(directory)))
                {
                    string path = Display(rawPath); FileAttributes attributes = File.GetAttributes(rawPath);
                    if ((attributes & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("La instalación contiene un enlace o punto de redirección y no se modificará: " + path);
                    if ((attributes & FileAttributes.Directory) != 0) pending.Push(path);
                }
            }
        }

        internal static bool IsNameSurrogateReparsePoint(string path)
        {
            FindData data; IntPtr handle = FindFirstFile(Extended(path), out data);
            if (handle == InvalidHandleValue)
                throw new IOException("No se pudo inspeccionar el punto de redirección: " + path,
                    new Win32Exception(Marshal.GetLastWin32Error()));
            try
            {
                // Symbolic links, junctions and other path-substitution tags set
                // IO_REPARSE_TAG_NAME_SURROGATE. Cloud placeholders do not.
                return (data.Reserved0 & 0x20000000U) != 0;
            }
            finally { FindClose(handle); }
        }

        internal static string Relative(string value)
        {
            if (String.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value) || value.IndexOf('\\') >= 0 ||
                value.IndexOf(':') >= 0 || value.IndexOf('\t') >= 0 || value.IndexOf('\r') >= 0 || value.IndexOf('\n') >= 0)
                throw new IOException("Ruta relativa no permitida en el manifiesto: " + value);
            string[] parts = value.Split('/');
            foreach (string part in parts)
            {
                if (String.IsNullOrEmpty(part) || part == "." || part == ".." || part != part.TrimEnd(' ', '.') ||
                    part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || DeviceName.IsMatch(part))
                    throw new IOException("Nombre no permitido en el manifiesto: " + value);
            }
            return String.Join("/", parts);
        }

        internal static string ManifestTarget(string root, string relative)
        {
            string target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!Inside(target, root)) throw new IOException("Una entrada del manifiesto sale de la instalación: " + relative);
            NoReparsePath(target);
            return target;
        }

        internal static string ReportPath(string value, string root)
        {
            if (value == null) return null;
            string report = Absolute(value, "El informe");
            if (Same(report, root) || Inside(report, root))
                throw new IOException("Guarde el informe fuera de la carpeta que se va a desinstalar.");
            string parent = Path.GetDirectoryName(report);
            if (String.IsNullOrEmpty(parent)) throw new IOException("La carpeta del informe no es válida.");
            NoReparsePath(parent);
            return report;
        }
    }

    internal static class Hashing
    {
        internal static string FileHash(string path)
        {
            using (var algorithm = SHA256.Create())
            using (var stream = new FileStream(Safety.Extended(path), FileMode.Open, FileAccess.Read, FileShare.Read))
                return BitConverter.ToString(algorithm.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
    }

    internal static class Installation
    {
        internal const string AppId = "PDFModder.Windows.PerUser";
        internal const string Version = "1.7.0";
        internal const string MarkerName = ".pdfmodder-installation.json";
        internal const string ManifestName = ".pdfmodder-files.tsv";

        internal static InstallationPlan Load(string requestedRoot)
        {
            string root = Safety.InstallationRoot(requestedRoot);
            Safety.RejectReparseTree(root);
            string marker = Path.Combine(root, MarkerName);
            string manifest = Path.Combine(root, ManifestName);
            if (!File.Exists(Safety.Extended(marker)) || new FileInfo(Safety.Extended(marker)).Length > 32768)
                throw new IOException("No se encontró un marcador válido de PDF Modder 1.7.0.");
            if (!File.Exists(Safety.Extended(manifest)) || new FileInfo(Safety.Extended(manifest)).Length > 67108864)
                throw new IOException("No se encontró el manifiesto de archivos de PDF Modder 1.7.0.");
            Safety.NoReparsePath(marker); Safety.NoReparsePath(manifest);
            var saved = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Safety.Extended(marker), Encoding.UTF8));
            if (saved == null || !saved.ContainsKey("application_id") || !saved.ContainsKey("version") ||
                !AppId.Equals(saved["application_id"] as string) || !Version.Equals(saved["version"] as string))
                throw new IOException("La carpeta no corresponde a una instalación reconocida de PDF Modder 1.7.0.");

            var plan = new InstallationPlan
            {
                Root = root,
                MarkerPath = marker,
                ManifestPath = manifest,
                MarkerHash = Hashing.FileHash(marker),
                ManifestHash = Hashing.FileHash(manifest)
            };
            var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int lines = 0;
            using (var reader = new StreamReader(Safety.Extended(manifest), Encoding.UTF8, true))
            {
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    lines++;
                    if (lines > 200000) throw new IOException("El manifiesto contiene demasiadas entradas.");
                    string[] parts = line.Split('\t'); long size;
                    if (parts.Length != 3 || !Regex.IsMatch(parts[0], "^[0-9a-f]{64}$", RegexOptions.CultureInvariant) ||
                        !Int64.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out size) || size < 0 || size > 1073741824)
                        throw new IOException("Entrada no válida en el manifiesto, línea " + lines.ToString(CultureInfo.InvariantCulture) + ".");
                    string relative = Safety.Relative(parts[2]);
                    if (relative.Equals(MarkerName, StringComparison.OrdinalIgnoreCase) ||
                        relative.Equals(ManifestName, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("El manifiesto intenta incluir un metadato de control reservado: " + relative);
                    if (!paths.Add(relative)) throw new IOException("Ruta repetida en el manifiesto: " + relative);
                    plan.Files.Add(new ExpectedFile { Hash = parts[0], Size = size, Relative = relative,
                        FullPath = Safety.ManifestTarget(root, relative) });
                }
            }
            if (!paths.Contains("Desinstalar.exe"))
                throw new IOException("El manifiesto no incluye el desinstalador y no es seguro continuar.");
            return plan;
        }

        internal static void BlockIfApplicationRunning(string root)
        {
            string expected = Path.Combine(root, "PDFModder.exe");
            foreach (Process process in Process.GetProcessesByName("PDFModder"))
            {
                try
                {
                    string executable = process.MainModule == null ? null : process.MainModule.FileName;
                    if (String.IsNullOrEmpty(executable))
                        throw new IOException("No se puede confirmar la ubicación de un proceso PDF Modder abierto. Ciérrelo antes de continuar.");
                    if (executable != null && Safety.Same(Path.GetFullPath(executable), expected))
                        throw new IOException("Cierre PDF Modder antes de desinstalarlo.");
                }
                catch (Win32Exception ex)
                {
                    throw new IOException("No se puede comprobar un proceso PDF Modder abierto. Ciérrelo antes de continuar.", ex);
                }
                catch (InvalidOperationException) { }
                finally { process.Dispose(); }
            }
        }
    }

    internal static class ShortcutCleaner
    {
        static IEnumerable<string> ShortcutFiles(string root, bool recursive)
        {
            if (String.IsNullOrEmpty(root) || !System.IO.Directory.Exists(Safety.Extended(root))) yield break;
            var pending = new Stack<string>(); pending.Push(root);
            while (pending.Count > 0)
            {
                string directory = pending.Pop();
                foreach (string rawPath in System.IO.Directory.EnumerateFileSystemEntries(Safety.Extended(directory)))
                {
                    string path = Safety.Display(rawPath);
                    FileAttributes attributes;
                    try { attributes = File.GetAttributes(rawPath); }
                    catch { continue; }
                    if ((attributes & FileAttributes.ReparsePoint) != 0)
                    {
                        if ((attributes & FileAttributes.Directory) != 0 ||
                            !path.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase)) continue;
                        try { if (Safety.IsNameSurrogateReparsePoint(path)) continue; }
                        catch { continue; }
                    }
                    if ((attributes & FileAttributes.Directory) != 0)
                    {
                        if (recursive) pending.Push(path);
                    }
                    else if (path.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase)) yield return path;
                }
            }
        }

        internal static int Remove(string installationRoot, List<string> warnings)
        {
            string app = Path.Combine(installationRoot, "PDFModder.exe");
            string uninstall = Path.Combine(installationRoot, "Desinstalar.exe");
            int removed = 0; object shell = null;
            try
            {
                shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell", true));
                var locations = new[] {
                    new KeyValuePair<string, bool>(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), false),
                    new KeyValuePair<string, bool>(Environment.GetFolderPath(Environment.SpecialFolder.Programs), true)
                };
                foreach (var location in locations)
                    foreach (string path in ShortcutFiles(location.Key, location.Value))
                    {
                        object link = null;
                        try
                        {
                            link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
                            string target = Convert.ToString(link.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null));
                            if (!String.IsNullOrWhiteSpace(target))
                            {
                                string full = Path.GetFullPath(target);
                                if (Safety.Same(full, app) || Safety.Same(full, uninstall))
                                {
                                    File.Delete(Safety.Extended(path)); removed++;
                                }
                            }
                        }
                        catch (Exception ex) { warnings.Add("No se pudo revisar el acceso directo " + path + ": " + ex.Message); }
                        finally { if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link); }
                    }
            }
            catch (Exception ex) { warnings.Add("No se pudieron revisar los accesos directos: " + ex.Message); }
            finally { if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell); }
            return removed;
        }
    }

    internal static class RegistryCleaner
    {
        const string KeyPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFModder-1.7.0";

        internal static void Remove(string installationRoot, List<string> warnings)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(KeyPath, false))
                {
                    if (key == null) return;
                    string location = Convert.ToString(key.GetValue("InstallLocation", ""));
                    string applicationId = Convert.ToString(key.GetValue("PDFModderApplicationId", ""));
                    if (!Installation.AppId.Equals(applicationId, StringComparison.Ordinal) ||
                        String.IsNullOrWhiteSpace(location) || !Safety.Same(Path.GetFullPath(location), installationRoot))
                    {
                        warnings.Add("Se conservó la entrada de desinstalación porque pertenece a otra ubicación.");
                        return;
                    }
                }
                Registry.CurrentUser.DeleteSubKeyTree(KeyPath, false);
            }
            catch (Exception ex) { warnings.Add("No se pudo retirar la entrada de Aplicaciones instaladas: " + ex.Message); }
        }
    }

    internal static class Uninstaller
    {
        static void Remember(List<string> values, string relative)
        {
            if (values.Count < 2000) values.Add(relative);
        }

        static bool IsEmpty(string directory)
        {
            using (IEnumerator<string> items = System.IO.Directory.EnumerateFileSystemEntries(Safety.Extended(directory)).GetEnumerator())
                return !items.MoveNext();
        }

        static void RemoveEmptyDirectories(string root)
        {
            if (!System.IO.Directory.Exists(Safety.Extended(root))) return;
            var pending = new Stack<string>(); var directories = new List<string>(); pending.Push(root);
            while (pending.Count > 0)
            {
                string directory = pending.Pop(); directories.Add(directory);
                foreach (string rawPath in System.IO.Directory.EnumerateDirectories(Safety.Extended(directory)))
                {
                    string path = Safety.Display(rawPath); FileAttributes attributes = File.GetAttributes(rawPath);
                    if ((attributes & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("Apareció un enlace durante la desinstalación: " + path);
                    pending.Push(path);
                }
            }
            directories.Sort(delegate(string left, string right) { return right.Length.CompareTo(left.Length); });
            foreach (string directory in directories)
                if (System.IO.Directory.Exists(Safety.Extended(directory)) && IsEmpty(directory)) System.IO.Directory.Delete(Safety.Extended(directory), false);
        }

        static void RemoveControlFile(string path, string capturedHash, string relative, Result result)
        {
            if (!File.Exists(Safety.Extended(path))) return;
            Safety.NoReparsePath(path);
            if (!Hashing.FileHash(path).Equals(capturedHash, StringComparison.Ordinal))
            {
                result.preserved++; Remember(result.preserved_files, relative); return;
            }
            FileAttributes attributes = File.GetAttributes(Safety.Extended(path));
            if ((attributes & FileAttributes.ReadOnly) != 0) File.SetAttributes(Safety.Extended(path), attributes & ~FileAttributes.ReadOnly);
            File.Delete(Safety.Extended(path)); result.removed++; Remember(result.removed_files, relative);
        }

        static void CountRemaining(string root, HashSet<string> alreadyPreserved, Result result)
        {
            if (!System.IO.Directory.Exists(Safety.Extended(root))) return;
            var pending = new Stack<string>(); pending.Push(root);
            while (pending.Count > 0)
            {
                string directory = pending.Pop();
                foreach (string rawPath in System.IO.Directory.EnumerateFileSystemEntries(Safety.Extended(directory)))
                {
                    string path = Safety.Display(rawPath); FileAttributes attributes = File.GetAttributes(rawPath);
                    if ((attributes & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("Apareció un enlace durante la desinstalación: " + path);
                    if ((attributes & FileAttributes.Directory) != 0) pending.Push(path);
                    else
                    {
                        string relative = path.Substring(root.TrimEnd('\\').Length + 1).Replace('\\', '/');
                        if (alreadyPreserved.Add(relative))
                        {
                            result.preserved++; Remember(result.preserved_files, relative);
                        }
                    }
                }
            }
        }

        internal static Result Run(Options options, Action<int, string> progress)
        {
            var result = new Result(); var watch = Stopwatch.StartNew();
            try
            {
                InstallationPlan plan = Installation.Load(options.Directory); result.directory = plan.Root;
                Installation.BlockIfApplicationRunning(plan.Root);
                var preserved = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                int position = 0;
                // Complete the read/lock preflight before deleting anything. This
                // keeps the control records available when an application file is
                // open and lets the user close it and retry safely.
                foreach (ExpectedFile expected in plan.Files)
                {
                    position++;
                    progress(Math.Min(30, position * 30 / Math.Max(1, plan.Files.Count)), "Comprobando " + expected.Relative);
                    if (File.Exists(Safety.Extended(expected.FullPath)))
                    {
                        Safety.NoReparsePath(expected.FullPath); expected.Exists = true;
                        var information = new FileInfo(Safety.Extended(expected.FullPath));
                        expected.Matches = information.Length == expected.Size &&
                            Hashing.FileHash(expected.FullPath).Equals(expected.Hash, StringComparison.Ordinal);
                    }
                    else expected.IsDirectory = System.IO.Directory.Exists(Safety.Extended(expected.FullPath));
                }

                var removalOrder = new List<ExpectedFile>(); ExpectedFile installedUninstaller = null;
                foreach (ExpectedFile expected in plan.Files)
                    if (expected.Relative.Equals("Desinstalar.exe", StringComparison.OrdinalIgnoreCase)) installedUninstaller = expected;
                    else removalOrder.Add(expected);
                removalOrder.Add(installedUninstaller);

                position = 0;
                foreach (ExpectedFile expected in removalOrder)
                {
                    position++;
                    progress(30 + Math.Min(55, position * 55 / Math.Max(1, plan.Files.Count)), "Retirando " + expected.Relative);
                    if (!expected.Exists)
                    {
                        if (expected.IsDirectory)
                        {
                            result.preserved++; preserved.Add(expected.Relative); Remember(result.preserved_files, expected.Relative);
                        }
                        continue;
                    }
                    Safety.NoReparsePath(expected.FullPath);
                    var information = new FileInfo(Safety.Extended(expected.FullPath));
                    if (!expected.Matches || !File.Exists(Safety.Extended(expected.FullPath)) || information.Length != expected.Size ||
                        !Hashing.FileHash(expected.FullPath).Equals(expected.Hash, StringComparison.Ordinal))
                    {
                        result.preserved++; preserved.Add(expected.Relative); Remember(result.preserved_files, expected.Relative); continue;
                    }
                    FileAttributes attributes = File.GetAttributes(Safety.Extended(expected.FullPath));
                    if ((attributes & FileAttributes.ReadOnly) != 0) File.SetAttributes(Safety.Extended(expected.FullPath), attributes & ~FileAttributes.ReadOnly);
                    File.Delete(Safety.Extended(expected.FullPath)); result.removed++; Remember(result.removed_files, expected.Relative);
                }

                progress(88, "Retirando accesos directos…");
                result.shortcuts_removed = ShortcutCleaner.Remove(plan.Root, result.warnings);
                RegistryCleaner.Remove(plan.Root, result.warnings);

                // These two validated records describe the installation itself;
                // payload files above are never removed without their manifest hash.
                RemoveControlFile(plan.MarkerPath, plan.MarkerHash, Installation.MarkerName, result);
                RemoveControlFile(plan.ManifestPath, plan.ManifestHash, Installation.ManifestName, result);
                CountRemaining(plan.Root, preserved, result);
                progress(96, "Retirando carpetas vacías…");
                RemoveEmptyDirectories(plan.Root);
                result.ok = true; progress(100, "Desinstalación terminada.");
            }
            catch (Exception ex) { result.error = ex.Message; result.diagnostic = ex.ToString(); }
            finally { result.elapsed_seconds = Math.Round(watch.Elapsed.TotalSeconds, 3); }
            return result;
        }
    }

    internal static class Reports
    {
        internal static FileStream Reserve(Options options)
        {
            if (options.Report == null) return null;
            string root = Safety.InstallationRoot(options.Directory);
            string report = Safety.ReportPath(options.Report, root);
            string parent = Path.GetDirectoryName(report);
            System.IO.Directory.CreateDirectory(Safety.Extended(parent));
            Safety.NoReparsePath(parent);
            return new FileStream(Safety.Extended(report), FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        }

        internal static void Write(FileStream stream, Result result)
        {
            if (stream == null) return;
            byte[] bytes = new UTF8Encoding(false).GetBytes(new JavaScriptSerializer().Serialize(result));
            stream.Write(bytes, 0, bytes.Length); stream.Flush(true);
        }

        internal static void WriteEarlyFailure(Options options, Exception exception)
        {
            if (options == null || options.Report == null) return;
            var result = new Result
            {
                ok = false,
                directory = options.Directory,
                error = exception.Message,
                diagnostic = exception.ToString()
            };
            using (FileStream report = Reserve(options)) Write(report, result);
        }
    }

    internal static class SelfRelaunch
    {
        const int MoveFileDelayUntilReboot = 0x4;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool MoveFileEx(string existingName, string newName, int flags);

        static string Quote(string value)
        {
            var output = new StringBuilder(); output.Append('"'); int slashes = 0;
            foreach (char character in value)
            {
                if (character == '\\') { slashes++; continue; }
                if (character == '"')
                {
                    output.Append('\\', slashes * 2 + 1); output.Append('"'); slashes = 0; continue;
                }
                output.Append('\\', slashes); slashes = 0; output.Append(character);
            }
            output.Append('\\', slashes * 2); output.Append('"'); return output.ToString();
        }

        internal static void Start(Options options)
        {
            string root = Safety.InstallationRoot(options.Directory);
            Installation.Load(root);
            options.Directory = root;
            options.Report = Safety.ReportPath(options.Report, root);
            string temporaryParent = Path.GetFullPath(Path.GetTempPath()).TrimEnd('\\');
            Safety.NoReparsePath(temporaryParent);
            string temporary = Path.Combine(temporaryParent, "PDFModder-uninstall-" + Guid.NewGuid().ToString("N"));
            System.IO.Directory.CreateDirectory(temporary); Safety.NoReparsePath(temporary);
            string copy = Path.Combine(temporary, "Desinstalar.exe");
            try
            {
                File.Copy(Application.ExecutablePath, copy, false);
                using (Process current = Process.GetCurrentProcess())
                {
                    var arguments = new List<string> { "--pdfmodder-worker", "--parent-pid", current.Id.ToString(CultureInfo.InvariantCulture),
                        "--parent-start", current.StartTime.ToUniversalTime().Ticks.ToString(CultureInfo.InvariantCulture), "--dir", root };
                    if (options.Silent) arguments.Add("--silent");
                    if (options.Report != null) { arguments.Add("--report"); arguments.Add(options.Report); }
                    var commandLine = new StringBuilder();
                    foreach (string argument in arguments)
                    {
                        if (commandLine.Length > 0) commandLine.Append(' ');
                        commandLine.Append(Quote(argument));
                    }
                    Process.Start(new ProcessStartInfo(copy, commandLine.ToString()) { UseShellExecute = false, WorkingDirectory = temporary });
                }
            }
            catch
            {
                try { if (File.Exists(copy)) File.Delete(copy); if (System.IO.Directory.Exists(temporary) && System.IO.Directory.GetFileSystemEntries(temporary).Length == 0) System.IO.Directory.Delete(temporary); }
                catch { }
                throw;
            }
        }

        internal static void ValidateWorkerLocation()
        {
            string directory = Path.GetDirectoryName(Application.ExecutablePath);
            string name = Path.GetFileName(directory);
            if (!Regex.IsMatch(name ?? "", "^PDFModder-uninstall-[0-9a-f]{32}$", RegexOptions.CultureInvariant) ||
                !Safety.Same(Path.GetDirectoryName(directory), Path.GetFullPath(Path.GetTempPath()).TrimEnd('\\')))
                throw new IOException("El proceso temporal de desinstalación no procede de una ubicación válida.");
            Safety.NoReparsePath(directory);
        }

        internal static void WaitForParent(Options options)
        {
            try
            {
                using (Process parent = Process.GetProcessById(options.ParentPid))
                {
                    if (parent.StartTime.ToUniversalTime().Ticks == options.ParentStartedUtcTicks) parent.WaitForExit();
                }
            }
            catch (ArgumentException) { }
            catch (InvalidOperationException) { }
        }

        internal static void ScheduleTemporaryCleanup()
        {
            string executable = Application.ExecutablePath;
            string directory = Path.GetDirectoryName(executable);
            MoveFileEx(executable, null, MoveFileDelayUntilReboot);
            MoveFileEx(directory, null, MoveFileDelayUntilReboot);
        }
    }

    internal sealed class UninstallWindow : Form
    {
        readonly Button uninstallButton = new Button { Text = "Desinstalar", AutoSize = true, Name = "uninstallButton" };
        readonly Button closeButton = new Button { Text = "Cancelar", AutoSize = true, Name = "closeButton" };
        readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Fill };
        readonly TextBox status = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None,
            BackColor = SystemColors.Control, ScrollBars = ScrollBars.Vertical, Name = "uninstallationStatus" };
        readonly Options options;
        bool busy;

        internal UninstallWindow(Options initial)
        {
            options = initial; Text = "Desinstalar PDF Modder 1.7.0"; Font = new Font("Segoe UI", 10F);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            AutoScaleMode = AutoScaleMode.Dpi; StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(680, 390); MinimumSize = new Size(620, 420); MaximizeBox = false;
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, RowCount = 8 };
            for (int i = 0; i < 8; i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles[5] = new RowStyle(SizeType.Percent, 100);
            layout.Controls.Add(new Label { Text = "PDF Modder 1.7.0", AutoSize = true, Font = new Font("Segoe UI", 19F, FontStyle.Bold), Margin = new Padding(0, 0, 0, 12) }, 0, 0);
            layout.Controls.Add(new Label { Text = "Se eliminarán únicamente los archivos instalados que no hayan sido modificados.", AutoSize = true }, 0, 1);
            layout.Controls.Add(new Label { Text = "Se conservarán los PDF, otros archivos personales y los ajustes de fuentes.", AutoSize = true, Margin = new Padding(0, 0, 0, 12) }, 0, 2);
            layout.Controls.Add(new Label { Text = "Carpeta: " + options.Directory, AutoSize = true, MaximumSize = new Size(620, 0) }, 0, 3);
            layout.Controls.Add(progress, 0, 4); layout.Controls.Add(status, 0, 5);
            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
            buttons.Controls.Add(closeButton); buttons.Controls.Add(uninstallButton); layout.Controls.Add(buttons, 0, 6);
            Controls.Add(layout); AcceptButton = uninstallButton; CancelButton = closeButton;
            status.Text = "Cierre PDF Modder antes de continuar.";
            closeButton.Click += delegate { Close(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) e.Cancel = true; };
            uninstallButton.Click += StartUninstall;
        }

        void StartUninstall(object sender, EventArgs e)
        {
            if (busy) return;
            if (MessageBox.Show(this, "¿Desea desinstalar PDF Modder 1.7.0?", "Confirmar desinstalación",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            busy = true; uninstallButton.Enabled = closeButton.Enabled = false; status.Text = "Preparando la desinstalación…";
            var worker = new BackgroundWorker { WorkerReportsProgress = true };
            worker.DoWork += delegate(object s, DoWorkEventArgs args)
            {
                using (FileStream report = Reports.Reserve(options))
                {
                    Result result = Uninstaller.Run(options, delegate(int percent, string message) { worker.ReportProgress(percent, message); });
                    Reports.Write(report, result); args.Result = result;
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
                    status.Text = "Desinstalación terminada. Archivos eliminados: " + result.removed + ".";
                    if (result.preserved > 0) status.Text += "\r\nArchivos conservados: " + result.preserved + ".";
                    if (result.warnings.Count > 0) status.Text += "\r\n" + String.Join("\r\n", result.warnings);
                    uninstallButton.Text = "Desinstalado";
                }
                else
                {
                    status.ForeColor = Color.Firebrick;
                    status.Text = "No se ha completado la desinstalación. " + (result == null ? "Error desconocido." : result.error);
                    uninstallButton.Enabled = true;
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
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
            bool silent = Array.IndexOf(args, "--silent") >= 0;
            bool worker = Array.IndexOf(args, "--pdfmodder-worker") >= 0;
            bool cleanupTemporary = false;
            Options parsedOptions = null;
            try
            {
                Options options = Options.Parse(args); parsedOptions = options;
                if (!options.Worker)
                {
                    SelfRelaunch.Start(options); return 0;
                }
                SelfRelaunch.ValidateWorkerLocation(); cleanupTemporary = true; SelfRelaunch.WaitForParent(options);
                options.Directory = Safety.InstallationRoot(options.Directory);
                options.Report = Safety.ReportPath(options.Report, options.Directory);
                if (options.Silent)
                {
                    Result result;
                    using (FileStream report = Reports.Reserve(options))
                    {
                        result = Uninstaller.Run(options, delegate { }); Reports.Write(report, result);
                    }
                    return result.ok ? 0 : 1;
                }
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new UninstallWindow(options)); return 0;
            }
            catch (Exception ex)
            {
                try { Reports.WriteEarlyFailure(parsedOptions, ex); }
                catch { }
                if (!silent) MessageBox.Show("No se ha completado la desinstalación.\n" + ex.Message,
                    "PDF Modder 1.7.0", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            finally
            {
                if (cleanupTemporary) SelfRelaunch.ScheduleTemporaryCleanup();
            }
        }
    }
}
