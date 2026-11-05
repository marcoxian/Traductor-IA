using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using BepInEx;

namespace AutoProxyLauncher
{
    [BepInPlugin("com.traductoria.autoproxy", "Traductor IA Auto Proxy", "1.0.0")]
    public class AutoProxyPlugin : BaseUnityPlugin
    {
        private static Process proxyProcess = null;

        void Awake()
        {
            DontDestroyOnLoad(this.gameObject);
            Logger.LogInfo("[Traductor IA] Verificando servidor proxy de traduccion...");
            EnsureProxyRunning();
        }

        private void EnsureProxyRunning()
        {
            if (IsProxyAlive())
            {
                Logger.LogInfo("[Traductor IA] El servidor proxy ya esta activo en http://127.0.0.1:11435/translate");
                return;
            }

            Logger.LogInfo("[Traductor IA] Proxy no detectado. Iniciando servidor en segundo plano automaticamente...");

            // Carpeta del Traductor IA: la escribe el instalador (traductor/motores/unity.py) en
            // traductor_ia_ruta.txt, junto a esta DLL; si no, la variable de entorno TRADUCTOR_IA_RUTA.
            string rootDir = null;
            try
            {
                string ficheroRuta = Path.Combine(Path.GetDirectoryName(typeof(AutoProxyPlugin).Assembly.Location), "traductor_ia_ruta.txt");
                if (File.Exists(ficheroRuta))
                {
                    rootDir = File.ReadAllText(ficheroRuta).Trim();
                }
            }
            catch (Exception) { }
            if (string.IsNullOrEmpty(rootDir))
            {
                rootDir = Environment.GetEnvironmentVariable("TRADUCTOR_IA_RUTA");
            }
            if (string.IsNullOrEmpty(rootDir) || !Directory.Exists(rootDir))
            {
                Logger.LogError("[Traductor IA] No se sabe donde esta el Traductor IA: falta traductor_ia_ruta.txt junto al plugin.");
                return;
            }
            string pythonExe = Path.Combine(rootDir, @"venv_traductor\Scripts\pythonw.exe");
            if (!File.Exists(pythonExe))
            {
                pythonExe = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                         @"Programs\Python\Python310\pythonw.exe");
            }
            if (!File.Exists(pythonExe))
            {
                pythonExe = "pythonw.exe";
            }

            string script = Path.Combine(rootDir, "ollama_proxy.py");
            string gameName = Path.GetFileName(Directory.GetCurrentDirectory()).ToLower().Replace(" ", "_");

            int currentPid = Process.GetCurrentProcess().Id;
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonExe;
            psi.Arguments = "\"" + script + "\" --juego " + gameName + " --puerto 11435 --pid " + currentPid;
            psi.WorkingDirectory = rootDir;
            psi.CreateNoWindow = true;
            psi.UseShellExecute = false;
            psi.WindowStyle = ProcessWindowStyle.Hidden;

            try
            {
                proxyProcess = Process.Start(psi);
                Logger.LogInfo("[Traductor IA] Proceso lanzado en segundo plano (PID: " + proxyProcess.Id + "). Esperando conexion...");

                for (int i = 0; i < 24; i++)
                {
                    Thread.Sleep(250);
                    if (IsProxyAlive())
                    {
                        Logger.LogInfo("[Traductor IA] Servidor proxy conectado con exito. Traduccion lista.");
                        return;
                    }
                }
                Logger.LogWarning("[Traductor IA] El servidor tardo en responder; AutoTranslator reintentara al conectar.");
            }
            catch (Exception ex)
            {
                Logger.LogError("[Traductor IA] Error al iniciar proxy automaticamente: " + ex.Message);
            }
        }

        private bool IsProxyAlive()
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:11435/health");
                req.Timeout = 1000;
                req.Method = "GET";
                using (HttpWebResponse res = (HttpWebResponse)req.GetResponse())
                {
                    return res.StatusCode == HttpStatusCode.OK;
                }
            }
            catch
            {
                return false;
            }
        }

        void OnApplicationQuit()
        {
            KillProxy();
        }

        private void KillProxy()
        {
            if (proxyProcess != null && !proxyProcess.HasExited)
            {
                try
                {
                    proxyProcess.Kill();
                    Logger.LogInfo("[Traductor IA] Servidor proxy finalizado al cerrar el juego.");
                }
                catch { }
                finally
                {
                    proxyProcess = null;
                }
            }
        }
    }
}
