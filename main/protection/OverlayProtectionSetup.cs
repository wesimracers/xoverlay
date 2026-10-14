// All privileged actions are fixed, embedded and entered through personal UAC.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
[assembly: AssemblyTitle("OverlayApp Protection Setup")]
[assembly: AssemblyProduct("OverlayApp Protection Setup")]
[DataContract] class SetupResult {
 [DataMember] public string Id;
 [DataMember] public int ExitCode;
 [DataMember] public string Message;
}
class OverlayProtectionSetup {
 static byte[] Resource(string name){using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))using(var memory=new MemoryStream()){stream.CopyTo(memory);return memory.ToArray();}}
 static string Hash(byte[] bytes){using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();}
 static void DirectoryForSetup(string path){
  if(Directory.Exists(path)&&(File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)throw new Exception("A setup directory is a reparse point; setup refused.");
  if(Directory.Exists(path)){
   var existing=Directory.GetAccessControl(path);string owner=((SecurityIdentifier)existing.GetOwner(typeof(SecurityIdentifier))).Value;
   if(owner!="S-1-5-18"&&owner!="S-1-5-32-544")throw new Exception("An existing setup folder has an untrusted owner; preserved for review.");
   var writes=FileSystemRights.Write|FileSystemRights.Delete|FileSystemRights.DeleteSubdirectoriesAndFiles|FileSystemRights.ChangePermissions|FileSystemRights.TakeOwnership;
   foreach(FileSystemAccessRule rule in existing.GetAccessRules(true,true,typeof(SecurityIdentifier))){string sid=rule.IdentityReference.Value;if(rule.AccessControlType==AccessControlType.Allow&&(rule.FileSystemRights&writes)!=0&&sid!="S-1-5-18"&&sid!="S-1-5-32-544")throw new Exception("An existing setup folder allows untrusted writes; setup refused.");}
  }
  Directory.CreateDirectory(path);var acl=new DirectorySecurity();acl.SetAccessRuleProtection(true,false);
  acl.SetOwner(new SecurityIdentifier("S-1-5-32-544"));
  foreach(string sid in new[]{"S-1-5-18","S-1-5-32-544","S-1-5-11"})acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid),sid=="S-1-5-11"?FileSystemRights.ReadAndExecute:FileSystemRights.FullControl,InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit,PropagationFlags.None,AccessControlType.Allow));
  Directory.SetAccessControl(path,acl);
 }
 [STAThread] static int Main(string[] args){
  string id="";string results=null;int exit=1;string message="Setup failed.";
  try{
   if(!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))throw new Exception("Personal administrative approval was not confirmed.");
   string sid="";bool firewall=false,elevation=false,remove=false;
   foreach(string arg in args){if(arg.StartsWith("--user-sid:"))sid=arg.Substring(11);else if(arg.StartsWith("--request-id:"))id=arg.Substring(13);else if(arg=="--firewall")firewall=true;else if(arg=="--elevation")elevation=true;else if(arg=="--remove")remove=true;else throw new Exception("Unknown setup argument.");}
   Guid request;if(!Guid.TryParse(id,out request)||!Regex.IsMatch(sid,"^S-1-(5-21|12-1)-[0-9-]+$")||(!firewall&&!elevation))throw new Exception("Invalid requesting account or setup request.");
   string state=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"OverlayProtectionSetup");DirectoryForSetup(state);results=Path.Combine(state,id+".json");
   using(var mutex=new Mutex(false,"Global\\OverlayProtectionInstaller")){
    bool owned=false;try{owned=mutex.WaitOne(0);}catch(AbandonedMutexException){owned=true;}
    if(!owned)throw new Exception("Another administrative setup is running; retry after it finishes.");
    try{
     string root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"OverlayProtectionSetup");DirectoryForSetup(root);
     byte[] firewallBytes=Resource("Firewall"),elevationBytes=Resource("Elevation");string firewallHash=Hash(firewallBytes),elevationHash=Hash(elevationBytes);
     string package=Path.Combine(root,Hash(firewallBytes.Concat(elevationBytes).ToArray()));DirectoryForSetup(package);
     foreach(var entry in new[]{Tuple.Create("OverlayRaceFirewall.exe",firewallBytes),Tuple.Create("OverlayElevationGate.exe",elevationBytes)}){
      string path=Path.Combine(package,entry.Item1);if(File.Exists(path)&&(File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)throw new Exception("A package file is a reparse point; setup refused.");
      File.WriteAllBytes(path,entry.Item2);if(Hash(File.ReadAllBytes(path))!=Hash(entry.Item2))throw new Exception("Protected embedded payload verification failed.");
     }
     string script=Encoding.UTF8.GetString(Resource("Setup"));
     string command="& {\n"+script+"\n} -PackageRoot '"+package.Replace("'","''")+"' -UserSid "+sid+" -FirewallHash "+firewallHash+" -ElevationHash "+elevationHash+(firewall?" -Firewall":"")+(elevation?" -Elevation":"")+(remove?" -Remove":"");
     string arguments="-NoLogo -NoProfile -NonInteractive -EncodedCommand "+Convert.ToBase64String(Encoding.Unicode.GetBytes(command));
     if(arguments.Length>32000)throw new Exception("Embedded setup exceeds the Windows command length limit.");
     using(var process=Process.Start(new ProcessStartInfo{FileName=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell\\v1.0\\powershell.exe"),Arguments=arguments,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardOutput=true,RedirectStandardError=true})){
      var output=process.StandardOutput.ReadToEndAsync();var error=process.StandardError.ReadToEndAsync();process.WaitForExit();Task.WaitAll(output,error);exit=process.ExitCode;message=exit==0?(remove?"Helpers removed; audit files retained.":"Helpers provisioned; runtime protection still requires confirmation."):"Setup failed; see the protected setup log.";
      File.WriteAllText(Path.Combine(state,id+".log"),output.Result+Environment.NewLine+error.Result,Encoding.UTF8);
     }
    }finally{mutex.ReleaseMutex();}
   }
  }catch(Exception error){message="Administrative setup failed; see the protected setup log or retry from Protection Config.";exit=1;if(results!=null)try{File.WriteAllText(Path.ChangeExtension(results,".log"),error.ToString(),Encoding.UTF8);}catch{}}
  if(results!=null)try{using(var stream=File.Create(results))new DataContractJsonSerializer(typeof(SetupResult)).WriteObject(stream,new SetupResult{Id=id,ExitCode=exit,Message=message});}catch{return 1;}
  return exit;
 }
}
