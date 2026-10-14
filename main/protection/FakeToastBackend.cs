using System;

// Used only by --self-test; never substituted into the operating service/guard.
public class FakeToastBackend : ToastBackend {
 public bool KeyExists;public bool ValueExists;public int Value;public bool OtherValues;
 public bool DenyProbe;public bool FailBeforeWrite;public bool FailAfterWrite;public bool FailAfterKeyCreate;public bool FailRestore;public bool UnknownAfterWrite;
 public int Writes;public int Probes;
 public ToastSnapshot Read(){if(UnknownAfterWrite&&Writes>0)throw new UnauthorizedAccessException("Simulated read unavailable.");return new ToastSnapshot{KeyExists=KeyExists,ValueExists=ValueExists,Value=Value,EmptyKey=KeyExists&&!ValueExists&&!OtherValues};}
 public void ProbeWriteAccess(){Probes++;if(DenyProbe)throw new UnauthorizedAccessException("Simulated read-only ACL.");}
 public void Apply(){
  if(FailBeforeWrite)throw new UnauthorizedAccessException("Write denied after preflight.");
  KeyExists=true;
  if(FailAfterKeyCreate)throw new InvalidOperationException("Failure after creating an empty key.");
  ValueExists=true;Value=1;Writes++;
  if(FailAfterWrite)throw new InvalidOperationException("Failure after applying the value.");
 }
 public bool Matches(ToastSnapshot original){var current=Read();return current.ValueExists==original.ValueExists&&(!current.ValueExists||current.Value==original.Value)&&(current.KeyExists==original.KeyExists||(!original.KeyExists&&current.KeyExists&&!current.EmptyKey));}
 public bool CanRestore(ToastSnapshot original){var current=Read();return current.ValueExists&&current.Value==1||!original.KeyExists&&current.KeyExists&&current.EmptyKey;}
 public void Restore(ToastSnapshot original){if(FailRestore)throw new UnauthorizedAccessException("Simulated restoration denied.");KeyExists=original.KeyExists;ValueExists=original.ValueExists;Value=original.Value;Writes++;}
}
public static class ToastTests {
 public static int Run(){
  int count=0;Action<bool,string> check=(condition,name)=>{if(!condition)throw new Exception("TOAST TEST: "+name);count++;};
  var denied=new FakeToastBackend{DenyProbe=true};var change=new ToastChange();int saves=0;
  var result=ToastTransaction.Apply(change,denied,()=>saves++,message=>{});
  check(result.AccessDenied&&!result.Configured&&!result.RestorationPending,"access denied is explicitly degraded");
  check(!change.Touched&&saves==0&&denied.Writes==0&&!denied.KeyExists,"denied preflight creates no false journal or key");
  var before=new FakeToastBackend{FailBeforeWrite=true};change=new ToastChange();saves=0;
  result=ToastTransaction.Apply(change,before,()=>saves++,message=>{});
  check(!change.Touched&&!result.RestorationPending&&saves==2&&before.Writes==0,"failure without mutation clears write-ahead");
  var partial=new FakeToastBackend{FailAfterWrite=true};change=new ToastChange();
  result=ToastTransaction.Apply(change,partial,()=>{},message=>{});
  check(!result.Configured&&!result.RestorationPending&&!change.Touched&&!partial.KeyExists,"partial mutation restored exactly");
  var empty=new FakeToastBackend{FailAfterKeyCreate=true};change=new ToastChange();
  result=ToastTransaction.Apply(change,empty,()=>{},message=>{});
  check(!empty.KeyExists&&!change.Touched,"partially created empty key removed");
  var pending=new FakeToastBackend{FailAfterWrite=true,FailRestore=true};change=new ToastChange();
  result=ToastTransaction.Apply(change,pending,()=>{},message=>{});
  check(change.Touched&&result.RestorationPending&&pending.Value==1,"actual restore failure preserves journal");
  pending.FailRestore=false;
  check(ToastTransaction.Restore(change,pending,()=>{},message=>{})&&!pending.KeyExists,"retry recovers partial mutation");
  var unknown=new FakeToastBackend{UnknownAfterWrite=true};change=new ToastChange();
  result=ToastTransaction.Apply(change,unknown,()=>{},message=>{});
  check(change.Touched&&result.RestorationPending,"unknown state retained");
  unknown.UnknownAfterWrite=false;
  check(ToastTransaction.Restore(change,unknown,()=>{},message=>{})&&!unknown.KeyExists,"recovery after reads resume");
  var original=new FakeToastBackend{KeyExists=true,ValueExists=true,Value=0};change=new ToastChange();
  result=ToastTransaction.Apply(change,original,()=>{},message=>{});
  check(result.Configured&&change.Touched,"active snapshot is not a restoration failure");
  ToastTransaction.Restore(change,original,()=>{},message=>{});
  check(original.KeyExists&&original.ValueExists&&original.Value==0,"original DWORD restored");
  var already=new FakeToastBackend{KeyExists=true,ValueExists=true,Value=1,DenyProbe=true};change=new ToastChange();
  result=ToastTransaction.Apply(change,already,()=>{},message=>{});
  check(result.Configured&&!change.Touched&&already.Probes==0,"existing policy value 1 is not rewritten");
  return count;
 }
}
