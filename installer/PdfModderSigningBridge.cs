// Local Windows certificate bridge. Only public certificates and signatures
// cross stdout. Private keys stay with their Windows CryptoAPI/CNG provider.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

internal static class PdfModderSigningBridge
{
    private const string Algorithm = "rsa_pkcs1_sha256";
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 4194304 };

    [STAThread]
    private static int Main(string[] args)
    {
        Console.InputEncoding = new UTF8Encoding(false, true);
        Console.OutputEncoding = new UTF8Encoding(false);
        try
        {
            object result;
            if (args.Length == 1 && args[0] == "--self-test") result = SelfTest();
            else
            {
                if (args.Length != 0) throw new ArgumentException("Opción del puente de firma no reconocida.");
                var request = ReadRequest();
                string command = Required(request, "command");
                if (command == "list") result = ListCertificates();
                else if (command == "sign") result = Sign(request);
                else throw new ArgumentException("Operación del puente de firma no reconocida.");
            }
            Console.WriteLine(Json.Serialize(result));
            return 0;
        }
        catch (ArgumentException exc) { return Error(exc.Message); }
        catch (UnauthorizedAccessException) { return Error("Windows no permite acceder a la clave del certificado seleccionado."); }
        catch (CryptographicException) { return Error("El proveedor de Windows no pudo firmar. Comprueba el certificado, su dispositivo y el PIN; la operación también puede haberse cancelado."); }
        catch (Exception) { return Error("No se pudo completar la operación con el almacén de certificados de Windows."); }
    }

    private static int Error(string message)
    {
        Console.WriteLine(Json.Serialize(new { ok = false, error = message }));
        return 1;
    }

    private static Dictionary<string, object> ReadRequest()
    {
        var input = new StringBuilder();
        var buffer = new char[1024];
        int count;
        while ((count = Console.In.Read(buffer, 0, buffer.Length)) > 0)
        {
            input.Append(buffer, 0, count);
            if (input.Length > 16384) throw new ArgumentException("La solicitud de firma supera el tamaño permitido.");
        }
        try
        {
            // Python's utf-8-sig transport may prefix a BOM on stdin.
            var request = Json.Deserialize<Dictionary<string, object>>(input.ToString().TrimStart('\uFEFF'));
            if (request == null) throw new ArgumentException();
            return request;
        }
        catch { throw new ArgumentException("La solicitud de firma no es un objeto JSON válido."); }
    }

    private static string Required(Dictionary<string, object> request, string name)
    {
        object value;
        if (!request.TryGetValue(name, out value) || !(value is string) || String.IsNullOrWhiteSpace((string)value))
            throw new ArgumentException("La solicitud de firma está incompleta.");
        return (string)value;
    }

    private static bool Suitable(X509Certificate2 certificate)
    {
        DateTime now = DateTime.UtcNow;
        if (!certificate.HasPrivateKey || certificate.NotBefore.ToUniversalTime() > now ||
            certificate.NotAfter.ToUniversalTime() <= now || certificate.GetKeyAlgorithm() != "1.2.840.113549.1.1.1") return false;
        foreach (X509Extension extension in certificate.Extensions)
        {
            if (extension.Oid.Value == "2.5.29.15")
            {
                var usage = new X509KeyUsageExtension(extension, extension.Critical);
                if ((usage.KeyUsages & (X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.NonRepudiation)) == 0) return false;
            }
            if (extension.Oid.Value == "2.5.29.19" && new X509BasicConstraintsExtension(extension, extension.Critical).CertificateAuthority)
                return false;
        }
        return true;
    }

    private static object ListCertificates()
    {
        var result = new List<object>();
        var warnings = new List<string>();
        foreach (StoreLocation location in new[] { StoreLocation.CurrentUser, StoreLocation.LocalMachine })
        {
            try
            {
                using (var store = new X509Store(StoreName.My, location))
                {
                    store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
                    foreach (X509Certificate2 certificate in store.Certificates)
                    using (certificate)
                    {
                        try
                        {
                            if (!Suitable(certificate)) continue;
                            result.Add(new { thumbprint = certificate.Thumbprint.ToUpperInvariant(), store = location.ToString(),
                                subject = certificate.Subject, issuer = certificate.Issuer,
                                not_before = certificate.NotBefore.ToUniversalTime().ToString("o", CultureInfo.InvariantCulture),
                                not_after = certificate.NotAfter.ToUniversalTime().ToString("o", CultureInfo.InvariantCulture),
                                certificate_der_base64 = Convert.ToBase64String(certificate.RawData),
                                algorithm = Algorithm, has_private_key = true });
                        }
                        catch (CryptographicException) { warnings.Add("Se omitió un certificado que Windows no pudo consultar."); }
                    }
                }
            }
            catch (CryptographicException) { warnings.Add("No se pudo leer el almacén " + location.ToString() + "."); }
            catch (UnauthorizedAccessException) { warnings.Add("Sin permiso de lectura para el almacén " + location.ToString() + "."); }
        }
        return new { ok = true, certificates = result, warnings = warnings };
    }

    private static object Sign(Dictionary<string, object> request)
    {
        string thumbprint = Required(request, "thumbprint").ToUpperInvariant();
        if (!Regex.IsMatch(thumbprint, "\\A[0-9A-F]{40}\\z")) throw new ArgumentException("La huella del certificado no es válida.");
        string storeName = Required(request, "store");
        StoreLocation location;
        if (storeName == "CurrentUser") location = StoreLocation.CurrentUser;
        else if (storeName == "LocalMachine") location = StoreLocation.LocalMachine;
        else throw new ArgumentException("Selecciona un almacén personal válido de Windows.");
        if (Required(request, "algorithm") != Algorithm) throw new ArgumentException("Este puente admite certificados RSA con SHA-256.");
        byte[] digest;
        try { digest = Convert.FromBase64String(Required(request, "digest_base64")); }
        catch (FormatException) { throw new ArgumentException("El resumen SHA-256 no tiene una codificación válida."); }
        if (digest.Length != 32) throw new ArgumentException("El resumen para firmar debe tener 32 bytes SHA-256.");
        using (var store = new X509Store(StoreName.My, location))
        {
            store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
            foreach (X509Certificate2 certificate in store.Certificates)
            using (certificate)
            {
                if (!String.Equals(certificate.Thumbprint, thumbprint, StringComparison.OrdinalIgnoreCase)) continue;
                if (!Suitable(certificate)) throw new ArgumentException("El certificado seleccionado no está vigente, no tiene clave privada o no permite firma RSA de documentos.");
                using (RSA key = certificate.GetRSAPrivateKey())
                {
                    if (key == null) throw new ArgumentException("Windows no proporciona la clave privada del certificado seleccionado.");
                    // The provider may show its own consent or PIN prompt here.
                    byte[] signature = key.SignHash(digest, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                    using (RSA publicKey = certificate.GetRSAPublicKey())
                        if (publicKey == null || !publicKey.VerifyHash(digest, signature, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1))
                            throw new CryptographicException();
                    return new { ok = true, signature_base64 = Convert.ToBase64String(signature),
                        certificate_der_base64 = Convert.ToBase64String(certificate.RawData) };
                }
            }
        }
        throw new ArgumentException("El certificado elegido ya no está disponible en ese almacén de Windows.");
    }

    // Explicit developer self-test only: an untrusted leaf, generated key and
    // random name. Never touches Root or any existing certificate/private key.
    private static object SelfTest()
    {
        string name = "PDFModder-Prueba-" + Guid.NewGuid().ToString("N");
        CngKey key = null;
        X509Certificate2 certificate = null;
        bool added = false, removed = false, deleted = false;
        object signature = null;
        try
        {
            var options = new CngKeyCreationParameters { Provider = CngProvider.MicrosoftSoftwareKeyStorageProvider,
                KeyUsage = CngKeyUsages.Signing, ExportPolicy = CngExportPolicies.None };
            options.Parameters.Add(new CngProperty("Length", BitConverter.GetBytes(2048), CngPropertyOptions.None));
            key = CngKey.Create(CngAlgorithm.Rsa, name, options);
            using (var rsa = new RSACng(key))
            {
                var request = new CertificateRequest("CN=" + name, rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
                request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature, true));
                certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-1), DateTimeOffset.UtcNow.AddMinutes(5));
            }
            using (var store = new X509Store(StoreName.My, StoreLocation.CurrentUser))
            {
                store.Open(OpenFlags.ReadWrite | OpenFlags.OpenExistingOnly);
                store.Add(certificate);
                added = true;
            }
            byte[] digest;
            using (var sha = SHA256.Create()) digest = sha.ComputeHash(Encoding.UTF8.GetBytes("PDFModder prueba local v1.6.0"));
            signature = Sign(new Dictionary<string, object> { { "thumbprint", certificate.Thumbprint },
                { "store", "CurrentUser" }, { "algorithm", Algorithm }, { "digest_base64", Convert.ToBase64String(digest) } });
            // Return only generated PUBLIC evidence for an independent verifier.
            return new { ok = true, synthetic = true, digest_base64 = Convert.ToBase64String(digest),
                result = signature, cleanup_completed = true };
        }
        finally
        {
            try
            {
                if (added)
                    using (var store = new X509Store(StoreName.My, StoreLocation.CurrentUser))
                    {
                        store.Open(OpenFlags.ReadWrite | OpenFlags.OpenExistingOnly);
                        store.Remove(certificate);
                        removed = store.Certificates.Find(X509FindType.FindByThumbprint, certificate.Thumbprint, false).Count == 0;
                    }
            }
            finally
            {
                if (certificate != null) certificate.Dispose();
                if (key != null) { key.Delete(); key.Dispose(); deleted = !CngKey.Exists(name, CngProvider.MicrosoftSoftwareKeyStorageProvider); }
            }
            if (added && !removed || key != null && !deleted) throw new CryptographicException();
        }
    }
}
