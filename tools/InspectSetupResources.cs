// Metadata/resource inspection only; never invokes a target assembly entry point.
using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
class InspectSetupResources {
 static int Main(string[] args){
  if(args.Length!=1)return 2;
  var assembly=Assembly.LoadFile(Path.GetFullPath(args[0]));
  using(var hash=SHA256.Create())foreach(string name in new[]{"Setup","Firewall","Elevation"}){
   using(var stream=assembly.GetManifestResourceStream(name))using(var memory=new MemoryStream()){
    stream.CopyTo(memory);Console.WriteLine(name+":"+BitConverter.ToString(hash.ComputeHash(memory.ToArray())).Replace("-","").ToLowerInvariant());
   }
  }
  return 0;
 }
}
