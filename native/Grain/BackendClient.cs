using System.Diagnostics;
using System.Text.Json;

namespace Grain;
public sealed class BackendClient : IDisposable
{
    private Process? process;
    private int sequence;
    private readonly SemaphoreSlim gate=new(1,1);
    public event Action<WorkProgress>? Progress;
    public string LogPath { get; }=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SegmentEveryGrainDesktop","winui-worker.log");
    public async Task StartAsync()
    {
        string app=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SegmentEveryGrainDesktop");
        string config=Path.Combine(app,"config.json");
        if(!File.Exists(config))throw new InvalidOperationException("The processing engine is not installed. Run the included Machine Setup application first.");
        using var doc=JsonDocument.Parse(await File.ReadAllTextAsync(config));
        string python=doc.RootElement.TryGetProperty("python",out var p)?p.GetString()!:Path.Combine(app,"runtime","Scripts","python.exe");
        if(!File.Exists(python))throw new FileNotFoundException("The private Python runtime was not found. Run Machine Setup to repair it.",python);
        var start=new ProcessStartInfo(python) {UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=System.Text.Encoding.UTF8,StandardErrorEncoding=System.Text.Encoding.UTF8};
        start.ArgumentList.Add("-u");start.ArgumentList.Add(Path.Combine(AppContext.BaseDirectory,"Backend","worker.py"));
        start.Environment["PYTHONIOENCODING"]="utf-8";
        start.Environment["MPLBACKEND"]="Agg";
        process=new Process {StartInfo=start};process.Start();
        _=Task.Run(async()=> {
            try {
                using var log=new StreamWriter(LogPath,append:true){AutoFlush=true};
                while(await process.StandardError.ReadLineAsync() is string line)await log.WriteLineAsync(line);
            }catch{/* Shutdown can close redirected streams. */}
        });
        var startup=Stopwatch.StartNew();
        while(true) {
            string? line=await process.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromMinutes(2)-startup.Elapsed);
            if(line is null)throw new InvalidOperationException($"The processing engine exited during startup. See {LogPath}");
            using var msg=JsonDocument.Parse(line);string? kind=msg.RootElement.GetProperty("event").GetString();
            if(kind=="ready")break;
            if(kind=="progress"){Progress?.Invoke(WorkProgress.Parse(msg.RootElement));continue;}
            throw new InvalidOperationException(msg.RootElement.GetProperty("message").GetString());
        }
    }
    public async Task<JsonElement> CallAsync(string method,object? args=null)
    {
        await gate.WaitAsync();
        try {
            if(process is null || process.HasExited)throw new InvalidOperationException("The processing engine is unavailable. Close and reopen the application.");
            int id=++sequence;
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new {id,method,args=args??new {}}));
            await process.StandardInput.FlushAsync();
            while(await process.StandardOutput.ReadLineAsync() is string line) {
                using var doc=JsonDocument.Parse(line);var msg=doc.RootElement;
                if(msg.TryGetProperty("event",out var ev)) {
                    if(ev.GetString()=="progress")Progress?.Invoke(WorkProgress.Parse(msg));
                    else if(ev.GetString()=="fatal")throw new InvalidOperationException(msg.GetProperty("message").GetString());
                    continue;
                }
                if(msg.GetProperty("id").GetInt32()!=id)throw new InvalidOperationException("Unexpected response from the processing engine.");
                if(msg.TryGetProperty("error",out var error))throw new InvalidOperationException(error.GetString());
                return msg.GetProperty("result").Clone();
            }
            throw new InvalidOperationException($"The processing engine stopped unexpectedly. See {LogPath}");
        }finally{gate.Release();}
    }
    public void Dispose()
    {
        try {if(process is {HasExited:false}){process.StandardInput.Close();if(!process.WaitForExit(1500))process.Kill(entireProcessTree:true);}}catch{}
        process?.Dispose();
    }
}

public sealed record WorkProgress(string Message,double? Percent=null,double? RemainingSeconds=null,
                                  double? Completed=null,double? Total=null,bool Indeterminate=true)
{
    private static double? Number(JsonElement json,string name)=>json.TryGetProperty(name,out var value)&&
        value.ValueKind==JsonValueKind.Number&&value.TryGetDouble(out double result)&&double.IsFinite(result)?result:null;
    public static WorkProgress Parse(JsonElement json)=>new(
        json.TryGetProperty("message",out var message)?message.GetString()??"Processing…":"Processing…",
        Number(json,"percent"),Number(json,"remainingSeconds"),Number(json,"completed"),Number(json,"total"),
        !json.TryGetProperty("indeterminate",out var unknown)||unknown.ValueKind!=JsonValueKind.False);
}
