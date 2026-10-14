using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;
using System.Linq;

class InstallFirewallHelper {
 static string Resource(string name){using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))using(var reader=new StreamReader(stream))return reader.ReadToEnd();}
 [STAThread] static int Main(string[] args){
  try{
   if(args.Any(argument=>argument!="--uninstall"&&argument!="--allow-running-game"))throw new Exception("Unknown argument.");
   bool remove=args.Contains("--uninstall");
   string dir=AppDomain.CurrentDomain.BaseDirectory;
   string expected="";
   if(!remove){
    expected=Resource("FirewallHash").Trim();string actual;
    using(var hash=SHA256.Create())using(var file=File.OpenRead(Path.Combine(dir,"bin","OverlayRaceFirewall.exe")))actual=BitConverter.ToString(hash.ComputeHash(file)).Replace("-","").ToLowerInvariant();
    if(actual!=expected)throw new Exception("Helper differs from the reviewed package; installation refused.");
   }
   string script=Resource(remove?"Uninstall":"Install");
   script=script.Replace("$PSScriptRoot","'"+dir.TrimEnd('\\').Replace("'","''")+"'");
   string command="& {\n"+script+"\n}"+(!remove?" -ExpectedHelperHash "+expected:"")+(!remove&&args.Contains("--allow-running-game")?" -PermitRunningGame":"");
   string encoded=Convert.ToBase64String(Encoding.Unicode.GetBytes(command));
   string shell=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe");
   using(var process=Process.Start(new ProcessStartInfo{FileName=shell,Arguments="-NoLogo -NoProfile -NonInteractive -EncodedCommand "+encoded,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardOutput=true,RedirectStandardError=true})){
    string output=process.StandardOutput.ReadToEnd(),error=process.StandardError.ReadToEnd();process.WaitForExit();
    if(process.ExitCode!=0)throw new Exception(error+output);
    Debug.WriteLine(output); // Successful provisioning has no extra popup/console.
   }
   return 0;
  }catch(Exception error){MessageBox.Show(error.Message,"OverlayApp - installation incomplete",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
 }
}
