using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
class InstallElevationGate {
 static string Resource(string name){using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))using(var reader=new StreamReader(stream))return reader.ReadToEnd();}
 static int Main(string[] args){
  string directory=AppDomain.CurrentDomain.BaseDirectory;
  try{
   if(args.Any(value=>value!="--uninstall"&&value!="--allow-live-provisioning"))throw new Exception("Unknown argument.");
   string expected=Resource("GateHash").Trim();bool uninstall=args.Contains("--uninstall");
   if(!uninstall){string actual;using(var hash=SHA256.Create())using(var file=File.OpenRead(Path.Combine(directory,"bin","OverlayElevationGate.exe")))actual=BitConverter.ToString(hash.ComputeHash(file)).Replace("-","").ToLowerInvariant();if(actual!=expected)throw new Exception("Helper differs from the reviewed package.");}
   string script=Resource("Install").Replace("$PSScriptRoot","'"+directory.TrimEnd('\\').Replace("'","''")+"'");
   string command="& {\n"+script+"\n} -ExpectedHelperHash "+expected+(uninstall?" -Uninstall":"")+(args.Contains("--allow-live-provisioning")?" -AllowLiveProvisioning":"");
   string shell=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe");
   using(var process=Process.Start(new ProcessStartInfo{FileName=shell,Arguments="-NoLogo -NoProfile -NonInteractive -EncodedCommand "+Convert.ToBase64String(Encoding.Unicode.GetBytes(command)),UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardOutput=true,RedirectStandardError=true})){
    var output=process.StandardOutput.ReadToEndAsync();var error=process.StandardError.ReadToEndAsync();process.WaitForExit();
    File.WriteAllText(Path.Combine(directory,"ElevationGate-install-result.txt"),output.Result+error.Result,Encoding.UTF8);
    return process.ExitCode;
   }
  }catch(Exception error){try{File.WriteAllText(Path.Combine(directory,"ElevationGate-install-result.txt"),error.ToString(),Encoding.UTF8);}catch{}return 1;}
 }
}
