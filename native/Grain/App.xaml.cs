using Microsoft.UI.Xaml;

namespace Grain;
public partial class App : Application
{
    public static MainWindow? Window;
    public App()
    {
        InitializeComponent();
        DebugSettings.IsXamlResourceReferenceTracingEnabled=true;
        DebugSettings.XamlResourceReferenceFailed+=(_,e)=>Log(e.Message);
        UnhandledException += (_,e) => {
            var dir=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SegmentEveryGrainDesktop");
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir,"winui-error.log"),$"{DateTimeOffset.Now}: {e.Exception}\n");
        };
    }
    private static void Log(string message)
    {
        string dir=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SegmentEveryGrainDesktop");
        Directory.CreateDirectory(dir);File.AppendAllText(Path.Combine(dir,"winui-resources.log"),message+"\n");
    }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Window=new MainWindow();Window.Activate();
    }
}
