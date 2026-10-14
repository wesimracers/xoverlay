using System;
using System.Runtime.Serialization;
using System.Security;
using Microsoft.Win32;

[DataContract] public class ToastSnapshot {
 [DataMember] public bool KeyExists;
 [DataMember] public bool ValueExists;
 [DataMember] public int Value;
 [DataMember] public bool EmptyKey;
}
[DataContract] public class ToastChange {
 [DataMember] public ToastSnapshot Original;
 [DataMember] public bool Touched;
}
public class ToastResult {
 public string Status="waiting for game";
 public bool Configured;
 public bool RestorationPending;
 public bool AccessDenied;
}
public interface ToastBackend {
 ToastSnapshot Read(); void ProbeWriteAccess(); void Apply(); void Restore(ToastSnapshot original);
 bool Matches(ToastSnapshot original); bool CanRestore(ToastSnapshot original);
}
public sealed class RegistryToastBackend : ToastBackend {
 public const string Key="Software\\Policies\\Microsoft\\Windows\\CurrentVersion\\PushNotifications";
 public const string ValueName="NoToastApplicationNotification";
 readonly RegistryKey hive;
 public RegistryToastBackend(RegistryKey root){if(root==null)throw new InvalidOperationException("User profile is not loaded.");hive=root;}
 public ToastSnapshot Read(){
  using(var key=hive.OpenSubKey(Key)){
   var snapshot=new ToastSnapshot{KeyExists=key!=null};
   if(key!=null){
    snapshot.EmptyKey=key.ValueCount==0&&key.SubKeyCount==0;
    snapshot.ValueExists=Array.Exists(key.GetValueNames(),name=>name.Equals(ValueName,StringComparison.OrdinalIgnoreCase));
    if(snapshot.ValueExists){if(key.GetValueKind(ValueName)!=RegistryValueKind.DWord)throw new InvalidOperationException("Existing policy is not a DWORD; preserved.");snapshot.Value=(int)key.GetValue(ValueName);}
   }
   return snapshot;
  }
 }
 public void ProbeWriteAccess(){
  // Open the nearest existing ancestor writable, without creating a key/value.
  string path=Key;
  while(path.Length>0){using(var key=hive.OpenSubKey(path,true)){if(key!=null)return;}int slash=path.LastIndexOf('\\');path=slash<0?"":path.Substring(0,slash);}
  throw new UnauthorizedAccessException("No writable ancestor key was confirmed.");
 }
 public void Apply(){using(var key=hive.CreateSubKey(Key))key.SetValue(ValueName,1,RegistryValueKind.DWord);}
 public bool Matches(ToastSnapshot original){
  var current=Read();
  if(original.ValueExists!=current.ValueExists||(original.ValueExists&&original.Value!=current.Value))return false;
  // Preserve unrelated values/subkeys added externally. A new empty key is our partial mutation.
  return original.KeyExists==current.KeyExists||(!original.KeyExists&&current.KeyExists&&!current.EmptyKey);
 }
 public bool CanRestore(ToastSnapshot original){var current=Read();return (current.ValueExists&&current.Value==1)||(!original.KeyExists&&current.KeyExists&&current.EmptyKey);}
 public void Restore(ToastSnapshot original){
  using(var key=hive.OpenSubKey(Key,true)){
   if(key!=null){if(original.ValueExists)key.SetValue(ValueName,original.Value,RegistryValueKind.DWord);else key.DeleteValue(ValueName,false);}
  }
  if(!original.KeyExists){using(var key=hive.OpenSubKey(Key)){if(key!=null&&key.ValueCount==0&&key.SubKeyCount==0){key.Close();hive.DeleteSubKey(Key,false);}}}
 }
}
public static class ToastTransaction {
 public static bool Restore(ToastChange change,ToastBackend backend,Action save,Action<string> log){
  if(!change.Touched)return true;
  try{
   if(backend.Matches(change.Original)){change.Touched=false;save();return true;}
   if(backend.CanRestore(change.Original)){
    backend.Restore(change.Original);
    if(!backend.Matches(change.Original))throw new InvalidOperationException("Toast restoration not confirmed.");
   }else log("TOASTS external change preserved.");
   change.Touched=false;save();return true;
  }catch(Exception error){log("TOAST RESTORE ERROR: "+error.Message);return false;}
 }
 public static ToastResult Apply(ToastChange change,ToastBackend backend,Action save,Action<string> log){
  var result=new ToastResult();
  try{
   if(change.Touched&&!Restore(change,backend,save,log))throw new InvalidOperationException("Previous restoration pending.");
   change.Original=backend.Read();
   if(change.Original.ValueExists&&change.Original.Value==1){result.Status="policy already set; Windows behavior needs validation";result.Configured=true;return result;}
   backend.ProbeWriteAccess(); // Access denied here creates no journal/mutation.
   change.Touched=true;save();
   backend.Apply();
   var verify=backend.Read();if(!verify.ValueExists||verify.Value!=1)throw new InvalidOperationException("Toast policy not confirmed.");
   result.Status="policy applied; Windows behavior needs validation";result.Configured=true;
   log("TOASTS policy applied and value verified.");
  }catch(Exception error){
   result.AccessDenied=error is UnauthorizedAccessException||error is SecurityException;
   result.Status=result.AccessDenied?"not applied: access denied; install administrator helper":"not applied: "+error.GetType().Name;
   if(change.Touched&&!Restore(change,backend,save,log)){result.RestorationPending=true;result.Status+="; restoration pending";}
   log("TOAST WARNING: "+error.Message);
  }
  return result;
 }
}
